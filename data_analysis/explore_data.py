"""Reproducible, read-only audit of the RAW financial datasets."""

from __future__ import annotations

import pandas as pd

import data_analysis.config as cfg
from data_analysis.io import datetime, numeric, read_csv, write_json


def pct(part: int, total: int) -> str:
    return f"{100 * part / max(total, 1):.1f}%"


def run() -> str:
    cfg.ensure_dirs()
    audit: dict[str, object] = {}
    lines = [
        "EMBAT X-RAY · DATA QUALITY REPORT V1",
        f"Complete flow window: {cfg.START_DATE.date()} -> {cfg.FLOW_END_DATE.date()}",
        f"Current snapshot date: {cfg.AS_OF_DATE.date()}",
        "",
    ]

    companies = read_csv("companies.csv", audit=audit)
    transactions = read_csv(
        "transactions.csv",
        audit=audit,
        usecols=["transaction_id", "company_id", "date", "amount", "status", "counterparty_id"],
    )
    invoices = read_csv(
        "invoices.csv",
        audit=audit,
        usecols=[
            "operation_id", "company_id", "document_type", "issuance_date", "due_date",
            "payment_date", "amount", "pending_amount", "status", "counterparty_id",
        ],
    )
    balances = read_csv("balances.csv", audit=audit)
    debt = read_csv("debt_products.csv", audit=audit)
    schedule = read_csv("debt_schedule_config.csv", audit=audit)
    assert companies is not None and transactions is not None and invoices is not None

    transactions["date"] = datetime(transactions["date"])
    transactions["amount"] = numeric(transactions["amount"])
    tx_window = transactions["date"].between(cfg.START_DATE, cfg.FLOW_END_DATE)
    tx_months = (
        transactions[tx_window]
        .assign(month=lambda frame: frame["date"].dt.to_period("M"))
        .groupby("company_id")["month"].nunique()
    )
    tx_counterparty_missing = int(transactions["counterparty_id"].isna().sum())

    invoices["due_date"] = datetime(invoices["due_date"])
    invoices["payment_date"] = datetime(invoices["payment_date"])
    invoices["amount"] = numeric(invoices["amount"])
    invoices["pending_amount"] = numeric(invoices["pending_amount"])
    status = invoices["status"].str.lower().str.replace(" ", "", regex=False)
    open_mask = ~status.eq("paid") & ~status.eq("cancel") & (invoices["pending_amount"].abs() > 0)
    misleading_payment = int((open_mask & invoices["payment_date"].notna()).sum())

    lines.extend([
        "COVERAGE",
        f"- Companies in master: {companies['company_id'].nunique():,}",
        f"- Companies with transactions: {transactions['company_id'].nunique():,}",
        f"- Companies with invoices: {invoices['company_id'].nunique():,}",
        f"- Median active transaction months: {tx_months.median():.0f}/{len(cfg.MONTHS)}",
        f"- Transaction counterparty missing: {tx_counterparty_missing:,} "
        f"({pct(tx_counterparty_missing, len(transactions))})",
        "",
        "INVOICE SEMANTICS",
        f"- Positive documents (receivables): {(invoices['amount'] > 0).sum():,}",
        f"- Negative documents (payables): {(invoices['amount'] < 0).sum():,}",
        f"- Open documents with populated payment_date (must ignore date): "
        f"{misleading_payment:,}",
        f"- Invalid due dates: {invoices['due_date'].isna().sum():,}",
        "",
    ])

    if balances is not None:
        balances["balance"] = numeric(balances["balance"])
        extreme = int((balances["balance"].abs() >= cfg.BALANCE_ABS_HARD_LIMIT).sum())
        lines.extend([
            "BALANCES",
            f"- Rows: {len(balances):,}",
            f"- Companies: {balances['company_id'].nunique():,}",
            f"- Absolute balance >= {cfg.BALANCE_ABS_HARD_LIMIT:,.0f}: {extreme:,}",
            "- Balance is a current snapshot and cannot be used in historical months.",
            "",
        ])

    if debt is not None:
        lines.extend([
            "DEBT",
            f"- Companies with products: {debt['company_id'].nunique():,}",
            f"- Products: {len(debt):,}",
            f"- Companies with amortisation schedule: "
            f"{schedule['company_id'].nunique() if schedule is not None else 0:,}",
            "",
        ])

    lines.extend([
        "NON-NEGOTIABLE MODEL RULES",
        "- Null denominator stays null; it is never converted to a healthy zero.",
        "- Open invoices remain open until the as-of date.",
        "- Snapshot balance/debt fields are current-only.",
        "- Missing sources reduce confidence and never improve a score.",
    ])
    report = "\n".join(lines)
    cfg.QUALITY_PATH.write_text(report, encoding="utf-8")
    write_json(cfg.OUT_DIR / "raw_audit.json", audit)
    print(report)
    print(f"\nSaved: {cfg.QUALITY_PATH}")
    return report


if __name__ == "__main__":
    run()
