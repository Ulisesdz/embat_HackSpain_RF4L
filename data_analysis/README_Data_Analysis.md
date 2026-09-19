# Data analysis and Financial Health Score V1

This directory contains the reproducible data pipeline for Embat X-Ray.
The RAW files under `data/` are never modified.

## Setup

```bash
uv venv
uv pip install -r requirements.txt
```

## Execution

Run from the repository root:

```bash
.venv/bin/python -m data_analysis.explore_data
.venv/bin/python -m data_analysis.build_features
.venv/bin/python -m data_analysis.score_engine
.venv/bin/python -m data_analysis.validate_features
```

The validator must finish with `VALIDATION OK` before generated scores are used
by the product.

## Pipeline

1. `io.py` canonicalises padded headers, IDs and values without touching RAW.
2. `explore_data.py` records source coverage and known data-quality risks.
3. `build_features.py` creates a 24-month leakage-safe panel and the V1 input.
4. `score_engine.py` applies deterministic financial rules and explanations.
5. `validate_features.py` checks invariants, temporal leakage and sensitivity.
6. `config.py` contains cutoffs, quality limits and score weights.

Generated artifacts are written to `data/features/` and are intentionally
ignored by Git.

## Important findings encoded in the pipeline

- Several RAW CSVs contain whitespace in headers and identifiers.
- Invoice sign is used for direction: positive is receivable, negative payable.
  A negative amount is not automatically a credit note.
- `payment_date` is populated on open documents, so it is only trusted when the
  invoice status is `paid`.
- The September 2026 balances and debt are current snapshots. They are not
  historical features.
- Extreme balance values incompatible with the SME context are excluded and
  reduce score confidence.
- Transactions cover all companies, while invoices, debt and debt schedules
  have partial coverage. Missing sources remain null and do not count as healthy.

Detailed formulas and the input contract are documented in
[`docs/score-v1.md`](../docs/score-v1.md).
