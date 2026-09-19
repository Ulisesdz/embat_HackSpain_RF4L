"""Monitor que avisa solo cuando una empresa se mueve de verdad: recorre los scores mes a mes y emite alertas con antirrebote.

Uso: python3 src/monitor.py [scores.parquet] [alerts.parquet]     (por defecto data/clean/scores.parquet -> data/clean/alerts.parquet)

Tipos de alerta (cada uno con su propio antirrebote, histéresis y rearme):
  cruce      el score cruza WARN (aviso) o CRIT (crítica) hacia abajo, o su simétrico hacia arriba (mejora);
  bloque     un bloque (liquidez/pago/financiacion/ingresos) cruza BLOCK_LOW/BLOCK_HIGH. Es el tipo con más señal: el bloque de
             ingresos <40 anticipa "ingresos que se secan" y el score agregado diluye esa información (ver anticipation.py);
  estado     la etiqueta pasa a 'deteriorando' / 'mejorando' y se mantiene 2 meses;
  movimiento el score cae/sube >= MOVE puntos en 3 meses durante 2 meses seguidos.
Solo se usan datos <= t en cada mes t. Una empresa que ya está en zona la primera vez que se la ve NO alerta (no se movió).
"""
import sys
from pathlib import Path

import numpy as np
import pandas as pd

_argv, sys.argv = sys.argv, ["x"]          # score.py lee sys.argv al importarse; se importa sin ejecutar su main
sys.path.insert(0, str(Path(__file__).parent))
import score as S                          # noqa: E402  (W, SIGNALS, LABEL, BLOCK, SCALE, REF)
import anticipation as A                   # noqa: E402  (eventos y evaluación)
sys.argv = _argv

D = Path("data/clean")

# ---- umbrales (constantes) ----
WARN_LOW, CRIT_LOW, WARN_HIGH, CRIT_HIGH = S.CUTS[0] + 7, S.CUTS[0], S.CUTS[2] - 5, S.CUTS[2]   # score: aviso y crítica (mejora simétrica)
BLOCK_LOW, BLOCK_HIGH = 40, 60                              # bloques (escala 0-100 como el score)
HYST = 5                                                    # puntos de histéresis: rearma al volver HYST por el lado sano
MIN_GAP = 6                                                 # antirrebote: meses mínimos entre dos alertas del mismo tipo/dirección
MOVE = 12                                                   # puntos en 3 meses (2 meses seguidos) para 'movimiento'
WARMUP = 3                                                  # no se alerta en los primeros WARMUP meses puntuados de cada empresa (ventana corta)
CONFIRM = False                                             # True: la alerta exige además que la versión rápida (3m) esté en zona
BLOCK_ALERTS = {"deterioro": ("ingresos",), "mejora": ("liquidez",)}   # bloques con señal medida (ver informe); el resto no supera el azar
ENABLED = {"cruce": True, "bloque": True, "estado": False, "movimiento": False}  # estado/movimiento: ver informe
NEG_STATE, POS_STATE = "deteriorando", "mejorando"
SHORT = lambda n: S.LABEL[n].split(" (")[0]


def mat(s, col, ids, months):
    return s.pivot(index="company_id", columns="month", values=col).reindex(index=ids, columns=months).to_numpy(float)


