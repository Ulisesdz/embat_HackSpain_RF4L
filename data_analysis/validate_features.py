"""Validador del panel maestro. No modifica datos.

Falla con código 1 si alguna invariante se rompe. Ejecutar siempre antes de
puntuar: un panel que no pasa estas pruebas invalida cualquier score.
"""

import json
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


def main():
    global ERRORES
    if not cfg.PANEL_PATH.exists():
        raise FileNotFoundError(f"No existe {cfg.PANEL_PATH}. Ejecuta build_features.py.")

    df = pd.read_csv(cfg.PANEL_PATH)
    df["year_month"] = pd.PeriodIndex(df["year_month"], freq="M")
    esperados = set(cfg.MONTHS)

    # 1. Cobertura temporal
    counts = df.groupby("company_id")["year_month"].nunique()
    if counts.min() != len(cfg.MONTHS) or counts.max() != len(cfg.MONTHS):
        fail(f"Cada empresa debe tener {len(cfg.MONTHS)} meses; "
             f"min={counts.min()}, max={counts.max()}")
    else:
        ok(f"Todas las empresas tienen {len(cfg.MONTHS)} buckets mensuales.")

    # 2. Calendario exacto
    malos = [c for c, g in df.groupby("company_id")
             if set(pd.PeriodIndex(g["year_month"], freq="M")) != esperados]
    if malos:
        fail(f"Empresas con calendario incorrecto: {len(malos)}")
    else:
        ok("Calendario alineado en todas las empresas.")

    # 3. Duplicados
    dup = int(df.duplicated(["company_id", "year_month"]).sum())
    fail(f"Duplicados company_id+year_month: {dup}") if dup else ok("Sin duplicados.")

    # 4. Identidad contable
    mismatch = ~np.isclose(df["caja_ingresos"] - df["caja_gastos"], df["flujo_neto"],
                           atol=1e-6)
    if mismatch.sum():
        fail(f"flujo_neto != ingresos - gastos en {int(mismatch.sum())} filas.")
    else:
        ok("flujo_neto = caja_ingresos - caja_gastos.")

    # 5. Ratios dentro de rango
    for col in ["pct_clientes_morosos", "pct_impagos_prov",
                "pct_clientes_morosos_3m", "pct_impagos_prov_3m"]:
        if col not in df.columns:
            continue
        s = df[col]
        fuera = s.notna() & ((s < -1e-9) | (s > 100 + 1e-9))
        if fuera.any():
            fail(f"{col}: {int(fuera.sum())} valores fuera de [0,100].")
        else:
            ok(f"{col} en [0,100] o NA.")

    # 6. No negativos
    for col in ["caja_ingresos", "caja_gastos", "volumen_ventas", "atrapado_ventas",
                "volumen_compras", "atrapado_compras", "deuda_viva",
                "stock_overdue_clientes", "stock_overdue_prov"]:
        if col in df.columns and (df[col] < -1e-9).any():
            fail(f"{col} contiene valores negativos.")

    # 7. Los rolling estrictos no pueden existir antes de tener historia
    orden = df.sort_values(["company_id", "year_month"])
    for col, w in [("flujo_neto_3m_avg", 3), ("clientes_morosos_3m_avg", 3),
                   ("impagos_prov_3m_avg", 3), ("flujo_neto_6m_avg", 6)]:
        if col not in df.columns:
            continue
        primeras = orden.groupby("company_id")[col].head(w - 1)
        if primeras.notna().any():
            fail(f"{col} tiene valor antes de completar {w} meses.")
        else:
            ok(f"{col} respeta min_periods={w}.")

    # 8. Disciplina de NaN: ratio sin denominador debe ser NA, no 0
    if "volumen_ventas" in df.columns:
        falsos_ceros = int(((df["volumen_ventas"] == 0)
                            & df["pct_clientes_morosos"].notna()).sum())
        if falsos_ceros:
            fail(f"{falsos_ceros} filas con morosidad calculada sin volumen de ventas.")
        else:
            ok("Sin ratios inventados donde no hay denominador.")

    # 9. Identificadores
    if df["company_id"].isna().any() or df["year_month"].isna().any():
        fail("Hay company_id / year_month nulos.")
    else:
        ok("Identificadores completos.")

    # 10. Señales de alerta que no son errores
    if "confianza" in df.columns:
        baja = (df["confianza"] == "baja").mean() * 100
        if baja > 30:
            warn(f"{baja:.1f}% de filas con confianza baja: revisar cobertura.")

    print("\n=== RESUMEN ===")
    print(f"Empresas: {df['company_id'].nunique():,}")
    print(f"Filas: {len(df):,}   Columnas: {df.shape[1]}")
    print(f"Meses por empresa: {counts.min()}–{counts.max()}")
    print(f"Errores: {ERRORES}")

    if cfg.AUDIT_PATH.exists():
        print("\n=== AUDITORÍA DEL BUILD ===")
        print(json.dumps(json.loads(cfg.AUDIT_PATH.read_text(encoding="utf-8")),
                         indent=2, ensure_ascii=False))

    if ERRORES:
        raise SystemExit(1)
    print("\nVALIDACIÓN COMPLETA: OK")


if __name__ == "__main__":
    main()