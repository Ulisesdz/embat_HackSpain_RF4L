"""Motor de scoring 0-100 con reglas expertas y explicabilidad.

Diferencia clave frente a un umbral en euros: todos los factores operan sobre
variables escala-libre (ratios, meses de runway, porcentajes). Además, un mes
solo se puntúa si existe evidencia suficiente: los pesos no se redistribuyen
hasta convertir una fila con poca información en un 0-100 aparentemente sólido.

Salidas:
  scores_mensuales.csv   score por empresa y mes
  scores_finales.csv     score agregado, clasificación y tendencia
  score_explanations.json  desglose por factor del último mes válido
"""

import json
import numpy as np
import pandas as pd

import data_analysis.config as cfg


# =============================================================================
# FACTORES (cada uno devuelve score 0-100, razón, y si es aplicable)
# =============================================================================

def f_liquidez(v):
    """Flujo neto como fracción de los ingresos medios."""
    if pd.isna(v):
        return None, "Sin base de ingresos para normalizar el flujo"
    pct = v * 100
    for umbral, score, txt in [
        (15, 100, "muy positivo"), (5, 85, "positivo"), (0, 68, "ligeramente positivo"),
        (-5, 45, "ligeramente negativo"), (-15, 22, "negativo"),
    ]:
        if pct > umbral:
            return score, f"Flujo neto {txt} ({pct:+.1f}% de los ingresos)"
    return 5, f"Flujo neto muy negativo ({pct:+.1f}% de los ingresos)"


def f_runway(v):
    """Meses de gasto que cubre la caja disponible."""
    if pd.isna(v):
        return None, "Sin caja reportada o sin gasto de referencia"
    if v < 0:
        return 0, f"Caja en negativo ({v:.1f} meses)"
    for umbral, score, txt in [
        (12, 100, "muy holgado"), (6, 85, "cómodo"), (3, 62, "ajustado"), (1, 32, "corto"),
    ]:
        if v >= umbral:
            return score, f"Runway {txt} ({v:.1f} meses de gasto cubiertos)"
    return 10, f"Runway crítico ({v:.1f} meses de gasto cubiertos)"


def f_eficiencia(v, sin_ingresos):
    if sin_ingresos:
        return 5, "Mes sin ingresos y con gastos: quema pura de caja"
    if pd.isna(v):
        return None, "Sin ingresos de referencia para el ratio de gasto"
    for umbral, score, txt in [
        (0.7, 100, "muy eficiente"), (1.0, 86, "sano"), (1.3, 62, "ajustado"),
        (2.0, 35, "en quema"),
    ]:
        if v < umbral:
            return score, f"Gasta {v:.2f}x lo que ingresa ({txt})"
    return 12, f"Gasta {v:.2f}x lo que ingresa (quema severa)"


def f_morosidad_prov(v):
    """Impagos a proveedores: síntoma de asfixia ya materializada."""
    if pd.isna(v):
        return None, "Sin compras suficientes para medir impagos"
    for umbral, score, txt in [
        (5, 100, "muy bajos"), (15, 82, "bajos"), (30, 55, "moderados"),
        (50, 30, "altos"), (80, 12, "severos"),
    ]:
        if v < umbral:
            return score, f"Impagos a proveedores {txt} ({v:.1f}% de las compras)"
    return 0, f"Impagos a proveedores críticos ({v:.1f}% de las compras)"


def f_morosidad_clientes(v):
    if pd.isna(v):
        return None, "Sin ventas suficientes para medir el cobro"
    for umbral, score, txt in [
        (10, 100, "muy sano"), (25, 80, "sano"), (45, 55, "tensionado"), (70, 30, "deteriorado"),
    ]:
        if v < umbral:
            return score, f"Cobro {txt} ({v:.1f}% de las ventas sin cobrar)"
    return 10, f"Cobro crítico ({v:.1f}% de las ventas sin cobrar)"


