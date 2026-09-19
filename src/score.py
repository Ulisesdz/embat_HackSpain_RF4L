"""Score de salud financiera 0-100 por empresa y mes, en 4 bloques (liquidez, pago, financiación, ingresos).

Uso: python3 src/score.py [dir_datos]     lee data/clean/panel.parquet, escribe scores.parquet y scores_group.parquet
     python3 src/score.py explain COMP_0001 [2026-08]

Método (sin etiquetas, sin modelo ajustado). Dos modos, `SCORE_MODE=abs` (por defecto) o `rel`:
  1. Señales suavizadas (ventana lenta 6m y rápida 3m), todas en ratios.
  2. abs  -> cada señal se puntúa 0-100 con una curva económica FIJA (p. ej. 4+ meses de caja = 100, 0 meses = 0). No
             depende de ninguna otra empresa: el score es absoluto e independiente y su distribución es la que sale.
     rel  -> percentil frente a una referencia congelada -> z (curva normal) -> 50 + 15 z. Relativo: 50 = empresa mediana.
  3. score = media ponderada de las señales (dato ausente = neutro 50). El score ES el nivel; la tendencia va aparte.
"""
import json
import os
import sys
from statistics import NormalDist
from pathlib import Path

import numpy as np
import pandas as pd

import trend as TREND

ARGS = sys.argv[1:]
EXPLAIN = ARGS[:1] == ["explain"]
D = Path((ARGS[0] if ARGS and not EXPLAIN else "data")) / "clean"

# señal -> (bloque, peso, sentido: +1 mayor es mejor / -1 mayor es peor, etiqueta legible)
SIGNALS = {
    "runway":         ("liquidez",     0.24,  +1, "Meses de caja (saldo / gasto mensual)"),
    "net_margin":     ("liquidez",     0.07,  +1, "Generación de caja (cobros - pagos)"),
    "ar_overdue":     ("pago",         0.10,  -1, "Clientes que no pagan a vencimiento"),
    "ap_overdue":     ("pago",         0.10,  -1, "Facturas de proveedores vencidas sin pagar"),
    "ar_days_late":   ("pago",         0.04,  -1, "Retraso medio de cobro a clientes"),
    "ap_days_late":   ("pago",         0.03,  -1, "Retraso medio de pago a proveedores"),
    "refund_rate":    ("pago",         0.06,  -1, "Recibos devueltos sobre cobros"),
    "debt_service":   ("financiacion", 0.05,  -1, "Peso del servicio de deuda sobre ingresos"),
    "leverage":       ("financiacion", 0.04,  -1, "Deuda viva sobre ingresos anuales"),
    "inflow_cv":      ("ingresos",     0.07,  -1, "Volatilidad de los ingresos mensuales"),
    "zero_months":    ("ingresos",     0.13,  -1, "Meses sin ingresos"),
    "top1_customer":  ("ingresos",     0.03,  -1, "Dependencia del mayor cliente"),
    "growth":         ("ingresos",     0.04,  +1, "Crecimiento de ingresos (vs ventana anterior)"),
}
BLOCKS = ["liquidez", "pago", "financiacion", "ingresos"]
W = pd.Series({k: v[1] for k, v in SIGNALS.items()})
BLOCK = pd.Series({k: v[0] for k, v in SIGNALS.items()})
LABEL = {k: v[3] for k, v in SIGNALS.items()}
SIGN = pd.Series({k: v[2] for k, v in SIGNALS.items()})
MIN_CONF = 0.45  # peso mínimo de señales observadas para puntuar
SLOW, FAST = 6, 3  # meses. El score es la versión lenta; la rápida sirve para detectar baches
MODE = os.environ.get("SCORE_MODE", "abs")

