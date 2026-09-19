# Financial Health Score V1

## Purpose

V1 produces a deterministic, explainable score from financial signals that are
available at `as_of_date`. It does not train a model because the challenge data
does not contain a ground-truth financial-health label.

The LLM/product layer may explain the result and recommend actions, but it must
not invent or overwrite the numeric score.

## Temporal contract

- Complete flow window: September 2024 through August 2026.
- Current snapshot: September 1, 2026.
- Transaction and invoice history is aggregated by calendar month.
- Balance and debt snapshots are current-only and never copied into historical
  months.
- Every feature is computed using information available on or before its
  corresponding cutoff.

## Invoice semantics

- Positive amount: receivable/customer document.
- Negative amount: payable/supplier document.
- `note` and `refund` are credit documents and are excluded from gross invoice
  volume because the RAW data does not link them to the original document.
- `payment_date` is considered a settlement event only when `status=paid`.
- `pending`, `overdue`, and `payment_in_progress` remain open at the cutoff even
  when RAW `payment_date` is populated.

## Input contract

`data/features/score_input_v1.csv` contains one row per company.
`data/features/score_input_v1.json` contains the same information grouped as:

```json
{
  "company_id": "COMP_0001",
  "as_of_date": "2026-09-01",
  "feature_version": "v1",
  "metrics": {},
  "data_quality": {
    "confidence": "high",
    "metric_coverage": 0.83
  }
}
```

Missing metrics are `null`, not zero. A source-availability flag distinguishes
“no debt” or “no overdue balance” from “no data”.

The debt-product catalogue is treated as complete: a company absent from that
catalogue has zero reported banking debt. Invoice and balance coverage is not
assumed complete and remains unavailable when the company has no source rows.

## Metric blocks

### Liquidity — 30%

- Cash balance and negative-cash flag.
- Three-month net cash-flow margin.
- Three-month burn rate.
- Runway in months: current cash divided by average monthly outflow over the
  last three complete months.

### Trajectory — 20%

- Last three months versus the previous three months.
- Six-month normalised cash-flow slope and volatility.
- Number of negative-cash-flow months in the last six months.
- Persistent deterioration flag.

### Receivables — 20%

- Current overdue receivables divided by three-month sales.
- Average realised collection delay over six months.
- Current overdue ageing buckets: 30–59, 60–89 and 90+ days.

### Payables — 15%

- Current overdue payables divided by three-month purchases.
- Average realised payment delay over six months.
- Current overdue ageing buckets: 30–59, 60–89 and 90+ days.

### Debt — 10%

- Outstanding debt divided by twelve-month cash inflows.
- Debt-service payments divided by three-month cash inflows.
- Credit-line utilisation when both limit and available liquidity are present.
- Debt due within 90 days where a schedule is available.

### Concentration — 5%

- Top-one and top-five customer shares over twelve months.
- Customer HHI. Supplier concentration is included in the input for monitoring,
  but V1 scores customer dependency.

## Missing data and confidence

An unavailable block is excluded and its weight is redistributed among
available blocks. At least two blocks are required for an evaluable score.
Coverage is reported separately:

- `high`: at least 12 active months, at least 70% core metric coverage and no
  excluded balance outlier.
- `medium`: usable but incomplete history or coverage.
- `low`: fewer than six active months or less than 40% core coverage.

Missing data can reduce confidence but cannot improve the score.

## Outputs

- `company_month_features.csv`: leakage-safe historical feature panel.
- `score_input_v1.csv` and `.json`: current scoring contract.
- `scores_finales.csv`: current deterministic score and classification.
- `scores_mensuales.csv`: history-only trajectory score.
- `score_explanations.json`: block scores, effective weights, reasons and alerts.
- `feature_audit.json` and `data_quality_report.txt`: discarded rows,
  anomalies and source coverage.

## Validation

The pipeline fails when calendars, joins, identities, ranges or temporal rules
are violated. It also reports distribution and ±10% weight sensitivity warnings.
Thresholds and weights are V1 expert assumptions and must be recalibrated when
labels or domain feedback become available.
