"""Panel mensual empresa x mes (2024-09..2026-08) con las señales en bruto. Lee data/clean/, escribe data/clean/panel.parquet.

Reglas de diseño:
- Todo son ratios por empresa (los importes vienen en moneda local y exchange_rate no es fiable).
- Un mes sin observar es NaN, no 0: la ventana observada de cada empresa es [primer mes completo, último mes con movimientos].
- Facturas "as-of": cada mes se reconstruye con las fechas reales de cobro/pago, no con el status de hoy.
"""
import sys
from pathlib import Path

import numpy as np
import pandas as pd

D = Path(sys.argv[1] if len(sys.argv) > 1 else "data") / "clean"
MONTHS = pd.period_range("2024-09", "2026-08", freq="M")
CASH_BAL_TYPES = ["checking", "saving", "wallet", "tpv", "expensesPlatform"]
COLLECT = ["collection", "bulk_collection", "pos_settlement", "cash_settlement"]
PAYROLL = ["salary", "social_security"]

co = pd.read_parquet(D / "companies.parquet").set_index("company_id")
idx = pd.MultiIndex.from_product([co.index, MONTHS.astype(str)], names=["company_id", "month"])


def msum(df, val, name):
    return df.groupby(["company_id", "month"], observed=True)[val].sum().rename(name)


# ---------- 1. transacciones ----------
t = pd.read_parquet(D / "transactions.parquet", columns=["company_id", "product_id", "date", "amount", "category",
                                                         "ptype", "flow", "is_cash_account", "month"])
t = t[t.is_cash_account & t.month.isin(MONTHS.astype(str))]
op = t[t.flow == "operating"]
parts = [
    msum(op[op.amount > 0], "amount", "inflow"),
    msum(op[op.amount < 0].assign(a=lambda d: -d.amount), "a", "outflow"),
    op.groupby(["company_id", "month"], observed=True).size().rename("n_tx"),
    msum(op[op.category.isin(COLLECT)], "amount", "collections"),
    msum(op[op.category == "collection_refund"].assign(a=lambda d: -d.amount), "a", "returned_receipts"),
    msum(op[op.category.isin(PAYROLL)].assign(a=lambda d: -d.amount), "a", "payroll"),
    msum(op[op.category == "tax"].assign(a=lambda d: -d.amount), "a", "tax"),
    msum(op[op.category == "fee"].assign(a=lambda d: -d.amount), "a", "bank_fees"),
    msum(t[(t.flow == "financing")].assign(a=lambda d: -d.amount), "a", "debt_service"),
    t.groupby(["company_id", "month"], observed=True).product_id.nunique().rename("n_accounts"),
]
p = pd.concat(parts, axis=1).reindex(idx)

# ventana observada: desde el primer mes completo hasta el último mes con movimientos
first = co.first_tx.dt.to_period("M")
first = first.where(co.first_tx.dt.day <= 3, first + 1)  # el mes de alta suele venir a medias
last = co.last_tx.dt.to_period("M")
mo = pd.PeriodIndex(p.index.get_level_values("month"), freq="M")
cid = p.index.get_level_values("company_id")
p["observed"] = (mo >= first.reindex(cid).values) & (mo <= last.reindex(cid).values)
flow_cols = ["inflow", "outflow", "n_tx", "collections", "returned_receipts", "payroll", "tax", "bank_fees", "debt_service"]
p[flow_cols] = p[flow_cols].fillna(0).where(p.observed)  # dentro de la ventana, sin movimientos = 0; fuera = NaN
p["n_accounts"] = p.n_accounts.fillna(0).where(p.observed)

# ---------- 2. caja reconstruida hacia atrás desde el saldo final ----------
bal = pd.read_parquet(D / "balances.parquet")
bal = bal[bal.ptype.isin(CASH_BAL_TYPES) & ~bal.balance_extreme].set_index("product_id").balance
tb = t[t.product_id.isin(bal.index)]
pm = tb.groupby(["product_id", "month"], observed=True).amount.sum().unstack(fill_value=0)
pm = pm.reindex(columns=MONTHS.astype(str), fill_value=0)
after = pm.iloc[:, ::-1].cumsum(axis=1).iloc[:, ::-1].shift(-1, axis=1).fillna(0)  # movimientos posteriores al cierre de cada mes
cash = (-after).add(bal, axis=0)
cash["company_id"] = tb.drop_duplicates("product_id").set_index("product_id").company_id.reindex(cash.index)
# productos con saldo pero sin movimientos: su saldo es constante
nomov = bal.index.difference(cash.index)
cash = cash.dropna(subset=["company_id"]).groupby("company_id").sum()
cash = cash.stack().rename("cash_end").rename_axis(["company_id", "month"])
p = p.join(cash)
p["cash_end"] = p.cash_end.where(p.observed)

