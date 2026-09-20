# Qué se entrega

Health Score de tesorería, explicable, sobre 1.286 empresas.

**Demo:** [https://embat-hack-spain-rf-4-l.vercel.app/](https://embat-hack-spain-rf-4-l.vercel.app/)

En local: `pip install -r requirements.txt` y `python -m src.brief_server` → http://127.0.0.1:8775/

## Dónde está cada cosa del reto

| Lo que pide el track | Dónde |
|---|---|
| Puntuar empresas nunca vistas | `model/pctl_reference.json` + `model/prior_contraccion.json` |
| Señal en las dos direcciones | `tendencia` MEJORANDO / DETERIORANDO (eje Trayectoria) |
| Trayectoria, no foto | Media exponencial + eje 18% |
| Explicación | `score_explanations.json` y los seis ejes en la ficha |
| Quién se tuerce estando sana | Giro en la ficha (bache vs caída estructural) |
| Demo | [Vercel](https://embat-hack-spain-rf-4-l.vercel.app/) · `dashboard/` |
| Agente | Catálogo + RAG. Gemini solo redacta |

## Scores que viajan en el repo

| Archivo | Grano |
|---|---|
| `data/features/scores_finales.csv` | 1 fila por empresa |
| `data/features/scores_mensuales.csv` | empresa × mes (curva) |
| `data/features/score_explanations.json` | el “por qué” de cada ficha |

El crudo no viaja. Cómo se calcula: [`docs/SCORE_ENGINE.md`](docs/SCORE_ENGINE.md). Cómo se usa: [`README.md`](README.md).
