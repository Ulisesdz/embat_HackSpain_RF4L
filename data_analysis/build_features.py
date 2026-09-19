"""Build leakage-safe company-month features and the score input V1."""

from __future__ import annotations

import math
from typing import Any

import numpy as np
import pandas as pd

import data_analysis.config as cfg
from data_analysis.io import datetime, numeric, read_csv, write_json

AUDIT: dict[str, Any] = {}


def _rolling_sum(panel: pd.DataFrame, column: str, window: int, minimum: int | None = None) -> pd.Series:
    return panel.groupby("company_id")[column].transform(
        lambda values: values.rolling(window, min_periods=minimum or window).sum()
    )


def _rolling_mean(panel: pd.DataFrame, column: str, window: int, minimum: int | None = None) -> pd.Series:
    return panel.groupby("company_id")[column].transform(
        lambda values: values.rolling(window, min_periods=minimum or window).mean()
    )


def _slope(values: np.ndarray) -> float:
    valid = np.isfinite(values)
    if valid.sum() < 3:
        return np.nan
    y = values[valid]
    return float(np.polyfit(np.arange(len(y)), y, 1)[0])


def build_transactions() -> pd.DataFrame:
    columns = [
        "transaction_id", "company_id", "date", "amount", "status",
        "category", "counterparty_id",
    ]
    tx = read_csv("transactions.csv", audit=AUDIT, usecols=columns)
    assert tx is not None
    tx["date"] = datetime(tx["date"])
    tx["amount"] = numeric(tx["amount"])
    tx["status"] = tx["status"].str.lower()
    tx["category"] = tx["category"].str.lower()

    AUDIT["transactions:invalid_dates"] = int(tx["date"].isna().sum())
    AUDIT["transactions:invalid_amounts"] = int(tx["amount"].isna().sum())
    pending = tx["status"].eq("pending").fillna(False)
    AUDIT["transactions:pending_excluded"] = int(pending.sum())
    tx = tx[
        tx["date"].between(cfg.START_DATE, cfg.FLOW_END_DATE)
        & tx["company_id"].notna()
        & tx["amount"].notna()
        & ~pending
    ].copy()
    tx["year_month"] = tx["date"].dt.to_period("M")
    tx["cash_inflow"] = tx["amount"].clip(lower=0)
    tx["cash_outflow"] = (-tx["amount"].clip(upper=0))
    tx["debt_service_outflow"] = np.where(
        tx["category"].eq("debt_repayment").fillna(False), tx["cash_outflow"], 0.0
    )
    tx["essential_outflow"] = np.where(
        tx["category"].isin({"salary", "tax", "utility", "social_security"}).fillna(False),
        tx["cash_outflow"],
        0.0,
    )

    monthly = tx.groupby(["company_id", "year_month"], as_index=False).agg(
        cash_inflow=("cash_inflow", "sum"),
        cash_outflow=("cash_outflow", "sum"),
        net_cashflow=("amount", "sum"),
        debt_service_outflow=("debt_service_outflow", "sum"),
        essential_outflow=("essential_outflow", "sum"),
        transaction_count=("transaction_id", "count"),
    )
    AUDIT["transactions:rows_in_complete_window"] = int(len(tx))
    AUDIT["transactions:companies_in_complete_window"] = int(tx["company_id"].nunique())
    del tx
    return monthly


