"""Mide la antelación real de la alerta temprana, sin etiquetas externas.

El dataset no trae ninguna etiqueta de "empresa que entró en problemas", así que
no se puede medir precisión contra una verdad conocida. Lo que sí se puede hacer
es definir el EVENTO con reglas de severidad absoluta observadas en los datos, y
medir cuántos meses antes se activó la alerta, que funciona con señales distintas
(percentil transversal, z-score propio y dirección sostenida).

El evento es un umbral de severidad ya materializada; la alerta es un cambio de
régimen. Por eso la antelación es informativa: mide cuánto se adelanta detectar
el movimiento frente a esperar a que la situación sea grave.

Reglas de medición, para que las cifras signifiquen algo:
  - La señal solo cuenta como detección si se activa ESTRICTAMENTE ANTES del
    evento y dentro de HORIZONTE_ANTICIPACION meses. Un aviso 18 meses antes no
    anticipó, coincidió.
  - La precisión se mide igual para la alerta y para el baseline. Una señal que
    se activa en casi todas las empresas obtiene recall y antelación altísimos
    sin aportar nada, y solo la precisión y el lift lo delatan.
  - El lift compara la precisión contra la tasa base del evento. Lift 1,0 = la
    señal no informa.

Limitación honesta: evento y alerta comparten variables subyacentes, así que esto
NO es una validación fuera de muestra. Mide adelanto frente a un umbral de
severidad, no capacidad predictiva frente a un desenlace externo (impago real,
concurso). Para eso haría falta una etiqueta que el dataset no incluye.
"""

import numpy as np
import pandas as pd

import src.config as cfg


def racha(cond, n):
    """True en el mes en que se completan n meses consecutivos cumpliendo cond."""
    return cond.fillna(False).rolling(n, min_periods=n).sum() >= n


def eventos(h):
    return {
        "impago_severo": racha(
            (h["pct_impagos_prov_3m"].fillna(0) >= cfg.EVENTO_IMPAGO_PCT)
            | (h["stock_prov_sobre_ingresos"].fillna(0) >= cfg.EVENTO_IMPAGO_STOCK),
            cfg.EVENTO_MESES),
        "asfixia_de_caja": racha(
            (h["flujo_relativo_3m"].fillna(0) <= cfg.EVENTO_ASFIXIA_FLUJO)
            & (h["burn_rate_3m_avg"].fillna(0) >= cfg.EVENTO_ASFIXIA_BURN),
            cfg.EVENTO_MESES),
    }


def primer_indice(serie):
    idx = np.flatnonzero(serie.fillna(False).to_numpy())
    return int(idx[0]) if len(idx) else None


def evaluar(disparos, i_evento, n):
    """Detección y antelación de una señal frente a un evento.

    disparos: array booleano por mes. i_evento: índice del evento o None.
    """
    idx = np.flatnonzero(disparos)
    if i_evento is None:
        # Sin evento: la señal se activó (falso positivo) o no.
        return {"detectado": 0, "antelacion": np.nan, "activada": int(len(idx) > 0)}
    ventana = idx[(idx < i_evento) & (idx >= i_evento - cfg.HORIZONTE_ANTICIPACION)]
    if len(ventana) == 0:
        return {"detectado": 0, "antelacion": np.nan, "activada": int(len(idx) > 0)}
    return {"detectado": 1, "antelacion": int(i_evento - ventana[0]), "activada": 1}