# ---------- 3. facturas as-of fin de cada mes ----------
inv = pd.read_parquet(D / "invoices.parquet", columns=["company_id", "direction", "issuance_date", "due_date",
                                                       "payment_date", "amount", "is_paid", "days_late", "counterparty_id"])
# winsor por empresa: una factura de 6e10 no puede dominar el ratio
cap = inv.groupby(["company_id", "direction"], observed=True).amount.transform(lambda s: s.quantile(0.99))
inv["amount"] = inv.amount.clip(upper=cap)
pay = inv.payment_date.fillna(pd.Timestamp("2100-01-01"))  # no pagada hoy = no pagada nunca (en la ventana)
rows = []
for m in MONTHS:
    end = m.end_time.normalize()
    lo = end - pd.Timedelta(days=90)
    due_w = inv[(inv.due_date > lo) & (inv.due_date <= end)]  # facturas que vencieron en los últimos 90 días
    unpaid = due_w[pay.loc[due_w.index] > end]
    g = due_w.groupby(["company_id", "direction"], observed=True).amount.agg(due_amt="sum", due_n="size")
    g["unpaid_amt"] = unpaid.groupby(["company_id", "direction"], observed=True).amount.sum()
    # comportamiento de pago del mes: días de retraso de lo que se pagó en este mes
    paid_m = inv[inv.is_paid & (inv.payment_date.dt.to_period("M") == m)]
    paid_m = paid_m.assign(late=paid_m.days_late.clip(-30, 180))
    lw = paid_m.groupby(["company_id", "direction"], observed=True).apply(
        lambda d: np.average(d.late, weights=d.amount) if d.amount.sum() > 0 else np.nan, include_groups=False)
    g["days_late"] = lw
    g["paid_n"] = paid_m.groupby(["company_id", "direction"], observed=True).size()
    # concentración de clientes: peso del mayor cliente en lo facturado los últimos 12 meses
    ar = inv[(inv.direction == "AR") & (inv.issuance_date > end - pd.Timedelta(days=365)) & (inv.issuance_date <= end)
             & inv.counterparty_id.notna()]
    cp = ar.groupby(["company_id", "counterparty_id"], observed=True).amount.sum()
    top = pd.DataFrame({"top": cp.groupby("company_id").max(), "tot": cp.groupby("company_id").sum(), "n": cp.groupby("company_id").size()})
    top["ar_top1_share"] = (top.top / top.tot).where(ar.groupby("company_id").size().reindex(top.index) >= 5)
    g = g.join(top[["ar_top1_share"]].assign(direction="AR").set_index("direction", append=True), how="outer")
    g["month"] = str(m)
    rows.append(g.reset_index())
ia = pd.concat(rows)
ia["overdue_ratio"] = (ia.unpaid_amt.fillna(0) / ia.due_amt).where(ia.due_n >= 3)  # mínimo 3 facturas: 1 sola factura no es comportamiento
ia["days_late"] = ia.days_late.where(ia.paid_n >= 3)
w = ia.pivot(index=["company_id", "month"], columns="direction", values=["overdue_ratio", "days_late", "due_amt", "ar_top1_share"])
w.columns = [f"{'ar' if d == 'AR' else 'ap'}_{v}" for v, d in w.columns]
w = w.drop(columns=["ap_ar_top1_share"], errors="ignore").rename(columns={"ar_ar_top1_share": "ar_top1_share"})
p = p.join(w)

# ---------- 4. deuda (solo hay foto final) ----------
dp = pd.read_parquet(D / "debt_products.parquet")
fin = dp[dp.type.isin(["loan", "mortgage", "leasing", "renting", "lineofcredit"])]
p = p.join(fin.groupby("company_id").outstanding.sum().rename("debt_outstanding"), on="company_id")
p["debt_outstanding"] = p.debt_outstanding.fillna(0)

p = p.reset_index()
p.to_parquet(D / "panel.parquet", index=False)
print(p.shape, "obs rows:", int(p.observed.sum()))
print(p.describe().T[["count", "mean", "std", "min", "50%", "max"]].round(3).to_string())
