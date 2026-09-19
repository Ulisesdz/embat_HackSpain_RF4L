from __future__ import annotations

import pandas as pd

import data_analysis.config as cfg
from data_analysis import build_features
from data_analysis.io import read_csv
from data_analysis.score_engine import score_record


def test_canonical_reader_strips_headers_and_ids(tmp_path, monkeypatch):
    (tmp_path / "sample.csv").write_text(
        " company_id  , amount \n COMP_0001 , 10\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(cfg, "DATA_DIR", tmp_path)
    frame = read_csv("sample.csv")
    assert list(frame.columns) == ["company_id", "amount"]
    assert frame.loc[0, "company_id"] == "COMP_0001"


def test_open_invoice_payment_date_is_not_a_settlement(tmp_path, monkeypatch):
    pd.DataFrame([{
        "operation_id": "INV_1",
        "company_id": "COMP_1",
        "document_type": "invoice",
        "issuance_date": "2026-01-01",
        "due_date": "2026-02-01",
        "payment_date": "2026-02-01",
        "amount": 100,
        "pending_amount": 100,
        "status": "overdue",
        "counterparty_id": "CP_1",
    }]).to_csv(tmp_path / "invoices.csv", index=False)
    monkeypatch.setattr(cfg, "DATA_DIR", tmp_path)
    build_features.AUDIT.clear()

    invoice = build_features.prepare_invoices().iloc[0]

    assert pd.isna(invoice["effective_payment_date"])
    assert bool(invoice["is_open_at_cutoff"])
    assert bool(invoice["is_overdue_at_cutoff"])


def test_negative_invoice_is_payable_not_automatically_credit_note(tmp_path, monkeypatch):
    pd.DataFrame([{
        "operation_id": "INV_2",
        "company_id": "COMP_1",
        "document_type": "invoice",
        "issuance_date": "2026-01-01",
        "due_date": "2026-02-01",
        "payment_date": "2026-02-10",
        "amount": -100,
        "pending_amount": 0,
        "status": "paid",
        "counterparty_id": "CP_2",
    }]).to_csv(tmp_path / "invoices.csv", index=False)
    monkeypatch.setattr(cfg, "DATA_DIR", tmp_path)
    build_features.AUDIT.clear()

    invoice = build_features.prepare_invoices().iloc[0]

    assert bool(invoice["is_payable"])
    assert not bool(invoice["is_credit_document"])


def test_paid_invoice_with_invalid_payment_date_is_not_marked_open(tmp_path, monkeypatch):
    pd.DataFrame([{
        "operation_id": "INV_3",
        "company_id": "COMP_1",
        "document_type": "invoice",
        "issuance_date": "2026-01-01",
        "due_date": "2026-02-01",
        "payment_date": "6913-01-01",
        "amount": 100,
        "pending_amount": 0,
        "status": "paid",
        "counterparty_id": "CP_3",
    }]).to_csv(tmp_path / "invoices.csv", index=False)
    monkeypatch.setattr(cfg, "DATA_DIR", tmp_path)
    build_features.AUDIT.clear()

    invoices = build_features.prepare_invoices()
    monthly = build_features.build_invoice_monthly(invoices)

    assert not bool(invoices.iloc[0]["is_open_at_cutoff"])
    assert monthly["late_receivable_amount"].fillna(0).sum() == 0


def test_score_requires_two_available_blocks():
    score, details = score_record(pd.Series({"net_cashflow_margin_3m": 0.1}))
    assert score is None
    assert details["liquidity"]["applicable"]


def test_explainable_score_stays_bounded():
    row = pd.Series({
        "net_cashflow_margin_3m": 0.08,
        "runway_months": 7,
        "burn_rate_3m": 0.92,
        "cash_negative_flag": 0,
        "net_cashflow_change_3m": 0.04,
        "net_cashflow_slope_6m": 0.01,
        "months_negative_cashflow_6m": 1,
        "cashflow_volatility_6m": 0.12,
        "persistent_deterioration_flag": 0,
    })
    score, details = score_record(row)
    assert score is not None
    assert 0 <= score <= 100
    assert details["liquidity"]["metrics"]