def run():
    panel = pd.read_csv(cfg.SCORES_MENSUAL_PATH)
    panel["year_month"] = pd.PeriodIndex(panel["year_month"], freq="M")
    panel = panel.sort_values(["company_id", "year_month"])

    senales = {
        # Capa NIVEL. Es también el baseline: lo que haría un cuadro de mando sin
        # ninguna capa de anticipación, reaccionar cuando el score ya está bajo.
        "nivel": lambda h: (h["senal_nivel"] == 1).to_numpy(),
        # Canales de cola: ven a quien está en la cola de su cohorte.
        "canales_cola": lambda h: ((h["alerta_canal"].fillna("") != "")
                                   & (h["alerta_canal"].fillna("") != "giro_propio")
                                   & (h["senal_anticipacion"] == 1)).to_numpy(),
        # Giro propio: ve a quien se mueve respecto a sí misma aunque siga arriba.
        "giro_propio": lambda h: (h["senal_giro"] == 1).to_numpy(),
        "combinada": lambda h: (h["alerta_temprana"] == 1).to_numpy(),
    }

    filas = []
    for cid, h in panel.groupby("company_id"):
        h = h.reset_index(drop=True)
        n = len(h)
        evs = eventos(h)
        disparos = {k: fn(h) for k, fn in senales.items()}

        for nombre_ev, ev in evs.items():
            i_ev = primer_indice(ev)
            fila = {"company_id": cid, "evento": nombre_ev,
                    "hubo_evento": int(i_ev is not None),
                    "mes_evento": str(h["year_month"].iloc[i_ev]) if i_ev is not None else None}
            for nombre_s, d in disparos.items():
                r = evaluar(d, i_ev, n)
                fila[f"{nombre_s}__detectado"] = r["detectado"]
                fila[f"{nombre_s}__antelacion"] = r["antelacion"]
                fila[f"{nombre_s}__activada"] = r["activada"]
            filas.append(fila)

    r = pd.DataFrame(filas)
    r.to_csv(cfg.ANTICIPATION_PATH, index=False)
    enriquecer_scores(r)

    n_emp = r["company_id"].nunique()
    print(f"Empresas analizadas: {n_emp:,}   "
          f"horizonte: {cfg.HORIZONTE_ANTICIPACION} meses   "
          f"evento: {cfg.EVENTO_MESES} meses consecutivos\n")

    for nombre_ev, g in r.groupby("evento"):
        base = g["hubo_evento"].mean()
        print(f"--- {nombre_ev} ---")
        print(f"  empresas con evento: {int(g['hubo_evento'].sum()):,} de {len(g):,} "
              f"(tasa base {base:.1%})")
        print(f"  {'señal':22s} {'activada':>9s} {'recall':>8s} {'precisión':>10s} "
              f"{'lift':>6s} {'antel. mediana':>15s}")
        for nombre_s in senales:
            act = g[f"{nombre_s}__activada"] == 1
            det = g[f"{nombre_s}__detectado"] == 1
            con_ev = g["hubo_evento"] == 1
            recall = det.sum() / max(con_ev.sum(), 1)
            precision = (g.loc[act, "hubo_evento"].mean() if act.any() else np.nan)
            ant = g.loc[det, f"{nombre_s}__antelacion"]
            print(f"  {nombre_s:22s} {act.mean():>8.1%} {recall:>8.1%} "
                  f"{precision:>10.1%} {precision/base:>6.2f} "
                  f"{ant.median() if len(ant) else float('nan'):>13.1f} m")
        # Lo que de verdad hay que medir: ¿la capa de anticipación avisa antes que
        # la de nivel? Si no gana meses sobre ella, no aporta nada al producto.
        amb = g[(g["canales_cola__detectado"] == 1) & (g["hubo_evento"] == 1)]
        if len(amb):
            gana = amb["canales_cola__antelacion"] - amb["nivel__antelacion"].fillna(0)
            solo = amb[amb["nivel__detectado"] == 0]
            print(f"  CANALES DE COLA sobre la capa de nivel:")
            print(f"    eventos avisados por anticipación: {len(amb):,} "
                  f"({len(amb)/max(int(g['hubo_evento'].sum()),1):.1%} de los eventos)")
            print(f"    meses ganados a la capa de nivel: mediana {gana.median():+.0f}, "
                  f"p75 {gana.quantile(.75):+.0f}")
            print(f"    eventos que SOLO ve la anticipación: {len(solo):,}")
        print()

    validar_giro(panel)
    print(f"Guardado en {cfg.ANTICIPATION_PATH} y columnas de antelación "
          f"añadidas a {cfg.SCORES_PATH.name}")
    return r


