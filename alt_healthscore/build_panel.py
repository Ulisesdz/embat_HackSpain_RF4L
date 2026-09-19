"""Construye el panel de métricas empresa x mes para el health score alternativo.

Salida: data/panel_metricas.csv  (una fila por empresa y mes, una columna por métrica)

Principio rector: los agregados operativos se definen POR SIGNO, y la categoría
solo se usa para excluir lo no operativo y para alimentar métricas concretas.
"""

from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
SALIDA = DATA / "panel_metricas.csv"

MESES = pd.period_range("2024-09", "2026-08", freq="M")
DIAS = pd.date_range("2024-09-01", "2026-08-31", freq="D")
REF = pd.Timestamp("2026-09-02")

TIPOS_CAJA = {"checking", "saving", "wallet"}
FUERA_DE_INGRESOS = {"investment_return", "payment_refund", "tax_refund"}
FUERA_DE_GASTOS = {"investment_deployment", "debt_repayment", "collection_refund"}
GASTO_INELUDIBLE = {"salary", "tax", "social_security"}
COSTE_FINANCIERO = {"fee", "interest_charge"}


def sin_categoria(s):
    return s.isna() | (s == "-")


def pendiente_ols(y):
    y = np.asarray(y, dtype=float)
    if np.isnan(y).any():
        return np.nan
    x = np.arange(len(y), dtype=float)
    return np.polyfit(x, y, 1)[0]


def ratio(num, den, min_den=0.0):
    den = den.where(den > min_den)
    return num / den


print("cargando...")
companies = pd.read_csv(DATA / "companies.csv")
bank = pd.read_csv(DATA / "banking_products.csv")
balances = pd.read_csv(DATA / "balances.csv")
tx = pd.read_csv(DATA / "transactions.csv")
inv = pd.read_csv(DATA / "invoices.csv")

tx["date"] = pd.to_datetime(tx["date"], errors="coerce")
tx["category"] = tx["category"].where(~sin_categoria(tx["category"]), np.nan)
tx["dia"] = tx["date"].dt.normalize()
tx["ym"] = tx["date"].dt.to_period("M")
tx = tx[tx["date"].notna() & tx["amount"].notna()].copy()
tx["category"] = tx["category"].replace({"cash_settlements": "cash_settlement"})
balances["date"] = pd.to_datetime(balances["date"], errors="coerce")

EMPRESAS = companies["company_id"].drop_duplicates().sort_values()
print(f"  {len(EMPRESAS)} empresas | {len(tx):,} transacciones | {len(inv):,} facturas")

print("detectando transferencias internas...")
tx["_abs"] = tx["amount"].abs().round(2)
tx["_pos"] = tx["amount"] > 0
clave = ["company_id", "dia", "_abs"]
conteo = tx.groupby(clave, sort=False)["_pos"].agg(["sum", "size"])
conteo["n_pos"] = conteo["sum"].astype(int)
conteo["n_neg"] = (conteo["size"] - conteo["sum"]).astype(int)
conteo["n_par"] = conteo[["n_pos", "n_neg"]].min(axis=1)
pares = conteo.loc[conteo["n_par"] > 0, "n_par"]
tx["_orden"] = tx.groupby(clave + ["_pos"], sort=False).cumcount()
tx = tx.join(pares.rename("_n_par"), on=clave)
tx["interno"] = tx["_n_par"].notna() & (tx["_orden"] < tx["_n_par"].fillna(0))
print(f"  {tx['interno'].sum():,} movimientos internos ({tx['interno'].mean():.1%})")

print("agregando por empresa y mes...")
op = tx[~tx["interno"]].copy()
cat = op["category"]
entrada = op["amount"] > 0
op["ingresos"] = np.where(entrada & ~cat.isin(FUERA_DE_INGRESOS), op["amount"], 0.0)
op["gastos"] = np.where(~entrada & ~cat.isin(FUERA_DE_GASTOS), -op["amount"], 0.0)
op["ingresos_cat"] = np.where(op["ingresos"] > 0, op["ingresos"], 0.0) * cat.notna()
op["devoluciones"] = np.where(cat == "collection_refund", op["amount"].abs(), 0.0)
op["ineludible"] = np.where(cat.isin(GASTO_INELUDIBLE), op["amount"].abs(), 0.0)
op["servicio_deuda"] = np.where(cat == "debt_repayment", op["amount"].abs(), 0.0)
op["coste_fin"] = np.where(cat.isin(COSTE_FINANCIERO), op["amount"].abs(), 0.0)