def prepare_invoices() -> pd.DataFrame:
    columns = [
        "operation_id", "company_id", "document_type", "issuance_date", "due_date",
        "payment_date", "amount", "pending_amount", "status", "counterparty_id",
    ]
    inv = read_csv("invoices.csv", audit=AUDIT, usecols=columns)
    assert inv is not None
    for column in ["issuance_date", "due_date", "payment_date"]:
        inv[column] = datetime(inv[column])
    inv["amount"] = numeric(inv["amount"])
    inv["pending_amount"] = numeric(inv["pending_amount"]).fillna(inv["amount"]).abs()
    inv["status_normalized"] = inv["status"].str.lower().str.replace(" ", "", regex=False)
    inv["document_type_normalized"] = inv["document_type"].str.lower()
    inv["amount_abs"] = inv["amount"].abs()
    pending_exceeds_amount = inv["pending_amount"] > inv["amount_abs"]
    AUDIT["invoices:pending_exceeds_amount_capped"] = int(pending_exceeds_amount.sum())
    inv["pending_amount"] = inv["pending_amount"].clip(upper=inv["amount_abs"])
    inv["is_receivable"] = inv["amount"] > 0
    inv["is_payable"] = inv["amount"] < 0
    inv["is_credit_document"] = inv["document_type_normalized"].isin(cfg.CREDIT_DOCUMENT_TYPES)
    inv["is_paid"] = inv["status_normalized"].isin(cfg.PAID_INVOICE_STATUSES)

    # payment_date is populated even for open invoices in this dataset. It is
    # only an actual settlement event when status says that the document is paid.
    payment_valid = (
        inv["is_paid"]
        & inv["payment_date"].notna()
        & inv["payment_date"].between(cfg.START_DATE - pd.DateOffset(years=5), cfg.EXTRACTION_DATE)
    )
    inv["effective_payment_date"] = inv["payment_date"].where(payment_valid)
    inv["is_open_at_cutoff"] = (
        ~inv["is_paid"]
        & ~inv["status_normalized"].eq("cancel")
        & (inv["pending_amount"] > 0)
    )
    inv["is_overdue_at_cutoff"] = (
        inv["is_open_at_cutoff"]
        & inv["due_date"].notna()
        & (inv["due_date"] < cfg.AS_OF_DATE)
    )
    inv["days_to_pay"] = (
        inv["effective_payment_date"] - inv["due_date"]
    ).dt.days.clip(lower=0)

    AUDIT["invoices:invalid_issuance_dates"] = int(inv["issuance_date"].isna().sum())
    AUDIT["invoices:invalid_due_dates"] = int(inv["due_date"].isna().sum())
    AUDIT["invoices:negative_amount_direction_payable"] = int(inv["is_payable"].sum())
    AUDIT["invoices:positive_amount_direction_receivable"] = int(inv["is_receivable"].sum())
    AUDIT["invoices:credit_documents"] = int(inv["is_credit_document"].sum())
    AUDIT["invoices:open_at_cutoff"] = int(inv["is_open_at_cutoff"].sum())
    AUDIT["invoices:overdue_at_cutoff"] = int(inv["is_overdue_at_cutoff"].sum())
    AUDIT["invoices:open_rows_with_populated_payment_date_ignored"] = int(
        (inv["is_open_at_cutoff"] & inv["payment_date"].notna()).sum()
    )
    return inv


