"""Panel maestro mensual (company_id x year_month).

Principios:
  - Nunca modifica los CSV RAW.
  - Calendario completo empresa x mes: los rolling son meses reales.
  - "Sin dato" y "cero" son cosas distintas: ratios a NaN + flags de disponibilidad.
  - Nivel, tendencia, persistencia y recuperación, no solo la foto.
  - Toda variable monetaria tiene su versión normalizada por tamaño.
  - El signo RAW de balances y deuda no se interpreta como signo económico.
"""

import json
import numpy as np
import pandas as pd

import data_analysis.config as cfg

AUDIT = {}


# =============================================================================
# UTILIDADES
# =============================================================================

def leer(nombre, obligatorio=True):
    path = cfg.DATA_DIR / nombre
    if not path.exists():
        if obligatorio:
            raise FileNotFoundError(f"No existe {path}")
        print(f"[WARN] Falta {path}")
        return None
    return pd.read_csv(path)


def num(s):
    return pd.to_numeric(s, errors="coerce")


def roll_mean(df, col, w, strict=True):
    mp = w if strict else 1
    return df.groupby("company_id")[col].transform(
        lambda s: s.rolling(w, min_periods=mp).mean())


def roll_sum(df, col, w, strict=False):
    mp = w if strict else 1
    return df.groupby("company_id")[col].transform(
        lambda s: s.rolling(w, min_periods=mp).sum())


def bloque_vs_bloque(df, col, w=3):
    """Media de los últimos w meses menos la del bloque inmediatamente anterior."""
    return df.groupby("company_id")[col].transform(
        lambda s: s.rolling(w, min_periods=w).mean()
        - s.shift(w).rolling(w, min_periods=w).mean())


def pendiente(serie):
    y = serie.dropna()
    if len(y) < 3:
        return np.nan
    return np.polyfit(np.arange(len(y)), y.values, 1)[0]


# =============================================================================
# 1. TRANSACCIONES
# =============================================================================

def build_transacciones():
    tx = leer("transactions.csv")
    fechas = pd.to_datetime(tx["date"], errors="coerce")
    AUDIT["tx_filas_raw"] = int(len(tx))
    AUDIT["tx_fechas_invalidas"] = int(fechas.isna().sum())

    tx = tx.assign(date=fechas).dropna(subset=["date", "company_id"])
    tx = tx[(tx["date"] >= cfg.START_DATE) & (tx["date"] <= cfg.END_DATE)].copy()
    tx["year_month"] = tx["date"].dt.to_period("M")
    tx["amount"] = num(tx["amount"])
    AUDIT["tx_filas_en_ventana"] = int(len(tx))

    g = tx.groupby(["company_id", "year_month"], as_index=False).agg(
        caja_ingresos=("amount", lambda s: s[s > 0].sum()),
        caja_gastos=("amount", lambda s: abs(s[s < 0].sum())),
        flujo_neto=("amount", "sum"),
        n_tx=("amount", "size"),
    )
    return g


# =============================================================================
# 2. FACTURAS
# =============================================================================

def clasificar_direccion(inv):
    """Cobrable (venta) vs pagable (compra). Coincidencia exacta, nunca substring."""
    col = cfg.detectar(inv, "direction")
    if col is not None:
        vals = inv[col].astype(str).str.strip().str.lower()
        es_venta = vals.isin(cfg.VALORES_RECEIVABLE)
        es_compra = vals.isin(cfg.VALORES_PAYABLE)
        if es_venta.any() and es_compra.any():
            print(f"  Dirección resuelta por '{col}' "
                  f"({int(es_venta.sum()):,} ventas / {int(es_compra.sum()):,} compras)")
            AUDIT["direccion_metodo"] = f"columna:{col}"
            return es_venta
        print(f"  [WARN] '{col}' no discrimina ventas y compras.")

    if {"client_id", "supplier_id"}.issubset(inv.columns):
        print("  Dirección resuelta por presencia de client_id / supplier_id")
        AUDIT["direccion_metodo"] = "client_id/supplier_id"
        return inv["client_id"].notna()

    print("  [WARN] Fallback al signo del importe: las rectificativas de venta")
    print("         se contarán como compras. Limitación documentada.")
    AUDIT["direccion_metodo"] = "fallback_signo"
    return num(inv["amount"]) > 0