def validar_giro(panel):
    """Valida el giro contra SU desenlace, que no es el evento de severidad.

    El giro mira empresas que todavía están bien, así que medirlo contra "¿acabará
    en impago severo?" lo condena por construcción: ahí obtiene lift 0,93 y 0,65.
    Lo que el giro afirma es otra cosa, "esta caída va a sostenerse", y eso se
    comprueba mirando el score suavizado varios meses después.

    Es la única forma honesta de evaluar la pregunta 4 del reto (bache o caída)
    sin etiquetas externas: el desenlace es el propio comportamiento futuro de la
    empresa, observado, no una opinión nuestra.
    """
    g = panel.groupby("company_id", sort=False)["score_suavizado"]
    fut = {h: g.transform(lambda s: s.shift(-h)) - panel["score_suavizado"]
           for h in (3, 6)}

    sub = panel[panel["senal_giro"] == 1]
    print("\n=== GIRO PROPIO: bache o caída, validado contra el score futuro ===")
    print(f"{'naturaleza':20s} {'n':>6s} {'Δ+3m':>8s} {'Δ+6m':>8s} "
          f"{'%recupera':>10s} {'%sigue cayendo':>15s}")
    for nat, gg in sub.groupby("naturaleza_caida"):
        f3, f6 = fut[3].loc[gg.index], fut[6].loc[gg.index]
        if f3.notna().sum() < 20:
            continue
        print(f"{nat:20s} {len(gg):6,} {f3.median():8.2f} {f6.median():8.2f} "
              f"{(f3 > 0).mean():10.1%} {(f3 < -3).mean():15.1%}")

    sanas = sub[sub["score_mensual"] >= 55]
    print(f"\nGiros sobre empresas que SIGUEN pareciendo sanas (score >= 55): "
          f"{len(sanas):,} filas-mes, {sanas['company_id'].nunique():,} empresas.")
    print("Es el caso 'de 82 a 68' del reto, invisible para los canales de cola.")


def enriquecer_scores(r):
    """Devuelve la antelación medida a `scores_finales.csv`, empresa por empresa.

    "Cuándo se vio venir" es una de las seis preguntas del reto y no se puede
    contestar con una media agregada: cada empresa necesita su propio número.

    Este paso va aparte del motor a propósito. La antelación mira hacia el
    FUTURO del mes de la alerta, así que calcularla dentro de `score_engine.py`
    metería información futura en un archivo que debe ser causal mes a mes. Aquí,
    en cambio, es lo que es: una evaluación a posteriori del sistema.
    """
    if not cfg.SCORES_PATH.exists():
        return
    # Se usa `canales_cola`, que es la señal validada contra estos eventos. El
    # giro se valida contra otro desenlace y su antelación ya viaja en las
    # columnas `primer_giro` y `naturaleza_caida` que escribe el motor.
    por_emp = (r[r["hubo_evento"] == 1]
               .groupby("company_id")
               .agg(eventos_detectados=("canales_cola__detectado", "sum"),
                    eventos_totales=("hubo_evento", "sum"),
                    meses_anticipacion=("canales_cola__antelacion", "max"),
                    meses_anticipacion_nivel=("nivel__antelacion", "max"))
               .reset_index())
    por_emp["meses_ganados_a_nivel"] = (
        por_emp["meses_anticipacion"] - por_emp["meses_anticipacion_nivel"].fillna(0))

    s = pd.read_csv(cfg.SCORES_PATH)
    s = s.drop(columns=[c for c in por_emp.columns if c != "company_id" and c in s.columns])
    s.merge(por_emp, on="company_id", how="left").to_csv(cfg.SCORES_PATH, index=False)


if __name__ == "__main__":
    run()