def build_invoice_monthly(inv: pd.DataFrame) -> pd.DataFrame:
    usable = inv[
        ~inv["is_credit_document"]
        & inv["amount"].notna()
        & (inv["is_receivable"] | inv["is_payable"])
    ].copy()

    issued = usable[
        usable["issuance_date"].between(cfg.START_DATE, cfg.FLOW_END_DATE)
    ].copy()
    issued["year_month"] = issued["issuance_date"].dt.to_period("M")
    issued["sales_amount"] = np.where(issued["is_receivable"], issued["amount_abs"], 0.0)
    issued["purchase_amount"] = np.where(issued["is_payable"], issued["amount_abs"], 0.0)
    issued["sales_invoice_count"] = issued["is_receivable"].astype(int)
    issued["purchase_invoice_count"] = issued["is_payable"].astype(int)
    volume = issued.groupby(["company_id", "year_month"], as_index=False).agg(
        sales_amount=("sales_amount", "sum"),
        purchase_amount=("purchase_amount", "sum"),
        sales_invoice_count=("sales_invoice_count", "sum"),
        purchase_invoice_count=("purchase_invoice_count", "sum"),
    )

    due = usable[usable["due_date"].between(cfg.START_DATE, cfg.FLOW_END_DATE)].copy()
    due["year_month"] = due["due_date"].dt.to_period("M")
    month_end = due["year_month"].dt.to_timestamp(how="end")
    unpaid_at_month_end = (
        due["is_open_at_cutoff"]
        | (due["effective_payment_date"] > month_end)
    )
    due["late_receivable_amount"] = np.where(
        due["is_receivable"] & unpaid_at_month_end,
        np.where(due["is_open_at_cutoff"], due["pending_amount"], due["amount_abs"]),
        0.0,
    )
    due["late_payable_amount"] = np.where(
        due["is_payable"] & unpaid_at_month_end,
        np.where(due["is_open_at_cutoff"], due["pending_amount"], due["amount_abs"]),
        0.0,
    )
    due["due_receivable_amount"] = np.where(due["is_receivable"], due["amount_abs"], 0.0)
    due["due_payable_amount"] = np.where(due["is_payable"], due["amount_abs"], 0.0)
    due["due_receivable_count"] = due["is_receivable"].astype(int)
    due["due_payable_count"] = due["is_payable"].astype(int)
    due["collection_delay_days"] = due["days_to_pay"].where(due["is_receivable"])
    due["payment_delay_days"] = due["days_to_pay"].where(due["is_payable"])
    cohorts = due.groupby(["company_id", "year_month"], as_index=False).agg(
        due_receivable_amount=("due_receivable_amount", "sum"),
        late_receivable_amount=("late_receivable_amount", "sum"),
        due_payable_amount=("due_payable_amount", "sum"),
        late_payable_amount=("late_payable_amount", "sum"),
        due_receivable_count=("due_receivable_count", "sum"),
        due_payable_count=("due_payable_count", "sum"),
        average_collection_delay_days=("collection_delay_days", "mean"),
        average_payment_delay_days=("payment_delay_days", "mean"),
    )
    return volume.merge(cohorts, on=["company_id", "year_month"], how="outer")


def build_calendar(company_ids: set[str]) -> pd.DataFrame:
    index = pd.MultiIndex.from_product(
        [sorted(company_ids), cfg.MONTHS],
        names=["company_id", "year_month"],
    )
    return index.to_frame(index=False)


