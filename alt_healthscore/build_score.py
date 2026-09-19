"""Motor de scoring alternativo: notas -> pilares -> topes -> nivel + momento.

Entradas: data/panel_notas.csv + data/panel_metricas.csv
Salidas : data/scores_mensuales.csv + data/scores_finales.csv

Uso: py alt_healthscore/build_score.py [COMP_XXXX]
"""

import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"

PESOS_INTERNOS = {
    "caja":        {"nota_m01": 0.60, "nota_m02": 0.40},
    "cobro":       {"nota_m05": 0.50, "nota_m06": 0.50},
    "pago":        {"nota_m07": 0.60, "nota_m08": 0.40},
    "deuda":       {"nota_m10": 1.00},
    "estabilidad": {"nota_m11": 0.50, "nota_m12": 0.50},
}
PESOS_PILAR = {"caja": 0.30, "cobro": 0.20, "pago": 0.20, "deuda": 0.10, "estabilidad": 0.20}
VIDA_MEDIA = 6.0
UMBRAL_MOMENTO = 3.0
CLASES = [(80, "SALUDABLE"), (60, "ESTABLE"), (40, "EN RIESGO"), (20, "FRÁGIL")]


def media_ponderada(df, pesos):
    cols = list(pesos)
    w = pd.DataFrame({c: np.where(df[c].notna(), pesos[c], 0.0) for c in cols}, index=df.index)
    num = (df[cols].fillna(0.0) * w).sum(axis=1)
    den = w.sum(axis=1)
    return num.div(den.where(den > 0)), den / sum(pesos.values())


def clasificar(s):
    for umbral, etiqueta in CLASES:
        if s >= umbral:
            return etiqueta
    return "CRÍTICO"


d = pd.read_csv(DATA / "panel_notas.csv").merge(
    pd.read_csv(DATA / "panel_metricas.csv",
                usecols=["company_id", "year_month", "ingresos", "gastos",
                         "saldo_cierre", "n_tx"]),
    on=["company_id", "year_month"], how="left")
d = d.sort_values(["company_id", "year_month"]).reset_index(drop=True)

d["mes_fantasma"] = d["n_tx"].fillna(0) == 0

for pilar, pesos in PESOS_INTERNOS.items():
    d["P_" + pilar], _ = media_ponderada(d, pesos)
d["score_bruto"], d["peso_cubierto"] = media_ponderada(
    d, {"P_" + k: v for k, v in PESOS_PILAR.items()})
d.loc[d["mes_fantasma"], ["score_bruto", "peso_cubierto"]] = np.nan

TOPES = [
    ("sin ingresos con actividad", (d["ingresos"].fillna(0) <= 0) & ~d["mes_fantasma"], 45),
    ("un tercio del mes en rojo", d["m03_pct_dias_negativo"].fillna(0) > 0.33, 45),
    ("caja negativa al cierre", d["saldo_cierre"].fillna(0) < 0, 45),
    ("menos de una semana de caja", d["m01_runway_meses"].fillna(99) < 0.25, 50),
    ("servicio de deuda > 25%", d["m09_servicio_deuda"].fillna(0) > 0.25, 55),
    ("devoluciones > 5%", d["m04_ratio_devoluciones"].fillna(0) > 0.05, 55),
]
techo = pd.Series(100.0, index=d.index)
motivos = pd.Series("", index=d.index)
for nombre, cond, limite in TOPES:
    c = cond.fillna(False) & d["score_bruto"].notna()
    techo = techo.where(~c, np.minimum(techo, limite))
    motivos = motivos.where(~c, motivos + nombre + "; ")

d["score_mes"] = np.minimum(d["score_bruto"], techo)
d["topes_activos"] = motivos.str.rstrip("; ")
d["gasto_cero"] = (d["gastos"].fillna(0) <= 0) & (d["ingresos"].fillna(0) > 0)
d["nivel"] = d.groupby("company_id")["score_mes"].transform(
    lambda s: s.ewm(halflife=VIDA_MEDIA, ignore_na=True).mean())


def resumen(sub):
    s = sub.dropna(subset=["score_mes"])
    if s.empty:
        return pd.Series({"score_final": np.nan, "momento": np.nan, "n_meses": 0})
    ult3 = s["score_mes"].tail(3).mean()
    prev3 = s["score_mes"].iloc[-6:-3].mean() if len(s) >= 4 else np.nan
    return pd.Series({
        "score_final": s["nivel"].iloc[-1],
        "score_ultimo_mes": s["score_mes"].iloc[-1],
        "momento": ult3 - prev3,
        "n_meses": len(s),
        "ultimo_mes": s["year_month"].iloc[-1],
        "peso_cubierto": s["peso_cubierto"].iloc[-1],
        "confianza": s["confianza"].iloc[-1],
        "topes_activos": s["topes_activos"].iloc[-1],
        "gasto_cero": bool(s["gasto_cero"].iloc[-1]),
        **{"P_" + k: s["P_" + k].iloc[-1] for k in PESOS_PILAR},
    })


fin = d.groupby("company_id").apply(resumen, include_groups=False).reset_index()
fin["clase"] = fin["score_final"].apply(lambda v: clasificar(v) if pd.notna(v) else "SIN DATOS")
fin["tendencia"] = np.select(
    [fin["momento"] > UMBRAL_MOMENTO, fin["momento"] < -UMBRAL_MOMENTO],
    ["MEJORANDO", "DETERIORANDO"], default="ESTABLE")
fin.loc[fin["momento"].isna(), "tendencia"] = "SIN HISTORIA"
fin = fin.merge(d[["company_id", "group_id"]].drop_duplicates(), on="company_id")

d.to_csv(DATA / "scores_mensuales.csv", index=False)
fin.to_csv(DATA / "scores_finales.csv", index=False)

print(f"meses fantasma anulados : {d['mes_fantasma'].sum():,}")
print(f"empresas puntuadas      : {fin['score_final'].notna().sum()} de {len(fin)}")

objetivo = sys.argv[1] if len(sys.argv) > 1 else None
if objetivo:
    f = fin[fin["company_id"] == objetivo]
    if f.empty:
        print(f"{objetivo} no encontrada")
    else:
        r = f.iloc[0]
        print(f"\n{objetivo}  score={r['score_final']:.1f}  {r['clase']}  {r['tendencia']}")
        print(f"  ultimo mes={r['score_ultimo_mes']:.1f}  momento={r['momento']:+.1f}")
        if r["topes_activos"] and str(r["topes_activos"]) != "nan":
            print(f"  topes: {r['topes_activos']}")