# Modo abs: señal -> puntos 0-100 por interpolación lineal entre estos nudos (valor natural, puntos). Criterio económico,
# no ajustado a datos. Fuera de los extremos se queda en el primero/último. Sin deuda ni pagos de deuda = NO_DEBT puntos.
CURVES = {
    "runway":        [(0, 0), (0.25, 15), (0.5, 30), (1, 50), (2, 75), (3, 90), (4, 100)],  # meses de gasto en caja (la caja mediana es 0,7)
    "net_margin":    [(-0.5, 0), (-0.2, 30), (0, 60), (0.15, 85), (0.3, 100)],       # (cobros-pagos)/(cobros+pagos)
    "ar_overdue":    [(0, 100), (0.1, 90), (0.3, 65), (0.6, 30), (0.9, 0)],          # % vencido sin cobrar (90 días)
    "ap_overdue":    [(0, 100), (0.1, 90), (0.3, 65), (0.6, 30), (0.9, 0)],          # % vencido sin pagar
    "ar_days_late":  [(0, 100), (10, 80), (30, 50), (60, 15), (90, 0)],              # días de retraso de cobro
    "ap_days_late":  [(0, 100), (10, 80), (30, 50), (60, 15), (90, 0)],              # días de retraso de pago
    "refund_rate":   [(0, 100), (0.005, 80), (0.02, 40), (0.05, 0)],                 # recibos devueltos / cobros
    "debt_service":  [(0, 100), (0.1, 80), (0.25, 40), (0.5, 0)],                    # servicio de deuda / ingresos
    "leverage":      [(0, 100), (0.5, 75), (1, 45), (2, 15), (3, 0)],                # deuda viva / ingresos anuales
    "inflow_cv":     [(0.3, 100), (0.7, 72), (1.2, 35), (2, 0)],                     # variabilidad de ingresos
    "zero_months":   [(0, 100), (0.17, 55), (0.33, 20), (0.5, 0)],                   # fracción de meses sin ingresos
    "top1_customer": [(0.3, 100), (0.6, 70), (0.9, 30), (1, 15)],                    # peso del mayor cliente
    "growth":        [(-0.7, 0), (-0.2, 40), (0, 65), (0.3, 90), (0.6, 100)],        # log-crecimiento de ingresos
}
NO_DEBT = 75
CUTS = (40, 55, 70) if MODE == "abs" else (35, 50, 65)  # frágil < c0 <= débil < c1 <= sana < c2 <= sólida