def marcar_impago(inv):
    """Impago as-of el cierre de cada mes, evitando el look-ahead de 'status'."""
    col_pago = cfg.detectar(inv, "payment_date")
    if col_pago:
        inv["payment_date"] = pd.to_datetime(inv[col_pago], errors="coerce")
        fin_mes = inv["year_month"].dt.to_timestamp(how="end")
        inv["is_overdue"] = (inv["due_date"] <= fin_mes) & (
            inv["payment_date"].isna() | (inv["payment_date"] > fin_mes))
        inv["dias_retraso"] = (inv["payment_date"] - inv["due_date"]).dt.days.clip(lower=0)
        print(f"  Impago reconstruido as-of por mes desde '{col_pago}' (sin look-ahead)")
        AUDIT["overdue_metodo"] = f"as_of:{col_pago}"
    else:
        inv["payment_date"] = pd.NaT
        inv["is_overdue"] = inv["status"].astype(str).str.lower().eq("overdue")
        inv["dias_retraso"] = np.nan
        print("  [WARN] Sin fecha de pago: se usa 'status' (LOOK-AHEAD presente)")
        AUDIT["overdue_metodo"] = "status_snapshot_con_lookahead"
    return inv


def build_facturas():
    inv = leer("invoices.csv")
    fechas = pd.to_datetime(inv["due_date"], errors="coerce")
    AUDIT["inv_filas_raw"] = int(len(inv))
    AUDIT["inv_fechas_invalidas"] = int(fechas.isna().sum())

    inv = inv.assign(due_date=fechas).dropna(subset=["due_date", "company_id"])
    inv = inv[(inv["due_date"] >= cfg.START_DATE) & (inv["due_date"] <= cfg.END_DATE)].copy()
    inv["year_month"] = inv["due_date"].dt.to_period("M")

    inv["amount"] = num(inv["amount"])
    inv["pending_amount"] = num(inv.get("pending_amount", inv["amount"]))
    inv["amount_abs"] = inv["amount"].abs()
    inv["pending_abs"] = inv["pending_amount"].abs()
    inv["is_credit_note"] = (inv["amount"] < 0).astype(int)
    inv["is_receivable"] = clasificar_direccion(inv)
    inv = marcar_impago(inv)

    AUDIT["inv_filas_en_ventana"] = int(len(inv))
    AUDIT["inv_rectificativas_en_ventana"] = int(inv["is_credit_note"].sum())

    # ---- Cohorte: volumen y atrapado por mes de vencimiento ----------------
    def cohorte(mask, sufijo):
        d = inv[mask]
        tot = d.groupby(["company_id", "year_month"], as_index=False).agg(
            **{f"volumen_{sufijo}": ("amount_abs", "sum"),
               f"n_fact_{sufijo}": ("amount_abs", "size")})
        ovr = d[d["is_overdue"]].groupby(["company_id", "year_month"], as_index=False).agg(
            **{f"atrapado_{sufijo}": ("pending_abs", "sum"),
               f"n_overdue_{sufijo}": ("pending_abs", "size")})
        return tot.merge(ovr, on=["company_id", "year_month"], how="left")

    ventas = cohorte(inv["is_receivable"], "ventas")
    compras = cohorte(~inv["is_receivable"], "compras")

    # ---- Stock vivo de impago (asfixia acumulada) --------------------------
    # Evento contable: +pending en el mes de vencimiento, -pending en el de cobro.
    # Sin fecha de pago no hay evento de salida y el stock es una cota superior.
    def eventos(mask, nombre):
        d = inv[mask & inv["is_overdue"]]
        if d.empty:
            return pd.DataFrame(columns=["company_id", "year_month", nombre])
        entra = d.groupby(["company_id", "year_month"])["pending_abs"].sum()
        if d["payment_date"].notna().any():
            pagadas = d[d["payment_date"].notna()].copy()
            pagadas["ym_pago"] = pagadas["payment_date"].dt.to_period("M")
            sale = pagadas.groupby(["company_id", "ym_pago"])["pending_abs"].sum()
            sale.index.names = ["company_id", "year_month"]
            neto = entra.subtract(sale, fill_value=0)
        else:
            neto = entra
        return neto.reset_index(name=nombre)

    flujo_stock_cli = eventos(inv["is_receivable"], "_delta_stock_clientes")
    flujo_stock_prov = eventos(~inv["is_receivable"], "_delta_stock_prov")

    # ---- DSO real ----------------------------------------------------------
    if inv["dias_retraso"].notna().any():
        dso = (inv[inv["is_receivable"]]
               .groupby(["company_id", "year_month"], as_index=False)["dias_retraso"]
               .mean().rename(columns={"dias_retraso": "dso_dias"}))
        dpo = (inv[~inv["is_receivable"]]
               .groupby(["company_id", "year_month"], as_index=False)["dias_retraso"]
               .mean().rename(columns={"dias_retraso": "dpo_dias"}))
    else:
        dso = pd.DataFrame(columns=["company_id", "year_month", "dso_dias"])
        dpo = pd.DataFrame(columns=["company_id", "year_month", "dpo_dias"])

    notas = inv[inv["is_credit_note"] == 1].groupby(
        ["company_id", "year_month"], as_index=False).agg(
        volumen_rectificativas=("amount_abs", "sum"),
        n_rectificativas=("amount_abs", "size"))

    return ventas, compras, flujo_stock_cli, flujo_stock_prov, dso, dpo, notas, inv


