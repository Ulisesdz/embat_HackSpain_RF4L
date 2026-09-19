"""
Validador del panel maestro. No modifica datos.

Falla con código 1 si alguna invariante estructural, temporal o numérica se rompe.
Ejecutar siempre antes de puntuar.
"""

import json
import sys
import numpy as np
import pandas as pd

import data_analysis.config as cfg

ERRORES = 0


def ok(msg):
    print(f"[ OK ] {msg}")


def fail(msg):
    global ERRORES
    ERRORES += 1
    print(f"[FAIL] {msg}")


def warn(msg):
    print(f"[WARN] {msg}")


def check_required(df, cols):
    missing = [c for c in cols if c not in df.columns]
    if missing:
        fail(f"Faltan columnas obligatorias: {missing}")
        return False
    ok("Columnas obligatorias presentes")
    return True


def main():
    global ERRORES

    if not cfg.PANEL_PATH.exists():
        raise FileNotFoundError(
            f"No existe {cfg.PANEL_PATH}. Ejecuta build_features.py."
        )

    df = pd.read_csv(cfg.PANEL_PATH)
    if df.empty:
        fail("El panel está vacío")
        sys.exit(1)

    required = [
        "company_id", "year_month", "flujo_neto",
        "caja_ingresos", "caja_gastos", "volumen_ventas",
        "volumen_compras", "deuda_viva",
        "pct_clientes_morosos", "pct_impagos_prov",
        "pct_clientes_morosos_3m", "pct_impagos_prov_3m",
        "flujo_neto_3m_avg", "flujo_neto_6m_avg",
        "clientes_morosos_3m_avg", "impagos_prov_3m_avg",
        "caja_reportada", "mes_parcial", "confianza",
    ]
    if not check_required(df, required):
        sys.exit(1)

    try:
        df["year_month"] = pd.PeriodIndex(df["year_month"], freq="M")
    except Exception as exc:
        fail(f"year_month no puede convertirse a Period[M]: {exc}")
        sys.exit(1)

    esperados = set(cfg.MONTHS)
    companies = df["company_id"].dropna().unique()

    # -------------------------------------------------------------------------
    # Calendario
    # -------------------------------------------------------------------------
    if len(companies) == 0:
        fail("No hay empresas")
    else:
        counts = df.groupby("company_id")["year_month"].nunique()
        if counts.min() != len(cfg.MONTHS) or counts.max() != len(cfg.MONTHS):
            fail("Alguna empresa no tiene exactamente 25 buckets mensuales")
        else:
            ok(f"Cada empresa tiene exactamente {len(cfg.MONTHS)} meses")

        malos = [
            c for c, g in df.groupby("company_id")
            if set(g["year_month"]) != esperados
        ]
        if malos:
            fail(f"Calendario incorrecto en {len(malos)} empresas")
        else:
            ok("Calendario coincide exactamente con cfg.MONTHS")

    dup = int(df.duplicated(["company_id", "year_month"]).sum())
    if dup:
        fail(f"Hay {dup} duplicados company_id + year_month")
    else:
        ok("No hay duplicados company_id + year_month")

    # -------------------------------------------------------------------------
    # Identidad de caja
    # -------------------------------------------------------------------------
    mismatch = ~np.isclose(
        df["caja_ingresos"].fillna(0) - df["caja_gastos"].fillna(0),
        df["flujo_neto"].fillna(0),
        atol=1e-6,
        equal_nan=False,
    )
    if mismatch.any():
        fail(f"Identidad flujo_neto = ingresos - gastos rota en {int(mismatch.sum())} filas")
    else:
        ok("Identidad flujo_neto = ingresos - gastos")

    # -------------------------------------------------------------------------
    # Ratios
    # -------------------------------------------------------------------------
    ratio_cols = [
        "pct_clientes_morosos", "pct_impagos_prov",
        "pct_clientes_morosos_3m", "pct_impagos_prov_3m",
    ]
    for c in ratio_cols:
        bad = df[c].notna() & ((df[c] < 0) | (df[c] > 100))
        if bad.any():
            fail(f"{c}: {int(bad.sum())} valores fuera de [0,100]")
        else:
            ok(f"{c}: rango válido")

    # -------------------------------------------------------------------------
    # No negatividad de magnitudes que por construcción lo exigen
    # -------------------------------------------------------------------------
    nonnegative = [
        "caja_ingresos", "caja_gastos", "volumen_ventas",
        "atrapado_ventas", "volumen_compras", "atrapado_compras",
        "stock_overdue_clientes", "stock_overdue_prov",
        "n_tx", "n_fact_ventas", "n_fact_compras",
    ]
    for c in nonnegative:
        if c not in df.columns:
            continue
        bad = df[c].notna() & (df[c] < 0)
        if bad.any():
            fail(f"{c}: {int(bad.sum())} valores negativos")
        else:
            ok(f"{c}: no negatividad")

    # -------------------------------------------------------------------------
    # Finitud numérica
    # -------------------------------------------------------------------------
    numeric = df.select_dtypes(include=[np.number]).columns
    inf_cols = []
    for c in numeric:
        if np.isinf(df[c].to_numpy(dtype=float)).any():
            inf_cols.append(c)
    if inf_cols:
        fail(f"Hay +/-inf en columnas: {inf_cols}")
    else:
        ok("No hay +/-inf en variables numéricas")

    # -------------------------------------------------------------------------
    # Rolling estricto
    # -------------------------------------------------------------------------
    strict_3m = [
        "flujo_neto_3m_avg",
        "clientes_morosos_3m_avg",
        "impagos_prov_3m_avg",
    ]
    strict_6m = ["flujo_neto_6m_avg"]

    for c in strict_3m:
        if c not in df.columns:
            continue
        first = df.groupby("company_id")[c].nth(0)
        second = df.groupby("company_id")[c].nth(1)
        if first.notna().any() or second.notna().any():
            fail(f"{c}: rolling 3m aparece antes de completar 3 meses")
        else:
            ok(f"{c}: rolling 3m estricto")

    for c in strict_6m:
        if c not in df.columns:
            continue
        first5 = df.groupby("company_id")[c].nth(list(range(5)))
        if first5.notna().any():
            fail(f"{c}: rolling 6m aparece antes de completar 6 meses")
        else:
            ok(f"{c}: rolling 6m estricto")

    # -------------------------------------------------------------------------
    # Disciplina de denominadores
    # -------------------------------------------------------------------------
    if "volumen_ventas" in df:
        bad = (df["volumen_ventas"] == 0) & df["pct_clientes_morosos"].notna()
        if bad.any():
            fail("pct_clientes_morosos no es NA cuando volumen_ventas == 0")
        else:
            ok("Morosidad de clientes respeta denominador")

    if "volumen_compras" in df:
        bad = (df["volumen_compras"] == 0) & df["pct_impagos_prov"].notna()
        if bad.any():
            fail("pct_impagos_prov no es NA cuando volumen_compras == 0")
        else:
            ok("Morosidad de proveedores respeta denominador")

    # -------------------------------------------------------------------------
    # Snapshot financiero: jamás backfilled
    # -------------------------------------------------------------------------
    ultimo_mes = max(m for m in cfg.MONTHS if m not in set(cfg.PARTIAL_MONTHS))
    snap = (
        df["caja_reportada"].eq(1)
        | df["deuda_viva"].notna()
    )
    fuera = snap & (df["year_month"] != ultimo_mes)
    if fuera.any():
        fail(
            f"Snapshot financiero propagado fuera de {ultimo_mes}: "
            f"{int(fuera.sum())} filas"
        )
    else:
        ok(f"Caja/deuda solo aparecen en el último mes completo ({ultimo_mes})")

    bad_caja = df["caja_reportada"].isin([0, 1]) == False
    if bad_caja.any():
        fail("caja_reportada contiene valores distintos de 0/1")
    else:
        ok("caja_reportada es binaria")

    bad_semantics = (
        df["caja_reportada"].eq(1) & df["caja_real"].isna()
    ) | (
        df["caja_reportada"].eq(0) & df["caja_real"].notna()
    )
    if bad_semantics.any():
        fail("caja_reportada no coincide con la disponibilidad de caja_real")
    else:
        ok("Semántica caja_reportada/caja_real consistente")

    # -------------------------------------------------------------------------
    # Parcial y evidencia
    # -------------------------------------------------------------------------
    partial_flag = df["year_month"].isin(cfg.PARTIAL_MONTHS).astype(int)
    if not np.array_equal(partial_flag.to_numpy(), df["mes_parcial"].to_numpy()):
        fail("mes_parcial no coincide con cfg.PARTIAL_MONTHS")
    else:
        ok("mes_parcial coincide con configuración")

    if "peso_cubierto" in df.columns:
        bad = df["peso_cubierto"].notna() & (
            (df["peso_cubierto"] < 0) | (df["peso_cubierto"] > 1)
        )
        if bad.any():
            fail("peso_cubierto fuera de [0,1]")
        else:
            ok("peso_cubierto en [0,1]")

    if "meses_activos_acum" in df.columns:
        bad = df["meses_activos_acum"] < 0
        if bad.any():
            fail("meses_activos_acum negativo")
        else:
            ok("meses_activos_acum válido")

    low_share = float((df["confianza"] == "baja").mean())
    if low_share > 0.30:
        warn(f"Confianza baja en {low_share:.1%} de las filas (>30%)")
    else:
        ok(f"Confianza baja en {low_share:.1%} de las filas")

    if "snapshot_financiero_disponible" in df.columns:
        bad = (
            df["snapshot_financiero_disponible"].eq(1)
            & (df["year_month"] != ultimo_mes)
        )
        if bad.any():
            fail("snapshot_financiero_disponible activo fuera del último mes completo")
        else:
            ok("snapshot_financiero_disponible no se backfillea")

    # -------------------------------------------------------------------------
    # IDs
    # -------------------------------------------------------------------------
    if df["company_id"].isna().any():
        fail("Hay company_id nulos")
    else:
        ok("No hay company_id nulos")

    print("\n=== RESUMEN VALIDACIÓN ===")
    print(f"Filas: {len(df):,}")
    print(f"Empresas: {df['company_id'].nunique():,}")
    print(f"Columnas: {df.shape[1]:,}")
    print(f"Errores: {ERRORES}")

    if cfg.AUDIT_PATH.exists():
        audit = json.loads(cfg.AUDIT_PATH.read_text(encoding="utf-8"))
        print("\n=== AUDITORÍA ===")
        for k, v in audit.items():
            print(f"{k}: {v}")

    if ERRORES:
        sys.exit(1)


if __name__ == "__main__":
    main()