def families(s, ids, months):
    """[(tipo, dirección, severidad, bloque, y, umbral, histéresis)]: alerta cuando y > umbral; rearma cuando y < umbral - histéresis."""
    m = lambda c: mat(s, c, ids, months)
    lag = lambda X, j: np.pad(X, ((0, 0), (j, 0)), constant_values=np.nan)[:, :-j]
    sc, f = m("score"), []
    fast = lambda x, sg: np.minimum(sg * x, sg * m("score_fast")) if CONFIRM else sg * x   # zona solo si lenta y rápida coinciden
    if ENABLED["cruce"]:
        f += [("cruce", "deterioro", "aviso", "", fast(sc, -1), -WARN_LOW, HYST), ("cruce", "deterioro", "critica", "", fast(sc, -1), -CRIT_LOW, HYST),
              ("cruce", "mejora", "aviso", "", fast(sc, 1), WARN_HIGH, HYST), ("cruce", "mejora", "critica", "", fast(sc, 1), CRIT_HIGH, HYST)]
    if ENABLED["bloque"]:
        for dr, sg, thr in (("deterioro", -1, BLOCK_LOW), ("mejora", 1, BLOCK_HIGH)):
            f += [("bloque", dr, "aviso", b, sg * m(b), sg * thr, HYST) for b in BLOCK_ALERTS[dr]]
    if ENABLED["estado"]:
        for dr, lb in (("deterioro", NEG_STATE), ("mejora", POS_STATE)):
            c = (s.assign(v=(s.label == lb).astype(float)).pipe(mat, "v", ids, months))
            f.append(("estado", dr, "aviso", "", np.minimum(c, lag(c, 1)), 0.5, 0.5))     # 2 meses seguidos en el estado
    if ENABLED["movimiento"]:
        d3 = m("d3")
        f += [("movimiento", "deterioro", "aviso", "", np.minimum(-d3, lag(-d3, 1)), MOVE, MOVE / 2),
              ("movimiento", "mejora", "aviso", "", np.minimum(d3, lag(d3, 1)), MOVE, MOVE / 2)]
    return f


def fire_family(y, thr, hyst, warm=None):
    """Máquina de estados por empresa: dispara al entrar en zona (y > thr) estando armada. Entrar en zona sin poder disparar
    (antirrebote) consume el armado; rearma al salir de zona por más de `hyst`. Si la primera vez que se ve ya está en zona, no dispara."""
    n, T = y.shape
    fired, armed, seen, last = np.zeros((n, T), bool), np.zeros(n, bool), np.zeros(n, bool), np.full(n, -10 ** 6)
    for t in range(T):
        x = y[:, t]
        ok = np.isfinite(x)
        zone = ok & (x > thr)
        new = ok & ~seen
        armed = np.where(new, ~zone, armed)
        seen |= ok
        fired[:, t] = armed & zone & (t - last >= MIN_GAP) & (warm[:, t] if warm is not None else True)
        last = np.where(fired[:, t], t, last)
        armed = np.where(zone, False, np.where(ok & (x < thr - hyst), True, armed))
    return fired


def explain(row, prev, k, blk):
    """Top-2 señales que más movieron el score en 3 meses (contribución en puntos = k * peso * cambio de z). Si no hay historia,
    las peores señales en nivel. `blk` restringe a las señales de un bloque."""
    sig = [n for n in S.SIGNALS if not blk or S.BLOCK[n] == blk]
    cur = row[sig].astype(float).fillna(0)
    if prev is not None:
        c, txt = k * S.W[sig] * (cur - prev[sig].astype(float).fillna(0)), "pesa"
    else:
        c, txt = k * S.W[sig] * cur, "nivel"
    return c, txt