# =============================================================================
# 3. ESTÁTICAS: CAJA REAL Y DEUDA
# =============================================================================

def build_caja():
    bal = leer("balances.csv", obligatorio=False)
    bp = leer("banking_products.csv", obligatorio=False)
    if bal is None:
        return pd.DataFrame(columns=["company_id"])

    bal["balance"] = num(bal["balance"])
    col_fecha = cfg.detectar(bal, "balance_date")
    por_producto = bal.groupby("product_id").size()

    if col_fecha and por_producto.max() > 1:
        bal[col_fecha] = pd.to_datetime(bal[col_fecha], errors="coerce")
        bal = bal[bal[col_fecha] <= cfg.END_DATE]
        # Último snapshot POR PRODUCTO, no la fecha máxima global: los productos
        # no reportan todos el mismo día.
        bal = bal.sort_values(col_fecha).groupby("product_id", as_index=False).last()
        AUDIT["balances_modo"] = f"ultimo_snapshot_por_producto:{col_fecha}"
    elif por_producto.max() > 1:
        AUDIT["balances_modo"] = "serie_temporal_sin_fecha_NO_DESAMBIGUABLE"
        print("  [WARN] balances tiene varias filas por producto y ninguna fecha.")
    else:
        AUDIT["balances_modo"] = "snapshot_unico"

    if bp is not None and {"product_id", "type"}.issubset(bp.columns):
        bal = bal.merge(bp[["product_id", "type"]].drop_duplicates("product_id"),
                        on="product_id", how="inner")
        tipos = bal["type"].astype(str).str.lower()
        mask = tipos.apply(lambda t: any(k in t for k in cfg.TIPOS_CAJA))
        if mask.any():
            AUDIT["balances_tipos_incluidos"] = sorted(bal.loc[mask, "type"].unique().tolist())
            bal = bal[mask]
        else:
            AUDIT["balances_tipos_incluidos"] = "ninguno_reconocido_se_usan_todos"

    out = bal.groupby("company_id", as_index=False).agg(caja_real=("balance", "sum"))
    # El signo se conserva: caja negativa es información, no ruido.
    out["caja_negativa_flag"] = (out["caja_real"] < 0).astype(int)
    AUDIT["balances_empresas"] = int(out["company_id"].nunique())
    AUDIT["balances_caja_mediana"] = float(out["caja_real"].median())
    return out


def build_deuda():
    debt = leer("debt_products.csv", obligatorio=False)
    if debt is None:
        return pd.DataFrame(columns=["company_id"])
    debt["outstanding"] = num(debt["outstanding"])
    out = debt.groupby("company_id", as_index=False).agg(
        deuda_raw=("outstanding", "sum"), n_deudas=("outstanding", "size"))
    out["deuda_viva"] = out["deuda_raw"].abs()
    out["deuda_signo_negativo_flag"] = (out["deuda_raw"] < 0).astype(int)
    AUDIT["deuda_empresas"] = int(out["company_id"].nunique())
    return out.drop(columns=["deuda_raw"])


# =============================================================================
# 4. PANEL
# =============================================================================

def calendario(empresas):
    idx = pd.MultiIndex.from_product([sorted(empresas), cfg.MONTHS],
                                     names=["company_id", "year_month"])
    return idx.to_frame(index=False)