COLS_SUMA = ["ingresos", "gastos", "ingresos_cat", "devoluciones",
             "ineludible", "servicio_deuda", "coste_fin"]
mensual = op.groupby(["company_id", "ym"])[COLS_SUMA].sum()
mensual["n_tx"] = op.groupby(["company_id", "ym"]).size()
mensual["sin_cat"] = op.assign(s=op["category"].isna()).groupby(["company_id", "ym"])["s"].mean()

print("reconstruyendo la curva de caja...")
prod_caja = bank.loc[bank["type"].isin(TIPOS_CAJA), ["product_id", "company_id"]]
snap = balances.merge(prod_caja[["product_id"]], on="product_id", how="inner")
tx_caja = tx[tx["product_id"].isin(set(prod_caja["product_id"]))].copy()
con_foto = set(snap["product_id"])
sin_foto = tx_caja.loc[~tx_caja["product_id"].isin(con_foto), "company_id"].unique()
tx_caja = tx_caja[tx_caja["product_id"].isin(con_foto)]

post = (tx_caja.merge(snap[["product_id", "date"]].rename(columns={"date": "fecha_snap"}),
                      on="product_id", how="left")
        .query("date > fecha_snap and date < @REF")
        .groupby("product_id")["amount"].sum())
snap = snap.set_index("product_id")
snap["balance_ref"] = snap["balance"] + post.reindex(snap.index).fillna(0.0)
saldo_ref = snap.groupby("company_id")["balance_ref"].sum()

flujo_dia = (tx_caja.groupby(["company_id", "dia"])["amount"].sum()
             .unstack(fill_value=0.0).reindex(columns=DIAS, fill_value=0.0))
flujo_total = tx_caja.groupby("company_id")["amount"].sum()
saldo_inicial = saldo_ref.reindex(flujo_dia.index) - flujo_total.reindex(flujo_dia.index)
saldo_dia = flujo_dia.cumsum(axis=1).add(saldo_inicial, axis=0)
ym_dia = pd.Series(DIAS.to_period("M"), index=DIAS)
saldo_cierre = saldo_dia.T.groupby(ym_dia).last().T.stack()
dias_negativo = (saldo_dia < 0).T.groupby(ym_dia).mean().T.stack()
print(f"  {saldo_dia.shape[0]} empresas con curva | {len(sin_foto)} con producto sin foto")

print("infiriendo dirección de las facturas...")
roles = (tx.loc[tx["counterparty_id"].notna()]
         .groupby(["company_id", "counterparty_id"])["amount"].sum())
roles = pd.Series(np.where(roles > 0, "cliente", "proveedor"), index=roles.index, name="rol")

inv = inv[inv["document_type"].isin(["invoice", "invoiceGroup"])].copy()
for c in ["issuance_date", "due_date", "payment_date"]:
    inv[c] = pd.to_datetime(inv[c], errors="coerce")
    inv.loc[(inv[c] < "2020-01-01") | (inv[c] > "2030-01-01"), c] = pd.NaT

inv = inv.join(roles, on=["company_id", "counterparty_id"])
inv["importe"] = inv["amount"].abs()
rol_signo = pd.Series(np.where(inv["amount"] > 0, "cliente", "proveedor"), index=inv.index)
ambas = inv["rol"].notna()
print(f"  acuerdo contraparte vs signo: "
      f"{(inv.loc[ambas, 'rol'] == rol_signo[ambas]).mean():.1%}")
inv["rol"] = inv["rol"].fillna(rol_signo)
inv["cobro_real"] = inv["payment_date"].where(inv["status"] == "paid")
print(f"  dirección resuelta en {inv['rol'].notna().mean():.1%} | "
      f"{inv.loc[inv['rol'].notna(), 'company_id'].nunique()} empresas")

pagadas = inv[(inv["rol"] == "cliente") & inv["cobro_real"].notna()
              & inv["issuance_date"].notna()].copy()
pagadas["dias"] = (pagadas["cobro_real"] - pagadas["issuance_date"]).dt.days
pagadas = pagadas[pagadas["dias"].between(0, 365)]
pagadas["ym"] = pagadas["cobro_real"].dt.to_period("M")
pagadas["_w"] = pagadas["dias"] * pagadas["importe"]
agg = pagadas.groupby(["company_id", "ym"])[["_w", "importe"]].sum()
dso = (agg["_w"] / agg["importe"]).rename("dso_dias")