def signals(p, win):
    """Señales suavizadas sobre una ventana de `win` meses a partir del panel bruto."""
    p = p.sort_values(["company_id", "month"]).reset_index(drop=True)
    g = p.groupby("company_id")
    mp = max(2, win * 2 // 3)
    rs = lambda c: g[c].transform(lambda s: s.rolling(win, min_periods=mp).sum())
    inflow, outflow, coll = rs("inflow"), rs("outflow"), rs("collections")
    s = pd.DataFrame({"company_id": p.company_id, "month": p.month})
    roll = lambda c, f: g[c].transform(lambda x: x.rolling(win, min_periods=mp).agg(f))  # media/desv. por mes observado
    s["net_margin"] = (inflow - outflow) / (inflow + outflow).where(lambda x: x > 0)
    s["runway"] = (p.cash_end / roll("outflow", "mean").where(lambda x: x > 0)).clip(-3, 12)
    s["debt_service"] = (rs("debt_service") / inflow.where(inflow > 0)).clip(0, 2)
    s["refund_rate"] = (rs("returned_receipts") / coll.where(coll > 0)).clip(0, 1)
    s["leverage"] = (p.debt_outstanding / (12 * roll("inflow", "mean")).where(lambda x: x > 0)).clip(0, 5)
    s["inflow_cv"] = (roll("inflow", "std") / roll("inflow", "mean").where(lambda x: x > 0)).clip(0, 3)
    p["no_inflow"] = (p.inflow <= 0).astype(float).where(p.inflow.notna())
    s["zero_months"] = g.no_inflow.transform(lambda x: x.rolling(win, min_periods=mp).mean())
    s["no_debt"] = (p.debt_outstanding == 0) & (rs("debt_service") == 0)  # sin deuda: no es ni buena ni mala señal
    s["growth"] = np.log1p(inflow).sub(np.log1p(inflow.groupby(p.company_id).shift(win))).clip(-2, 2)
    for k, name in [("ar_overdue_ratio", "ar_overdue"), ("ap_overdue_ratio", "ap_overdue"), ("ar_days_late", "ar_days_late"),
                    ("ap_days_late", "ap_days_late"), ("ar_top1_share", "top1_customer")]:
        s[name] = g[k].transform(lambda x: x.rolling(win, min_periods=1).mean())
    return s[p.observed.values].reset_index(drop=True)


NQ = 1001                                    # puntos de la rejilla de cuantiles de referencia
PPF = np.array([NormalDist().inv_cdf(min(max(i / (2 * NQ), 0.001), 0.999)) for i in range(2 * NQ + 1)])
TREND_SD = json.loads(TREND.REP.read_text())["coefs"]["3"]["resid_sd"] if TREND.REP.exists() else float("nan")
SCALE = 15                                   # puntos de score por desviación típica de level_z
REF = D / "reference.json"


def to_z(s, q):
    """Señales -> z (alto = sano). Percentil de rango medio frente a la rejilla `q` (así los empates en 0 no sesgan)."""
    out = s[["company_id", "month"]].copy()
    for k in SIGNALS:
        x, g = s[k].to_numpy(float), np.asarray(q[k])
        z = SIGN[k] * PPF[np.searchsorted(g, x, "left") + np.searchsorted(g, x, "right")]
        out[k] = np.where(np.isnan(x), np.nan, z)
    out.loc[s.no_debt, ["debt_service", "leverage"]] = 0.0  # sin deuda: neutro, y cuenta como observado
    return out


def to_sub(s):
    """Modo abs: señales -> puntos 0-100 por su curva; se devuelve (puntos - 50) para compartir formato con el modo rel."""
    out = s[["company_id", "month"]].copy()
    for k, pts in CURVES.items():
        xs, ys = zip(*pts)
        out[k] = np.where(s[k].isna(), np.nan, np.interp(s[k].fillna(0), xs, ys) - 50)
    out.loc[s.no_debt, ["debt_service", "leverage"]] = NO_DEBT - 50
    return out


def kpt():
    """Puntos de score por unidad de z (para repartir el score entre señales): 1 en abs, SCALE/sd en rel."""
    return 1.0 if MODE == "abs" else SCALE / json.loads(REF.read_text())[str(SLOW)]["sd_level"]


def blocks_z(z):
    filled = z[list(SIGNALS)].fillna(0)
    b = {n: (filled[BLOCK.index[BLOCK == n]] * W[BLOCK == n]).sum(axis=1) / W[BLOCK == n].sum() for n in BLOCKS}
    return (filled * W).sum(axis=1), pd.DataFrame(b)


def fit_reference(p):
    """Congela la referencia con el panel de entrenamiento: cuantiles por señal y dispersión de level_z y de cada bloque."""
    ref = {}
    for win in (SLOW, FAST):
        s = signals(p, win)
        # deuda: el percentil se calcula solo entre empresas endeudadas (sin deuda ya es neutro), si no los ceros sesgan
        q = {k: np.nanquantile(s[k][~s.no_debt] if k in ("debt_service", "leverage") else s[k], np.linspace(0, 1, NQ)).tolist()
             for k in SIGNALS}
        lvl, blk = blocks_z(to_z(s, q))
        ref[str(win)] = {"q": q, "sd_level": float(lvl.std()), "sd_block": {b: float(blk[b].std()) for b in BLOCKS}}
    REF.write_text(json.dumps(ref))
    return ref


def score_win(p, win, ref):
    s = signals(p, win)
    if MODE == "abs":
        z, k, kb = to_sub(s), 1.0, {b: 1.0 for b in BLOCKS}
    else:
        r = ref[str(win)]
        z, k, kb = to_z(s, r["q"]), SCALE / r["sd_level"], {b: SCALE / r["sd_block"][b] for b in BLOCKS}
    lvl, blk = blocks_z(z)
    z["confidence"] = z[list(SIGNALS)].notna().mul(W, axis=1).sum(axis=1)  # peso de las señales realmente observadas
    z["score"] = (50 + k * lvl).clip(0, 100).where(z.confidence >= MIN_CONF)  # sin caja ni generación de caja no se puntúa
    for b in BLOCKS:
        z[b] = (50 + kb[b] * blk[b]).clip(0, 100)
    return z


def score_all(p, ref=None):
    ref = ref or ((json.loads(REF.read_text()) if REF.exists() else fit_reference(p)) if MODE == "rel" else None)
    s = score_win(p, SLOW, ref)
    s["score_fast"] = score_win(p, FAST, ref).score
    g = s.groupby("company_id")
    s["d1"] = g.score.diff()
    s["d3"] = s.score - g.score.shift(3)
    s["d6"] = s.score - g.score.shift(6)                 # descriptivo: lo que pasó (revierte, NO predice)
    s["trend"] = s.d6 / 6                                # puntos/mes; NaN si no hay 6 meses de historia
    s["gap"] = s.score_fast - s.score                    # <0: el último trimestre está por debajo de lo habitual
    if TREND.REP.exists():                               # cambio esperado a 3 meses con coeficientes congelados
        s = s.merge(TREND.predict_change(s, 3)[["company_id", "month", "exp_change"]], on=["company_id", "month"], how="left")
        s = s.rename(columns={"exp_change": "exp_change3"})
    else:
        s["exp_change3"] = np.nan
    s["label"] = classify(s)
    return s


BLIP, UP, DOWN = -11, TREND.UMBRAL[3], -TREND.UMBRAL[3]  # puntos


def classify(s):
    """Nivel + dirección. 'mejorando'/'deteriorando' = cambio ESPERADO del score a 3 meses (src/trend.py, validado fuera de
    muestra); 'bache puntual' = el trimestre reciente cae >= 11 pts bajo la base de 6 meses."""
    level = pd.cut(s.score, [-1, *CUTS, 101], labels=["frágil", "débil", "sana", "sólida"]).astype(object)
    return pd.Series(np.select(
        [s.score.isna(), s.gap <= BLIP, s.exp_change3 <= DOWN, s.exp_change3 >= UP],
        ["sin datos", "bache puntual", "deteriorando", "mejorando"], default=level.fillna("sin datos")), index=s.index)


def explain(s, company, month=None):
    r = s[s.company_id == company].sort_values("month")
    month = month or r.month.iloc[-1]
    i = r.index[r.month == month][0]
    z = lambda x: x[list(SIGNALS)].astype(float).fillna(0)
    cur, prev, prev6 = z(r.loc[i]), z(r.shift(1).loc[i]), z(r.shift(6).loc[i])
    head = r.loc[i]
    k = kpt()   # z -> puntos de score
    contrib = k * W * cur
    fmt = lambda ch: ", ".join(f"{LABEL[n]} {c:+.1f}" for n, c in ch.sort_values(key=abs, ascending=False).head(3).items() if abs(c) >= 0.1) or "sin cambios relevantes"
    lines = [f"{company} {month}: score {head.score:.1f} | {head.label} | confianza {head.confidence:.0%}",
             "  bloques: " + " | ".join(f"{b} {head[b]:.0f}" for b in BLOCKS)]
    lines += [f"  {c:+5.1f}  {LABEL[n]} ({"nota %d/100" % (cur[n] + 50) if MODE == "abs" else "mejor que el %.0f%% de las empresas" % (100 * NormalDist().cdf(cur[n]))})"
              for n, c in contrib.sort_values(key=abs, ascending=False).head(4).items()]
    lines.append(f"  vs mes anterior: {head.d1:+.1f} pts  <- {fmt(k * W * (cur - prev))}" if not np.isnan(head.d1) else "  vs mes anterior: sin dato")
    lines.append(f"  vs hace 6 meses: {head.d6:+.1f} pts  <- {fmt(k * W * (cur - prev6))}" if not np.isnan(head.d6) else "  vs hace 6 meses: sin historia suficiente")
    if not np.isnan(head.exp_change3):
        lines.append(f"  esperado a 3 meses: {head.exp_change3:+.1f} pts (sobre todo reversión al nivel propio; ±{TREND_SD:.0f} pts de error típico)")
    lines.append(f"  trimestre reciente (rápido) {head.score_fast:.1f} vs base 6m {head.score:.1f}")
    return "\n".join(lines)


if __name__ == "__main__":
    panel = pd.read_parquet(D / "panel.parquet")
    sc = score_all(panel)
    sc.to_parquet(D / "scores.parquet", index=False)
    if not TREND.REP.exists():  # primera vez (o tras cambiar pesos: borra trend_report.json): ajusta la tendencia y reetiqueta
        TREND.main(D / "scores.parquet")
        sc = score_all(panel)
        sc.to_parquet(D / "scores.parquet", index=False)
    co = pd.read_parquet(D / "companies.parquet")[["company_id", "group_id"]]
    gs = sc.merge(co, on="company_id").groupby(["group_id", "month"]).agg(
        score=("score", "mean"), trend=("trend", "mean"), n_companies=("score", "count")).reset_index()
    gs.to_parquet(D / "scores_group.parquet", index=False)
    if EXPLAIN:
        print(explain(sc, ARGS[1], ARGS[2] if len(ARGS) > 2 else None))
    else:
        last = sc[sc.month == "2026-08"]
        print(f"{len(sc)} filas empresa-mes | mes 2026-08: {last.score.notna().sum()} empresas puntuadas")
        print(last.score.describe().round(1).to_string()); print(last.label.value_counts().to_string())
