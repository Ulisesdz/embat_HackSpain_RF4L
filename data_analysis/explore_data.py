"""Auditoría de los CSV RAW. No modifica ningún dato.

Cuantifica todo lo que el pipeline va a descartar y deja constancia de los
sesgos que los datos no permiten corregir. Genera data_quality_report.txt.
"""

import pandas as pd
import numpy as np

import data_analysis.config as cfg

LINEAS = []


def log(txt=""):
    LINEAS.append(str(txt))
    print(txt)


def leer(nombre):
    path = cfg.DATA_DIR / nombre
    if not path.exists():
        log(f"[WARN] Falta {path}")
        return None
    return pd.read_csv(path)


# =============================================================================
# FECHAS
# =============================================================================

def auditar_fechas(df, col, nombre):
    n0 = len(df)
    fechas = pd.to_datetime(df[col], errors="coerce")
    n_nat = int(fechas.isna().sum())
    validas = fechas.dropna()
    n_antes = int((validas < cfg.START_DATE).sum())
    n_despues = int((validas > cfg.END_DATE).sum())
    n_dentro = len(validas) - n_antes - n_despues

    log(f"--- {nombre} · columna '{col}' ---")
    log(f"  Filas originales:           {n0:>9,}")
    log(f"  No parseables (NaT):        {n_nat:>9,}  ({n_nat/max(n0,1)*100:5.2f}%)")
    if n_nat:
        ejemplos = df.loc[fechas.isna(), col].astype(str).value_counts().head(5)
        log(f"    Ejemplos: {list(ejemplos.index)}")
    log(f"  Anteriores a la ventana:    {n_antes:>9,}  ({n_antes/max(n0,1)*100:5.2f}%)")
    log(f"  Posteriores a la ventana:   {n_despues:>9,}  ({n_despues/max(n0,1)*100:5.2f}%)")
    log(f"  RETENIDAS:                  {n_dentro:>9,}  ({n_dentro/max(n0,1)*100:5.2f}%)")
    if len(validas):
        log(f"  Rango válido observado:     {validas.min().date()} → {validas.max().date()}")
    log()
    return fechas


# =============================================================================
# TRANSACCIONES
# =============================================================================

def auditar_transacciones(tx):
    log("=" * 74)
    log("TRANSACTIONS")
    log("=" * 74)
    log(f"Columnas: {list(tx.columns)}")
    fechas = auditar_fechas(tx, "date", "TRANSACTIONS")

    a = pd.to_numeric(tx["amount"], errors="coerce")
    log(f"  amount no numérico: {int(a.isna().sum()):,} | "
        f"positivos: {int((a > 0).sum()):,} | negativos: {int((a < 0).sum()):,} | "
        f"ceros: {int((a == 0).sum()):,}")

    dentro = tx[fechas.between(cfg.START_DATE, cfg.END_DATE)].copy()
    dentro["ym"] = fechas[dentro.index].dt.to_period("M")
    meses = dentro.groupby("company_id")["ym"].nunique()
    perdidas = 1 - dentro.groupby("company_id").size() / tx.groupby("company_id").size()

    log(f"  Empresas con transacciones:              {tx['company_id'].nunique():>6,}")
    log(f"  Empresas que pierden >20% de registros:  {int((perdidas > 0.20).sum()):>6,}")
    log(f"  Empresas que pierden >50% de registros:  {int((perdidas > 0.50).sum()):>6,}")
    log(f"  Mediana de meses con actividad:          {meses.median():>6.0f} de {len(cfg.MONTHS)}")
    log(f"  Empresas con <{cfg.MIN_MESES_HISTORIA} meses de historia:     "
        f"{int((meses < cfg.MIN_MESES_HISTORIA).sum()):>6,}")
    log()


# =============================================================================
# FACTURAS
# =============================================================================