def build_panel():
    cfg.asegurar_dirs()
    print(f"Ventana: {cfg.START_DATE.date()} → {cfg.END_DATE.date()} "
          f"({len(cfg.MONTHS)} buckets mensuales)")

    print("\n[1/6] Transacciones...")
    tx = build_transacciones()

    print("\n[2/6] Facturas...")
    ventas, compras, dstock_cli, dstock_prov, dso, dpo, notas, inv = build_facturas()

    print("\n[3/6] Caja real y deuda...")
    caja = build_caja()
    deuda = build_deuda()

    print("\n[4/6] Calendario completo...")
    empresas = set(tx["company_id"]) | set(inv["company_id"])
    companies = leer("companies.csv", obligatorio=False)
    if companies is not None and "company_id" in companies.columns:
        empresas |= set(companies["company_id"].dropna())
    for extra in (caja, deuda):
        if not extra.empty:
            empresas |= set(extra["company_id"].dropna())

    panel = calendario(empresas)
    for extra in [tx, ventas, compras, dstock_cli, dstock_prov, dso, dpo, notas]:
        if not extra.empty:
            panel = panel.merge(extra, on=["company_id", "year_month"], how="left")

    print(f"  {len(empresas):,} empresas x {len(cfg.MONTHS)} meses = {len(panel):,} filas")

    # ---- Ceros legítimos: ausencia de fila = ausencia de actividad ---------
    a_cero = ["caja_ingresos", "caja_gastos", "flujo_neto", "n_tx",
              "volumen_ventas", "n_fact_ventas", "atrapado_ventas", "n_overdue_ventas",
              "volumen_compras", "n_fact_compras", "atrapado_compras", "n_overdue_compras",
              "_delta_stock_clientes", "_delta_stock_prov",
              "volumen_rectificativas", "n_rectificativas"]
    for c in a_cero:
        if c in panel.columns:
            panel[c] = panel[c].fillna(0)
        else:
            panel[c] = 0.0

    panel = panel.sort_values(["company_id", "year_month"]).reset_index(drop=True)

    print("\n[5/6] Ratios, stock y tendencias...")
    panel = derivar(panel)

    print("\n[6/6] Normalización y confianza...")
    for extra in (caja, deuda):
        if not extra.empty:
            panel = panel.merge(extra, on="company_id", how="left")
    panel = normalizar(panel, companies)

    panel["year_month"] = panel["year_month"].astype(str)
    panel.to_csv(cfg.PANEL_PATH, index=False)

    AUDIT.update({
        "ventana_inicio": str(cfg.START_DATE.date()),
        "ventana_fin": str(cfg.END_DATE.date()),
        "buckets_mensuales": len(cfg.MONTHS),
        "meses_parciales_excluidos_del_score": [str(m) for m in cfg.PARTIAL_MONTHS],
        "panel_filas": int(len(panel)),
        "panel_columnas": int(panel.shape[1]),
        "panel_empresas": int(panel["company_id"].nunique()),
    })
    cfg.AUDIT_PATH.write_text(json.dumps(AUDIT, indent=2, ensure_ascii=False),
                              encoding="utf-8")

    print(f"\nPanel: {cfg.PANEL_PATH} ({len(panel):,} filas, {panel.shape[1]} columnas)")
    print(f"Auditoría: {cfg.AUDIT_PATH}")
    resumen(panel)
    return panel


# =============================================================================
# 5. DERIVADAS
# =============================================================================

