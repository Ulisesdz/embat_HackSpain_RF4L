"""Limpia los CSV crudos de data/ y deja parquet tipado en data/clean/.

Uso: python3 src/clean.py [dir_datos]      (por defecto ./data)
Cada decisión que descarta o modifica filas se cuenta en data/clean/cleaning_log.json.
"""
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

RAW = Path(sys.argv[1] if len(sys.argv) > 1 else "data")
OUT = RAW / "clean"
OUT.mkdir(exist_ok=True)
START, END = pd.Timestamp("2024-09-01"), pd.Timestamp("2026-09-01")  # 2026-09 solo trae 1 día
LOG = {}

COUNTRY = {"ESPAÑA": "ES", "ESPANYA": "ES", "SPAIN": "ES", "PORTUGAL": "PT", "ITALIA": "IT", "ALEMANIA": "DE"}


def read(name, **kw):
    return pd.read_csv(RAW / f"{name}.csv", **kw)


# ---------- companies / groups ----------
comp = read("companies", parse_dates=["created_at"])
comp["country"] = comp.country.str.strip().str.upper().replace(COUNTRY)
comp["is_eur"] = comp.currency.eq("EUR")
groups = read("groups")
groups["erp"] = groups.erp.str.strip()

# ---------- productos ----------
bank = read("banking_products", parse_dates=["created_at"])
debt = read("debt_products", parse_dates=["created_at"])
# convención del origen: deuda = negativo. Trabajamos en magnitud y dejamos el flag por si importa.
debt["outstanding_positive_sign"] = debt.outstanding.gt(0)
for c in ["granted", "outstanding"]:
    debt[c] = debt[c].abs()
debt["liquidity"] = debt.liquidity.abs()
LOG["debt_outstanding_positive_sign"] = int(debt.outstanding_positive_sign.sum())
sched = read("debt_schedule_config", parse_dates=["next_payment_date", "last_payment_date"])
ptype = pd.concat([bank, debt]).set_index("product_id").type

# ---------- balances ----------
bal = read("balances", parse_dates=["date"]).drop(columns=["available"])  # 100% nulo
bal["ptype"] = bal.product_id.map(ptype)
bal["balance_extreme"] = bal.balance.abs() >= 1e9  # ej. 9.99e10: basura del origen, se marca (no se borra)
LOG["balances_extreme"] = int(bal.balance_extreme.sum())

# ---------- transactions ----------
t = read("transactions", usecols=["transaction_id", "company_id", "product_id", "date", "amount", "status",
                                  "category", "description", "counterparty_id"])
LOG["tx_raw"] = len(t)
t["date"] = pd.to_datetime(t.date, errors="coerce")
bad = ~t.date.between(START, END + pd.Timedelta(days=1))
LOG["tx_bad_date"] = int(bad.sum())
t = t[~bad].copy()
# 'cash_settlements' es typo de 'cash_settlement'; '-' y NaN = sin categoría
t["category"] = t.category.replace({"cash_settlements": "cash_settlement", "-": "uncategorized"}).fillna("uncategorized")
t["ptype"] = t.product_id.map(ptype).fillna("unknown")
# transferencias entre cuentas propias, inversión y deuda NO son actividad operativa
t["flow"] = np.select(
    [t.category.eq("transfer"), t.category.isin(["investment_deployment", "investment_return"]),
     t.category.isin(["debt_repayment", "interest_charge"])],
    ["internal", "investment", "financing"], "operating")
# movimientos de líneas de crédito/préstamos son de la cuenta de deuda, no de tesorería: no sumar dos veces
t["is_cash_account"] = ~t.ptype.isin(["lineofcredit", "loan", "confirming", "factoring", "lineofcomex", "risk"])
t["month"] = t.date.dt.to_period("M").astype(str)
# NO se deduplica: 107k filas idénticas pero con transaction_id distinto, concentradas en importes pequeños
# (TPV, comisiones): son repeticiones legítimas, no doble carga.
LOG["tx_kept"] = len(t)
LOG["tx_exact_dupes_kept"] = int(t.drop(columns="transaction_id").duplicated().sum())
LOG["tx_non_cash_account"] = int((~t.is_cash_account).sum())
for c in ["category", "ptype", "flow", "status"]:
    t[c] = t[c].astype("category")