def auditar_facturas(inv):
    log("=" * 74)
    log("INVOICES")
    log("=" * 74)
    log(f"Columnas: {list(inv.columns)}")
    auditar_fechas(inv, "due_date", "INVOICES (vencimiento)")

    col_dir = cfg.detectar(inv, "direction")
    col_pago = cfg.detectar(inv, "payment_date")
    col_emision = cfg.detectar(inv, "invoice_date")
    col_cp = cfg.detectar(inv, "counterparty")

    log("--- DECISIONES QUE DEPENDEN DEL ESQUEMA ---")
    if col_dir:
        vals = inv[col_dir].astype(str).str.strip().str.lower()
        reconocidos = set(vals.unique()) & (cfg.VALORES_RECEIVABLE | cfg.VALORES_PAYABLE)
        log(f"  Dirección: columna '{col_dir}' con valores {dict(vals.value_counts().head(8))}")
        log(f"    Valores reconocidos por el mapeo: {sorted(reconocidos) or 'NINGUNO → fallback por signo'}")
    else:
        log("  Dirección: NO HAY COLUMNA → fallback por signo del importe.")
        log("    Riesgo: si el signo es la convención real (+venta/-compra), el fallback")
        log("    puede ser CORRECTO. Verificar con el desglose de document_type/concept.")

    col_doc = cfg.detectar(inv, "document_kind")
    log("--- DOCUMENT_TYPE / CONCEPT (para separar rectificativas de dirección) ---")
    if col_doc:
        vals_doc = inv[col_doc].astype(str).str.strip().str.lower()
        log(f"  Columna '{col_doc}': {dict(vals_doc.value_counts().head(10))}")
        reconocidos_doc = set(vals_doc.unique()) & cfg.VALORES_RECTIFICATIVA
        log(f"    Valores reconocidos como rectificativa: {sorted(reconocidos_doc) or 'NINGUNO'}")
    else:
        log("  Sin columna de tipo de documento.")
    if "concept" in inv.columns:
        log(f"  'concept' (top 10, orientativo): "
            f"{dict(inv['concept'].astype(str).str.lower().value_counts().head(10))}")
    a_neg = pd.to_numeric(inv["amount"], errors="coerce") < 0
    log(f"  amount < 0: {int(a_neg.sum()):,} ({a_neg.mean()*100:.1f}%)  ← si document_type no")
    log(f"    confirma que esto son rectificativas, NO se debe llamar así en el pipeline;")
    log(f"    lo más probable es que sea la convención de signo de la dirección.")
    log()

    if col_pago:
        log(f"  Fecha de pago: '{col_pago}' → estado overdue reconstruible as-of por mes.")
    else:
        log("  Fecha de pago: NO EXISTE → 'status' es el estado en la extracción.")
        log("    LOOK-AHEAD irreducible: la morosidad del pasado queda subestimada.")

    log(f"  Fecha de emisión: {col_emision or 'no disponible'}")
    log(f"  Contraparte: {col_cp or 'no disponible → sin concentración de clientes'}")
    log()

    a = pd.to_numeric(inv["amount"], errors="coerce")
    log(f"  Rectificativas (amount < 0): {int((a < 0).sum()):,} "
        f"({(a < 0).mean()*100:.2f}%)")
    log(f"  Estados: {dict(inv['status'].astype(str).str.lower().value_counts())}")
    if "pending_amount" in inv.columns:
        p = pd.to_numeric(inv["pending_amount"], errors="coerce")
        log(f"  pending_amount nulo: {int(p.isna().sum()):,}")
        log(f"  Filas con |pending| > |amount|: {int((p.abs() > a.abs() + 1e-6).sum()):,}")
    log()

    auditar_multidivisa(inv, "INVOICES")


# =============================================================================
# MULTIDIVISA
# =============================================================================

def auditar_multidivisa(df, nombre):
    if "currency" not in df.columns:
        return
    log(f"--- MULTIDIVISA ({nombre}) ---")
    log(f"  currency: {dict(df['currency'].value_counts())}")
    if "accounting_currency" in df.columns:
        log(f"  accounting_currency: {dict(df['accounting_currency'].value_counts())}")
        distinto = (df["currency"].astype(str) != df["accounting_currency"].astype(str))
        log(f"  Filas con currency != accounting_currency: {int(distinto.sum()):,} "
            f"({distinto.mean()*100:.2f}%)")
        if distinto.any() and "exchange_rate" in df.columns:
            er = pd.to_numeric(df.loc[distinto, "exchange_rate"], errors="coerce")
            log(f"    exchange_rate en esas filas: nulo={int(er.isna().sum())}, "
                f"rango=[{er.min():.4f}, {er.max():.4f}]")
            log("    Si accounting_currency es homogénea, se puede normalizar con")
            log("    amount * exchange_rate antes de sumar entre empresas.")
        elif distinto.any():
            log("    AVISO: hay divisas mixtas y no hay exchange_rate para convertir.")
    log()


# =============================================================================
# BALANCES Y DEUDA
# =============================================================================