def f_tendencia(pendiente, rec_prov, rec_cli):
    """Premia la mejora igual que penaliza el deterioro."""
    if pd.isna(pendiente) and pd.isna(rec_prov) and pd.isna(rec_cli):
        return None, "Historia insuficiente para medir trayectoria"
    s, razones = 50, []
    if not pd.isna(pendiente):
        p = pendiente * 100
        if p > 2:
            s += 25; razones.append(f"flujo mejorando ({p:+.1f} pp/mes)")
        elif p > 0:
            s += 10; razones.append("flujo estable o en leve mejora")
        elif p > -2:
            s -= 12; razones.append("flujo en leve deterioro")
        else:
            s -= 28; razones.append(f"flujo cayendo ({p:+.1f} pp/mes)")
    for rec, etiqueta in [(rec_prov, "impagos a proveedores"), (rec_cli, "morosidad de clientes")]:
        if pd.isna(rec):
            continue
        if rec > 10:
            s += 12; razones.append(f"{etiqueta} bajando")
        elif rec < -10:
            s -= 12; razones.append(f"{etiqueta} subiendo")
    return int(np.clip(s, 0, 100)), "; ".join(razones)


def f_apalancamiento(deuda_ing, caja_neg):
    if pd.isna(deuda_ing):
        return None, "Sin ingresos de referencia para medir apalancamiento"
    if deuda_ing == 0:
        base, txt = 85, "Sin deuda bancaria viva"
    elif deuda_ing < 0.25:
        base, txt = 90, f"Deuda controlada ({deuda_ing:.2f}x ingresos anuales)"
    elif deuda_ing < 0.75:
        base, txt = 62, f"Deuda moderada ({deuda_ing:.2f}x ingresos anuales)"
    elif deuda_ing < 1.5:
        base, txt = 35, f"Deuda alta ({deuda_ing:.2f}x ingresos anuales)"
    else:
        base, txt = 12, f"Deuda muy alta ({deuda_ing:.2f}x ingresos anuales)"
    if caja_neg:
        base, txt = max(0, base - 25), txt + "; saldo bancario en negativo"
    return base, txt


# =============================================================================
# SCORE MENSUAL
# =============================================================================

FACTORES = ["liquidez", "runway", "eficiencia", "morosidad_prov",
            "morosidad_clientes", "tendencia", "apalancamiento"]


def score_mes(row):
    crudos = {
        "liquidez": f_liquidez(row.get("flujo_relativo_3m")),
        "runway": f_runway(row.get("runway_meses")),
        "eficiencia": f_eficiencia(
            row.get("burn_rate_3m_avg"),
            bool(row.get("mes_sin_ingresos", 0))
        ),
        "morosidad_prov": f_morosidad_prov(row.get("impagos_prov_3m_avg")),
        "morosidad_clientes": f_morosidad_clientes(row.get("clientes_morosos_3m_avg")),
        "tendencia": f_tendencia(
            row.get("flujo_pendiente_6m"),
            row.get("recuperacion_prov"),
            row.get("recuperacion_clientes")
        ),
        "apalancamiento": f_apalancamiento(
            row.get("deuda_sobre_ingresos"),
            bool(row.get("caja_negativa_flag", 0))
        ),
    }

    activos = {k: v for k, v in crudos.items() if v[0] is not None}
    if not activos:
        return pd.Series({
            "score_mensual": np.nan,
            "peso_cubierto": 0.0,
            "n_componentes_validos": 0,
            "detalle": {}
        })

    peso_total = sum(cfg.PESOS[k] for k in activos)
    n_validos = len(activos)

    detalle = {
        k: {
            "score": crudos[k][0],
            "peso_efectivo": round(cfg.PESOS[k] / peso_total, 4) if k in activos else 0.0,
            "aplicable": k in activos,
            "razon": crudos[k][1],
        }
        for k in FACTORES
    }

    # La redistribución sigue existiendo, pero no se permite ocultar una
    # cobertura demasiado baja detrás de una normalización a 100.
    if peso_total < cfg.MIN_PESO_CUBIERTO_SCORE:
        return pd.Series({
            "score_mensual": np.nan,
            "peso_cubierto": round(peso_total, 3),
            "n_componentes_validos": n_validos,
            "detalle": detalle,
        })

    score = sum(cfg.PESOS[k] * activos[k][0] for k in activos) / peso_total
    return pd.Series({
        "score_mensual": round(float(score), 2),
        "peso_cubierto": round(peso_total, 3),
        "n_componentes_validos": n_validos,
        "detalle": detalle,
    })


