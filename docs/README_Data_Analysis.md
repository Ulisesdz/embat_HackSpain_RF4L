# Pipeline

Cómo se construye el panel. Principio: `NaN` es “sin evidencia”; `0` es “medido y vale cero”. Los CSV crudos no se escriben.

```
src/config.py                 fechas, pesos, umbrales
src/build_features.py         master_panel.csv + auditoría + cleaning_log
src/validate_features.py      exit 1 si rompe una invariante
src/score_engine.py           scores + explanations
src/evaluate_anticipation.py  anticipation_report.csv  (después del motor)
src/monitor.py                alerts.csv
src/build_dashboard.py        dashboard/index.html
src/screen_signals.py         AUC / lift (calibración; no va en src.run)
src/explore_data.py           data_quality_report.txt (opcional)
```

```bash
pip install -r requirements.txt
python -m src.run
python -m src.brief_server    # http://127.0.0.1:8775/
```

Hace falta el dataset del reto en `data/`. Las salidas van a `data/features/`. La calibración (`model/`) no se toca.

| Artefacto | Grano |
|---|---|
| `master_panel.csv` | 1.286 empresas × 25 meses = 32.150 filas. Diccionario: [`FEATURES.md`](FEATURES.md) |
| `scores_mensuales.csv` | empresa × mes. NaN si peso cubierto < 55% |
| `scores_finales.csv` | 1 fila por empresa |
| `scores_grupo.csv` | 249 grupos |
| `score_explanations.json` | el “por qué” del último mes evaluable |
| `anticipation_report.csv` | empresa × evento × señal |
| `alerts.csv` | avisos (no dispara si ya estaba en zona la primera vez) |
| `model/*.json` | percentiles y prior congelados |

Motor: [`SCORE_ENGINE.md`](SCORE_ENGINE.md). Moneda y suciedad: [`LIMPIEZA.md`](LIMPIEZA.md).
