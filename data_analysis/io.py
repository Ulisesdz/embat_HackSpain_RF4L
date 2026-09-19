"""Canonical readers for the HackSpain financial datasets.

The raw CSVs are intentionally left untouched. Some files contain padded
headers and values, so every downstream job must use this module.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd

import data_analysis.config as cfg


KEY_COLUMNS = {
    "company_id",
    "group_id",
    "product_id",
    "settlement_product_id",
    "transaction_id",
    "operation_id",
    "counterparty_id",
}


def read_csv(name: str, *, required: bool = True, audit: dict[str, Any] | None = None,
             **kwargs: Any) -> pd.DataFrame | None:
    """Read and canonicalise a RAW CSV without mutating it."""
    path = cfg.DATA_DIR / name
    if not path.exists():
        if required:
            raise FileNotFoundError(f"No existe {path}")
        return None

    df = pd.read_csv(path, low_memory=False, **kwargs)
    original_columns = list(df.columns)
    df.columns = [str(column).strip() for column in df.columns]
    if len(df.columns) != len(set(df.columns)):
        raise ValueError(f"{name}: hay columnas duplicadas tras normalizar cabeceras")

    object_columns = df.select_dtypes(include=["object", "string"]).columns
    for column in object_columns:
        df[column] = df[column].astype("string").str.strip()
        df[column] = df[column].replace("", pd.NA)

    for column in KEY_COLUMNS.intersection(df.columns):
        df[column] = df[column].astype("string").str.strip()

    if audit is not None:
        audit[f"{name}:rows"] = int(len(df))
        audit[f"{name}:columns_trimmed"] = int(
            sum(str(before) != str(after) for before, after in zip(original_columns, df.columns))
        )
        audit[f"{name}:duplicate_rows"] = int(df.duplicated().sum())
        if "company_id" in df:
            audit[f"{name}:companies"] = int(df["company_id"].nunique(dropna=True))
            audit[f"{name}:missing_company_id"] = int(df["company_id"].isna().sum())

    return df


def numeric(series: pd.Series) -> pd.Series:
    """Convert a series to numeric, coercing malformed values to NA."""
    return pd.to_numeric(series, errors="coerce")


def datetime(series: pd.Series) -> pd.Series:
    """Parse heterogeneous timestamps without raising on malformed dates."""
    return pd.to_datetime(series, errors="coerce", format="mixed")


def write_json(path: Path, payload: Any) -> None:
    import json

    path.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False, default=str),
        encoding="utf-8",
    )
