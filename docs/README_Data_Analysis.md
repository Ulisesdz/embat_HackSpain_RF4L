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

En el repo (y en Vercel) solo viajan `scores_finales.csv`, `scores_mensuales.csv` y `score_explanations.json`. El resto se genera en local al correr `python -m src.run`.

| Artefacto | Grano | ¿Viaja? |
|---|---|---|
| `master_panel.csv` | 1.286 empresas × 25 meses = 32.150 filas. Diccionario: [`FEATURES.md`](FEATURES.md) | no |
| `scores_mensuales.csv` | empresa × mes. NaN si peso cubierto < 55% | sí |
| `scores_finales.csv` | 1 fila por empresa | sí |
| `scores_grupo.csv` | 249 grupos | no |
| `score_explanations.json` | el “por qué” del último mes evaluable | sí |
| `anticipation_report.csv` | empresa × evento × señal | no |
| `alerts.csv` | avisos (no dispara si ya estaba en zona la primera vez) | no |
| `model/*.json` | percentiles y prior congelados | sí |

Motor: [`SCORE_ENGINE.md`](SCORE_ENGINE.md). Moneda y suciedad: [`LIMPIEZA.md`](LIMPIEZA.md).