def derivar(panel):
    # ---- Actividad y disponibilidad ---------------------------------------
    panel["tx_disponible"] = (panel["n_tx"] > 0).astype(int)
    panel["ventas_disponible"] = (panel["volumen_ventas"] > 0).astype(int)
    panel["compras_disponible"] = (panel["volumen_compras"] > 0).astype(int)
    panel["mes_activo"] = ((panel["tx_disponible"] + panel["ventas_disponible"]
                            + panel["compras_disponible"]) > 0).astype(int)

    # ---- Burn rate: NaN cuando no hay denominador, flag aparte -------------
    panel["mes_sin_ingresos"] = ((panel["caja_ingresos"] == 0)
                                 & (panel["caja_gastos"] > 0)).astype(int)
    panel["burn_rate"] = np.where(panel["caja_ingresos"] > 0,
                                  panel["caja_gastos"] / panel["caja_ingresos"], np.nan)
    panel["burn_rate_cap"] = panel["burn_rate"].clip(upper=cfg.BURN_RATE_CAP)

    # ---- Morosidad cohorte mensual (NaN sin denominador) -------------------
    panel["pct_clientes_morosos"] = np.where(
        panel["volumen_ventas"] > 0,
        100 * panel["atrapado_ventas"] / panel["volumen_ventas"], np.nan)
    panel["pct_impagos_prov"] = np.where(
        panel["volumen_compras"] > 0,
        100 * panel["atrapado_compras"] / panel["volumen_compras"], np.nan)

    # ---- Morosidad sobre sumas móviles (robusta a meses de pocas facturas) -
    for nombre, num_c, den_c, nf_c in [
        ("pct_clientes_morosos_3m", "atrapado_ventas", "volumen_ventas", "n_fact_ventas"),
        ("pct_impagos_prov_3m", "atrapado_compras", "volumen_compras", "n_fact_compras"),
    ]:
        n3 = roll_sum(panel, num_c, cfg.ROLL_SHORT)
        d3 = roll_sum(panel, den_c, cfg.ROLL_SHORT)
        f3 = roll_sum(panel, nf_c, cfg.ROLL_SHORT)
        ratio = np.where(d3 > 0, 100 * n3 / d3, np.nan)
        panel[nombre] = np.where(f3 >= cfg.MIN_FACTURAS_RATIO, ratio, np.nan)
        panel[f"n_fact_{nombre.split('_')[1]}_3m"] = f3

    # ---- Stock vivo de impago ---------------------------------------------
    panel["stock_overdue_clientes"] = (panel.groupby("company_id")["_delta_stock_clientes"]
                                       .cumsum().clip(lower=0))
    panel["stock_overdue_prov"] = (panel.groupby("company_id")["_delta_stock_prov"]
                                   .cumsum().clip(lower=0))
    panel = panel.drop(columns=["_delta_stock_clientes", "_delta_stock_prov"])

    # ---- Medias móviles ----------------------------------------------------
    for col, pref in [("flujo_neto", "flujo_neto"), ("burn_rate", "burn_rate"),
                      ("pct_clientes_morosos_3m", "clientes_morosos"),
                      ("pct_impagos_prov_3m", "impagos_prov")]:
        panel[f"{pref}_3m_avg"] = roll_mean(panel, col, cfg.ROLL_SHORT)
        panel[f"{pref}_6m_avg"] = roll_mean(panel, col, cfg.ROLL_LONG)
        panel[f"{pref}_3m_vs_prev3m"] = bloque_vs_bloque(panel, col, cfg.ROLL_SHORT)

    panel["ingresos_3m_avg"] = roll_mean(panel, "caja_ingresos", cfg.ROLL_SHORT, strict=False)
    panel["ingresos_12m_avg"] = panel.groupby("company_id")["caja_ingresos"].transform(
        lambda s: s.rolling(12, min_periods=3).mean())
    panel["gastos_3m_avg"] = roll_mean(panel, "caja_gastos", cfg.ROLL_SHORT, strict=False)

    # ---- Señales de recuperación (delta negativo = mejora) -----------------
    panel["recuperacion_clientes"] = -panel["clientes_morosos_3m_vs_prev3m"]
    panel["recuperacion_prov"] = -panel["impagos_prov_3m_vs_prev3m"]
    panel["recuperacion_flujo"] = panel["flujo_neto_3m_vs_prev3m"]

    # ---- Flags de estrés y persistencia -----------------------------------
    flags = {
        "flag_flujo_negativo": panel["flujo_neto"] < 0,
        "flag_estres_prov": panel["pct_impagos_prov_3m"] >= 30,
        "flag_estres_clientes": panel["pct_clientes_morosos_3m"] >= 30,
        "flag_burn_alto": panel["burn_rate"] >= 1,
    }
    for nombre, serie in flags.items():
        panel[nombre] = serie.fillna(False).astype(int)
        panel[f"{nombre}_3m"] = roll_sum(panel, nombre, cfg.ROLL_SHORT, strict=True)
        panel[f"{nombre}_6m"] = roll_sum(panel, nombre, cfg.ROLL_LONG, strict=True)
        panel[f"persistente_{nombre}"] = (panel[f"{nombre}_3m"] == 3).astype(int)

    return panel