def run(path, out=None):
    s = pd.read_parquet(path).sort_values(["company_id", "month"]).reset_index(drop=True)
    ids, months = sorted(s.company_id.unique()), sorted(s.month.unique())
    k = S.kpt()
    row = {(c, m): i for i, (c, m) in enumerate(zip(s.company_id, s.month))}
    rows = []
    warm = np.cumsum(np.isfinite(mat(s, "score", ids, months)), 1) > WARMUP     # ya hay más de WARMUP meses puntuados
    for tipo, dr, sev, blk, y, thr, hy in families(s, ids, months):
        F = fire_family(y, thr, hy, warm)
        for i, t in zip(*np.nonzero(F)):
            r = s.loc[row[ids[i], months[t]]]
            p = row.get((ids[i], months[t - 3])) if t >= 3 else None
            prev = s.loc[p] if p is not None else None
            c, how = explain(r, prev, k, blk)
            c = c.sort_values(ascending=(dr == "deterioro")).head(2)
            c = c[c.abs() >= 0.3]
            sen = ", ".join(f"{SHORT(n)} {v:+.1f}" for n, v in c.items())
            x = r[blk] if blk else r.score
            lbl = f"bloque {blk}" if blk else "score"
            if tipo == "estado":
                head = f"Cambio de estado a '{r.label}'"
            elif tipo == "movimiento":
                head = f"Score {'cae' if dr == 'deterioro' else 'sube'} >={MOVE} pts en 3 meses, dos meses seguidos"
            else:
                head = f"{lbl} {'cae por debajo de' if dr == 'deterioro' else 'sube por encima de'} {abs(thr):.0f}" + f" ({x:.0f})"
            if blk:
                head += f", score {r.score:.0f}"
            txt = head + (f". Señales que más {'cambiaron (pts de score, 3m)' if how == 'pesa' else 'pesan (nivel)'}: {sen}" if sen else "")
            rows.append({"company_id": ids[i], "month": months[t], "tipo": tipo, "direccion": dr, "severidad": sev, "bloque": blk,
                         "score": float(r.score), "score_fast": float(r.score_fast), "texto": txt,
                         # solo evaluación (usa meses posteriores): la alerta 'rebotó' si en 1-2 meses volvió al lado sano
                         "rebota_2m": bool((y[i, t + 1:t + 3] < thr - hy).any()) if t + 2 < len(months) else np.nan})
    al = pd.DataFrame(rows, columns=["company_id", "month", "tipo", "direccion", "severidad", "bloque", "score", "score_fast", "texto", "rebota_2m"])
    # una crítica el mismo mes sustituye al aviso del mismo tipo/dirección
    al = al.sort_values(["company_id", "month", "tipo", "direccion", "bloque", "severidad"], ascending=[1, 1, 1, 1, 1, 0]).drop_duplicates(
        ["company_id", "month", "tipo", "direccion", "bloque"]).reset_index(drop=True)
    if out is not None:
        al.drop(columns="rebota_2m").to_parquet(out, index=False)
    return al, ids, months


MATCH = {"deterioro": {"ingresos": "b4 ingresos se secan (<50% base)", "liquidez": "b1 caja agotada (runway<0,5m)",
                       "pago": "b2 morosidad clientes se dispara"},
         "mejora": {"ingresos": "b4 ingresos crecen (>=150% base)", "liquidez": "b1 caja se recupera (runway>=2m)",
                    "pago": "b2 morosidad clientes se normaliza"}}   # evento observable que cada bloque debería anticipar


def precision(al, ids, months, path):
    """¿Qué fracción de las alertas fue seguida de un evento real en (t, t+H]? Base = misma pregunta para cualquier empresa-mes
    elegible (una alerta aleatoria acertaría eso). Eventos observables (b*) del panel bruto, no el score."""
    d, ids2, months2 = A.load(path)
    ev = A.build_events(d)
    ii, mm = {c: i for i, c in enumerate(ids2)}, {m: i for i, m in enumerate(months2)}
    res = {}
    for dr in ("deterioro", "mejora"):
        for tipo, sub in [("todas", al[al.direccion == dr])] + [(t, g) for t, g in al[al.direccion == dr].groupby("tipo")] + \
                         [(f"bloque {b}", g) for b, g in al[(al.direccion == dr) & (al.tipo == "bloque")].groupby("bloque")]:
            A_ = np.zeros(d["score"].shape, bool)
            sub = sub[sub.company_id.isin(ii)]
            A_[sub.company_id.map(ii).values, sub.month.map(mm).values] = True
            r = {"alertas": int(len(sub))}
            for en, lab in ((f"{dr}: b* cualquier evento observable", "observable"),
                            (f"{dr}: a1 score {'cae' if dr == 'deterioro' else 'sube'} >=15 pts (3m)", "score_15pts")):
                E, K = ev[dr, en.split(": ", 1)[1]]
                U = np.isfinite(E) & A_
                r[f"precision_{lab}"] = float(E[U].mean()) if U.any() else None
                r[f"base_{lab}"] = float(np.nanmean(E))
                r[f"n_{lab}"] = int(U.sum())
            r["rebota_2m"] = float(sub.rebota_2m.astype(float).mean())
            if sub.bloque.nunique() == 1 and sub.bloque.iloc[0] in MATCH[dr]:            # alertas de un bloque: su evento emparejado
                E, K = ev[dr, MATCH[dr][sub.bloque.iloc[0]]]
                U = np.isfinite(E) & A_
                r["evento_emparejado"], r["precision_emparejado"] = MATCH[dr][sub.bloque.iloc[0]], float(E[U].mean()) if U.any() else None
                r["base_emparejado"] = float(np.nanmean(E))
            m = A.evaluate(A_, *ev[dr, "b* cualquier evento observable"])
            r["recall_observable"], r["antelacion_mediana_observable"] = m.get("recall"), m.get("antelacion_mediana")
            res[f"{dr} | {tipo}"] = r
    return res


