"""Chequeo mínimo del score: python3 src/test_pipeline.py (requiere data/clean/ generado con src/score.py)."""
import sys
sys.argv = ["x"]
import numpy as np
import pandas as pd
import score as S

assert abs(S.W.sum() - 1) < 1e-9 and (S.W >= 0).all(), "los pesos deben sumar 1"
sc = pd.read_parquet("data/clean/scores.parquet")
assert sc.score.dropna().between(0, 100).all(), "score fuera de 0-100"
panel = pd.read_parquet("data/clean/panel.parquet")
assert len(sc) == int(panel.observed.sum()), "solo se puntúan meses observados"
assert sc.exp_change3.notna().any(), "falta la tendencia predictiva (data/clean/trend_report.json)"

# monotonía: mismo panel con menos caja no puede subir el score
cid = sc.dropna(subset=["score"]).company_id.iloc[0]
p = panel[panel.company_id == cid].copy()
worse = p.assign(cash_end=p.cash_end - 10 * p.outflow.mean())
a, b = S.score_all(p).score.dropna(), S.score_all(worse).score.dropna()
assert (b.values <= a.values + 1e-9).all() and (b.values < a.values).any(), "menos caja debe bajar el score"

# referencia congelada: puntuar una empresa sola da lo mismo que dentro del lote (no depende de las demás)
one = S.score_all(p).set_index("month").score.dropna()
full = sc[sc.company_id == cid].set_index("month").score
assert np.allclose(one, full.reindex(one.index), atol=1e-6), "el score no debe depender del lote"

assert cid in S.explain(sc, cid)
print("ok")