def derive_monthly(panel: pd.DataFrame, invoice_companies: set[str]) -> pd.DataFrame:
    zero_columns = [
        "cash_inflow", "cash_outflow", "net_cashflow", "debt_service_outflow",
        "essential_outflow", "transaction_count", "sales_amount", "purchase_amount",
        "sales_invoice_count", "purchase_invoice_count", "due_receivable_amount",
        "late_receivable_amount", "due_payable_amount", "late_payable_amount",
        "due_receivable_count", "due_payable_count",
    ]
    for column in zero_columns:
        panel[column] = panel[column].fillna(0.0)

    panel = panel.sort_values(["company_id", "year_month"]).reset_index(drop=True)
    panel["invoice_source_available"] = panel["company_id"].isin(invoice_companies).astype(int)
    panel["month_active"] = (
        (panel["transaction_count"] > 0)
        | (panel["sales_invoice_count"] > 0)
        | (panel["purchase_invoice_count"] > 0)
    ).astype(int)
    panel["month_without_inflow"] = (
        (panel["cash_inflow"] == 0) & (panel["cash_outflow"] > 0)
    ).astype(int)
    panel["cashflow_margin"] = np.where(
        panel["cash_inflow"] > 0,
        panel["net_cashflow"] / panel["cash_inflow"],
        np.nan,
    )
    panel["burn_rate"] = np.where(
        panel["cash_inflow"] > 0,
        panel["cash_outflow"] / panel["cash_inflow"],
        np.nan,
    )

    panel["cash_inflow_3m"] = _rolling_sum(panel, "cash_inflow", 3)
    panel["cash_outflow_3m"] = _rolling_sum(panel, "cash_outflow", 3)
    panel["net_cashflow_3m"] = _rolling_sum(panel, "net_cashflow", 3)
    panel["net_cashflow_margin_3m"] = np.where(
        panel["cash_inflow_3m"] > 0,
        panel["net_cashflow_3m"] / panel["cash_inflow_3m"],
        np.nan,
    )
    panel["burn_rate_3m"] = np.where(
        panel["cash_inflow_3m"] > 0,
        panel["cash_outflow_3m"] / panel["cash_inflow_3m"],
        np.nan,
    )
    panel["cash_inflow_12m"] = _rolling_sum(panel, "cash_inflow", 12)
    panel["cash_outflow_12m"] = _rolling_sum(panel, "cash_outflow", 12)
    panel["debt_service_outflow_3m"] = _rolling_sum(panel, "debt_service_outflow", 3)
    panel["debt_service_to_inflows_3m"] = np.where(
        panel["cash_inflow_3m"] > 0,
        panel["debt_service_outflow_3m"] / panel["cash_inflow_3m"],
        np.nan,
    )

    group = panel.groupby("company_id", sort=False)
    panel["net_cashflow_margin_prev_3m"] = group["net_cashflow_margin_3m"].shift(3)
    panel["net_cashflow_change_3m"] = (
        panel["net_cashflow_margin_3m"] - panel["net_cashflow_margin_prev_3m"]
    )
    panel["net_cashflow_slope_6m"] = group["cashflow_margin"].transform(
        lambda values: values.rolling(6, min_periods=3).apply(_slope, raw=True)
    )
    panel["cashflow_volatility_6m"] = group["cashflow_margin"].transform(
        lambda values: values.rolling(6, min_periods=3).std()
    )
    panel["months_negative_cashflow_6m"] = group["net_cashflow"].transform(
        lambda values: (values < 0).astype(int).rolling(6, min_periods=6).sum()
    )
    prior_year_inflow = group["cash_inflow"].shift(12)
    panel["inflow_growth_yoy"] = np.where(
        prior_year_inflow > 0,
        panel["cash_inflow"] / prior_year_inflow - 1,
        np.nan,
    )
    panel["persistent_deterioration_flag"] = (
        (panel["months_negative_cashflow_6m"] >= 4)
        & (panel["net_cashflow_slope_6m"] < 0)
    ).astype(int)

    for prefix, numerator, denominator, count in [
        ("receivables", "late_receivable_amount", "due_receivable_amount", "due_receivable_count"),
        ("payables", "late_payable_amount", "due_payable_amount", "due_payable_count"),
    ]:
        numerator_3m = _rolling_sum(panel, numerator, 3)
        denominator_3m = _rolling_sum(panel, denominator, 3)
        count_3m = _rolling_sum(panel, count, 3)
        panel[f"overdue_{prefix}_ratio_3m"] = np.where(
            (denominator_3m > 0) & (count_3m >= cfg.MIN_INVOICES_RATIO),
            numerator_3m / denominator_3m,
            np.nan,
        )
        panel[f"overdue_{prefix}_ratio_prev_3m"] = group[
            f"overdue_{prefix}_ratio_3m"
        ].shift(3)
        panel[f"overdue_{prefix}_change_3m"] = (
            panel[f"overdue_{prefix}_ratio_3m"]
            - panel[f"overdue_{prefix}_ratio_prev_3m"]
        )

    panel["average_collection_delay_6m"] = _rolling_mean(
        panel, "average_collection_delay_days", 6, minimum=2
    )
    panel["average_payment_delay_6m"] = _rolling_mean(
        panel, "average_payment_delay_days", 6, minimum=2
    )
    panel["active_months_12m"] = _rolling_sum(panel, "month_active", 12, minimum=1)
    panel["history_months"] = group.cumcount() + 1
    return panel


