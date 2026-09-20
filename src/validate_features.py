"""
Validador del panel maestro. No modifica datos.

Falla con código 1 si alguna invariante estructural, temporal o numérica se rompe.
Ejecutar siempre antes de puntuar.
"""

import json
import sys
import numpy as np
import pandas as pd

import src.config as cfg

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
        "caja_reportada", "mes_parcial", "confianza",
        "refund_rate_3m", "debt_service_3m",
        "volumen_vencido_ventas", "volumen_vencido_compras",
        "stock_overdue_clientes", "stock_overdue_prov",
        "observado",
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
    # Ventana observada: 0 solo dentro; NaN fuera
    # -------------------------------------------------------------------------
    if "observado" in df.columns:
        obs = df["observado"].astype(bool)
        vol = [
            "caja_ingresos", "caja_gastos", "flujo_neto",
            "volumen_ventas", "volumen_compras",
        ]
        for c in vol:
            if c not in df.columns:
                continue
            fuera_con_dato = (~obs) & df[c].notna()
            dentro_sin_dato = obs & df[c].isna()
            if fuera_con_dato.any():
                fail(f"{c}: {int(fuera_con_dato.sum())} valores fuera de la ventana observada")
            elif dentro_sin_dato.any():
                fail(f"{c}: {int(dentro_sin_dato.sum())} NaN dentro de la ventana observada")
            else:
                ok(f"{c}: 0 dentro de la ventana, NaN fuera")
        if int(obs.sum()) == 0:
            fail("Ninguna fila marcada como observada")
        else:
            ok(f"Ventana observada: {int(obs.sum()):,} / {len(df):,} filas")

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
    # Tolerancia de coma flotante: una suma móvil donde numerador == denominador
    # devuelve 100.00000000000004. Es ruido de float64, no un error de cohorte,
    # y recortar el dato en el panel escondería los que sí lo son.
    TOL_RATIO = 1e-6
    for c in ratio_cols:
        bad = df[c].notna() & ((df[c] < -TOL_RATIO) | (df[c] > 100 + TOL_RATIO))
        if bad.any():
            exceso = float((df.loc[bad, c] - 100).abs().max())
            fail(f"{c}: {int(bad.sum())} valores fuera de [0,100] (exceso máx {exceso:.4g})")
        else:
            ok(f"{c}: rango válido")

    # -------------------------------------------------------------------------
    # No negatividad de magnitudes que por construcción lo exigen
    # -------------------------------------------------------------------------
    nonnegative = [
        "caja_ingresos", "caja_gastos", "volumen_ventas",
        "atrapado_ventas", "volumen_compras", "atrapado_compras",
        "stock_overdue_clientes", "stock_overdue_prov",
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
    if "volumen_vencido_ventas" in df:
        bad = (df["volumen_vencido_ventas"] == 0) & df["pct_clientes_morosos"].notna()
        if bad.any():
            fail("pct_clientes_morosos no es NA cuando volumen_vencido_ventas == 0")
        else:
            ok("Morosidad de clientes respeta denominador de vencimiento")
        overflow = (
            df["volumen_vencido_ventas"].gt(0)
            & df["atrapado_ventas"].gt(df["volumen_vencido_ventas"] + 1e-4)
        )
        if overflow.any():
            fail(f"atrapado_ventas > volumen_vencido_ventas en {int(overflow.sum())} filas")
        else:
            ok("Cohorte clientes: atrapado <= vencido")

    if "volumen_vencido_compras" in df:
        bad = (df["volumen_vencido_compras"] == 0) & df["pct_impagos_prov"].notna()
        if bad.any():
            fail("pct_impagos_prov no es NA cuando volumen_vencido_compras == 0")
        else:
            ok("Morosidad de proveedores respeta denominador de vencimiento")
        overflow = (
            df["volumen_vencido_compras"].gt(0)
            & df["atrapado_compras"].gt(df["volumen_vencido_compras"] + 1e-4)
        )
        if overflow.any():
            fail(f"atrapado_compras > volumen_vencido_compras en {int(overflow.sum())} filas")
        else:
            ok("Cohorte proveedores: atrapado <= vencido")

    # -------------------------------------------------------------------------
    # Métricas de anticipación: rangos acotados por construcción
    # -------------------------------------------------------------------------
    acotadas = [
        ("share_stock_clientes_antiguo", 0.0, 1.0),
        ("share_stock_prov_antiguo", 0.0, 1.0),
        ("top1_clientes_share_3m", 0.0, 1.0),
        ("top1_prov_share_3m", 0.0, 1.0),
        ("edad_media_stock_prov_dias", 0.0, float(cfg.CAP_DIAS_IMPAGO)),
        ("refund_rate", 0.0, cfg.CAP_REFUND_RATE),
        ("refund_rate_3m", 0.0, cfg.CAP_REFUND_RATE),
        ("debt_service", 0.0, cfg.CAP_DEBT_SERVICE),
        ("debt_service_3m", 0.0, cfg.CAP_DEBT_SERVICE),
        ("stock_prov_sobre_ingresos", 0.0, cfg.CAP_STOCK_SOBRE_INGRESOS),
        ("stock_clientes_sobre_ingresos", 0.0, cfg.CAP_STOCK_SOBRE_INGRESOS),
        ("colchon_flujo_meses", -cfg.CAP_COLCHON_MESES, cfg.CAP_COLCHON_MESES),
        ("ingresos_momentum_3m", -1.0, cfg.CAP_MOMENTUM),
        ("gastos_momentum_3m", -1.0, cfg.CAP_MOMENTUM),
        ("runway_meses", -12.0, cfg.CAP_RUNWAY_MESES),
        ("flujo_relativo", -cfg.CAP_FLUJO_RELATIVO, cfg.CAP_FLUJO_RELATIVO),
        # La pendiente robusta y la volatilidad viven en la misma escala que
        # flujo_relativo, así que su tope se deduce del de la serie base. Si esto
        # falla, el tope de flujo_relativo dejó de aplicarse.
        ("flujo_pendiente_robusta_6m", -cfg.CAP_FLUJO_RELATIVO, cfg.CAP_FLUJO_RELATIVO),
        ("flujo_volatilidad_6m", 0.0, 2 * cfg.CAP_FLUJO_RELATIVO),
    ]
    acotadas += [(c, -cfg.Z_CLIP, cfg.Z_CLIP)
                 for c in df.columns if c.startswith("z_")]
    acotadas += [(c, 0.0, 1.0) for c in df.columns if c.startswith("pctl_")]

    fuera = []
    for c, lo, hi in acotadas:
        if c not in df.columns:
            continue
        bad = df[c].notna() & ((df[c] < lo - 1e-6) | (df[c] > hi + 1e-6))
        if bad.any():
            fuera.append(f"{c} ({int(bad.sum())} filas)")
    if fuera:
        fail(f"Métricas fuera de su rango declarado: {fuera}")
    else:
        ok(f"{len(acotadas)} métricas acotadas dentro de su rango")

    for suf in ("clientes", "prov"):
        tot, ant = f"stock_overdue_{suf}", f"stock_{suf}_antiguo"
        if tot in df.columns and ant in df.columns:
            bad = df[ant].gt(df[tot] + 1e-4)
            if bad.any():
                fail(f"{ant} > {tot} en {int(bad.sum())} filas")
            else:
                ok(f"Stock antiguo {suf} <= stock total")

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

    if "caja_negativa_flag" in df.columns:
        mal_foto = df["caja_reportada"].eq(1) & df["caja_negativa_flag"].isna()
        mal_vacio = df["caja_reportada"].eq(0) & df["caja_negativa_flag"].notna()
        if mal_foto.any() or mal_vacio.any():
            fail("caja_negativa_flag debe ser 0/1 con foto de caja y NaN sin foto")
        else:
            ok("caja_negativa_flag: 0/1 con foto, NaN sin visibilidad")

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