t.to_parquet(OUT / "transactions.parquet", index=False)
first_last = t[t.is_cash_account].groupby("company_id").date.agg(first_tx="min", last_tx="max", n_tx="size")
del t

# ---------- invoices ----------
inv = read("invoices", usecols=lambda c: c != "concept")
LOG["inv_raw"] = len(inv)
for c in ["issuance_date", "due_date", "payment_date"]:
    inv[c] = pd.to_datetime(inv[c], errors="coerce")
# solo documentos que son derecho de cobro/pago real; sin canceladas ni importes 0
inv = inv[inv.document_type.isin(["invoice", "invoiceGroup"]) & inv.status.ne("cancel") & inv.amount.ne(0)].copy()
LOG["inv_kept_doc_types"] = len(inv)
# la dirección no viene en ningún campo: el signo la da (97,6% de acuerdo con el signo del cobro/pago en banco)
inv["direction"] = np.where(inv.amount > 0, "AR", "AP")  # AR = emitida (cobrar), AP = recibida (pagar)
inv["amount"] = inv.amount.abs()
inv["pending_amount"] = inv.pending_amount.abs()
# vencimientos imposibles (año 2000/2050, anteriores a la emisión, >2 años): se sustituye por emisión+30d
term = (inv.due_date - inv.issuance_date).dt.days
bad_due = inv.due_date.isna() | term.lt(0) | term.gt(730)
LOG["inv_bad_due_date_fixed"] = int(bad_due.sum())
inv.loc[bad_due, "due_date"] = inv.issuance_date + pd.Timedelta(days=30)
# payment_date solo es real si status == paid; en overdue/pending viene rellenada con el vencimiento
inv["is_paid"] = inv.status.eq("paid")
inv.loc[~inv.is_paid, "payment_date"] = pd.NaT
fut = inv.is_paid & (inv.payment_date > END)
LOG["inv_paid_future_date_clipped"] = int(fut.sum())
inv.loc[fut, "payment_date"] = END
early = inv.is_paid & (inv.payment_date < inv.issuance_date)
LOG["inv_paid_before_issuance_clipped"] = int(early.sum())
inv.loc[early, "payment_date"] = inv.issuance_date
inv.loc[inv.is_paid & inv.payment_date.isna(), "is_paid"] = False
inv["days_late"] = (inv.payment_date - inv.due_date).dt.days  # solo facturas pagadas
inv["is_eur"] = inv.currency.eq("EUR")
LOG["inv_kept"] = len(inv)
for c in ["document_type", "status", "currency", "accounting_currency", "direction"]:
    inv[c] = inv[c].astype("category")
inv.drop(columns=["exchange_rate", "accounting_currency"]).to_parquet(OUT / "invoices.parquet", index=False)

# ---------- cobertura por empresa ----------
cov = comp.set_index("company_id").join(first_last)
inv_cov = inv.groupby("company_id").issuance_date.agg(first_inv="min", last_inv="max", n_inv="size")
cov = cov.join(inv_cov).join(groups.set_index("group_id").erp.rename("group_erp"), on="group_id")
cov["n_tx"] = cov.n_tx.fillna(0).astype(int)
cov["n_inv"] = cov.n_inv.fillna(0).astype(int)
cov["has_invoices"] = cov.n_inv > 0
cov["n_products_bank"] = bank.groupby("company_id").size().reindex(cov.index).fillna(0).astype(int)
cov["n_products_debt"] = debt.groupby("company_id").size().reindex(cov.index).fillna(0).astype(int)
LOG["companies"] = len(cov)
LOG["companies_with_invoices"] = int(cov.has_invoices.sum())
LOG["companies_without_tx"] = int((cov.n_tx == 0).sum())

cov.reset_index().to_parquet(OUT / "companies.parquet", index=False)
groups.to_parquet(OUT / "groups.parquet", index=False)
bank.to_parquet(OUT / "banking_products.parquet", index=False)
debt.to_parquet(OUT / "debt_products.parquet", index=False)
sched.to_parquet(OUT / "debt_schedule_config.parquet", index=False)
bal.to_parquet(OUT / "balances.parquet", index=False)

(OUT / "cleaning_log.json").write_text(json.dumps(LOG, indent=2))
print(json.dumps(LOG, indent=2))