# =============================================================================
# AGREGACIÓN TEMPORAL
# =============================================================================

def agregar(hist):
    """Agregación exponencial ponderada por recencia, confianza y cobertura.

    La cobertura entra como factor de evidencia: dos meses con el mismo score
    no pesan igual si uno se obtuvo con 95% de los factores y otro con 55%.
    """
    h = hist.dropna(subset=["score_mensual"]).copy()
    if h.empty:
        return np.nan

    n = len(h)
    w_recencia = np.exp(
        -np.log(2) * (n - 1 - np.arange(n)) / cfg.HALF_LIFE_MONTHS
    )
    w_confianza = h["confianza"].map(cfg.PESO_CONFIANZA).fillna(0.5).values
    w_cobertura = h["peso_cubierto"].fillna(0.0).clip(0, 1).values

    w = w_recencia * w_confianza * w_cobertura
    if w.sum() == 0:
        return np.nan

    return float((h["score_mensual"].values * (w / w.sum())).sum())


def confianza_final(hist):
    """Confianza agregada: historia + cobertura, no la etiqueta del último mes."""
    evaluados = hist.dropna(subset=["score_mensual"])
    if evaluados.empty:
        return "baja", 0.0, 0

    cobertura_media = float(evaluados["peso_cubierto"].mean())
    cobertura_reciente = float(evaluados["peso_cubierto"].tail(6).mean())
    meses_evaluados = int(len(evaluados))
    meses_activos = int(hist["mes_activo"].sum()) if "mes_activo" in hist else meses_evaluados

    # La historia activa limita explícitamente la confianza.
    if (
        cobertura_media >= 0.80
        and cobertura_reciente >= 0.80
        and meses_evaluados >= cfg.MIN_MESES_HISTORIA
        and meses_activos >= cfg.MIN_MESES_HISTORIA
    ):
        nivel = "alta"
    elif (
        cobertura_media >= 0.65
        and cobertura_reciente >= 0.60
        and meses_evaluados >= 6
        and meses_activos >= 6
    ):
        nivel = "media"
    else:
        nivel = "baja"

    return nivel, cobertura_media, cobertura_reciente


def etiqueta_tendencia(hist):
    h = hist.dropna(subset=["score_mensual"])
    if len(h) < 6:
        return "SIN DATOS"
    dif = h["score_mensual"].tail(3).mean() - h["score_mensual"].iloc[-6:-3].mean()
    if dif > 5:
        return "MEJORANDO"
    if dif < -5:
        return "DETERIORANDO"
    return "ESTABLE"


def alertas(hist):
    """Señales accionables para el CFO, derivadas de persistencia, no de un mes."""
    if hist.empty:
        return []
    last = hist.iloc[-1]
    out = []
    if last.get("persistente_flag_flujo_negativo", 0) == 1:
        out.append("Tres meses consecutivos de flujo de caja negativo")
    if last.get("persistente_flag_estres_prov", 0) == 1:
        out.append("Impagos a proveedores por encima del 30% durante tres meses")
    if last.get("persistente_flag_estres_clientes", 0) == 1:
        out.append("Más del 30% de las ventas sin cobrar durante tres meses")
    if pd.notna(last.get("runway_meses")) and last["runway_meses"] < 3:
        out.append(f"Runway por debajo de 3 meses ({last['runway_meses']:.1f})")
    if pd.notna(last.get("recuperacion_prov")) and last["recuperacion_prov"] < -15:
        out.append("Deterioro rápido en el pago a proveedores frente al trimestre anterior")
    return out


