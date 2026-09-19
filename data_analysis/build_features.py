"""Panel maestro mensual (company_id x year_month).

Principios:
  - Nunca modifica los CSV RAW.
  - Calendario completo empresa x mes: los rolling son meses reales.
  - "Sin dato" y "cero" son cosas distintas: ratios a NaN + flags de disponibilidad.
  - Nivel, tendencia, persistencia y recuperación, no solo la foto.
  - Toda variable monetaria tiene su versión normalizada por tamaño.
  - Caja y deuda son snapshots actuales: solo entran en el último mes evaluable,
    nunca se propagan hacia atrás por todo el histórico.
  - Los importes de factura se normalizan a accounting_currency cuando el tipo de
    cambio es válido; las filas no convertibles quedan auditadas.
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


def normalizar_importes(inv):
    """Lleva amount/pending_amount a accounting_currency cuando es posible.

    Si moneda == accounting_currency no hace falta conversión. Si son distintas,
    exige exchange_rate > 0. No se inventan tipos de cambio para filas inválidas.
    """
    inv["currency"] = inv.get("currency", "").astype(str).str.upper().str.strip()
    inv["accounting_currency"] = inv.get("accounting_currency", "").astype(str).str.upper().str.strip()
    inv["exchange_rate"] = num(inv.get("exchange_rate", np.nan))

    misma = (
        inv["currency"].notna()
        & inv["accounting_currency"].notna()
        & (inv["currency"] == inv["accounting_currency"])
    )
    rate_ok = inv["exchange_rate"].gt(0) & np.isfinite(inv["exchange_rate"])
    convertible = misma | rate_ok

    inv["amount_reporting"] = np.where(
        misma, inv["amount"], np.where(rate_ok, inv["amount"] * inv["exchange_rate"], np.nan)
    )
    inv["pending_reporting"] = np.where(
        misma,
        inv["pending_amount"],
        np.where(rate_ok, inv["pending_amount"] * inv["exchange_rate"], np.nan),
    )

    distinta = inv["currency"].ne(inv["accounting_currency"])
    AUDIT["inv_moneda_distinta_contable"] = int(distinta.sum())
    AUDIT["inv_tipo_cambio_invalido_en_monedas_distintas"] = int((distinta & ~rate_ok).sum())
    AUDIT["inv_importes_no_convertibles"] = int((~convertible).sum())
    if distinta.any():
        AUDIT["inv_exchange_rate_min_no_nulo"] = float(inv.loc[distinta & rate_ok, "exchange_rate"].min()) if (distinta & rate_ok).any() else None
        AUDIT["inv_exchange_rate_max_no_nulo"] = float(inv.loc[distinta & rate_ok, "exchange_rate"].max()) if (distinta & rate_ok).any() else None
        AUDIT["inv_pares_moneda_top"] = (
            inv.loc[distinta, ["currency", "accounting_currency"]]
            .value_counts().head(15).reset_index().astype(str).to_dict("records")
        )
    return inv


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

def detectar_rectificativa(inv):
    """Rectificativa real, no 'amount < 0'. El signo marca dirección en la
    convención receivable(+)/payable(-), no una corrección contable."""
    col = cfg.detectar(inv, "document_kind")
    if col is not None:
        vals = inv[col].astype(str).str.strip().str.lower()
        es_rect = vals.isin(cfg.VALORES_RECTIFICATIVA)
        if es_rect.any():
            print(f"  Rectificativas resueltas por '{col}' ({int(es_rect.sum()):,} filas)")
            AUDIT["rectificativa_metodo"] = f"columna:{col}"
            return es_rect
        print(f"  [WARN] '{col}' no contiene valores de rectificativa reconocidos.")

    if "concept" in inv.columns:
        c = inv["concept"].astype(str).str.lower()
        es_rect = c.str.contains("|".join(cfg.VALORES_RECTIFICATIVA), na=False, regex=True)
        if es_rect.any():
            print(f"  Rectificativas resueltas por texto en 'concept' ({int(es_rect.sum()):,} filas)")
            AUDIT["rectificativa_metodo"] = "concept_texto"
            return es_rect

    print("  [WARN] Sin columna fiable para rectificativas. NO se usa 'amount < 0' como")
    print("         proxy (mezclaría dirección con corrección). Se marca todo en 0.")
    AUDIT["rectificativa_metodo"] = "no_detectable_se_asume_cero"
    return pd.Series(False, index=inv.index)


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

    print("  [WARN] Fallback al signo del importe para la dirección.")
    print("         Si la convención real es receivable(+)/payable(-), esto es correcto;")
    print("         verificar con el desglose de document_type en el informe de calidad.")
    AUDIT["direccion_metodo"] = "fallback_signo"
    return num(inv["amount"]) > 0


def marcar_impago(inv):
    """Impago as-of el cierre de cada mes, evitando el look-ahead de 'status'."""
    col_pago = cfg.detectar(inv, "payment_date")
    if col_pago:
        inv["payment_date"] = pd.to_datetime(inv[col_pago], errors="coerce")
        fin_mes = inv["year_month_vencimiento"].dt.to_timestamp(how="end")
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
    due = pd.to_datetime(inv["due_date"], errors="coerce")
    issue_col = "issuance_date" if "issuance_date" in inv.columns else None
    issue = pd.to_datetime(inv[issue_col], errors="coerce") if issue_col else due.copy()

    AUDIT["inv_filas_raw"] = int(len(inv))
    AUDIT["inv_fechas_invalidas_due"] = int(due.isna().sum())
    AUDIT["inv_fechas_invalidas_issuance"] = int(issue.isna().sum()) if issue_col else None

    inv = inv.assign(due_date=due, issuance_date=issue)
    inv = inv.dropna(subset=["company_id", "due_date"])

    # Para morosidad necesitamos conservar facturas cuyo vencimiento cae en la
    # ventana; para volumen mensual usamos SIEMPRE issuance_date.
    en_ventana_due = inv["due_date"].between(cfg.START_DATE, cfg.END_DATE)
    en_ventana_issue = inv["issuance_date"].between(cfg.START_DATE, cfg.END_DATE)
    inv = inv[en_ventana_due | en_ventana_issue].copy()

    inv["year_month"] = inv["issuance_date"].dt.to_period("M")
    inv["year_month_vencimiento"] = inv["due_date"].dt.to_period("M")

    inv["amount"] = num(inv["amount"])
    inv["pending_amount"] = num(inv.get("pending_amount", inv["amount"]))
    inv = normalizar_importes(inv)

    # Para cálculos monetarios solo entran importes convertibles.
    inv["amount_abs"] = inv["amount_reporting"].abs()
    inv["pending_abs"] = inv["pending_reporting"].abs()
    inv["is_credit_note"] = detectar_rectificativa(inv).astype(int)
    inv["is_receivable"] = clasificar_direccion(inv)
    inv = marcar_impago(inv)

    AUDIT["inv_filas_en_ventana"] = int(len(inv))
    AUDIT["inv_filas_con_issuance_en_ventana"] = int(en_ventana_issue.loc[inv.index].sum())
    AUDIT["inv_filas_con_due_en_ventana"] = int(en_ventana_due.loc[inv.index].sum())
    AUDIT["inv_rectificativas_en_ventana"] = int(inv["is_credit_note"].sum())

    def cohorte(mask, sufijo):
        # Volumen: mes de emisión. Impago: mes de vencimiento.
        d = inv[mask & inv["year_month"].notna() & inv["amount_abs"].notna()]
        tot = d.groupby(["company_id", "year_month"], as_index=False).agg(
            **{f"volumen_{sufijo}": ("amount_abs", "sum"),
               f"n_fact_{sufijo}": ("amount_abs", "size")}
        )

        d_ovr = inv[
            mask
            & inv["year_month_vencimiento"].between(cfg.MONTH_START, cfg.MONTH_END)
            & inv["is_overdue"]
            & inv["pending_abs"].notna()
        ]
        ovr = d_ovr.groupby(
            ["company_id", "year_month_vencimiento"], as_index=False
        ).agg(
            **{f"atrapado_{sufijo}": ("pending_abs", "sum"),
               f"n_overdue_{sufijo}": ("pending_abs", "size")}
        ).rename(columns={"year_month_vencimiento": "year_month"})

        return tot.merge(ovr, on=["company_id", "year_month"], how="left")

    ventas = cohorte(inv["is_receivable"], "ventas")
    compras = cohorte(~inv["is_receivable"], "compras")

    def eventos(mask, nombre):
        d = inv[
            mask
            & inv["is_overdue"]
            & inv["year_month_vencimiento"].between(cfg.MONTH_START, cfg.MONTH_END)
            & inv["pending_abs"].notna()
        ]
        if d.empty:
            return pd.DataFrame(columns=["company_id", "year_month", nombre])

        entra = d.groupby(["company_id", "year_month_vencimiento"])["pending_abs"].sum()
        entra.index.names = ["company_id", "year_month"]

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

    if inv["dias_retraso"].notna().any():
        dso = (
            inv[inv["is_receivable"] & inv["year_month"].notna()]
            .groupby(["company_id", "year_month"], as_index=False)["dias_retraso"]
            .mean().rename(columns={"dias_retraso": "dso_dias"})
        )
        dpo = (
            inv[(~inv["is_receivable"]) & inv["year_month"].notna()]
            .groupby(["company_id", "year_month"], as_index=False)["dias_retraso"]
            .mean().rename(columns={"dias_retraso": "dpo_dias"})
        )
    else:
        dso = pd.DataFrame(columns=["company_id", "year_month", "dso_dias"])
        dpo = pd.DataFrame(columns=["company_id", "year_month", "dpo_dias"])

    notas = inv[
        (inv["is_credit_note"] == 1) & inv["year_month"].notna()
    ].groupby(["company_id", "year_month"], as_index=False).agg(
        volumen_rectificativas=("amount_abs", "sum"),
        n_rectificativas=("amount_abs", "size")
    )

    return ventas, compras, flujo_stock_cli, flujo_stock_prov, dso, dpo, notas, inv


# =============================================================================
# 3. ESTÁTICAS: CAJA REAL Y DEUDA
# =============================================================================

def build_caja():
    bal = leer("balances.csv", obligatorio=False)
    bp = leer("banking_products.csv", obligatorio=False)
    if bal is None:
        return pd.DataFrame(columns=["company_id", "year_month"])

    bal["balance"] = num(bal["balance"])
    col_fecha = cfg.detectar(bal, "balance_date")
    por_producto = bal.groupby("product_id").size()

    if col_fecha:
        bal[col_fecha] = pd.to_datetime(bal[col_fecha], errors="coerce")
        bal = bal.dropna(subset=[col_fecha])
        # Un snapshot actual NO se propaga hacia atrás. Solo se usa como
        # estado actual en el último mes completo evaluado.
        bal = bal[bal[col_fecha] <= cfg.EXTRACTION_DATE].copy()
        if bal.empty:
            return pd.DataFrame(columns=["company_id", "year_month"])
        bal = bal.sort_values(col_fecha).groupby("product_id", as_index=False).last()
        AUDIT["balances_modo"] = f"ultimo_snapshot_por_producto:{col_fecha}"
        AUDIT["balances_snapshot_max"] = str(bal[col_fecha].max().date())
    else:
        AUDIT["balances_modo"] = "snapshot_sin_fecha"
        print("  [WARN] balances no tiene fecha; se trata como snapshot actual.")

    if bp is not None and {"product_id", "type"}.issubset(bp.columns):
        bal = bal.merge(
            bp[["product_id", "type"]].drop_duplicates("product_id"),
            on="product_id", how="inner"
        )
        tipos = bal["type"].astype(str).str.lower()
        mask = tipos.apply(lambda t: any(k in t for k in cfg.TIPOS_CAJA))
        if mask.any():
            AUDIT["balances_tipos_incluidos"] = sorted(
                bal.loc[mask, "type"].astype(str).unique().tolist()
            )
            bal = bal[mask].copy()
        else:
            AUDIT["balances_tipos_incluidos"] = "ninguno_reconocido"
            bal = bal.iloc[0:0].copy()

    # Valores centinela conocidos / no financieros se dejan fuera del saldo.
    sentinel = bal["balance"].abs().isin(cfg.VALORES_SENTINELA_BALANCE)
    AUDIT["balances_sentinelas_excluidos"] = int(sentinel.sum())
    bal.loc[sentinel, "balance"] = np.nan

    out = bal.groupby("company_id", as_index=False).agg(caja_real=("balance", "sum"))
    out["caja_negativa_flag"] = (out["caja_real"] < 0).astype(int)
    out["caja_reportada"] = out["caja_real"].notna().astype(int)
    # Snapshot actual: solo el último mes completo del score.
    out["year_month"] = cfg.MONTHS[cfg.MONTHS < cfg.PARTIAL_MONTHS[0]][-1]
    AUDIT["balances_empresas"] = int(out["company_id"].nunique())
    AUDIT["balances_caja_mediana"] = float(out["caja_real"].median())
    return out


def build_deuda():
    debt = leer("debt_products.csv", obligatorio=False)
    if debt is None:
        return pd.DataFrame(columns=["company_id", "year_month"])

    debt["outstanding"] = num(debt["outstanding"])
    out = debt.groupby("company_id", as_index=False).agg(
        deuda_raw=("outstanding", "sum"), n_deudas=("outstanding", "size")
    )
    out["deuda_viva"] = out["deuda_raw"].abs()
    out["deuda_signo_negativo_flag"] = (out["deuda_raw"] < 0).astype(int)

    # debt_products no contiene fecha de snapshot. Por tanto, NO se backfillea:
    # representa estado actual y solo entra en el último mes completo.
    out["year_month"] = cfg.MONTHS[cfg.MONTHS < cfg.PARTIAL_MONTHS[0]][-1]

    if "currency" in debt.columns:
        curr = debt["currency"].astype(str).str.upper().str.strip()
        n_curr = debt.assign(_currency=curr).groupby("company_id")["_currency"].nunique()
        out["deuda_multimoneda"] = out["company_id"].map(n_curr).gt(1).astype(int)
        out["deuda_no_eur"] = out["company_id"].map(
            debt.assign(_no_eur=~curr.eq("EUR")).groupby("company_id")["_no_eur"].max()
        ).fillna(False).astype(int)
        AUDIT["deuda_empresas_multimoneda"] = int((n_curr > 1).sum())
        AUDIT["deuda_empresas_con_moneda_no_eur"] = int(out["deuda_no_eur"].sum())

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
    # Caja y deuda son snapshots actuales: se unen por empresa + último mes
    # completo, nunca por company_id a todos los meses históricos.
    for extra in (caja, deuda):
        if not extra.empty:
            panel = panel.merge(extra, on=["company_id", "year_month"], how="left")
    panel = normalizar(panel, companies)

    panel["year_month"] = panel["year_month"].astype(str)
    panel.to_csv(cfg.PANEL_PATH, index=False)

    AUDIT.update({
        "ventana_inicio": str(cfg.START_DATE.date()),
        "ventana_fin": str(cfg.END_DATE.date()),
        "buckets_mensuales": len(cfg.MONTHS),
        "meses_parciales_excluidos_del_score": [str(m) for m in cfg.PARTIAL_MONTHS],
        "mes_snapshot_financiero_actual": str(cfg.MONTHS[cfg.MONTHS < cfg.PARTIAL_MONTHS[0]][-1]),
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
    # Con ~1 factura/mes por empresa, una ventana de 3 meses partida entre
    # ventas y compras a menudo no llega al mínimo. Si falla, se intenta con
    # 6 meses antes de rendirse a NaN, y se deja constancia de qué ventana
    # sostiene el dato para que el score pueda rebajar su confianza.
    for nombre, num_c, den_c, nf_c in [
        ("pct_clientes_morosos_3m", "atrapado_ventas", "volumen_ventas", "n_fact_ventas"),
        ("pct_impagos_prov_3m", "atrapado_compras", "volumen_compras", "n_fact_compras"),
    ]:
        n3, d3, f3 = roll_sum(panel, num_c, cfg.ROLL_SHORT), roll_sum(panel, den_c, cfg.ROLL_SHORT), roll_sum(panel, nf_c, cfg.ROLL_SHORT)
        n6, d6, f6 = roll_sum(panel, num_c, cfg.ROLL_LONG), roll_sum(panel, den_c, cfg.ROLL_LONG), roll_sum(panel, nf_c, cfg.ROLL_LONG)

        ratio_3m = np.where(d3 > 0, 100 * n3 / d3, np.nan)
        ratio_6m = np.where(d6 > 0, 100 * n6 / d6, np.nan)

        usa_3m = f3 >= cfg.MIN_FACTURAS_RATIO
        usa_6m = (~usa_3m) & (f6 >= cfg.MIN_FACTURAS_RATIO_LARGO)

        panel[nombre] = np.select([usa_3m, usa_6m], [ratio_3m, ratio_6m], default=np.nan)
        panel[f"{nombre}_fuente"] = np.select([usa_3m, usa_6m], ["3m", "6m"], default="sin_datos")
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
    # caja_real y caja_negativa_flag NO se rellenan a 0: la ausencia de un
    # balance reportado es "sin visibilidad", no "cero en caja". Confundirlas
    # hundía el runway de las empresas sin cuenta corriente detectada.
    if "caja_real" not in panel.columns:
        panel["caja_real"] = np.nan
    panel["caja_reportada"] = panel.get("caja_reportada", 0)
    panel["caja_reportada"] = panel["caja_reportada"].fillna(0).astype(int)
    if "caja_negativa_flag" in panel.columns:
        panel["caja_negativa_flag"] = np.where(panel["caja_reportada"] == 1,
                                               panel["caja_negativa_flag"], np.nan)

    for c in ["deuda_viva", "n_deudas", "deuda_signo_negativo_flag"]:
        if c not in panel.columns:
            panel[c] = np.nan
    # La ausencia histórica significa "sin snapshot", no "deuda cero".
    if "deuda_viva" in panel.columns:
        panel.loc[panel["deuda_viva"].notna(), "n_deudas"] = panel.loc[
            panel["deuda_viva"].notna(), "n_deudas"
        ].fillna(0)
        panel.loc[panel["deuda_viva"].notna(), "deuda_signo_negativo_flag"] = panel.loc[
            panel["deuda_viva"].notna(), "deuda_signo_negativo_flag"
        ].fillna(0)

    # ---- Variables escala-libre: comparables entre una pyme y un grupo -----
    panel["flujo_relativo"] = np.where(panel["ingresos_12m_avg"] > 0,
                                       panel["flujo_neto"] / panel["ingresos_12m_avg"], np.nan)
    panel["flujo_relativo_3m"] = roll_mean(panel, "flujo_relativo", cfg.ROLL_SHORT)
    # min_periods=1 aquí daría "runway" a partir de un solo mes de gasto, que
    # puede ser casi nulo en el primer mes de actividad y disparar el ratio
    # al techo. Se exige un mínimo de MIN_MESES_RUNWAY antes de calcularlo.
    gastos_runway = panel.groupby("company_id")["caja_gastos"].transform(
        lambda s: s.rolling(cfg.ROLL_SHORT, min_periods=cfg.MIN_MESES_RUNWAY).mean())
    panel["runway_meses"] = np.where(
        (gastos_runway > 0) & (panel["caja_reportada"] == 1),
        panel["caja_real"] / gastos_runway, np.nan)
    # No se usa un techo 60: la transformación al score ya es monótona.
    panel["runway_meses"] = panel["runway_meses"].clip(lower=-12)
    panel["deuda_sobre_ingresos"] = np.where(
        (panel["ingresos_12m_avg"] > 0) & panel["deuda_viva"].notna(),
        panel["deuda_viva"] / (panel["ingresos_12m_avg"] * 12), np.nan)
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

    # Visibilidad del snapshot actual: solo el último mes completo puede tenerla.
    panel["snapshot_financiero_disponible"] = (
        panel["caja_reportada"].eq(1) | panel["deuda_viva"].notna()
    ).astype(int)

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
    print(f"  Filas con snapshot financiero actual: {int(panel['snapshot_financiero_disponible'].sum()):,}")


if __name__ == "__main__":
    build_panel()