if __name__ == "__main__":
    a = sys.argv[1:]
    path = Path(a[0]) if a else D / "scores.parquet"
    out = Path(a[1]) if len(a) > 1 else D / "alerts.parquet"
    al, ids, months = run(path, out)
    n_cy = pd.read_parquet(path).score.notna().sum() / 12
    print(f"{len(al)} alertas ({len(al) / n_cy:.2f} por empresa-año puntuado) | empresas con >=1: {al.company_id.nunique()} de {len(ids)}")
    print("\nalertas por mes y dirección:\n" + al.groupby(["month", "direccion"]).size().unstack(fill_value=0).to_string())
    print("\npor tipo:\n" + al.groupby(["tipo", "direccion", "severidad", "bloque"]).size().to_string())
    pr = precision(al, ids, months, path)
    print("\nprecisión = fracción de alertas seguidas de un evento real observable en (t, t+6m), vs base (alerta aleatoria):")
    f = lambda v: "  -  " if v is None else f"{v:.2f}"
    for k_, r in pr.items():
        emp = f" | emparejado {f(r['precision_emparejado'])} (base {f(r['base_emparejado'])})" if "evento_emparejado" in r else ""
        print(f"  {k_:32s} n={r['alertas']:4d} obs {f(r['precision_observable'])} (base {f(r['base_observable'])}) rebota<=2m {f(r['rebota_2m'])} "
              f"recall {f(r['recall_observable'])} antel {f(r['antelacion_mediana_observable'])}{emp}")
    rep_f = out.parent / "anticipation_report.json"   # junto al parquet de alertas (en la ruta por defecto, data/clean/)
    rep = __import__("json").loads(rep_f.read_text()) if rep_f.exists() else {}
    rep["monitor"] = {"alertas": len(al), "alertas_por_empresa_anio": len(al) / n_cy, "empresas_con_alerta": int(al.company_id.nunique()),
                      "por_mes": al.groupby("month").size().to_dict(), "por_tipo": {" | ".join(k_): int(v) for k_, v in al.groupby(["tipo", "direccion", "severidad", "bloque"]).size().items()},
                      "alertas_por_empresa": al.groupby("company_id").size().describe().to_dict(), "precision": pr,
                      "config": {"WARN_LOW": WARN_LOW, "CRIT_LOW": CRIT_LOW, "WARN_HIGH": WARN_HIGH, "CRIT_HIGH": CRIT_HIGH, "BLOCK_LOW": BLOCK_LOW,
                                 "BLOCK_HIGH": BLOCK_HIGH, "HYST": HYST, "MIN_GAP": MIN_GAP, "WARMUP": WARMUP, "BLOCK_ALERTS": BLOCK_ALERTS, "ENABLED": ENABLED}}
    rep_f.write_text(__import__("json").dumps(rep, ensure_ascii=False, indent=1, default=lambda o: None))
    print("\nejemplos:")
    print(al.sample(8, random_state=1)[["company_id", "month", "texto"]].to_string(index=False, max_colwidth=200))