# =============================================================================
# MAIN
# =============================================================================

def run():
    cfg.asegurar_dirs()
    panel = pd.read_csv(cfg.PANEL_PATH)
    panel["year_month"] = pd.PeriodIndex(panel["year_month"], freq="M")

    if cfg.EXCLUIR_MES_PARCIAL_DEL_SCORE and "mes_parcial" in panel.columns:
        n = int((panel["mes_parcial"] == 1).sum())
        panel = panel[panel["mes_parcial"] == 0].copy()
        print(f"Excluidas {n:,} filas de meses parciales (flujos truncados).")

    print("Calculando score mensual...")
    panel = panel.join(panel.apply(score_mes, axis=1))
    panel = panel.sort_values(["company_id", "year_month"])

    print("Agregando por empresa...")
    filas, explicaciones = [], {}
    for cid, hist in panel.groupby("company_id"):
        s = agregar(hist)
        validos = hist["score_mensual"].notna()
        conf, cobertura_media, cobertura_reciente = confianza_final(hist)
        fila = {
            "company_id": cid,
            "score_final": round(s, 2) if pd.notna(s) else np.nan,
            "clasificacion": cfg.clasificar(s) if pd.notna(s) else "NO EVALUABLE",
            "tendencia": etiqueta_tendencia(hist),
            "meses_evaluados": int(validos.sum()),
            "meses_activos": int(hist["mes_activo"].sum()) if "mes_activo" in hist else int(validos.sum()),
            "cobertura_media": round(cobertura_media, 3),
            "cobertura_reciente": round(cobertura_reciente, 3),
            "confianza": conf,
            "score_ultimo_mes": (
                float(hist.loc[validos, "score_mensual"].iloc[-1])
                if validos.any() else np.nan
            ),
        }
        filas.append(fila)

        if validos.any():
            ultimo = hist[validos].iloc[-1]
            explicaciones[str(cid)] = {
                "year_month": str(ultimo["year_month"]),
                "score_final": fila["score_final"],
                "clasificacion": fila["clasificacion"],
                "tendencia": fila["tendencia"],
                "confianza": fila["confianza"],
                "cobertura_media": fila["cobertura_media"],
                "cobertura_reciente": fila["cobertura_reciente"],
                "peso_cubierto": ultimo["peso_cubierto"],
                "n_componentes_validos": int(ultimo["n_componentes_validos"]),
                "factores": ultimo["detalle"],
                "alertas": alertas(hist[validos]),
            }

    scores = pd.DataFrame(filas).sort_values("score_final", ascending=False)

    panel.drop(columns=["detalle"]).to_csv(cfg.SCORES_MENSUAL_PATH, index=False)
    scores.to_csv(cfg.SCORES_PATH, index=False)
    cfg.EXPLAIN_PATH.write_text(json.dumps(explicaciones, indent=2, ensure_ascii=False,
                                           default=str), encoding="utf-8")

    cols = ["company_id", "score_final", "clasificacion", "tendencia",
            "confianza", "cobertura_media", "meses_evaluados"]
    print("\n=== TOP 5 SALUDABLES ===")
    print(scores.head(5)[cols].to_string(index=False))
    print("\n=== TOP 5 CRÍTICOS ===")
    print(scores.dropna(subset=["score_final"]).tail(5)[cols].to_string(index=False))
    print("\n=== DISTRIBUCIÓN ===")
    print(scores["clasificacion"].value_counts().to_string())
    print(scores["tendencia"].value_counts().to_string())
    print(f"\nCobertura media del score: {scores['cobertura_media'].mean():.3f}")
    print(f"Meses evaluados (mediana): {scores['meses_evaluados'].median():.0f}")
    print(f"\nGuardado en {cfg.SCORES_PATH}, {cfg.SCORES_MENSUAL_PATH}, {cfg.EXPLAIN_PATH}")
    return scores


if __name__ == "__main__":
    run()