def build_balance_snapshot() -> pd.DataFrame:
    balances = read_csv("balances.csv", required=False, audit=AUDIT)
    products = read_csv("banking_products.csv", required=False, audit=AUDIT)
    if balances is None or products is None:
        return pd.DataFrame(columns=["company_id", "cash_balance"])

    balances["balance"] = numeric(balances["balance"])
    balances["date"] = datetime(balances["date"])
    products["type"] = products["type"].str.lower()
    joined = balances.merge(
        products[["product_id", "type"]].drop_duplicates("product_id"),
        on="product_id",
        how="inner",
        validate="many_to_one",
    )
    joined = joined[
        joined["type"].isin(cfg.CASH_PRODUCT_TYPES)
        & (joined["date"] <= cfg.AS_OF_DATE)
    ].copy()
    joined = joined.sort_values("date").drop_duplicates("product_id", keep="last")
    joined["balance_outlier"] = joined["balance"].abs() >= cfg.BALANCE_ABS_HARD_LIMIT
    AUDIT["balances:cash_products"] = int(len(joined))
    AUDIT["balances:hard_outliers_excluded"] = int(joined["balance_outlier"].sum())
    joined["valid_balance"] = joined["balance"].mask(joined["balance_outlier"])

    result = joined.groupby("company_id", as_index=False).agg(
        cash_balance=("valid_balance", lambda values: values.sum(min_count=1)),
        cash_product_count=("product_id", "nunique"),
        cash_balance_outlier_count=("balance_outlier", "sum"),
    )
    aggregate_outlier = result["cash_balance"].abs() >= cfg.BALANCE_ABS_HARD_LIMIT
    AUDIT["balances:aggregate_hard_outliers_excluded"] = int(aggregate_outlier.sum())
    result.loc[aggregate_outlier, "cash_balance"] = np.nan
    result.loc[aggregate_outlier, "cash_balance_outlier_count"] += 1
    return result


def build_debt_snapshot() -> pd.DataFrame:
    debt = read_csv("debt_products.csv", required=False, audit=AUDIT)
    if debt is None:
        AUDIT["debt:source_available"] = 0
        return pd.DataFrame(columns=["company_id", "debt_outstanding"])
    AUDIT["debt:source_available"] = 1
    debt["outstanding_abs"] = numeric(debt["outstanding"]).abs()
    debt["granted_abs"] = numeric(debt["granted"]).abs()
    debt["liquidity_value"] = numeric(debt["liquidity"])
    debt["type"] = debt["type"].str.lower()

    base = debt.groupby("company_id", as_index=False).agg(
        debt_outstanding=("outstanding_abs", "sum"),
        debt_product_count=("product_id", "nunique"),
    )
    credit = debt[
        debt["type"].eq("lineofcredit")
        & (debt["granted_abs"] > 0)
        & debt["liquidity_value"].notna()
    ].copy()
    credit["used_amount"] = (
        credit["granted_abs"] - credit["liquidity_value"]
    ).clip(lower=0, upper=credit["granted_abs"])
    utilisation = credit.groupby("company_id", as_index=False).agg(
        credit_used=("used_amount", "sum"),
        credit_limit=("granted_abs", "sum"),
    )
    utilisation["credit_line_utilization"] = np.where(
        utilisation["credit_limit"] > 0,
        utilisation["credit_used"] / utilisation["credit_limit"],
        np.nan,
    )
    AUDIT["debt:companies_with_credit_utilization"] = int(
        utilisation["company_id"].nunique()
    )
    return base.merge(
        utilisation[["company_id", "credit_line_utilization"]],
        on="company_id",
        how="left",
    )


def build_schedule_snapshot() -> pd.DataFrame:
    schedule = read_csv("debt_schedule_config.csv", required=False, audit=AUDIT)
    if schedule is None:
        return pd.DataFrame(columns=["company_id", "upcoming_debt_balance_90d"])
    schedule["next_payment_date"] = datetime(schedule["next_payment_date"])
    schedule["outstanding_balance_abs"] = numeric(schedule["outstanding_balance"]).abs()
    upper = cfg.AS_OF_DATE + pd.DateOffset(days=90)
    due = schedule["next_payment_date"].between(cfg.AS_OF_DATE, upper)
    return (
        schedule[due]
        .groupby("company_id", as_index=False)
        .agg(upcoming_debt_balance_90d=("outstanding_balance_abs", "sum"))
    )


