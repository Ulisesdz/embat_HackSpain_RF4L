# HackSpain 2026 · Health Score (Embat / X-Ray)

Nota de tesorería **0–100** sobre 1.286 empresas. Lee banco, facturas, pagos y deuda. No predice quiebra y no es un modelo opaco.

**Demo:** [https://embat-hack-spain-rf-4-l.vercel.app/](https://embat-hack-spain-rf-4-l.vercel.app/)

---

## Cómo usarlo

### En el navegador

Abre la demo. Selector de empresa arriba. **Este resultado** es la ficha. **Cómo se calcula** es la receta. **Generar con IA** pide una key de [Google AI Studio](https://aistudio.google.com); sin ella el score se ve igual.

### En local

Python **3.10+**. No hace falta el dataset crudo: los scores ya van en el repo.

```bash
pip install -r requirements.txt
python -m src.brief_server
```

Abre **http://127.0.0.1:8775/** (si está ocupado, el servidor prueba hasta 8784).

---

## Cómo se calcula

No es ML. El dataset no trae etiqueta de quiebra.

1. **El mes.** Cada eje saca una nota 0–100. Se mezclan con peso fijo. Si falta la fuente, **ese eje se apaga**. Nunca se imputa un 50.
2. **La historia.** Media exponencial de los meses (semivida 6). Un pico no manda.
3. **Si hay poco dato.** La nota se acerca al prior **54**. Un único mes bueno no te convierte en SALUDABLE.

| Eje | Peso | Pregunta |
|---|---|---|
| Deuda comercial | 20% | ¿Pagáis a los proveedores? |
| Liquidez | 18% | ¿El negocio genera caja? |
| Colchón | 18% | ¿Cuántos meses de aire hay? |
| Trayectoria | 18% | ¿Va a mejor o a peor? |
| Eficiencia | 14% | ¿Se come el gasto la caja? |
| Cobro | 12% | ¿Os pagan a vosotros? |

**SALUDABLE ≥ 68 · ESTABLE ≥ 52 · EN RIESGO ≥ 42 · FRÁGIL ≥ 33 · si no, CRÍTICO**

Tres lecturas distintas en la ficha:

| Etiqueta | Qué es | Cuidado |
|---|---|---|
| **Nivel** | El Health Score. ¿Está sana hoy? | — |
| **Dirección** | Media de 3 meses del eje Trayectoria | No es el cambio del 76. Por eso puede poner **SALUDABLE + DETERIORANDO** |
| **Giro** | Se torció contra su propia historia | **Bache** suele rebotar. **Caída estructural** se sostiene |

El Δ del mes (p. ej. −4,8) es otra cosa: qué ejes han movido el compuesto. El agente **no recalcula**. Lee la ficha y un catálogo; Gemini solo redacta.

Detalle: [`docs/SCORE_ENGINE.md`](docs/SCORE_ENGINE.md).

---

## Repo

```
frontend/       UI (TypeScript + bundle)
dashboard/      la misma UI ya empaquetada; es lo que publica Vercel
src/            motor, servidor, agente y API de la ficha
api/            funciones de Vercel (leen los scores, no los recalculan)
data/features/  scores_finales, scores_mensuales, explanations
model/          percentiles y prior congelados
docs/           motor, diccionario, limpieza, corpus del agente
```

`dashboard/` no es otro producto: es la copia que publica Vercel. El TypeScript de `frontend/src/` se empaqueta en `frontend/assets/app.js`. El dataset crudo no viaja.

Regenerar el motor (opcional, hace falta el RAW en `data/`): `python -m src.run`. No borres `model/`.

| Documento | Para qué |
|---|---|
| [`ENTREGA_PRODUCTO.md`](ENTREGA_PRODUCTO.md) | Qué cubre del reto |
| [`docs/SCORE_ENGINE.md`](docs/SCORE_ENGINE.md) | Receta, cascadas, giro |
| [`docs/FEATURES.md`](docs/FEATURES.md) | Diccionario del panel |
| [`docs/LIMPIEZA.md`](docs/LIMPIEZA.md) | Fechas, moneda, lo que no se imputa |
| [`docs/TEORIA_PYME.md`](docs/TEORIA_PYME.md) | Corpus del agente (no es el manual) |
| [`docs/DEPLOY.md`](docs/DEPLOY.md) | Cómo está publicado en Vercel |
