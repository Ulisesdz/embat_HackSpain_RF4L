"""Deterministic and explainable score engine for score_input_v1."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

import numpy as np
import pandas as pd

import data_analysis.config as cfg
from data_analysis.io import write_json


@dataclass
class MetricScore:
    name: str
    score: float
    value: float
    reason: str


def _value(row: pd.Series, name: str) -> float | None:
    value = row.get(name)
    return None if pd.isna(value) else float(value)


def _curve(value: float | None, points: list[tuple[float, float]]) -> float | None:
    if value is None or not np.isfinite(value):
        return None
    x, y = zip(*sorted(points))
    return float(np.interp(value, x, y))


def _metric(
    row: pd.Series,
    name: str,
    points: list[tuple[float, float]],
    label: str,
    formatter: Callable[[float], str] | None = None,
) -> MetricScore | None:
    value = _value(row, name)
    score = _curve(value, points)
    if score is None or value is None:
        return None
    rendered = formatter(value) if formatter else f"{value:.2f}"
    return MetricScore(name, round(score, 2), value, f"{label}: {rendered}")


def _average(metrics: list[MetricScore | None]) -> tuple[float | None, list[MetricScore]]:
    active = [metric for metric in metrics if metric is not None]
    if not active:
        return None, []
    return float(np.mean([metric.score for metric in active])), active


def score_liquidity(row: pd.Series) -> tuple[float | None, list[MetricScore]]:
    score, metrics = _average([
        _metric(
            row, "net_cashflow_margin_3m",
            [(-0.30, 0), (-0.10, 30), (0, 60), (0.10, 85), (0.20, 100)],
            "Margen de caja 3m", lambda value: f"{value:.1%}",
        ),
        _metric(
            row, "runway_months",
            [(-1, 0), (0, 10), (1, 30), (3, 60), (6, 85), (12, 100)],
            "Runway", lambda value: f"{value:.1f} meses",
        ),
        _metric(
            row, "burn_rate_3m",
            [(0.6, 100), (1.0, 72), (1.2, 45), (1.5, 20), (2.0, 0)],
            "Burn rate", lambda value: f"{value:.2f}x",
        ),
    ])
    if score is not None and _value(row, "cash_negative_flag") == 1:
        score = max(0.0, score - 20)
    return score, metrics


def score_trajectory(row: pd.Series) -> tuple[float | None, list[MetricScore]]:
    score, metrics = _average([
        _metric(
            row, "net_cashflow_change_3m",
            [(-0.25, 0), (-0.10, 25), (0, 60), (0.10, 85), (0.25, 100)],
            "Cambio frente al trimestre anterior", lambda value: f"{value:+.1%}",
        ),
        _metric(
            row, "net_cashflow_slope_6m",
            [(-0.08, 0), (-0.03, 25), (0, 60), (0.03, 85), (0.08, 100)],
            "Pendiente de caja 6m", lambda value: f"{value:+.2%}/mes",
        ),
        _metric(
            row, "months_negative_cashflow_6m",
            [(0, 100), (1, 85), (2, 65), (3, 45), (4, 25), (6, 0)],
            "Meses con caja negativa", lambda value: f"{value:.0f}/6",
        ),
        _metric(
            row, "cashflow_volatility_6m",
            [(0, 100), (0.10, 85), (0.25, 60), (0.50, 30), (1.0, 0)],
            "Volatilidad de caja", lambda value: f"{value:.1%}",
        ),
    ])
    if score is not None and _value(row, "persistent_deterioration_flag") == 1:
        score = max(0.0, score - 15)
    return score, metrics


def score_receivables(row: pd.Series) -> tuple[float | None, list[MetricScore]]:
    return _average([
        _metric(
            row, "overdue_receivables_to_sales",
            [(0, 100), (0.10, 85), (0.25, 60), (0.50, 25), (1.0, 0)],
            "Cartera vencida / ventas 3m", lambda value: f"{value:.1%}",
        ),
        _metric(
            row, "average_collection_delay_6m",
            [(0, 100), (15, 90), (30, 70), (60, 35), (90, 10), (120, 0)],
            "Retraso medio de cobro", lambda value: f"{value:.0f} días",
        ),
    ])


def score_payables(row: pd.Series) -> tuple[float | None, list[MetricScore]]:
    return _average([
        _metric(
            row, "overdue_payables_to_purchases",
            [(0, 100), (0.05, 85), (0.15, 60), (0.30, 30), (0.50, 5), (1.0, 0)],
            "Pagos vencidos / compras 3m", lambda value: f"{value:.1%}",
        ),
        _metric(
            row, "average_payment_delay_6m",
            [(0, 100), (10, 88), (20, 68), (45, 35), (75, 10), (120, 0)],
            "Retraso medio de pago", lambda value: f"{value:.0f} días",
        ),
    ])


def score_debt(row: pd.Series) -> tuple[float | None, list[MetricScore]]:
    return _average([
        _metric(
            row, "debt_to_annual_inflows",
            [(0, 100), (0.20, 90), (0.50, 70), (1.0, 40), (1.5, 15), (2.0, 0)],
            "Deuda / entradas anuales", lambda value: f"{value:.2f}x",
        ),
        _metric(
            row, "debt_service_to_inflows_3m",
            [(0, 100), (0.05, 90), (0.15, 65), (0.30, 30), (0.50, 0)],
            "Servicio de deuda / entradas", lambda value: f"{value:.1%}",
        ),
        _metric(
            row, "credit_line_utilization",
            [(0, 100), (0.40, 90), (0.70, 60), (0.90, 25), (1.0, 0)],
            "Utilización de líneas", lambda value: f"{value:.1%}",
        ),
    ])


def score_concentration(row: pd.Series) -> tuple[float | None, list[MetricScore]]:
    return _average([
        _metric(
            row, "top1_customer_share",
            [(0.10, 100), (0.25, 85), (0.40, 60), (0.60, 25), (0.80, 0)],
            "Peso del principal cliente", lambda value: f"{value:.1%}",
        ),
        _metric(
            row, "customer_hhi",
            [(0.05, 100), (0.15, 85), (0.25, 60), (0.40, 30), (0.70, 0)],
            "Concentración HHI de clientes", lambda value: f"{value:.3f}",
        ),
    ])


BLOCK_FUNCTIONS = {
    "liquidity": score_liquidity,
    "trajectory": score_trajectory,
    "receivables": score_receivables,
    "payables": score_payables,
    "debt": score_debt,
    "concentration": score_concentration,
}


def score_record(
    row: pd.Series,
    weights: dict[str, float] | None = None,
) -> tuple[float | None, dict[str, dict[str, object]]]:
    weights = weights or cfg.BLOCK_WEIGHTS
    results: dict[str, tuple[float | None, list[MetricScore]]] = {
        name: function(row) for name, function in BLOCK_FUNCTIONS.items()
    }
    active = {name: result for name, result in results.items() if result[0] is not None}
    covered_weight = sum(weights[name] for name in active)
    if len(active) < 2 or covered_weight <= 0:
        return None, {
            name: {
                "applicable": result[0] is not None,
                "score": result[0],
                "effective_weight": 0.0,
                "metrics": [metric.__dict__ for metric in result[1]],
            }
            for name, result in results.items()
        }
    final = sum(weights[name] * float(result[0]) for name, result in active.items()) / covered_weight
    detail = {
        name: {
            "applicable": result[0] is not None,
            "score": round(float(result[0]), 2) if result[0] is not None else None,
            "effective_weight": round(weights[name] / covered_weight, 4) if name in active else 0.0,
            "metrics": [metric.__dict__ for metric in result[1]],
        }
        for name, result in results.items()
    }
    return round(float(np.clip(final, 0, 100)), 2), detail


def _alerts(row: pd.Series) -> list[str]:
    alerts = []
    if _value(row, "runway_months") is not None and float(row["runway_months"]) < 3:
        alerts.append(f"Runway inferior a 3 meses ({row['runway_months']:.1f})")
    if _value(row, "persistent_deterioration_flag") == 1:
        alerts.append("Deterioro persistente del flujo de caja")
    if (_value(row, "overdue_payables_to_purchases") or 0) > 0.30:
        alerts.append("Pagos vencidos superiores al 30% de las compras trimestrales")
    if (_value(row, "overdue_receivables_to_sales") or 0) > 0.50:
        alerts.append("Cartera vencida superior al 50% de las ventas trimestrales")
    if (_value(row, "top1_customer_share") or 0) > 0.50:
        alerts.append("Más del 50% de la facturación depende de un único cliente")
    return alerts


def _classification(score: float | None, confidence: str) -> str:
    if score is None:
        return "NO EVALUABLE"
    if confidence == "low":
        return "NO CONCLUYENTE"
    return cfg.classify(score)


def _monthly_trajectory_scores() -> pd.DataFrame:
    panel = pd.read_csv(cfg.PANEL_PATH)
    components = []
    for name, points in [
        ("net_cashflow_margin_3m", [(-0.30, 0), (-0.10, 30), (0, 60), (0.10, 85), (0.20, 100)]),
        ("overdue_receivables_ratio_3m", [(0, 100), (0.10, 85), (0.25, 60), (0.50, 25), (1, 0)]),
        ("overdue_payables_ratio_3m", [(0, 100), (0.05, 85), (0.15, 60), (0.30, 30), (0.50, 5), (1, 0)]),
    ]:
        components.append(panel[name].map(
            lambda value: _curve(None if pd.isna(value) else float(value), points)
        ))
    panel["trajectory_score"] = pd.concat(components, axis=1).mean(axis=1, skipna=True)
    panel.loc[pd.concat(components, axis=1).notna().sum(axis=1) < 1, "trajectory_score"] = np.nan
    return panel[["company_id", "year_month", "trajectory_score"]]


def run() -> pd.DataFrame:
    cfg.ensure_dirs()
    score_input = pd.read_csv(cfg.SCORE_INPUT_PATH)
    rows = []
    explanations: dict[str, object] = {}
    for _, row in score_input.iterrows():
        score, detail = score_record(row)
        company_id = str(row["company_id"])
        classification = _classification(score, str(row["confidence"]))
        rows.append({
            "company_id": company_id,
            "score_final": score,
            "classification": classification,
            "confidence": row["confidence"],
            "metric_coverage": row["metric_coverage"],
            "as_of_date": row["as_of_date"],
        })
        explanations[company_id] = {
            "as_of_date": row["as_of_date"],
            "score_final": score,
            "classification": classification,
            "confidence": row["confidence"],
            "metric_coverage": row["metric_coverage"],
            "blocks": detail,
            "alerts": _alerts(row),
        }

    scores = pd.DataFrame(rows).sort_values("score_final", ascending=False, na_position="last")
    scores.to_csv(cfg.SCORES_PATH, index=False)
    monthly = _monthly_trajectory_scores()
    monthly.to_csv(cfg.SCORES_MENSUAL_PATH, index=False)
    write_json(cfg.EXPLAIN_PATH, explanations)
    print(scores["classification"].value_counts(dropna=False).to_string())
    print(f"Scores: {cfg.SCORES_PATH}")
    return scores


if __name__ == "__main__":
    run()