def _concentration(inv: pd.DataFrame, receivable: bool, prefix: str) -> pd.DataFrame:
    start = cfg.AS_OF_DATE - pd.DateOffset(months=12)
    mask = (
        (inv["is_receivable"] if receivable else inv["is_payable"])
        & ~inv["is_credit_document"]
        & inv["issuance_date"].between(start, cfg.FLOW_END_DATE)
        & inv["counterparty_id"].notna()
    )
    data = inv[mask].groupby(
        ["company_id", "counterparty_id"], as_index=False
    )["amount_abs"].sum()
    if data.empty:
        return pd.DataFrame(columns=["company_id"])
    totals = data.groupby("company_id")["amount_abs"].transform("sum")
    data["share"] = np.where(totals > 0, data["amount_abs"] / totals, np.nan)
    rows = []
    for company_id, values in data.groupby("company_id"):
        shares = values["share"].dropna().sort_values(ascending=False)
        rows.append({
            "company_id": company_id,
            f"top1_{prefix}_share": float(shares.iloc[0]) if len(shares) else np.nan,
            f"top5_{prefix}_share": float(shares.head(5).sum()) if len(shares) else np.nan,
            f"{prefix}_hhi": float((shares ** 2).sum()) if len(shares) else np.nan,
            f"{prefix}_counterparty_count": int(len(shares)),
        })
    return pd.DataFrame(rows)


def build_current_invoice_snapshot(inv: pd.DataFrame) -> pd.DataFrame:
    current = inv[
        inv["is_overdue_at_cutoff"]
        & ~inv["is_credit_document"]
        & (inv["is_receivable"] | inv["is_payable"])
    ].copy()
    current["days_overdue"] = (cfg.AS_OF_DATE - current["due_date"]).dt.days.clip(lower=0)
    current["overdue_receivable"] = np.where(
        current["is_receivable"], current["pending_amount"], 0.0
    )
    current["overdue_payable"] = np.where(
        current["is_payable"], current["pending_amount"], 0.0
    )
    for side in ["receivable", "payable"]:
        amount = current[f"overdue_{side}"]
        current[f"{side}_overdue_30d"] = np.where(
            (current["days_overdue"] >= 30) & (current["days_overdue"] < 60), amount, 0.0
        )
        current[f"{side}_overdue_60d"] = np.where(
            (current["days_overdue"] >= 60) & (current["days_overdue"] < 90), amount, 0.0
        )
        current[f"{side}_overdue_90d"] = np.where(
            current["days_overdue"] >= 90, amount, 0.0
        )
    return current.groupby("company_id", as_index=False).agg(
        overdue_receivables_current=("overdue_receivable", "sum"),
        overdue_payables_current=("overdue_payable", "sum"),
        receivables_overdue_30d=("receivable_overdue_30d", "sum"),
        receivables_overdue_60d=("receivable_overdue_60d", "sum"),
        receivables_overdue_90d=("receivable_overdue_90d", "sum"),
        payables_overdue_30d=("payable_overdue_30d", "sum"),
        payables_overdue_60d=("payable_overdue_60d", "sum"),
        payables_overdue_90d=("payable_overdue_90d", "sum"),
    )