def normalizar(panel, companies):
    for c in ["caja_real", "deuda_viva", "n_deudas", "caja_negativa_flag",
              "deuda_signo_negativo_flag"]:
        if c in panel.columns:
            panel[c] = panel[c].fillna(0)
        else:
            panel[c] = 0.0

    # ---- Variables escala-libre: comparables entre una pyme y un grupo -----
    panel["flujo_relativo"] = np.where(panel["ingresos_12m_avg"] > 0,
                                       panel["flujo_neto"] / panel["ingresos_12m_avg"], np.nan)
    panel["flujo_relativo_3m"] = roll_mean(panel, "flujo_relativo", cfg.ROLL_SHORT)
    panel["runway_meses"] = np.where(panel["gastos_3m_avg"] > 0,
                                     panel["caja_real"] / panel["gastos_3m_avg"],
                                     np.nan)
    panel["runway_meses"] = panel["runway_meses"].clip(-12, 60)
    panel["deuda_sobre_ingresos"] = np.where(panel["ingresos_12m_avg"] > 0,
                                             panel["deuda_viva"] / (panel["ingresos_12m_avg"] * 12),
                                             np.nan)
    panel["stock_prov_sobre_ingresos"] = np.where(panel["ingresos_12m_avg"] > 0,
                                                  panel["stock_overdue_prov"] / panel["ingresos_12m_avg"],
                                                  np.nan)
    panel["stock_clientes_sobre_ingresos"] = np.where(panel["ingresos_12m_avg"] > 0,
                                                      panel["stock_overdue_clientes"] / panel["ingresos_12m_avg"],
                                                      np.nan)

    # ---- Tendencia y volatilidad ------------------------------------------
    g = panel.groupby("company_id")
    panel["flujo_pendiente_6m"] = g["flujo_relativo"].transform(
        lambda s: s.rolling(cfg.ROLL_LONG, min_periods=3).apply(pendiente, raw=False))
    panel["flujo_volatilidad_6m"] = g["flujo_relativo"].transform(
        lambda s: s.rolling(cfg.ROLL_LONG, min_periods=3).std())
    panel["flujo_yoy"] = panel["flujo_relativo"] - g["flujo_relativo"].shift(12)

    # ---- Confianza ---------------------------------------------------------
    panel["mes_idx"] = g.cumcount() + 1
    panel["meses_activos_acum"] = g["mes_activo"].cumsum()
    fin_mes = pd.PeriodIndex(panel["year_month"]).to_timestamp(how="end")
    panel["mes_parcial"] = pd.PeriodIndex(panel["year_month"]).isin(cfg.PARTIAL_MONTHS).astype(int)
    panel["morosidad_censurada"] = (
        (cfg.EXTRACTION_DATE - fin_mes).days < cfg.DIAS_MADURACION).astype(int)
    panel["confianza"] = np.select(
        [panel["meses_activos_acum"] < 6,
         panel["meses_activos_acum"] < cfg.MIN_MESES_HISTORIA],
        ["baja", "media"], default="alta")
    panel.loc[(panel["morosidad_censurada"] == 1) & (panel["confianza"] == "alta"),
              "confianza"] = "media"
    panel.loc[panel["mes_parcial"] == 1, "confianza"] = "baja"

    if companies is not None:
        col_sector = cfg.detectar(companies, "sector")
        col_grupo = cfg.detectar(companies, "group")
        cols = ["company_id"] + [c for c in (col_sector, col_grupo) if c]
        extra = companies[cols].drop_duplicates("company_id").copy()
        if col_sector:
            extra = extra.rename(columns={col_sector: "sector"})
        if col_grupo:
            extra = extra.rename(columns={col_grupo: "group_id"})
        panel = panel.merge(extra, on="company_id", how="left")

    return panel


# =============================================================================
# 6. RESUMEN
# =============================================================================

def resumen(panel):
    activas = panel.groupby("company_id")["mes_activo"].sum().sort_values(ascending=False)
    emp = activas.index[0]
    cols = ["year_month", "flujo_relativo_3m", "runway_meses", "burn_rate",
            "pct_clientes_morosos_3m", "pct_impagos_prov_3m",
            "stock_prov_sobre_ingresos", "confianza"]
    print(f"\n--- TRAYECTORIA: {emp} ---")
    print(panel[panel["company_id"] == emp][cols].to_string(index=False))

    print("\n--- COBERTURA ---")
    print(f"  Meses activos por empresa (media): {activas.mean():.1f} de {len(cfg.MONTHS)}")
    print(f"  Morosidad cliente no fiable: {panel['pct_clientes_morosos_3m'].isna().mean()*100:.1f}% de filas")
    print(f"  Morosidad proveedor no fiable: {panel['pct_impagos_prov_3m'].isna().mean()*100:.1f}% de filas")
    print(f"  Confianza: {dict(panel['confianza'].value_counts())}")


if __name__ == "__main__":
    build_panel()