print("calculando el stock vencido mes a mes...")
stock = {}
vivas = inv[inv["due_date"].notna() & inv["rol"].notna()]
for m in MESES:
    fin = m.end_time
    impagada = (vivas["due_date"] <= fin) & (vivas["cobro_real"].isna() | (vivas["cobro_real"] > fin))
    stock[m] = vivas[impagada].groupby(["company_id", "rol"])["importe"].sum()
stock = pd.concat(stock, names=["ym"]).unstack("rol").reorder_levels([1, 0]).sort_index()

print("montando el panel...")
idx = pd.MultiIndex.from_product([EMPRESAS, MESES], names=["company_id", "year_month"])
p = pd.DataFrame(index=idx)
for col in COLS_SUMA:
    p[col] = mensual[col].reindex(idx).fillna(0.0)
p["n_tx"] = mensual["n_tx"].reindex(idx).fillna(0).astype(int)
p["pct_sin_categoria"] = mensual["sin_cat"].reindex(idx)
p["saldo_cierre"] = saldo_cierre.reindex(idx)
p["stock_clientes"] = stock.get("cliente", pd.Series(dtype=float)).reindex(idx).fillna(0.0)
p["stock_proveedores"] = stock.get("proveedor", pd.Series(dtype=float)).reindex(idx).fillna(0.0)

g = p.groupby(level="company_id")
r3 = lambda c: g[c].transform(lambda s: s.rolling(3, min_periods=3).sum())
ing3, gas3 = r3("ingresos"), r3("gastos")

p["m01_runway_meses"] = ratio(p["saldo_cierre"], gas3 / 3)
p["m02_flujo_relativo_3m"] = ratio(ing3 - gas3, ing3)
p["m03_pct_dias_negativo"] = dias_negativo.reindex(idx)
p["m04_ratio_devoluciones"] = ratio(r3("devoluciones"), r3("ingresos_cat"))
p["m05_dso_dias"] = dso.reindex(idx)
p["m06_stock_clientes_rel"] = ratio(p["stock_clientes"], ing3 / 3)
p["m07_cobertura_ineludible"] = ratio(ing3, r3("ineludible"))
p["m08_stock_proveedores_rel"] = ratio(p["stock_proveedores"], ing3 / 3)
p["m09_servicio_deuda"] = ratio(r3("servicio_deuda"), r3("ingresos_cat"))
p["m10_coste_financiero"] = ratio(r3("coste_fin"), r3("ingresos_cat"))
p["_flujo_rel_mes"] = ratio(p["ingresos"] - p["gastos"], p["ingresos"])
p["m11_volatilidad_6m"] = (p.groupby(level="company_id")["_flujo_rel_mes"]
                           .transform(lambda s: s.rolling(6, min_periods=6).std()))
p["_log_ing"] = np.log1p(p["ingresos"].clip(lower=0))
p["m12_tendencia_cobros_6m"] = (p.groupby(level="company_id")["_log_ing"]
                                .transform(lambda s: s.rolling(6, min_periods=6)
                                           .apply(pendiente_ols, raw=True)))

activo = (p["n_tx"] > 0).astype(int)
p["meses_historia"] = activo.groupby(level="company_id").cumsum()
p["tiene_facturas"] = p.index.get_level_values("company_id").isin(
    inv.loc[inv["rol"].notna(), "company_id"].unique()).astype(int)
p["divisa_mixta"] = p.index.get_level_values("company_id").isin(
    tx.loc[tx["exchange_rate"] != 1, "company_id"].unique()).astype(int)
p["caja_incompleta"] = p.index.get_level_values("company_id").isin(sin_foto).astype(int)
p = p.join(companies.set_index("company_id")["group_id"], on="company_id")

METRICAS = [
    "m01_runway_meses", "m02_flujo_relativo_3m", "m03_pct_dias_negativo",
    "m04_ratio_devoluciones", "m05_dso_dias", "m06_stock_clientes_rel",
    "m07_cobertura_ineludible", "m08_stock_proveedores_rel",
    "m09_servicio_deuda", "m10_coste_financiero",
    "m11_volatilidad_6m", "m12_tendencia_cobros_6m",
]
CONTEXTO = ["ingresos", "gastos", "saldo_cierre", "n_tx", "meses_historia",
            "pct_sin_categoria", "tiene_facturas", "divisa_mixta", "caja_incompleta"]
p = p[["group_id"] + METRICAS + CONTEXTO].reset_index()
p["year_month"] = p["year_month"].astype(str)
p.to_csv(SALIDA, index=False)
print(f"\nescrito {SALIDA}  ->  {len(p):,} filas x {p.shape[1]} columnas")
