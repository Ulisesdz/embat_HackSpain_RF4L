"""Single source of truth for the Embat X-Ray feature and score pipeline."""

from pathlib import Path

import pandas as pd

# Paths
DATA_DIR = Path("data")
OUT_DIR = DATA_DIR / "features"
PANEL_PATH = OUT_DIR / "company_month_features.csv"
AUDIT_PATH = OUT_DIR / "feature_audit.json"
QUALITY_PATH = OUT_DIR / "data_quality_report.txt"
SCORE_INPUT_PATH = OUT_DIR / "score_input_v1.csv"
SCORE_INPUT_JSON_PATH = OUT_DIR / "score_input_v1.json"
SCORES_PATH = OUT_DIR / "scores_finales.csv"
SCORES_MENSUAL_PATH = OUT_DIR / "scores_mensuales.csv"
EXPLAIN_PATH = OUT_DIR / "score_explanations.json"

# Twenty-four complete flow months. The 2026-09-01 snapshots are only valid
# for the current score and must never be propagated backwards.
START_DATE = pd.Timestamp("2024-09-01")
FLOW_END_DATE = pd.Timestamp("2026-08-31 23:59:59")
AS_OF_DATE = pd.Timestamp("2026-09-01")
EXTRACTION_DATE = pd.Timestamp("2026-09-18")
MONTHS = pd.period_range(START_DATE.to_period("M"), FLOW_END_DATE.to_period("M"), freq="M")

# Business and quality parameters
ROLL_SHORT = 3
ROLL_LONG = 6
ROLL_YEAR = 12
MIN_INVOICES_RATIO = 2
MIN_ACTIVE_MONTHS = 6
HIGH_CONFIDENCE_MONTHS = 12
HALF_LIFE_MONTHS = 6.0
BALANCE_ABS_HARD_LIMIT = 100_000_000.0
WINSOR_LOWER = 0.01
WINSOR_UPPER = 0.99

# Deterministic score blocks
BLOCK_WEIGHTS = {
    "liquidity": 0.30,
    "trajectory": 0.20,
    "receivables": 0.20,
    "payables": 0.15,
    "debt": 0.10,
    "concentration": 0.05,
}

CLASSIFICATION_THRESHOLDS = [
    (80, "SALUDABLE"),
    (60, "ESTABLE"),
    (40, "EN RIESGO"),
    (20, "FRÁGIL"),
]

CASH_PRODUCT_TYPES = {"checking", "saving", "savings", "wallet"}
OPEN_INVOICE_STATUSES = {"overdue", "pending", "payment_in_progress", "paymentorder"}
PAID_INVOICE_STATUSES = {"paid"}
CREDIT_DOCUMENT_TYPES = {"note", "refund"}


def classify(score: float) -> str:
    for threshold, label in CLASSIFICATION_THRESHOLDS:
        if score >= threshold:
            return label
    return "CRÍTICO"


def ensure_dirs() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
