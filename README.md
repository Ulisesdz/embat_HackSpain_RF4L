# HackSpain 2026 · Health Score (Embat / X-Ray)

Nota de tesorería **0–100** sobre 1.286 empresas y 25 meses. Lee banco, facturas, pagos y deuda. No es un modelo opaco ni una predicción de quiebra: cada mes mira seis cosas de caja, las mezcla con un peso fijo y junta la historia.

```
src/          motor, pipeline, servidor y agente
src/features/client_health_score/   UI (frontend + adaptador de API)
model/        percentiles y prior congelados
dashboard/    copia de la UI para Vercel
docs/         motor, diccionario, limpieza, corpus del agente
```

---

## Arrancar la demo

Python **3.10+**.

```bash
pip install -r requirements.txt
python -m src.brief_server
```

Abre **http://127.0.0.1:8775/** (si está ocupado, el servidor prueba hasta 8784).

La ficha carga el score real (`/api/health-score`). El selector cambia de empresa.
**Cómo se calcula** es la receta de los seis ejes. **Generar con IA** pide a Gemini
un párrafo con esas señales; pega una key de [aistudio.google.com](https://aistudio.google.com)
o deja `GEMINI_API_KEY` en el entorno. Sin key, el diagnóstico numérico sigue ahí.

Si tocas el TypeScript: `cd src/features/client_health_score/frontend && npm install && npm run build`
y luego `python -m src.build_dashboard` (copia la UI a `dashboard/`).

Publicar: [`docs/DEPLOY.md`](docs/DEPLOY.md).

---

## Cómo se llega al score

No es ML. El dataset no trae etiqueta de quiebra.

1. **El mes.** Cada eje saca una nota 0–100. Se mezclan: Deuda 20 + Liquidez 18 + Colchón 18 + Trayectoria 18 + Eficiencia 14 + Cobro 12. Si falta la fuente, **ese eje se apaga**. Nunca se imputa un 50.
2. **La historia.** Media exponencial de los meses. Semivida 6: un pico no manda.
3. **Si hay poco dato.** La nota se acerca al prior **54,41**. Un único mes bueno no te convierte en SALUDABLE.

Cortes fijos (no un ranking contra las demás):

**SALUDABLE ≥ 68 · ESTABLE ≥ 52 · EN RIESGO ≥ 42 · FRÁGIL ≥ 33 · si no, CRÍTICO**

Tres etiquetas en la ficha, y no son lo mismo:

| Etiqueta | Qué es | Cuidado |
|---|---|---|
| **Nivel** | El Health Score. ¿Está sana hoy? | — |
| **Dirección** | Media de 3 meses del eje Trayectoria. >58 MEJORANDO, <42 DETERIORANDO | No es el cambio del 76. Por eso puede poner **SALUDABLE + DETERIORANDO** |
| **Giro** | Se torció contra su propia historia | **Bache** = suele rebotar. **Caída** = se sostiene |

Detalle técnico: [`docs/SCORE_ENGINE.md`](docs/SCORE_ENGINE.md). En la UI: **Cómo se calcula**.

---

## Las seis métricas

| Eje | Peso | Pregunta | Qué mira |
|---|---|---|---|
| Deuda comercial | 20% | ¿Pagáis a los proveedores? | Impagos 3m; si no, deuda / ingresos. Es decisión propia |
| Liquidez | 18% | ¿El negocio genera caja? | Flujo / tamaño (ingresos 12m), sobre todo el trimestre |
| Colchón | 18% | ¿Cuántos meses de aire hay? | Flujo de 6m / gasto. El saldo de caja solo si existe de verdad |
| Trayectoria | 18% | ¿Va a mejor o a peor? | Pendiente del flujo, deuda a proveedores, ingresos, persistencia |
| Eficiencia | 14% | ¿Se come el gasto la caja? | Burn 3m. 1,0 = equilibrio |
| Cobro | 12% | ¿Os pagan a vosotros? | Facturas vencidas y devoluciones 3m. Pesa menos: decide el cliente |

---

## Qué responde (última corrida)

| Pregunta | Campo | Resultado |
|---|---|---|
| Quién está sano | `clasificacion` | 229 SALUDABLE · 538 ESTABLE · 315 EN RIESGO · 132 FRÁGIL · 66 CRÍTICO · 6 sin evidencia |
| Quién está mejorando | `tendencia` | 262 MEJORANDO · 398 DETERIORANDO · 611 ESTABLE |
| Quién empieza a torcerse | giro + score ≥ 55 | **420 llamadas** (aún parecían sanas ese mes) |
| Bache o caída | `naturaleza_caida` | Bache: +4,7 pts a 6 meses (más de la mitad recupera). Caída: −1,7 |
| Por qué ha cambiado | `motivo_cambio`, `aporte_*` | Comportamiento vs dato nuevo, eje a eje |
| Cuándo se vio venir | `meses_anticipacion` | Cola vs nivel: +2 meses en asfixia, +1 en impago |

No mezclar recuentos: **1.111** es alerta de nivel o cola; **624** tuvieron giro alguna vez; **420** es la lista de llamadas.

El grupo es **vista**, no segundo cálculo. 74 de 249 holdings esconden una filial en riesgo.

---

## Regenerar (opcional)

Hace falta el dataset crudo en `data/` (sigue fuera de git).
`scores_finales.csv`, `scores_mensuales.csv` y `score_explanations.json` sí
viajan: con ellos `python -m src.brief_server` funciona sin el RAW.

```bash
python -m src.run
```

Orden: features → validador → score → anticipación → monitor → dashboard.

`evaluate_anticipation` va **después** del motor: mira al futuro. Si viviera dentro, el archivo del score dejaría de ser causal.

`model/` no se borra. Borrarlo recalibra percentiles y prior en silencio.

---

## Documentación

| Documento | Contenido |
|---|---|
| [`ENTREGA_PRODUCTO.md`](ENTREGA_PRODUCTO.md) | Qué se entrega y dónde está |
| [`docs/SCORE_ENGINE.md`](docs/SCORE_ENGINE.md) | Receta, cascadas, giro, anticipación |
| [`docs/FEATURES.md`](docs/FEATURES.md) | Diccionario del panel (69 columnas) |
| [`docs/LIMPIEZA.md`](docs/LIMPIEZA.md) | Fechas rotas, moneda, lo que no se imputa |
| [`docs/TEORIA_PYME.md`](docs/TEORIA_PYME.md) | Corpus del agente: tesorería + qué puede hacer Embat. No es el manual |

---