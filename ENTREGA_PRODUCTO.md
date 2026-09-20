# Qué se entrega

Producto encima de un score de tesorería explicable. El comprador es Embat; quien firma es riesgo / tesorería del cliente.

## Cómo se ve

```bash
pip install -r requirements.txt
python -m src.brief_server
```

http://127.0.0.1:8775/ — pestaña **Métricas** para la receta; **Ficha** para señalar los seis ejes.

## Dónde está cada cosa del reto

| Lo que pide el track | Dónde |
|---|---|
| Puntuar empresas nunca vistas | `model/pctl_reference.json` + `model/prior_contraccion.json` |
| Señal en las dos direcciones | `tendencia` MEJORANDO / DETERIORANDO (eje Trayectoria, no el Δ del 76) |
| Trayectoria, no foto | Media exponencial 25 meses + eje 18% |
| Explicación | `score_explanations.json`, `motivo_cambio_*`, seis ejes en la ficha |
| Lista accionable | 420 llamadas (giro estando sana) + bache vs caída |
| Anticipación medida | `anticipation_report.csv` |
| Monitor | `data/features/alerts.csv` · pestaña Avisos |
| Demo | `dashboard/index.html` |
| Agente | Plan local (catálogo + RAG). Gemini solo redacta |

## Salidas del motor

Viven en `data/features/` (regenerables; el dataset crudo no viaja en el repo).

| Archivo | Grano |
|---|---|
| `scores_finales.csv` | 1 fila por empresa |
| `scores_mensuales.csv` | empresa × mes |
| `scores_grupo.csv` | 249 grupos |
| `score_explanations.json` | el “por qué” de cada ficha |
| `anticipation_report.csv` | empresa × evento |
| `alerts.csv` | avisos del monitor |

Cómo se calcula: [`docs/SCORE_ENGINE.md`](docs/SCORE_ENGINE.md). Cómo se lee: [`README.md`](README.md).
