# Alternative health score (mateo_dev)

Pipeline **experimental** y paralelo al scoring de `data_analysis/` (y al de otras ramas como `mateo_demo` / `src/`).

No sustituye el motor del equipo: es otra forma de construir el health score para comparar enfoques.

## En qué se diferencia

| | `data_analysis/` (rama principal de features) | Esta alternativa |
|---|---|---|
| Agregados | Features del panel maestro + reglas expertas | 12 métricas escala-libre + 5 pilares |
| Facturas | Esquema flexible / dirección por candidatos | Dirección por contraparte + fallback por signo |
| Score | Pesos en `config.py` + EMA | Anclajes calibrados en subconjunto “oro”, topes, nivel + momento |
| Salidas | `data/features/scores_*.csv` | `data/panel_metricas.csv`, `panel_notas.csv`, `scores_*.csv` |

## Cómo se ejecuta

Desde la raíz del repo (necesita los CSV en `data/`):

```bash
py alt_healthscore/build_panel.py
py alt_healthscore/calibrate_anchors.py
py alt_healthscore/build_score.py COMP_0691
```

Orden obligatorio: panel → anclajes/notas → score.

## Archivos

- `build_panel.py` — panel empresa × mes con las 12 métricas
- `calibrate_anchors.py` — anclajes 0–100 sobre subconjunto oro + notas
- `build_score.py` — pilares, pesos, topes, nivel/momento, ficha por empresa
- `anclajes.json` — se genera al calibrar (congelado para reproducibilidad)

Los CSV de salida viven en `data/` (ignorados por git).
