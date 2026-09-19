"""Calibra anclajes 0-100 sobre un subconjunto oro y los aplica a todas las empresas.

Entrada : data/panel_metricas.csv
Salidas : alt_healthscore/anclajes.json  +  data/panel_notas.csv
"""

import json
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
PANEL = ROOT / "data" / "panel_metricas.csv"
SALIDA = ROOT / "data" / "panel_notas.csv"
CONFIG = Path(__file__).resolve().parent / "anclajes.json"

MIN_MESES_ORO = 12
MAX_SIN_CATEGORIA_ORO = 0.5

ESPEC = {
    "m01_runway_meses":          ("log", 10, 90),
    "m02_flujo_relativo_3m":     ("lin", 10, 90),
    "m03_pct_dias_negativo":     ("lin", 95, 0),
    "m04_ratio_devoluciones":    ("lin", 99, 0),
    "m05_dso_dias":              ("lin", 90, 10),
    "m06_stock_clientes_rel":    ("log", 90, 0),
    "m07_cobertura_ineludible":  ("log", 10, 90),
    "m08_stock_proveedores_rel": ("log", 90, 0),
    "m09_servicio_deuda":        ("lin", 95, 0),
    "m10_coste_financiero":      ("lin", 95, 0),
    "m11_volatilidad_6m":        ("log", 90, 10),
    "m12_tendencia_cobros_6m":   ("lin", 10, 80),
}

PILARES = {
    "caja":        ["m01_runway_meses", "m02_flujo_relativo_3m", "m03_pct_dias_negativo"],
    "cobro":       ["m04_ratio_devoluciones", "m05_dso_dias", "m06_stock_clientes_rel"],
    "pago":        ["m07_cobertura_ineludible", "m08_stock_proveedores_rel"],
    "deuda":       ["m09_servicio_deuda", "m10_coste_financiero"],
    "estabilidad": ["m11_volatilidad_6m", "m12_tendencia_cobros_6m"],
}
METRICAS = list(ESPEC)


def transformar(s, modo):
    return np.log1p(s.clip(lower=0)) if modo == "log" else s


def aplicar(s, anc):
    x = transformar(s, anc["transformacion"])
    v0, v100 = anc["valor_cero"], anc["valor_cien"]
    if v0 == v100:
        return pd.Series(np.nan, index=s.index)
    return (100 * (x - v0) / (v100 - v0)).clip(0, 100)


p = pd.read_csv(PANEL)
oro = (
    (p["meses_historia"] >= MIN_MESES_ORO)
    & (p["pct_sin_categoria"].fillna(1) < MAX_SIN_CATEGORIA_ORO)
    & (p["n_tx"] > 0)
)
print(f"subconjunto oro: {oro.sum():,} filas ({oro.mean():.1%}) | "
      f"{p.loc[oro, 'company_id'].nunique()} empresas")

anclajes = {}
for m, (modo, p_cero, p_cien) in ESPEC.items():
    base = transformar(p.loc[oro, m].dropna(), modo)
    v0 = float(np.percentile(base, p_cero))
    v100 = float(np.percentile(base, p_cien))
    anclajes[m] = {
        "transformacion": modo,
        "percentil_cero": p_cero,
        "percentil_cien": p_cien,
        "valor_cero": v0,
        "valor_cien": v100,
        "n_calibracion": int(len(base)),
    }

notas = pd.DataFrame(index=p.index)
for m in METRICAS:
    notas["nota_" + m[:3]] = aplicar(p[m], anclajes[m])
cols_nota = list(notas.columns)
p = pd.concat([p, notas], axis=1)
p["n_metricas"] = p[cols_nota].notna().sum(axis=1)

for pilar, ms in PILARES.items():
    p["pilar_" + pilar] = p[["nota_" + m[:3] for m in ms]].mean(axis=1)

alta = (p["meses_historia"] >= 18) & (p["pct_sin_categoria"].fillna(1) < 0.3) & (p["n_metricas"] >= 8)
media = (p["meses_historia"] >= 12) & (p["n_metricas"] >= 6)
p["confianza"] = np.select([alta, media], ["alta", "media"], default="baja")

COLS = (["company_id", "year_month", "group_id"] + METRICAS + cols_nota
        + ["pilar_" + k for k in PILARES] + ["n_metricas", "confianza",
           "meses_historia", "pct_sin_categoria", "tiene_facturas",
           "divisa_mixta", "caja_incompleta"])
p[COLS].to_csv(SALIDA, index=False)
CONFIG.write_text(json.dumps({
    "criterios_oro": {"min_meses": MIN_MESES_ORO, "max_sin_categoria": MAX_SIN_CATEGORIA_ORO},
    "anclajes": anclajes,
}, indent=2), encoding="utf-8")
print(f"escrito {SALIDA} y {CONFIG}")