def auditar_balances(bal, banking):
    log("=" * 74)
    log("BALANCES / BANKING PRODUCTS")
    log("=" * 74)
    if bal is None:
        return
    log(f"Columnas: {list(bal.columns)} | filas: {len(bal):,}")

    por_producto = bal.groupby("product_id").size()
    col_fecha = cfg.detectar(bal, "balance_date")
    log(f"  Filas por product_id: mediana={por_producto.median():.0f} "
        f"máx={por_producto.max():.0f}")
    if por_producto.max() > 1:
        log("  SERIE TEMPORAL: sumar sin filtrar multiplica la caja por el nº de snapshots.")
        log(f"    Columna de fecha: {col_fecha or 'NINGUNA → no se puede desambiguar'}")
    else:
        log("  Snapshot único por producto: la suma directa es válida.")

    for extra_col in ("available", "countable", "liquidity"):
        if extra_col in bal.columns:
            s = bal[extra_col]
            if s.dtype == bool or set(s.dropna().unique()) <= {0, 1, True, False}:
                log(f"  '{extra_col}': {dict(s.value_counts(dropna=False))}")
            else:
                diff = pd.to_numeric(s, errors="coerce") - pd.to_numeric(bal["balance"], errors="coerce")
                log(f"  '{extra_col}' vs 'balance': diferencia media {diff.mean():,.2f}, "
                    f"máx abs {diff.abs().max():,.2f}")
                log("    Si difieren, 'available' puede ser el saldo realmente disponible")
                log("    (descontando retenciones), más fiel para runway que 'balance'.")

    if banking is not None and "type" in banking.columns:
        tipos = banking["type"].value_counts()
        log(f"  Tipos en banking_products: {dict(tipos)}")
        caja = [t for t in tipos.index
                if any(k in str(t).lower() for k in cfg.TIPOS_CAJA)]
        log(f"    Considerados caja disponible: {caja or 'NINGUNO → revisar mapeo'}")
    log()


def auditar_deuda(debt):
    if debt is None:
        return
    log("=" * 74)
    log("DEBT PRODUCTS")
    log("=" * 74)
    log(f"Columnas: {list(debt.columns)}")
    d = pd.to_numeric(debt["outstanding"], errors="coerce")
    log(f"  outstanding positivos: {int((d > 0).sum()):,} | negativos: {int((d < 0).sum()):,}")
    log(f"  media RAW: {d.mean():,.2f} | media ABS: {d.abs().mean():,.2f}")
    log("  El signo RAW no se interpreta como riesgo: el pipeline usa la magnitud.")
    if "granted" in debt.columns:
        g = pd.to_numeric(debt["granted"], errors="coerce").fillna(0)
        log(f"  Productos con granted = 0 (global): {int((g == 0).sum()):,} de {len(debt):,} "
            f"({(g == 0).mean()*100:.1f}%)")
        col_tipo = cfg.detectar(debt, "debt_type")
        if col_tipo:
            log(f"  Desglose de granted=0 por '{col_tipo}' "
                f"(la cifra global puede esconder que un solo tipo concentre los ceros):")
            tabla = (pd.DataFrame({"tipo": debt[col_tipo], "granted_cero": (g == 0)})
                    .groupby("tipo")["granted_cero"].agg(["sum", "count"]))
            for tipo, fila in tabla.iterrows():
                log(f"    {tipo}: {int(fila['sum'])}/{int(fila['count'])} "
                    f"({fila['sum']/fila['count']*100:.1f}%) con granted=0")
    auditar_multidivisa(debt, "DEBT_PRODUCTS")
    log()


# =============================================================================
# MAIN
# =============================================================================

def main():
    cfg.asegurar_dirs()
    log("=" * 74)
    log("INFORME DE CALIDAD DE DATOS · EMBAT X-RAY")
    log(f"Ventana declarada: {cfg.START_DATE.date()} → {cfg.END_DATE.date()}")
    log(f"Buckets mensuales inclusivos: {len(cfg.MONTHS)}")
    log(f"Mes parcial (extracción {cfg.EXTRACTION_DATE.date()}): "
        f"{[str(m) for m in cfg.PARTIAL_MONTHS]}")
    log("=" * 74)
    log()

    tx = leer("transactions.csv")
    inv = leer("invoices.csv")
    if tx is not None:
        auditar_transacciones(tx)
    if inv is not None:
        auditar_facturas(inv)
    auditar_balances(leer("balances.csv"), leer("banking_products.csv"))
    auditar_deuda(leer("debt_products.csv"))

    log("=" * 74)
    log("SESGOS CONOCIDOS")
    log("=" * 74)
    log("  1. LOOK-AHEAD: si 'status' es el único indicador de impago, refleja el")
    log("     estado en la extracción y no el de cada mes. Las facturas pagadas con")
    log("     retraso figuran hoy como sanas, así que el histórico parece mejor de lo")
    log("     que fue y toda empresa aparenta un deterioro que es artefacto.")
    log(f"  2. CENSURA A LA DERECHA: las facturas vencidas en los últimos "
        f"{cfg.DIAS_MADURACION} días")
    log("     aún no han madurado. Esos meses se marcan con confianza reducida.")
    log("  3. MES PARCIAL: el último bucket tiene flujos truncados y queda excluido")
    log("     del score agregado.")
    log()

    cfg.QUALITY_PATH.write_text("\n".join(LINEAS), encoding="utf-8")
    print(f"\nInforme guardado en: {cfg.QUALITY_PATH}")


if __name__ == "__main__":
    main()