def build_score_input(panel: pd.DataFrame, inv: pd.DataFrame) -> pd.DataFrame:
    current = panel[panel["year_month"].eq(cfg.MONTHS[-1])].copy()
    current = current.rename(columns={
        "sales_amount": "sales_1m",
        "purchase_amount": "purchases_1m",
    })
    current["sales_3m"] = (
        panel.groupby("company_id")["sales_amount"]
        .transform(lambda values: values.rolling(3, min_periods=3).sum())
        .loc[current.index]
    )
    current["purchases_3m"] = (
        panel.groupby("company_id")["purchase_amount"]
        .transform(lambda values: values.rolling(3, min_periods=3).sum())
        .loc[current.index]
    )

    for snapshot in [
        build_balance_snapshot(),
        build_debt_snapshot(),
        build_schedule_snapshot(),
        build_current_invoice_snapshot(inv),
        _concentration(inv, True, "customer"),
        _concentration(inv, False, "supplier"),
    ]:
        current = current.merge(snapshot, on="company_id", how="left", validate="one_to_one")

    zero_if_source = [
        "overdue_receivables_current", "overdue_payables_current",
        "receivables_overdue_30d", "receivables_overdue_60d",
        "receivables_overdue_90d", "payables_overdue_30d",
        "payables_overdue_60d", "payables_overdue_90d",
        "debt_outstanding", "debt_product_count", "upcoming_debt_balance_90d",
    ]
    for column in zero_if_source:
        if column not in current:
            current[column] = np.nan

    has_invoices = current["invoice_source_available"].eq(1)
    invoice_amount_columns = [column for column in zero_if_source if "debt" not in column]
    current.loc[has_invoices, invoice_amount_columns] = current.loc[
        has_invoices, invoice_amount_columns
    ].fillna(0.0)
    debt_source_available = int(AUDIT.get("debt:source_available", 0))
    current["debt_source_available"] = debt_source_available
    if debt_source_available:
        current[[
            "debt_outstanding", "debt_product_count", "upcoming_debt_balance_90d",
        ]] = current[[
            "debt_outstanding", "debt_product_count", "upcoming_debt_balance_90d",
        ]].fillna(0.0)
    current["balance_source_available"] = current["cash_product_count"].notna().astype(int)

    current["cash_negative_flag"] = np.where(
        current["cash_balance"].notna(), (current["cash_balance"] < 0).astype(float), np.nan
    )
    current["average_monthly_outflow_3m"] = current["cash_outflow_3m"] / 3
    current["runway_months"] = np.where(
        current["average_monthly_outflow_3m"] > 0,
        current["cash_balance"] / current["average_monthly_outflow_3m"],
        np.nan,
    )
    current["runway_months"] = current["runway_months"].clip(-12, 60)
    current["overdue_receivables_to_sales"] = np.where(
        current["sales_3m"] > 0,
        current["overdue_receivables_current"] / current["sales_3m"],
        np.nan,
    )
    current["overdue_payables_to_purchases"] = np.where(
        current["purchases_3m"] > 0,
        current["overdue_payables_current"] / current["purchases_3m"],
        np.nan,
    )
    current["debt_to_annual_inflows"] = np.where(
        current["cash_inflow_12m"] > 0,
        current["debt_outstanding"] / current["cash_inflow_12m"],
        np.nan,
    )

    current["metric_coverage"] = current[[
        "net_cashflow_margin_3m", "runway_months", "overdue_receivables_to_sales",
        "overdue_payables_to_purchases", "debt_to_annual_inflows",
        "top1_customer_share",
    ]].notna().mean(axis=1)
    current["confidence"] = np.select(
        [
            (current["active_months_12m"] < cfg.MIN_ACTIVE_MONTHS)
            | (current["metric_coverage"] < 0.4),
            (current["active_months_12m"] < cfg.HIGH_CONFIDENCE_MONTHS)
            | (current["metric_coverage"] < 0.7)
            | (current["cash_balance_outlier_count"].fillna(0) > 0),
        ],
        ["low", "medium"],
        default="high",
    )
    current["as_of_date"] = cfg.AS_OF_DATE.date().isoformat()
    current["feature_version"] = "v1"

    identifiers = [
        "company_id", "as_of_date", "feature_version", "confidence",
        "metric_coverage", "active_months_12m", "invoice_source_available",
        "balance_source_available", "debt_source_available",
        "cash_balance_outlier_count",
    ]
    metrics = [
        "cash_balance", "cash_negative_flag", "runway_months",
        "net_cashflow_margin_3m", "burn_rate_3m", "months_negative_cashflow_6m",
        "net_cashflow_margin_prev_3m", "net_cashflow_change_3m",
        "net_cashflow_slope_6m", "cashflow_volatility_6m", "inflow_growth_yoy",
        "persistent_deterioration_flag", "sales_3m", "overdue_receivables_current",
        "overdue_receivables_to_sales", "average_collection_delay_6m",
        "receivables_overdue_30d", "receivables_overdue_60d",
        "receivables_overdue_90d", "top1_customer_share", "top5_customer_share",
        "customer_hhi", "purchases_3m", "overdue_payables_current",
        "overdue_payables_to_purchases", "average_payment_delay_6m",
        "payables_overdue_30d", "payables_overdue_60d", "payables_overdue_90d",
        "debt_outstanding", "debt_to_annual_inflows",
        "debt_service_to_inflows_3m", "credit_line_utilization",
        "upcoming_debt_balance_90d", "top1_supplier_share", "top5_supplier_share",
        "supplier_hhi",
    ]
    for column in identifiers + metrics:
        if column not in current:
            current[column] = np.nan
    return current[identifiers + metrics].sort_values("company_id").reset_index(drop=True)


