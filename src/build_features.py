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
  - Cada corrección de limpieza se cuenta en cleaning_log.json. Fuera de la
    ventana observada de cada empresa, volumen = NaN (no 0).
"""

import json
import numpy as np
import pandas as pd

import src.config as cfg

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
    rate_ok = (
        inv["exchange_rate"].between(cfg.EXCHANGE_RATE_MIN, cfg.EXCHANGE_RATE_MAX)
        & np.isfinite(inv["exchange_rate"])
    )
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
    AUDIT["inv_tipo_cambio_fuera_de_rango"] = int(
        (distinta & inv["exchange_rate"].gt(0) & ~rate_ok).sum()
    )
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


def z_autoref(df, col):
    """Desviación del mes frente a la propia base histórica de la empresa.

    La base EXCLUYE el mes corriente (shift(1)): se compara el presente contra
    el pasado, no contra una media que ya contiene el presente. Es la primitiva
    de anticipación: detecta que una empresa se sale de SU normal antes de que
    cruce cualquier umbral absoluto, y hace comparables a la pyme y al grupo.
    """
    g = df.groupby("company_id")[col]
    base = g.shift(1)
    mu = base.groupby(df["company_id"]).transform(
        lambda s: s.rolling(cfg.Z_VENTANA, min_periods=cfg.Z_MIN_PERIODOS).mean())
    sd = base.groupby(df["company_id"]).transform(
        lambda s: s.rolling(cfg.Z_VENTANA, min_periods=cfg.Z_MIN_PERIODOS).std())
    z = np.where(sd > 0, (df[col] - mu) / sd, np.nan)
    return np.clip(z, -cfg.Z_CLIP, cfg.Z_CLIP)


def pctl_mes(df, col, mas_es_mejor=True, referencia=None):
    """Percentil transversal dentro del mes, orientado: 0 = peor, 1 = mejor.

    Un umbral absoluto envejece: lo que era morosidad alta en 2024 puede ser la
    norma en 2026. El rango relativo mantiene el score estable frente a la
    deriva agregada del dataset y permite hablar de "peor decil de su cohorte".

    La orientación es obligatoria y explícita porque rank() ordena por valor
    crudo: sin invertir, en deuda o impagos el percentil 1,0 sería la PEOR
    empresa, y todo consumidor que lea "percentil bajo = malo" se equivoca de
    lado. Con esta firma, pctl_* siempre significa lo mismo.

    Si se pasa una `referencia` (rejilla de cuantiles guardada), el percentil se
    mide contra ella en lugar de contra las empresas presentes en el DataFrame.
    Esto es lo que permite puntuar 60-80 empresas nuevas y obtener el mismo
    resultado que si estuvieran dentro de la población completa: sin referencia
    congelada, una empresa cambiaría de percentil según con quién la comparen.
    """
    if referencia is None:
        r = df.groupby("year_month")[col].rank(pct=True)
    else:
        r = pd.Series(np.nan, index=df.index, dtype=float)
        for mes, idx in df.groupby("year_month").groups.items():
            rejilla = referencia.get(str(mes))
            if not rejilla:
                continue
            v = df.loc[idx, col]
            grid = np.asarray(rejilla, dtype=float)
            x = v.to_numpy(dtype=float)
            # Punto medio del empate, para replicar la convención de rank(), que
            # promedia los rangos empatados. Sin esto, las columnas con mucha masa
            # en un valor (stock_prov_sobre_ingresos es 0 en el 60% de las filas)
            # se irían al borde inferior del escalón y desplazarían el canal entero.
            lo = np.searchsorted(grid, x, side="left")
            hi = np.searchsorted(grid, x, side="right")
            r.loc[idx] = np.where(v.isna(), np.nan,
                                  (lo + hi) / 2 / (len(grid) - 1))
        r = r.clip(0.0, 1.0)
    return r if mas_es_mejor else 1.0 - r


def rejilla_cuantiles(df, col, n=101):
    """Guarda la distribución de una columna por mes como rejilla de cuantiles.

    101 puntos dan resolución de 1 percentil, que es más fina que cualquier
    umbral que use el motor (el más estricto es 0,10) y ocupa nada.
    """
    out = {}
    for mes, g in df.groupby("year_month"):
        v = g[col].dropna()
        if len(v) >= 20:
            out[str(mes)] = [round(float(x), 6)
                             for x in np.quantile(v, np.linspace(0, 1, n))]
    return out


def pendiente_robusta(serie):
    """Pendiente de Theil-Sen: mediana de las pendientes entre todos los pares.

    Con 6 puntos y flujos de pyme, una regresión por mínimos cuadrados queda
    dominada por los extremos: un solo mes atípico invierte el signo de la
    tendencia. La mediana de pendientes por pares necesita que se corrompa la
    mitad de la serie para moverse, así que distingue mucho mejor un cambio de
    trayectoria real de un mes raro.
    """
    y = serie.dropna()
    n = len(y)
    if n < 3:
        return np.nan
    v = y.to_numpy(dtype=float)
    i, j = np.triu_indices(n, k=1)
    return float(np.median((v[j] - v[i]) / (j - i)))


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
    cero = tx["amount"].eq(0)
    AUDIT["tx_importe_cero_excluidas"] = int(cero.sum())
    tx = tx.loc[~cero].copy()
    if "status" in tx.columns:
        pend = tx["status"].astype(str).str.lower().isin(cfg.TX_STATUS_EXCLUIDOS)
        AUDIT["tx_pending_excluidas"] = int(pend.sum())
        tx = tx.loc[~pend].copy()
    if "accounting_status" in tx.columns:
        disc = tx["accounting_status"].astype(str).str.upper().eq("DISCARDED")
        AUDIT["tx_discarded_conservadas"] = int(disc.sum())
    if "exchange_rate" in tx.columns:
        er = num(tx["exchange_rate"])
        AUDIT["tx_tipo_cambio_fuera_de_rango"] = int(
            (~er.between(cfg.EXCHANGE_RATE_MIN, cfg.EXCHANGE_RATE_MAX)).sum()
        )
        AUDIT["tx_tipo_cambio_igual_a_uno"] = int(er.eq(1).sum())
    AUDIT["tx_politica_moneda"] = (
        "amount ya está en moneda de la cuenta. NO se multiplica por "
        "exchange_rate para inventar EUR (en cuentas no-EUR el tipo es 1 "
        "en el 64% de las filas). Los ratios del score son invariantes a "
        "la moneda. Las facturas sí se llevan a accounting_currency."
    )
    AUDIT["tx_filas_en_ventana"] = int(len(tx))
    # 107k filas idénticas con transaction_id distinto (TPV, comisiones): son
    # repeticiones legítimas, no doble carga. Se cuentan y se dejan.
    cols_dup = [c for c in tx.columns if c != "transaction_id"]
    AUDIT["tx_exact_dupes_kept"] = int(tx.duplicated(subset=cols_dup).sum())
    cov_tx = tx.groupby("company_id")["date"].agg(first_tx="min", last_tx="max")

    # Tesorería operativa: solo cuentas de caja y sin transferencias internas,
    # inversión ni servicio de deuda. Sin este filtro, un traspaso entre
    # cuentas propias o una disposición de préstamo inflan ingresos y gastos.
    bp = leer("banking_products.csv", obligatorio=False)
    if bp is not None and {"product_id", "type"}.issubset(bp.columns):
        tx = tx.merge(
            bp[["product_id", "type"]].drop_duplicates("product_id"),
            on="product_id", how="left",
        )
        tipos = tx["type"].astype(str).str.lower()
        tx["is_cash"] = tipos.apply(
            lambda t: any(k in t for k in cfg.TIPOS_CAJA_FLUJO)
        )
        tx.loc[tx["type"].isna(), "is_cash"] = True
    else:
        tx["is_cash"] = True

    cat = (tx["category"].astype(str).str.lower().str.strip()
           if "category" in tx.columns
           else pd.Series("", index=tx.index))
    n_typo = int(cat.eq("cash_settlements").sum())
    cat = cat.replace({"cash_settlements": "cash_settlement", "-": "uncategorized"})
    AUDIT["tx_cash_settlements_typo"] = n_typo
    tx["cat_bucket"] = np.select(
        [cat.isin(cfg.CAT_INTERNAL),
         cat.isin(cfg.CAT_INVESTMENT),
         cat.isin(cfg.CAT_FINANCING)],
        ["internal", "investment", "financing"],
        default="operational",
    )
    op = tx["is_cash"] & tx["cat_bucket"].eq("operational")
    AUDIT["tx_cash_share"] = round(float(tx["is_cash"].mean()), 4)
    AUDIT["tx_bucket"] = tx["cat_bucket"].value_counts().to_dict()
    AUDIT["tx_filas_operativas"] = int(op.sum())

    tx["amt_in"] = np.where(op & tx["amount"].gt(0), tx["amount"], 0.0)
    tx["amt_out"] = np.where(op & tx["amount"].lt(0), -tx["amount"], 0.0)
    tx["amt_net"] = np.where(op, tx["amount"], 0.0)
    tx["amt_cobro"] = np.where(cat.isin(cfg.CAT_COBROS) & tx["amount"].gt(0),
                               tx["amount"], 0.0)
    tx["amt_refund"] = np.where(cat.isin(cfg.CAT_REFUND), tx["amount"].abs(), 0.0)
    tx["amt_deuda"] = np.where(cat.isin(cfg.CAT_FINANCING), tx["amount"].abs(), 0.0)

    g = tx.groupby(["company_id", "year_month"], as_index=False).agg(
        caja_ingresos=("amt_in", "sum"),
        caja_gastos=("amt_out", "sum"),
        flujo_neto=("amt_net", "sum"),
        cobros=("amt_cobro", "sum"),
        devoluciones=("amt_refund", "sum"),
        deuda_pagada=("amt_deuda", "sum"),
    )

    mapa_cp = None
    if "counterparty_id" in tx.columns:
        d = tx.dropna(subset=["counterparty_id"])
        d = d[d["counterparty_id"].astype(str).str.strip().ne("")]
        if not d.empty:
            mapa_cp = d.groupby(["company_id", "counterparty_id"])["amount"].sum()
            AUDIT["tx_contrapartes_resueltas"] = int(len(mapa_cp))
            AUDIT["tx_sin_contraparte"] = int(len(tx) - len(d))
    return g, mapa_cp, cov_tx


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


def direccion_por_contraparte(inv, mapa_cp):
    """Dirección deducida del flujo bancario real con esa contraparte.

    invoices.csv no trae columna de dirección, pero counterparty_id es el mismo
    espacio de IDs que en transactions.csv (ver data_dictionary.md). Si el neto
    cobrado a una contraparte es positivo, es un cliente: sus facturas son
    cobrables. Si es negativo, es un proveedor.
    """
    if mapa_cp is None or "counterparty_id" not in inv.columns:
        return None

    clave = pd.MultiIndex.from_arrays([inv["company_id"], inv["counterparty_id"]])
    neto = pd.Series(clave.map(mapa_cp), index=inv.index)
    cobertura = float(neto.notna().mean())
    AUDIT["direccion_contraparte_cobertura"] = round(cobertura, 4)

    es_venta = neto > 0
    por_signo = num(inv["amount"]) > 0
    comparables = neto.notna()
    if comparables.any():
        acuerdo = float((es_venta[comparables] == por_signo[comparables]).mean())
        AUDIT["direccion_acuerdo_contraparte_vs_signo"] = round(acuerdo, 4)

    if cobertura < 0.80:
        print(f"  [WARN] counterparty_id solo cubre {cobertura:.1%} de las facturas; "
              f"no se usa como dirección.")
        return None

    # Las facturas sin contraparte resuelta caen al signo, que es la única señal.
    es_venta = es_venta.where(comparables, por_signo)
    print(f"  Dirección resuelta por flujo bancario de 'counterparty_id' "
          f"(cobertura {cobertura:.1%}, acuerdo con el signo "
          f"{AUDIT.get('direccion_acuerdo_contraparte_vs_signo', float('nan')):.1%})")
    AUDIT["direccion_metodo"] = "counterparty_id:neto_transacciones"
    AUDIT["direccion_reparto"] = {
        "ventas": int(es_venta.sum()), "compras": int((~es_venta).sum()),
    }
    return es_venta


def clasificar_direccion(inv, mapa_cp=None):
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

    por_cp = direccion_por_contraparte(inv, mapa_cp)
    if por_cp is not None:
        return por_cp

    col_doc = cfg.detectar(inv, "document_kind")
    if col_doc is not None:
        vals = inv[col_doc].astype(str).str.strip().str.lower()
        es_venta = vals.isin(cfg.VALORES_RECEIVABLE)
        es_compra = vals.isin(cfg.VALORES_PAYABLE)
        if es_venta.any() and es_compra.any():
            print(f"  Dirección resuelta por '{col_doc}' "
                  f"({int(es_venta.sum()):,} ventas / {int(es_compra.sum()):,} compras)")
            AUDIT["direccion_metodo"] = f"columna:{col_doc}"
            return es_venta

    if "concept" in inv.columns:
        c = inv["concept"].astype(str).str.lower()
        es_venta = c.str.contains(r"venta|sales|receivable|cliente|customer", na=False, regex=True)
        es_compra = c.str.contains(r"compra|purchase|payable|proveedor|supplier", na=False, regex=True)
        # Solo vale si clasifica casi todo y sin ambigüedad: un texto que cubre
        # el 3% de las filas dejaría el 97% restante etiquetado como compra.
        clasificadas = (es_venta ^ es_compra)
        cobertura = float(clasificadas.mean())
        AUDIT["direccion_concept_cobertura"] = round(cobertura, 4)
        if cobertura >= 0.95:
            print(f"  Dirección resuelta por texto en 'concept' "
                  f"(cobertura {cobertura:.1%})")
            AUDIT["direccion_metodo"] = "concept_texto"
            return es_venta & ~es_compra
        print(f"  [WARN] 'concept' solo clasifica {cobertura:.1%} de las filas; se descarta.")

    print("  [WARN] Fallback al signo del importe para la dirección.")
    print("         Si la convención real es receivable(+)/payable(-), esto es correcto;")
    print("         verificar con el desglose de document_type en el informe de calidad.")
    AUDIT["direccion_metodo"] = "fallback_signo"
    es_venta = num(inv["amount"]) > 0
    AUDIT["direccion_reparto"] = {
        "ventas": int(es_venta.sum()), "compras": int((~es_venta).sum()),
    }
    return es_venta


def marcar_impago(inv):
    """Impago as-of el cierre de cada mes, sin look-ahead y sin creer a ciegas
    a 'payment_date'.

    Hallazgo del dataset: payment_date está poblada en el 99,99% de las filas,
    incluidas las que siguen con status 'overdue' y pending_amount == amount.
    Es decir, para una factura no cobrada es una fecha PREVISTA, no un cobro.
    Tomarla como cobro real anulaba todo impago histórico (morosidad 0,0).

    Criterio: una factura está cobrada solo si su pendiente está liquidado. En
    ese caso payment_date sí es la fecha de cobro. Si sigue pendiente, continúa
    abierta hasta el final de la ventana.
    """
    col_pago = cfg.detectar(inv, "payment_date")
    if not col_pago:
        inv["fecha_cobro"] = pd.NaT
        inv["is_overdue"] = inv["status"].astype(str).str.lower().eq("overdue")
        inv["dias_retraso"] = np.nan
        print("  [WARN] Sin fecha de pago: se usa 'status' (LOOK-AHEAD presente)")
        AUDIT["overdue_metodo"] = "status_snapshot_con_lookahead"
        return inv

    inv["payment_date"] = pd.to_datetime(inv[col_pago], errors="coerce")
    cobrada = inv["pending_abs"].le(cfg.TOLERANCIA_COBRO) | inv["pending_abs"].isna()
    inv["fecha_cobro"] = inv["payment_date"].where(cobrada)

    # payment_date de una cobrada puede venir en el futuro o antes de emitir.
    # Se recorta; no se usa status==paid (pending_amount es la verdad as-of).
    fut = cobrada & inv["fecha_cobro"].notna() & (inv["fecha_cobro"] > cfg.EXTRACTION_DATE)
    AUDIT["inv_paid_future_date_clipped"] = int(fut.sum())
    inv.loc[fut, "fecha_cobro"] = cfg.EXTRACTION_DATE
    early = (
        cobrada
        & inv["fecha_cobro"].notna()
        & inv["issuance_date"].notna()
        & (inv["fecha_cobro"] < inv["issuance_date"])
    )
    AUDIT["inv_paid_before_issuance_clipped"] = int(early.sum())
    inv.loc[early, "fecha_cobro"] = inv.loc[early, "issuance_date"]

    fin_mes = inv["year_month_vencimiento"].dt.to_timestamp(how="end")
    inv["is_overdue"] = (inv["due_date"] <= fin_mes) & (
        inv["fecha_cobro"].isna() | (inv["fecha_cobro"] > fin_mes))

    retraso = (inv["fecha_cobro"] - inv["due_date"]).dt.days
    inv["dias_retraso"] = retraso.clip(lower=0, upper=cfg.MAX_DIAS_RETRASO)

    print(f"  Impago reconstruido as-of por mes desde '{col_pago}' + pendiente "
          f"(sin look-ahead)")
    AUDIT["overdue_metodo"] = f"as_of:{col_pago}+pending_amount"
    AUDIT["inv_cobradas"] = int(cobrada.sum())
    AUDIT["inv_abiertas_al_cierre"] = int((~cobrada).sum())
    AUDIT["inv_retraso_corrupto_recortado"] = int(
        (retraso.notna() & ((retraso < 0) | (retraso > cfg.MAX_DIAS_RETRASO))).sum()
    )
    return inv


def periodos_desde_ordinales(ordinales):
    """PeriodIndex mensual a partir de ordinales, compatible entre versiones."""
    if hasattr(pd.PeriodIndex, "from_ordinals"):
        return pd.PeriodIndex.from_ordinals(ordinales, freq="M")
    return pd.PeriodIndex(ordinales, freq="M")


def stock_asof_mensual(inv, mask, sufijo):
    """Importe impagado vivo al cierre de cada mes del panel, con antigüedad.

    Una factura entra el mes de vencimiento si sigue impagada a fin de ese mes
    y permanece hasta el mes anterior al pago (o hasta MONTH_END si no hay pago).

    Devuelve tres columnas por cohorte:
      stock_overdue_{sufijo}  importe total vivo
      stock_{sufijo}_antiguo  parte con más de DIAS_STOCK_ANTIGUO días vencida
      _peso_dias_{sufijo}     sum(importe x días vencido), para la edad media
    """
    nombre = f"stock_overdue_{sufijo}"
    col_antiguo = f"stock_{sufijo}_antiguo"
    col_peso = f"_peso_dias_{sufijo}"
    cols = ["company_id", "year_month", nombre, col_antiguo, col_peso]
    d = inv.loc[
        mask
        & (inv["is_credit_note"] == 0)
        & inv["impago_abs"].notna()
        & inv["due_date"].notna()
        & inv["company_id"].notna()
        & inv["is_overdue"].astype(bool)
    ].copy()
    if d.empty:
        return pd.DataFrame(columns=cols)

    # Se trabaja en ordinales de periodo mensual: el tramo vivo de cada factura
    # va del mes de vencimiento al mes anterior al pago (o al fin de ventana).
    ord_min, ord_max = cfg.MONTH_START.ordinal, cfg.MONTH_END.ordinal
    start = pd.PeriodIndex(d["year_month_vencimiento"]).asi8
    # NaT no tiene ordinal utilizable: se sustituye por el fin de ventana antes
    # de pasar a enteros para que la resta no desborde.
    ym_cobro = d["fecha_cobro"].dt.to_period("M").fillna(cfg.MONTH_END)
    cobrada = d["fecha_cobro"].notna().to_numpy()
    end = np.where(cobrada, pd.PeriodIndex(ym_cobro).asi8 - 1, ord_max)

    start = np.clip(start, ord_min, ord_max)
    end = np.clip(end, ord_min, ord_max)
    keep = start <= end
    d, start, end = d.loc[keep], start[keep], end[keep]
    if d.empty:
        return pd.DataFrame(columns=cols)

    n = end - start + 1
    row_idx = np.repeat(np.arange(len(d)), n)
    offsets = np.arange(int(n.sum())) - np.repeat(np.cumsum(n) - n, n)

    ym = periodos_desde_ordinales(start[row_idx] + offsets)
    importe = d["impago_abs"].to_numpy()[row_idx]
    # Días vencida al cierre de cada mes en que sigue viva.
    dias = (ym.to_timestamp(how="end")
            - d["due_date"].to_numpy()[row_idx]).days.to_numpy().clip(
                min=0, max=cfg.CAP_DIAS_IMPAGO)

    out = pd.DataFrame({
        "company_id": d["company_id"].to_numpy()[row_idx],
        "year_month": ym,
        nombre: importe,
        col_antiguo: np.where(dias > cfg.DIAS_STOCK_ANTIGUO, importe, 0.0),
        col_peso: importe * dias,
    })
    return out.groupby(["company_id", "year_month"], as_index=False)[
        [nombre, col_antiguo, col_peso]].sum()


def concentracion(inv, mask, sufijo):
    """Dependencia de pocas contrapartes, por empresa y mes.

    Un HHI alto no es malo por sí mismo, pero convierte cualquier impago de esa
    contraparte en un problema sistémico: es el multiplicador del riesgo, no el
    riesgo. Mensual es ruidoso con pocas facturas; usar la versión suavizada 3m.
    """
    cols = ["company_id", "year_month", f"top1_{sufijo}_share"]
    if "counterparty_id" not in inv.columns:
        return pd.DataFrame(columns=cols)

    d = inv[
        mask
        & (inv["is_credit_note"] == 0)
        & inv["amount_abs"].notna()
        & inv["counterparty_id"].notna()
        & inv["year_month"].between(cfg.MONTH_START, cfg.MONTH_END)
    ]
    if d.empty:
        return pd.DataFrame(columns=cols)

    por_cp = d.groupby(["company_id", "year_month", "counterparty_id"])["amount_abs"].sum()
    total = por_cp.groupby(level=[0, 1]).sum()
    share = por_cp / total.reindex(por_cp.index.droplevel(2)).to_numpy()

    # Solo top1: el HHI y el conteo de contrapartes se calculaban y nadie los
    # leía. El modulador usa `top1_*_share_3m`.
    out = pd.DataFrame({
        f"top1_{sufijo}_share": share.groupby(level=[0, 1]).max(),
    }).reset_index()
    return out


def winsorizar_facturas(inv):
    """Una factura de 6e10 no puede dominar el ratio de la empresa.

    Tope = p99 por empresa y dirección. Con menos de 5 facturas no se recorta
    (el p99 sería el propio máximo).
    """
    g = inv.groupby(["company_id", "is_receivable"], sort=False)["amount_abs"]
    cap = g.transform(
        lambda s: s.quantile(0.99) if s.notna().sum() >= 5 else (
            s.max() if s.notna().any() else np.nan)
    )
    clipped = inv["amount_abs"].notna() & cap.notna() & (inv["amount_abs"] > cap)
    AUDIT["inv_winsor_p99"] = int(clipped.sum())
    AUDIT["inv_winsor_p99_importe"] = float(
        (inv.loc[clipped, "amount_abs"] - cap[clipped]).sum()
    ) if clipped.any() else 0.0
    inv["amount_abs"] = inv["amount_abs"].clip(upper=cap)
    return inv


def build_facturas(mapa_cp=None):
    inv = leer("invoices.csv")
    due = pd.to_datetime(inv["due_date"], errors="coerce")
    issue_col = "issuance_date" if "issuance_date" in inv.columns else None
    issue = pd.to_datetime(inv[issue_col], errors="coerce") if issue_col else due.copy()

    AUDIT["inv_filas_raw"] = int(len(inv))
    AUDIT["inv_fechas_invalidas_due"] = int(due.isna().sum())
    AUDIT["inv_fechas_invalidas_issuance"] = int(issue.isna().sum()) if issue_col else None

    inv = inv.assign(due_date=due, issuance_date=issue)
    inv = inv.dropna(subset=["company_id"])

    inv["amount"] = num(inv["amount"])
    cero = inv["amount"].eq(0)
    AUDIT["inv_importe_cero_excluidas"] = int(cero.sum())
    inv = inv.loc[~cero].copy()

    # Vencimientos imposibles (NaT, plazo < 0 o > 2 años): emisión + 30d.
    term = (inv["due_date"] - inv["issuance_date"]).dt.days
    bad_due = inv["due_date"].isna() | term.lt(0) | term.gt(cfg.MAX_PLAZO_FACTURA_DIAS)
    reparable = bad_due & inv["issuance_date"].notna()
    AUDIT["inv_bad_due_date_fixed"] = int(reparable.sum())
    inv.loc[reparable, "due_date"] = (
        inv.loc[reparable, "issuance_date"]
        + pd.Timedelta(days=cfg.PLAZO_REPARACION_DIAS)
    )
    sin_fecha = inv["due_date"].isna() & inv["issuance_date"].isna()
    AUDIT["inv_sin_fecha_util_excluidas"] = int(sin_fecha.sum())
    inv = inv.loc[~sin_fecha].copy()

    # ---- Documentos que no son factura ni derecho de cobro -----------------
    col_doc = cfg.detectar(inv, "document_kind")
    if col_doc:
        tipos = inv[col_doc].astype(str).str.strip().str.lower()
        comercial = tipos.isin(cfg.TIPOS_DOC_COMERCIAL) | tipos.isin(
            {v.lower() for v in cfg.VALORES_RECTIFICATIVA})
        AUDIT["inv_doc_excluidos_por_tipo"] = (
            inv.loc[~comercial, col_doc].astype(str).value_counts().to_dict()
        )
        inv = inv[comercial].copy()

    if "status" in inv.columns:
        anulada = inv["status"].astype(str).str.strip().str.lower().isin(
            cfg.ESTADOS_ANULADOS)
        AUDIT["inv_anuladas_excluidas"] = int(anulada.sum())
        inv = inv[~anulada].copy()

    col_pago = cfg.detectar(inv, "payment_date")
    if col_pago:
        inv["payment_date"] = pd.to_datetime(inv[col_pago], errors="coerce")

    inv["pending_amount"] = num(inv.get("pending_amount", inv["amount"]))
    pending_tmp = inv["pending_amount"].abs()
    sigue_abierta = pending_tmp.gt(cfg.TOLERANCIA_COBRO) | pending_tmp.isna()

    # Volumen y vencimientos en ventana, más impagos abiertos anteriores (stock).
    # Abierta = pendiente no liquidado. payment_date sola no basta: en overdue
    # viene rellenada con el vencimiento y expulsaba stock anterior a 2024-09.
    en_ventana_due = inv["due_date"].between(cfg.START_DATE, cfg.END_DATE)
    en_ventana_issue = inv["issuance_date"].between(cfg.START_DATE, cfg.END_DATE)
    if "payment_date" in inv.columns:
        abierto_previo = (
            (inv["due_date"] < cfg.START_DATE)
            & (sigue_abierta
               | inv["payment_date"].isna()
               | (inv["payment_date"] >= cfg.START_DATE))
        )
    else:
        abierto_previo = (inv["due_date"] < cfg.START_DATE) & sigue_abierta
    AUDIT["inv_abiertas_previas_recuperadas"] = int(abierto_previo.sum())
    inv = inv[en_ventana_due | en_ventana_issue | abierto_previo].copy()

    inv["year_month"] = inv["issuance_date"].dt.to_period("M")
    inv["year_month_vencimiento"] = inv["due_date"].dt.to_period("M")

    inv = normalizar_importes(inv)

    inv["amount_abs"] = inv["amount_reporting"].abs()
    pending_abs = inv["pending_reporting"].abs()
    # pending_amount es 0 en cuanto la factura se paga (ver data_dictionary.md):
    # es el estado EN LA EXTRACCIÓN, no el de cada mes. Usarlo como numerador
    # histórico anulaba todo impago que acabó cobrándose y dejaba la morosidad
    # a 0. El importe vivo as-of un mes es el nominal mientras siga impagada.
    inv["impago_abs"] = inv["amount_abs"]
    inv["pending_abs"] = np.fmin(pending_abs.fillna(inv["amount_abs"]), inv["amount_abs"])
    inv["is_credit_note"] = detectar_rectificativa(inv).astype(int)
    inv["is_receivable"] = clasificar_direccion(inv, mapa_cp)
    inv = winsorizar_facturas(inv)
    inv["impago_abs"] = inv["amount_abs"]
    inv["pending_abs"] = np.fmin(inv["pending_abs"], inv["amount_abs"])
    inv = marcar_impago(inv)

    AUDIT["inv_filas_en_ventana"] = int(len(inv))
    AUDIT["inv_filas_con_issuance_en_ventana"] = int(en_ventana_issue.loc[inv.index].sum())
    AUDIT["inv_filas_con_due_en_ventana"] = int(en_ventana_due.loc[inv.index].sum())
    AUDIT["inv_rectificativas_en_ventana"] = int(inv["is_credit_note"].sum())
    AUDIT["inv_pending_mayor_que_amount"] = int(
        (pending_abs.fillna(0) > inv["amount_abs"].fillna(0) + 1e-6).sum()
    )
    AUDIT["inv_impago_metodo"] = "nominal_mientras_impagada (pending_amount es snapshot)"
    AUDIT["inv_parcialmente_pagadas"] = int(
        (inv["pending_abs"].gt(0) & inv["pending_abs"].lt(inv["amount_abs"] - 1e-6)).sum()
    )

    def cohorte(mask, sufijo):
        # Emisión: tamaño comercial. Vencimiento: denominador de morosidad.
        # Impago: misma cohorte de vencimiento, as-of cierre de ese mes.
        base = mask & (inv["is_credit_note"] == 0)

        d = inv[base & inv["year_month"].between(cfg.MONTH_START, cfg.MONTH_END)
                & inv["amount_abs"].notna()]
        tot = d.groupby(["company_id", "year_month"], as_index=False).agg(
            **{f"volumen_{sufijo}": ("amount_abs", "sum"),
               f"n_fact_{sufijo}": ("amount_abs", "size")}
        )

        d_due = inv[base & inv["year_month_vencimiento"].between(cfg.MONTH_START, cfg.MONTH_END)
                    & inv["amount_abs"].notna()]
        venc = d_due.groupby(
            ["company_id", "year_month_vencimiento"], as_index=False
        ).agg(
            **{f"volumen_vencido_{sufijo}": ("amount_abs", "sum"),
               f"n_fact_vencidas_{sufijo}": ("amount_abs", "size")}
        ).rename(columns={"year_month_vencimiento": "year_month"})

        d_ovr = inv[
            base
            & inv["year_month_vencimiento"].between(cfg.MONTH_START, cfg.MONTH_END)
            & inv["is_overdue"]
            & inv["impago_abs"].notna()
        ]
        ovr = d_ovr.groupby(
            ["company_id", "year_month_vencimiento"], as_index=False
        ).agg(
            **{f"atrapado_{sufijo}": ("impago_abs", "sum")}
        ).rename(columns={"year_month_vencimiento": "year_month"})

        return tot.merge(venc, on=["company_id", "year_month"], how="outer").merge(
            ovr, on=["company_id", "year_month"], how="outer"
        )

    ventas = cohorte(inv["is_receivable"], "ventas")
    compras = cohorte(~inv["is_receivable"], "compras")
    stock_cli = stock_asof_mensual(inv, inv["is_receivable"], "clientes")
    stock_prov = stock_asof_mensual(inv, ~inv["is_receivable"], "prov")
    conc_cli = concentracion(inv, inv["is_receivable"], "clientes")
    conc_prov = concentracion(inv, ~inv["is_receivable"], "prov")

    # Las rectificativas se excluyen de volumen_* (is_credit_note). No se
    # emiten columnas propias: nadie las leía.

    return (ventas, compras, stock_cli, stock_prov, conc_cli, conc_prov, inv)


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
    # 9.99e10 y similares: basura del origen. Se anulan, no se suman a caja.
    extreme = bal["balance"].notna() & (bal["balance"].abs() >= cfg.BALANCE_EXTREMO)
    AUDIT["balances_extreme_excluidos"] = int(extreme.sum())
    bal.loc[extreme, "balance"] = np.nan

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
    mag = debt["outstanding"].abs()

    col_tipo = cfg.detectar(debt, "debt_type")
    if col_tipo:
        AUDIT["deuda_tipos_incluidos"] = (
            debt[col_tipo].astype(str).value_counts().to_dict()
        )

    if "currency" in debt.columns:
        curr = debt["currency"].astype(str).str.upper().str.strip()
        if "exchange_rate" in debt.columns:
            rate = num(debt["exchange_rate"])
            rate_ok = rate.between(cfg.EXCHANGE_RATE_MIN, cfg.EXCHANGE_RATE_MAX)
        else:
            rate = pd.Series(np.nan, index=debt.index)
            rate_ok = pd.Series(False, index=debt.index)
        eur = curr.eq("EUR")
        debt["outstanding_eur"] = np.where(
            eur, mag, np.where(rate_ok, mag * rate, np.nan)
        )
        AUDIT["deuda_productos_sin_eur"] = int((~eur).sum())
        AUDIT["deuda_productos_no_convertibles"] = int(debt["outstanding_eur"].isna().sum())
    else:
        debt["outstanding_eur"] = mag

    g = debt.groupby("company_id")
    out = g.agg(
        deuda_viva=("outstanding_eur", "sum"),
        n_deudas=("outstanding_eur", "count"),
        n_deudas_raw=("outstanding", "size"),
        deuda_raw=("outstanding", "sum"),
    ).reset_index()
    sin_convertibles = g["outstanding_eur"].apply(lambda s: int(s.notna().sum()) == 0)
    out.loc[out["company_id"].map(sin_convertibles), "deuda_viva"] = np.nan
    out["deuda_signo_negativo_flag"] = (out["deuda_raw"] < 0).astype(int)
    out["deuda_conversion_incompleta"] = (
        out["n_deudas"] < out["n_deudas_raw"]
    ).astype(int)

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
    return out.drop(columns=["deuda_raw", "n_deudas_raw"])


# =============================================================================
# 4. PANEL
# =============================================================================

def calendario(empresas):
    idx = pd.MultiIndex.from_product([sorted(empresas), cfg.MONTHS],
                                     names=["company_id", "year_month"])
    return idx.to_frame(index=False)


def aplicar_ventana_observada(panel, cov_tx, inv, a_cero):
    """Dentro de la ventana, sin movimiento = 0. Fuera = NaN, no silencio.

    Ventana = [primer mes completo, último mes con tx o factura]. Si el primer
    movimiento cae después del día 3, ese mes de alta se descarta (incompleto).
    """
    parts = []
    if cov_tx is not None and len(cov_tx):
        parts.append(cov_tx.rename(columns={"first_tx": "inicio", "last_tx": "fin"}))
    if inv is not None and len(inv):
        fechas = [c for c in ("issuance_date", "due_date") if c in inv.columns]
        if fechas:
            d = inv.melt(id_vars=["company_id"], value_vars=fechas, value_name="d")
            d = d.dropna(subset=["d"])
            if not d.empty:
                parts.append(d.groupby("company_id")["d"].agg(inicio="min", fin="max"))

    if not parts:
        panel["observado"] = False
        AUDIT["filas_observadas"] = 0
        AUDIT["filas_fuera_ventana_nan"] = int(len(panel))
        return panel

    cov = pd.concat(parts).groupby(level=0).agg({"inicio": "min", "fin": "max"})
    first = pd.to_datetime(cov["inicio"])
    last = pd.to_datetime(cov["fin"])
    first_m = first.dt.to_period("M")
    first_m = first_m.where(first.dt.day <= cfg.DIA_MES_COMPLETO, first_m + 1)
    last_m = last.dt.to_period("M")
    first_m = first_m.where(first_m <= last_m, last_m)

    f = panel["company_id"].map(first_m)
    l = panel["company_id"].map(last_m)
    panel["observado"] = f.notna() & l.notna() & (panel["year_month"] >= f) & (
        panel["year_month"] <= l)
    panel["observado"] = panel["observado"].fillna(False)

    fuera = ~panel["observado"]
    for c in a_cero:
        if c in panel.columns:
            panel.loc[fuera, c] = np.nan

    AUDIT["empresas_con_ventana"] = int(cov.shape[0])
    AUDIT["filas_observadas"] = int(panel["observado"].sum())
    AUDIT["filas_fuera_ventana_nan"] = int(fuera.sum())
    AUDIT["primer_mes_incompleto_descartado"] = int((first.dt.day > cfg.DIA_MES_COMPLETO).sum())
    return panel


def escribir_cleaning_log():
    """Log de limpieza para el sponsor: cada corrección, numerada."""
    claves = [
        "tx_filas_raw", "tx_fechas_invalidas", "tx_filas_en_ventana",
        "tx_importe_cero_excluidas", "tx_pending_excluidas",
        "tx_discarded_conservadas", "tx_tipo_cambio_fuera_de_rango",
        "tx_tipo_cambio_igual_a_uno", "tx_politica_moneda",
        "tx_exact_dupes_kept", "tx_cash_settlements_typo",
        "tx_filas_operativas", "tx_bucket",
        "inv_filas_raw", "inv_fechas_invalidas_due", "inv_fechas_invalidas_issuance",
        "inv_importe_cero_excluidas", "inv_bad_due_date_fixed",
        "inv_sin_fecha_util_excluidas", "inv_anuladas_excluidas",
        "inv_doc_excluidos_por_tipo", "inv_abiertas_previas_recuperadas",
        "inv_paid_future_date_clipped", "inv_paid_before_issuance_clipped",
        "inv_winsor_p99", "inv_winsor_p99_importe",
        "inv_filas_en_ventana", "inv_importes_no_convertibles",
        "inv_tipo_cambio_fuera_de_rango", "overdue_metodo",
        "balances_sentinelas_excluidos", "balances_extreme_excluidos",
        "balances_modo",
        "empresas_con_ventana", "filas_observadas", "filas_fuera_ventana_nan",
        "primer_mes_incompleto_descartado",
    ]
    log = {k: AUDIT[k] for k in claves if k in AUDIT}
    log["principio"] = (
        "Cada corrección se cuenta. NaN = sin evidencia. 0 = medido y vale cero. "
        "pending_amount es la verdad del cobro, no status ni payment_date."
    )
    log["tipo_cambio"] = (
        "Se convierte a accounting_currency solo si el tipo está en "
        f"[{cfg.EXCHANGE_RATE_MIN}, {cfg.EXCHANGE_RATE_MAX}]; si no, el importe "
        "queda NaN. No se inventan tipos."
    )
    log["no_adoptado"] = [
        "reconstruccion_caja_hacia_atras",
        "imputar_50_si_falta_dato",
        "backfill_deuda_o_caja_a_todos_los_meses",
        "payment_date_como_cobro_si_status_paid",
        "incluir_card_en_flujos_de_tesoreria",
    ]
    cfg.CLEANING_LOG_PATH.write_text(
        json.dumps(log, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"Limpieza: {cfg.CLEANING_LOG_PATH}")


def build_panel():
    cfg.asegurar_dirs()
    print(f"Ventana: {cfg.START_DATE.date()} → {cfg.END_DATE.date()} "
          f"({len(cfg.MONTHS)} buckets mensuales)")

    print("\n[1/6] Transacciones...")
    tx, mapa_cp, cov_tx = build_transacciones()

    print("\n[2/6] Facturas...")
    (ventas, compras, stock_cli, stock_prov, conc_cli, conc_prov,
     inv) = build_facturas(mapa_cp)

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
    for extra in [tx, ventas, compras, stock_cli, stock_prov, conc_cli, conc_prov]:
        if not extra.empty:
            panel = panel.merge(extra, on=["company_id", "year_month"], how="left")

    print(f"  {len(empresas):,} empresas x {len(cfg.MONTHS)} meses = {len(panel):,} filas")

    # ---- Ceros legítimos: ausencia de fila = ausencia de actividad ---------
    a_cero = ["caja_ingresos", "caja_gastos", "flujo_neto",
              "cobros", "devoluciones", "deuda_pagada",
              "volumen_ventas", "n_fact_ventas", "atrapado_ventas",
              "volumen_compras", "n_fact_compras", "atrapado_compras",
              "volumen_vencido_ventas", "n_fact_vencidas_ventas",
              "volumen_vencido_compras", "n_fact_vencidas_compras",
              "stock_overdue_clientes", "stock_overdue_prov",
              "stock_clientes_antiguo", "stock_prov_antiguo",
              "_peso_dias_clientes", "_peso_dias_prov"]
    for c in a_cero:
        if c in panel.columns:
            panel[c] = panel[c].fillna(0)
        else:
            panel[c] = 0.0

    panel = panel.sort_values(["company_id", "year_month"]).reset_index(drop=True)
    panel = aplicar_ventana_observada(panel, cov_tx, inv, a_cero)

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
    escribir_cleaning_log()

    print(f"\nPanel: {cfg.PANEL_PATH} ({len(panel):,} filas, {panel.shape[1]} columnas)")
    print(f"Auditoría: {cfg.AUDIT_PATH}")
    resumen(panel)
    return panel


# =============================================================================
# 5. DERIVADAS
# =============================================================================

def derivar(panel):
    # ---- Actividad y disponibilidad ---------------------------------------
    panel["tx_disponible"] = (panel["caja_ingresos"] + panel["caja_gastos"] > 0).astype(int)
    panel["ventas_disponible"] = (panel["volumen_ventas"] > 0).astype(int)
    panel["compras_disponible"] = (panel["volumen_compras"] > 0).astype(int)
    panel["mes_activo"] = ((panel["tx_disponible"] + panel["ventas_disponible"]
                            + panel["compras_disponible"]) > 0).astype(int)

    # Recibos devueltos y servicio de deuda: señales mensuales que el otro
    # enfoque sí usaba y que aquí existen todos los meses (no son snapshot).
    panel["refund_rate"] = np.where(
        panel["cobros"] > 0,
        np.clip(panel["devoluciones"] / panel["cobros"], 0, cfg.CAP_REFUND_RATE),
        np.nan)
    cobros_3m = roll_sum(panel, "cobros", cfg.ROLL_SHORT, strict=False)
    ref_3m = roll_sum(panel, "devoluciones", cfg.ROLL_SHORT, strict=False)
    panel["refund_rate_3m"] = np.where(
        cobros_3m > 0, np.clip(ref_3m / cobros_3m, 0, cfg.CAP_REFUND_RATE), np.nan)

    panel["debt_service"] = np.where(
        panel["caja_ingresos"] > 0,
        np.clip(panel["deuda_pagada"] / panel["caja_ingresos"], 0, cfg.CAP_DEBT_SERVICE),
        np.nan)
    deuda_3m = roll_sum(panel, "deuda_pagada", cfg.ROLL_SHORT, strict=False)
    ing_3m = roll_sum(panel, "caja_ingresos", cfg.ROLL_SHORT, strict=False)
    panel["debt_service_3m"] = np.where(
        ing_3m > 0, np.clip(deuda_3m / ing_3m, 0, cfg.CAP_DEBT_SERVICE), np.nan)

    # ---- Burn rate: NaN cuando no hay denominador, flag aparte -------------
    panel["mes_sin_ingresos"] = ((panel["caja_ingresos"] == 0)
                                 & (panel["caja_gastos"] > 0)).astype(int)
    panel["burn_rate"] = np.where(panel["caja_ingresos"] > 0,
                                  panel["caja_gastos"] / panel["caja_ingresos"], np.nan)
    panel["burn_rate"] = panel["burn_rate"].clip(upper=cfg.CAP_BURN_RATE)

    # ---- Morosidad: misma cohorte (vencimiento), NaN sin denominador --------
    panel["pct_clientes_morosos"] = np.where(
        panel["volumen_vencido_ventas"] > 0,
        100 * panel["atrapado_ventas"] / panel["volumen_vencido_ventas"], np.nan)
    panel["pct_impagos_prov"] = np.where(
        panel["volumen_vencido_compras"] > 0,
        100 * panel["atrapado_compras"] / panel["volumen_vencido_compras"], np.nan)

    # ---- Morosidad sobre sumas móviles (robusta a meses de pocas facturas) -
    # Con ~1 factura/mes por empresa, una ventana de 3 meses partida entre
    # ventas y compras a menudo no llega al mínimo. Si falla, se intenta con
    # 6 meses antes de rendirse a NaN, y se deja constancia de qué ventana
    # sostiene el dato para que el score pueda rebajar su confianza.
    for nombre, num_c, den_c, nf_c in [
        ("pct_clientes_morosos_3m", "atrapado_ventas", "volumen_vencido_ventas",
         "n_fact_vencidas_ventas"),
        ("pct_impagos_prov_3m", "atrapado_compras", "volumen_vencido_compras",
         "n_fact_vencidas_compras"),
    ]:
        n3, d3, f3 = roll_sum(panel, num_c, cfg.ROLL_SHORT), roll_sum(panel, den_c, cfg.ROLL_SHORT), roll_sum(panel, nf_c, cfg.ROLL_SHORT)
        n6, d6, f6 = roll_sum(panel, num_c, cfg.ROLL_LONG), roll_sum(panel, den_c, cfg.ROLL_LONG), roll_sum(panel, nf_c, cfg.ROLL_LONG)

        ratio_3m = np.where(d3 > 0, 100 * n3 / d3, np.nan)
        ratio_6m = np.where(d6 > 0, 100 * n6 / d6, np.nan)

        usa_3m = f3 >= cfg.MIN_FACTURAS_RATIO
        usa_6m = (~usa_3m) & (f6 >= cfg.MIN_FACTURAS_RATIO_LARGO)

        panel[nombre] = np.select([usa_3m, usa_6m], [ratio_3m, ratio_6m], default=np.nan)
        panel[f"{nombre}_fuente"] = np.select([usa_3m, usa_6m], ["3m", "6m"], default="sin_datos")

    # ---- Antigüedad del stock de impago -----------------------------------
    # Mismo importe atrapado no significa lo mismo con 20 o con 200 días. La
    # edad es lo que distingue un retraso de gestión de un impago estructural.
    for suf in ("clientes", "prov"):
        stock = panel[f"stock_overdue_{suf}"]
        panel[f"edad_media_stock_{suf}_dias"] = np.where(
            stock > 0, panel[f"_peso_dias_{suf}"] / stock, np.nan)
        panel[f"share_stock_{suf}_antiguo"] = np.where(
            stock > 0, panel[f"stock_{suf}_antiguo"] / stock, np.nan)
    panel = panel.drop(columns=["_peso_dias_clientes", "_peso_dias_prov"])

    # stock_overdue_* llega ya como foto as-of de cada mes.

    # ---- Medias móviles ----------------------------------------------------
    # La ventana de 6 meses solo se conserva para el flujo, donde el validador
    # comprueba la invariante de estrictez. En morosidad y burn_rate nadie leía
    # el `_6m_avg`: la ventana larga de morosidad ya vive dentro de
    # `pct_*_3m` vía su cascada de fuentes (ver `*_fuente`).
    for col, pref, con_6m, con_vs in [
        ("flujo_neto", "flujo_neto", True, False),
        ("burn_rate", "burn_rate", False, False),
        ("pct_clientes_morosos_3m", "clientes_morosos", False, False),
        ("pct_impagos_prov_3m", "impagos_prov", False, True),
    ]:
        panel[f"{pref}_3m_avg"] = roll_mean(panel, col, cfg.ROLL_SHORT)
        if con_6m:
            panel[f"{pref}_6m_avg"] = roll_mean(panel, col, cfg.ROLL_LONG)
        if con_vs:
            panel[f"{pref}_3m_vs_prev3m"] = bloque_vs_bloque(panel, col, cfg.ROLL_SHORT)

    panel["ingresos_3m_avg"] = roll_mean(panel, "caja_ingresos", cfg.ROLL_SHORT, strict=False)
    panel["ingresos_12m_avg"] = panel.groupby("company_id")["caja_ingresos"].transform(
        lambda s: s.rolling(12, min_periods=3).mean())
    panel["gastos_3m_avg"] = roll_mean(panel, "caja_gastos", cfg.ROLL_SHORT, strict=False)

    # ---- Momentum de ingresos y gastos (cobertura total) -------------------
    # Las transacciones son la única fuente sin huecos, así que aquí viven las
    # señales que sí existen en los 24 meses. La caída de ingresos precede al
    # impago: se puede medir mucho antes de que una factura venza.
    ing_prev = panel.groupby("company_id")["ingresos_3m_avg"].shift(cfg.ROLL_SHORT)
    gas_prev = panel.groupby("company_id")["gastos_3m_avg"].shift(cfg.ROLL_SHORT)
    panel["ingresos_momentum_3m"] = np.clip(
        np.where(ing_prev > 0, panel["ingresos_3m_avg"] / ing_prev - 1, np.nan),
        -1.0, cfg.CAP_MOMENTUM)
    panel["gastos_momentum_3m"] = np.clip(
        np.where(gas_prev > 0, panel["gastos_3m_avg"] / gas_prev - 1, np.nan),
        -1.0, cfg.CAP_MOMENTUM)
    # Tijera: ingresos cayendo mientras el gasto sube. El deterioro estructural
    # clásico, visible antes de que el flujo neto se vuelva negativo.
    panel["flag_tijera"] = (
        panel["ingresos_momentum_3m"].lt(-0.05)
        & panel["gastos_momentum_3m"].gt(0.05)
    ).fillna(False).astype(int)

    # ---- Colchón de flujo: runway disponible en TODOS los meses -----------
    # caja_real solo existe en el último mes. Este proxy usa el flujo acumulado
    # de 6 meses sobre el gasto medio: cuántos meses de gasto ha generado (o
    # quemado) la empresa por sí misma. Negativo = consumiendo colchón.
    flujo_6m = roll_sum(panel, "flujo_neto", cfg.ROLL_LONG, strict=True)
    panel["colchon_flujo_meses"] = np.clip(
        np.where(panel["gastos_3m_avg"] > 0, flujo_6m / panel["gastos_3m_avg"], np.nan),
        -cfg.CAP_COLCHON_MESES, cfg.CAP_COLCHON_MESES)

    # ---- Señales de recuperación (positivo = mejora) -----------------------
    # Solo se conserva la de proveedores: es el fallback del eje de trayectoria
    # cuando falta recuperacion_stock_prov. Las de clientes y flujo no las leía
    # nadie.
    panel["recuperacion_prov"] = -panel["impagos_prov_3m_vs_prev3m"]

    # ---- Flags de estrés y persistencia -----------------------------------
    flags = {
        "flag_flujo_negativo": panel["flujo_neto"] < 0,
        "flag_estres_prov": panel["pct_impagos_prov_3m"] >= 30,
        "flag_estres_clientes": panel["pct_clientes_morosos_3m"] >= 30,
        "flag_stock_prov_antiguo": panel["share_stock_prov_antiguo"] >= 0.5,
        "flag_tijera": panel["flag_tijera"] == 1,
    }
    # El conteo a 3 meses existe porque de él sale `persistente_*`, que es lo que
    # lee el motor. La versión a 6 meses se calculaba y no la leía nadie.
    for nombre, serie in flags.items():
        panel[nombre] = serie.fillna(False).astype(int)
        panel[f"{nombre}_3m"] = roll_sum(panel, nombre, cfg.ROLL_SHORT, strict=True)
        panel[f"persistente_{nombre}"] = (panel[f"{nombre}_3m"] == 3).astype(int)

    return panel


def normalizar(panel, companies):
    # caja_real y caja_negativa_flag NO se rellenan a 0: la ausencia de un
    # balance reportado es "sin visibilidad", no "cero en caja". Confundirlas
    # hundía el runway de las empresas sin cuenta corriente detectada.
    # El motor DEBE comparar el flag con == 1. bool(nan) es True en Python.
    if "caja_real" not in panel.columns:
        panel["caja_real"] = np.nan
    panel["caja_reportada"] = panel.get("caja_reportada", 0)
    panel["caja_reportada"] = panel["caja_reportada"].fillna(0).astype(int)
    if "caja_negativa_flag" in panel.columns:
        panel["caja_negativa_flag"] = np.where(panel["caja_reportada"] == 1,
                                               panel["caja_negativa_flag"], np.nan)

    for c in ["deuda_viva", "n_deudas", "deuda_signo_negativo_flag",
              "deuda_conversion_incompleta"]:
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
    panel["flujo_relativo"] = np.clip(
        np.where(panel["ingresos_12m_avg"] > 0,
                 panel["flujo_neto"] / panel["ingresos_12m_avg"], np.nan),
        -cfg.CAP_FLUJO_RELATIVO, cfg.CAP_FLUJO_RELATIVO)
    panel["flujo_relativo_3m"] = roll_mean(panel, "flujo_relativo", cfg.ROLL_SHORT)
    # min_periods=1 aquí daría "runway" a partir de un solo mes de gasto, que
    # puede ser casi nulo en el primer mes de actividad y disparar el ratio
    # al techo. Se exige un mínimo de MIN_MESES_RUNWAY antes de calcularlo.
    gastos_runway = panel.groupby("company_id")["caja_gastos"].transform(
        lambda s: s.rolling(cfg.ROLL_SHORT, min_periods=cfg.MIN_MESES_RUNWAY).mean())
    panel["runway_meses"] = np.where(
        (gastos_runway > 0) & (panel["caja_reportada"] == 1),
        panel["caja_real"] / gastos_runway, np.nan)
    panel["runway_meses"] = panel["runway_meses"].clip(
        lower=-12, upper=cfg.CAP_RUNWAY_MESES)
    panel["deuda_sobre_ingresos"] = np.where(
        (panel["ingresos_12m_avg"] > 0) & panel["deuda_viva"].notna(),
        panel["deuda_viva"] / (panel["ingresos_12m_avg"] * 12), np.nan)
    # Los topes evitan que un ingresos_12m_avg casi nulo genere ratios de seis
    # cifras que destruyen cualquier media, percentil o z-score posterior.
    for suf, origen in (("prov", "stock_overdue_prov"),
                        ("clientes", "stock_overdue_clientes")):
        crudo = np.where(panel["ingresos_12m_avg"] > 0,
                         panel[origen] / panel["ingresos_12m_avg"], np.nan)
        col = f"stock_{suf}_sobre_ingresos"
        panel[col] = np.clip(crudo, 0, cfg.CAP_STOCK_SOBRE_INGRESOS)
        panel[f"{col}_topado"] = (
            pd.Series(crudo, index=panel.index) > cfg.CAP_STOCK_SOBRE_INGRESOS
        ).fillna(False).astype(int)

    # ---- Tendencia y volatilidad ------------------------------------------
    g = panel.groupby("company_id")
    panel["flujo_pendiente_robusta_6m"] = g["flujo_relativo"].transform(
        lambda s: s.rolling(cfg.ROLL_LONG, min_periods=3).apply(
            pendiente_robusta, raw=False))
    panel["flujo_volatilidad_6m"] = g["flujo_relativo"].transform(
        lambda s: s.rolling(cfg.ROLL_LONG, min_periods=3).std())

    # ---- Dirección de la deuda comercial (alta cobertura) ------------------
    # recuperacion_prov depende de pct_impagos_prov_3m, que falta en el 69% de
    # las filas. Sobre el stock normalizado la misma señal existe en el 69%,
    # así que es la que sostiene el eje de trayectoria. Signo invertido: en
    # todas las 'recuperacion_*', positivo significa mejora.
    col = "stock_prov_sobre_ingresos"
    panel[f"{col}_3m_vs_prev3m"] = bloque_vs_bloque(panel, col, cfg.ROLL_SHORT)
    panel["recuperacion_stock_prov"] = -panel[f"{col}_3m_vs_prev3m"]

    # ---- Historia comercial acumulada --------------------------------------
    # Permite afirmar "ha comprado y no debe nada vencido", que es un dato, no
    # una ausencia de dato. Sin esto, stock 0 era indistinguible de sin datos.
    panel["ventas_acum"] = g["volumen_ventas"].cumsum()
    panel["compras_acum"] = g["volumen_compras"].cumsum()

    # ---- Concentración suavizada -------------------------------------------
    for col in ("top1_clientes_share", "top1_prov_share"):
        if col in panel.columns:
            panel[f"{col}_3m"] = roll_mean(panel, col, cfg.ROLL_SHORT, strict=False)

    # ---- Posición relativa dentro del mes ----------------------------------
    # mas_es_mejor=False en todo lo que es un problema cuando crece.
    #
    # La referencia se congela en disco la primera vez y se reutiliza después.
    # Sin esto el sistema no sería reproducible sobre empresas nuevas: puntuar 70
    # empresas las compararía entre ellas y no contra la población de referencia,
    # y los canales de alerta, que son todos percentiles, se moverían de sitio.
    referencia = {}
    if cfg.USAR_REFERENCIA_PCTL and cfg.PCTL_REF_PATH.exists():
        referencia = json.loads(cfg.PCTL_REF_PATH.read_text(encoding="utf-8"))
        print(f"    referencia de percentiles cargada de {cfg.PCTL_REF_PATH.name} "
              f"({len(referencia)} columnas)")

    nueva_ref = {}
    # Solo los percentiles que consume el motor (ejes, moduladores o canales).
    # Se dejaron de generar pctl_impagos_prov_3m, pctl_edad_stock_prov y
    # pctl_gastos_momentum_3m: nadie los leía.
    for col, alias, mejor in (
            ("flujo_relativo_3m", "flujo_relativo_3m", True),
            ("burn_rate_3m_avg", "burn_rate_3m", False),
            ("pct_clientes_morosos_3m", "clientes_morosos_3m", False),
            ("stock_prov_sobre_ingresos", "stock_prov_sobre_ingresos", False),
            ("colchon_flujo_meses", "colchon_flujo_meses", True),
            ("runway_meses", "runway_meses", True),
            ("flujo_volatilidad_6m", "flujo_volatilidad_6m", False),
            ("stock_clientes_sobre_ingresos", "stock_clientes_sobre_ingresos", False),
            ("recuperacion_stock_prov", "recuperacion_stock_prov", True),
            ("flujo_pendiente_robusta_6m", "flujo_pendiente_robusta_6m", True)):
        panel[f"pctl_{alias}"] = pctl_mes(panel, col, mas_es_mejor=mejor,
                                         referencia=referencia.get(col))
        nueva_ref[col] = rejilla_cuantiles(panel, col)

    if cfg.USAR_REFERENCIA_PCTL and not cfg.PCTL_REF_PATH.exists():
        cfg.PCTL_REF_PATH.write_text(json.dumps(nueva_ref), encoding="utf-8")
        print(f"    referencia de percentiles congelada en {cfg.PCTL_REF_PATH.name}")

    # ---- Confianza ---------------------------------------------------------
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
    fuente_debil = (
        panel["pct_clientes_morosos_3m_fuente"].eq("6m")
        | panel["pct_impagos_prov_3m_fuente"].eq("6m")
    )
    panel.loc[fuente_debil & panel["confianza"].eq("alta"), "confianza"] = "media"

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

    # Andamiaje: se calcula, se usa, y no se escribe. Producto y el motor
    # leen las derivadas (share_*, persistente_*, *_3m, confianza).
    drop = [
        "n_tx", "n_fact_ventas", "n_fact_compras",
        "n_fact_vencidas_ventas", "n_fact_vencidas_compras",
        "stock_clientes_antiguo", "stock_prov_antiguo",
        "tx_disponible", "ventas_disponible", "compras_disponible", "mes_activo",
        "pct_clientes_morosos_3m_fuente", "pct_impagos_prov_3m_fuente",
        "impagos_prov_3m_vs_prev3m",
        "ingresos_3m_avg", "ingresos_12m_avg", "gastos_3m_avg",
        "flag_tijera", "flag_flujo_negativo", "flag_estres_prov",
        "flag_estres_clientes", "flag_stock_prov_antiguo",
        "flag_flujo_negativo_3m", "flag_estres_prov_3m",
        "flag_estres_clientes_3m", "flag_stock_prov_antiguo_3m", "flag_tijera_3m",
        "n_deudas", "deuda_signo_negativo_flag", "deuda_conversion_incompleta",
        "deuda_multimoneda", "deuda_no_eur",
        "stock_prov_sobre_ingresos_topado", "stock_clientes_sobre_ingresos_topado",
        "stock_prov_sobre_ingresos_3m_vs_prev3m",
        "stock_clientes_sobre_ingresos_3m_vs_prev3m",
        "morosidad_censurada", "snapshot_financiero_disponible",
        "top1_clientes_share", "top1_prov_share",
        "clientes_morosos_3m_avg", "impagos_prov_3m_avg",
        "edad_media_stock_clientes_dias",
        "cobros", "devoluciones", "deuda_pagada",
        "z_caja_ingresos", "z_stock_prov_sobre_ingresos",
        "flujo_pendiente_6m", "gastos_momentum_3m",
        "recuperacion_stock_clientes",
    ]
    panel = panel.drop(columns=[c for c in drop if c in panel.columns])
    return panel


# =============================================================================
# 6. RESUMEN
# =============================================================================

def resumen(panel):
    activas = panel.groupby("company_id")["meses_activos_acum"].max().sort_values(ascending=False)
    emp = activas.index[0]
    cols = ["year_month", "flujo_relativo_3m", "runway_meses", "burn_rate",
            "pct_clientes_morosos_3m", "pct_impagos_prov_3m",
            "stock_prov_sobre_ingresos", "refund_rate_3m", "debt_service_3m",
            "confianza"]
    print(f"\n--- TRAYECTORIA: {emp} ---")
    print(panel[panel["company_id"] == emp][cols].to_string(index=False))

    print("\n--- COBERTURA ---")
    print(f"  Meses activos por empresa (media): {activas.mean():.1f} de {len(cfg.MONTHS)}")
    print(f"  Morosidad cliente no fiable: {panel['pct_clientes_morosos_3m'].isna().mean()*100:.1f}% de filas")
    print(f"  Morosidad proveedor no fiable: {panel['pct_impagos_prov_3m'].isna().mean()*100:.1f}% de filas")
    print(f"  Confianza: { {k: int(v) for k, v in panel['confianza'].value_counts().items()} }")
    print(f"  Filas con snapshot de caja: {int(panel['caja_reportada'].sum()):,}")
    print(f"  Filas con refund_rate_3m: {int(panel['refund_rate_3m'].notna().sum()):,}")
    print(f"  Filas con debt_service_3m: {int(panel['debt_service_3m'].notna().sum()):,}")


if __name__ == "__main__":
    build_panel()