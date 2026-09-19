"""Fail-fast validation for monthly features, score input and score output."""

from __future__ import annotations

import json

import numpy as np
import pandas as pd

import data_analysis.config as cfg
from data_analysis.score_engine import score_record


class Validation:
    def __init__(self) -> None:
        self.errors: list[str] = []
        self.warnings: list[str] = []

    def check(self, condition: bool, message: str) -> None:
        if condition:
            print(f"[ OK ] {message}")
        else:
            self.errors.append(message)
            print(f"[FAIL] {message}")

    def warn(self, condition: bool, message: str) -> None:
        if not condition:
            self.warnings.append(message)
            print(f"[WARN] {message}")


def _score_with_weights(frame: pd.DataFrame, weights: dict[str, float]) -> pd.Series:
    return frame.apply(lambda row: score_record(row, weights)[0], axis=1)


def main() -> None:
    validation = Validation()
    required = [cfg.PANEL_PATH, cfg.SCORE_INPUT_PATH, cfg.SCORES_PATH, cfg.AUDIT_PATH]
    validation.check(all(path.exists() for path in required), "Existen todas las salidas requeridas")
    if validation.errors:
        raise SystemExit(1)

    panel = pd.read_csv(cfg.PANEL_PATH)
    score_input = pd.read_csv(cfg.SCORE_INPUT_PATH)
    scores = pd.read_csv(cfg.SCORES_PATH)
    audit = json.loads(cfg.AUDIT_PATH.read_text(encoding="utf-8"))
    panel["year_month"] = pd.PeriodIndex(panel["year_month"], freq="M")

    validation.check(
        not panel.duplicated(["company_id", "year_month"]).any(),
        "No hay duplicados company_id + year_month",
    )
    counts = panel.groupby("company_id")["year_month"].nunique()
    validation.check(
        counts.min() == len(cfg.MONTHS) and counts.max() == len(cfg.MONTHS),
        f"Cada empresa tiene exactamente {len(cfg.MONTHS)} meses completos",
    )
    validation.check(
        set(panel["year_month"].unique()) == set(cfg.MONTHS),
        "El calendario mensual coincide con la ventana configurada",
    )
    validation.check(
        np.allclose(
            panel["cash_inflow"] - panel["cash_outflow"],
            panel["net_cashflow"],
            equal_nan=True,
        ),
        "Se cumple cash_inflow - cash_outflow = net_cashflow",
    )
    validation.check(
        not np.isinf(panel.select_dtypes(include=[np.number])).any().any(),
        "El panel no contiene infinitos",
    )

    for ratio in ["overdue_receivables_ratio_3m", "overdue_payables_ratio_3m"]:
        values = panel[ratio].dropna()
        validation.check(
            bool(((values >= 0) & (values <= 1 + 1e-9)).all()),
            f"{ratio} permanece en [0,1]",
        )
    debt_service = panel["debt_service_to_inflows_3m"].dropna()
    validation.check(
        bool((debt_service >= 0).all()),
        "debt_service_to_inflows_3m no contiene valores negativos",
    )

    validation.check(
        score_input["company_id"].is_unique,
        "score_input_v1 contiene una fila por empresa",
    )
    validation.check(
        set(score_input["as_of_date"].astype(str)) == {cfg.AS_OF_DATE.date().isoformat()},
        "Todas las filas usan la fecha de corte configurada",
    )
    validation.check(
        set(score_input["feature_version"]) == {"v1"},
        "El contrato declara feature_version=v1",
    )
    validation.check(
        score_input.loc[
            score_input["invoice_source_available"].eq(0),
            "overdue_receivables_to_sales",
        ].isna().all(),
        "Sin fuente de facturas no se inventa una ratio de cobro",
    )
    validation.check(
        score_input.loc[
            score_input["balance_source_available"].eq(0), "runway_months"
        ].isna().all(),
        "Sin snapshot de balance no se inventa runway",
    )
    validation.check(
        score_input["cash_balance"].abs().dropna().lt(cfg.BALANCE_ABS_HARD_LIMIT).all(),
        "Los balances extremos no alcanzan el input del score",
    )

    # Current-only snapshots must not be present in the historical panel.
    forbidden_history = {"cash_balance", "runway_months", "debt_outstanding"}
    validation.check(
        forbidden_history.isdisjoint(panel.columns),
        "Los snapshots actuales no se propagan al histórico",
    )
    validation.check(
        audit.get("invoices:open_rows_with_populated_payment_date_ignored", 0) > 0,
        "Las fechas engañosas de facturas abiertas se detectan y se ignoran",
    )

    score_values = scores["score_final"].dropna()
    validation.check(
        bool(((score_values >= 0) & (score_values <= 100)).all()),
        "Todos los scores están en [0,100]",
    )
    validation.check(
        scores.loc[scores["confidence"].eq("low"), "classification"]
        .isin({"NO CONCLUYENTE", "NO EVALUABLE"})
        .all(),
        "Un score de confianza baja nunca se presenta como conclusión financiera",
    )
    validation.warn(
        score_values.nunique() >= 20,
        "La distribución del score tiene menos de 20 valores distintos",
    )
    validation.warn(
        score_values.std() >= 5,
        "La desviación del score es inferior a 5 puntos; revisar discriminación",
    )

    # Sensitivity: perturb every block weight by +/-10%, renormalise and ensure
    # the median company does not move dramatically.
    baseline = _score_with_weights(score_input, cfg.BLOCK_WEIGHTS)
    sensitivity_deltas = []
    for block in cfg.BLOCK_WEIGHTS:
        for factor in (0.9, 1.1):
            weights = cfg.BLOCK_WEIGHTS.copy()
            weights[block] *= factor
            total = sum(weights.values())
            weights = {name: value / total for name, value in weights.items()}
            perturbed = _score_with_weights(score_input, weights)
            sensitivity_deltas.append((perturbed - baseline).abs())
    max_delta = pd.concat(sensitivity_deltas, axis=1).max(axis=1)
    validation.warn(
        float(max_delta.median()) <= 3,
        f"Sensibilidad mediana elevada ({max_delta.median():.2f} puntos)",
    )
    validation.warn(
        float(max_delta.quantile(0.95)) <= 8,
        f"Sensibilidad p95 elevada ({max_delta.quantile(0.95):.2f} puntos)",
    )

    print("\nSUMMARY")
    print(f"Companies: {score_input['company_id'].nunique():,}")
    print(f"Panel rows: {len(panel):,}")
    print(f"Errors: {len(validation.errors)}")
    print(f"Warnings: {len(validation.warnings)}")
    if validation.errors:
        raise SystemExit(1)
    print("VALIDATION OK")


if __name__ == "__main__":
    main()