def score_input_json(records: pd.DataFrame) -> list[dict[str, Any]]:
    quality_columns = {
        "confidence", "metric_coverage", "active_months_12m",
        "invoice_source_available", "balance_source_available",
        "debt_source_available", "cash_balance_outlier_count",
    }
    identity_columns = {"company_id", "as_of_date", "feature_version"}
    payload = []
    for raw in records.replace({np.nan: None}).to_dict(orient="records"):
        payload.append({
            "company_id": raw["company_id"],
            "as_of_date": raw["as_of_date"],
            "feature_version": raw["feature_version"],
            "metrics": {
                key: value for key, value in raw.items()
                if key not in quality_columns | identity_columns
            },
            "data_quality": {
                key: raw[key] for key in quality_columns
            },
        })
    return payload


def build() -> tuple[pd.DataFrame, pd.DataFrame]:
    cfg.ensure_dirs()
    companies = read_csv("companies.csv", audit=AUDIT)
    assert companies is not None
    tx_monthly = build_transactions()
    invoices = prepare_invoices()
    invoice_monthly = build_invoice_monthly(invoices)

    company_ids = set(companies["company_id"].dropna())
    company_ids |= set(tx_monthly["company_id"].dropna())
    company_ids |= set(invoices["company_id"].dropna())
    panel = build_calendar(company_ids)
    panel = panel.merge(
        tx_monthly, on=["company_id", "year_month"], how="left", validate="one_to_one"
    )
    panel = panel.merge(
        invoice_monthly, on=["company_id", "year_month"], how="left", validate="one_to_one"
    )
    panel = derive_monthly(panel, set(invoices["company_id"].dropna()))
    score_input = build_score_input(panel, invoices)

    output_panel = panel.copy()
    output_panel["year_month"] = output_panel["year_month"].astype(str)
    output_panel.to_csv(cfg.PANEL_PATH, index=False)
    score_input.to_csv(cfg.SCORE_INPUT_PATH, index=False)
    write_json(cfg.SCORE_INPUT_JSON_PATH, score_input_json(score_input))

    AUDIT.update({
        "window:start": cfg.START_DATE.date().isoformat(),
        "window:flow_end": cfg.FLOW_END_DATE.date().isoformat(),
        "as_of_date": cfg.AS_OF_DATE.date().isoformat(),
        "panel:companies": int(panel["company_id"].nunique()),
        "panel:months": int(panel["year_month"].nunique()),
        "panel:rows": int(len(panel)),
        "score_input:rows": int(len(score_input)),
        "score_input:high_confidence": int(score_input["confidence"].eq("high").sum()),
    })
    write_json(cfg.AUDIT_PATH, AUDIT)
    print(f"Panel mensual: {cfg.PANEL_PATH} ({panel.shape[0]:,} x {panel.shape[1]})")
    print(f"Input V1: {cfg.SCORE_INPUT_PATH} ({score_input.shape[0]:,} x {score_input.shape[1]})")
    return panel, score_input


if __name__ == "__main__":
    build()
