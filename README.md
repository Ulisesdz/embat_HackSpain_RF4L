# HackSpain 2026 · X-Ray — Reto de Embat

Score de salud financiera sobre 1.286 empresas y 25 meses. Lee banco, facturas,
pagos y deuda, y responde las seis preguntas del reto **empresa a empresa y mes
a mes**, con explicación y sin caja negra.

```
src/          código (paquete Python)
data/         CSV crudos + salidas en data/features/
model/        percentiles y prior congelados (viajan con el sistema)
dashboard/    demo navegable (un HTML)
docs/         diccionario, motor, limpieza, teoría del agente
```

---

## Por dónde empezar

| Si quieres saber... | Lee |
|---|---|
| Qué se entrega y qué pinta el producto | [`ENTREGA_PRODUCTO.md`](ENTREGA_PRODUCTO.md) |
| Cómo se calcula el score | [`docs/SCORE_ENGINE.md`](docs/SCORE_ENGINE.md) |
| Qué es cada variable del panel | [`docs/FEATURES.md`](docs/FEATURES.md) |
| Pipeline y artefactos | [`docs/README_Data_Analysis.md`](docs/README_Data_Analysis.md) |
| Limpieza, fechas rotas y moneda | [`docs/LIMPIEZA.md`](docs/LIMPIEZA.md) |

---

## Las seis preguntas

| Pregunta | Campo | Resultado (última corrida) |
|---|---|---|
| **Quién está sano** | `clasificacion` | 229 SALUDABLE · 538 ESTABLE · 315 EN RIESGO · 132 FRÁGIL · 66 CRÍTICO · 6 NO EVALUABLE |
| **Quién está mejorando** | `tendencia` | 262 MEJORANDO · 398 DETERIORANDO · 611 ESTABLE |
| **Quién empieza a torcerse** | `senal_giro` + `score_final` ≥ 55 | **420 llamadas** (417 tuvieron el giro aún sanas ese mes) |
| **Bache o caída** | `naturaleza_caida` | Bache +4,69 pts a 6 meses (52% recupera); caída estructural −1,66 (33% sigue cayendo) |
| **Por qué ha cambiado** | `motivo_cambio`, `aporte_*` | 17.744 filas-mes; solo el 5,5% lo mueve un dato nuevo, no el comportamiento |
| **Cuándo se vio venir** | `meses_anticipacion` | Cola vs nivel: +2 meses en asfixia (56 eventos solo ella), +1 en impago |

El dashboard (`dashboard/index.html`) pinta las seis: mapa nivel × dirección,
lista de giros aún sanos, y en cada ficha la curva con la dirección reciente.
No es predicción de quiebra.

---

## Cómo se ejecuta

```bash
pip install -r requirements.txt
python -m src.run
python -m src.brief_server
```

`src.run` hace features → validador → score → anticipación → monitor → dashboard.
La interfaz se abre en http://127.0.0.1:8765/ (o el puerto que imprima).

- **Plan de acciones** — ficha + RAG + catálogo, sin red.
- **Agente + LLM** — redacta con Gemini. Pega la key de
  [aistudio.google.com](https://aistudio.google.com) en la cabecera
  (`AIza…` o `AQ.…`). Modelo `gemini-3-flash-preview` (`google-genai`).

`evaluate_anticipation` va **después** del motor: mira al futuro de cada mes.
Si viviera dentro, el archivo del score dejaría de ser causal.

No hay ML: el dataset no trae etiqueta de quiebra. El motor es reglas medidas
(AUC / lift sobre eventos de severidad) más Theil-Sen, percentiles y contracción
hacia el prior. Cada número se puede explicar.

---

## Los seis ejes

| Eje | Peso | Qué pregunta | Si falta el dato |
|---|---|---|---|
| Deuda comercial | 20% | ¿Paga a proveedores? (mejor predictor, AUC 0,83) | Se apaga. Nunca un 50 |
| Liquidez | 18% | Flujo / tamaño, media 3 meses | Se apaga |
| Colchón | 18% | Meses de gasto cubiertos por el flujo 6m; runway solo si hay foto de caja | Se apaga |
| Trayectoria | 18% | ¿Va a mejor o a peor? Pesa por producto (AUC 0,49 sobre eventos) | Se apaga |
| Eficiencia | 14% | Gasto / ingreso. 1,0 = equilibrio. Topado a 8× | Se apaga |
| Cobro | 12% | ¿Le pagan a ella? Contagio, no decisión propia | Se apaga |

Pesos medidos en `screen_signals.py`. Si cubren menos del 55% del peso, el mes
es `NaN` (NO EVALUABLE).

### Cómo se lee una ficha

1. **`score_final`** (0–100) — media exponencial de 25 meses, contraída al prior
   **54,41** si hay poca evidencia. Media de cartera 55,4. Umbrales:
   SALUDABLE ≥68, ESTABLE ≥52, EN RIESGO ≥42, FRÁGIL ≥33, CRÍTICO <33.
2. **`tendencia`** — dirección. Un 48 MEJORANDO puede ser mejor apuesta que un 62
   DETERIORANDO. No sale del score compuesto: sale del eje trayectoria.
3. **`confianza` / `apto_ranking`** — 47,9% de filas-mes son confianza baja
   (primeros meses + facturas huecas). 1.169 empresas son aptas para ranking.
4. **`motivo_cambio_ultimo_mes`** — qué eje empujó. Si va vacío, el giro fue
   antes: se usa el texto de `naturaleza_caida`.
5. **Grupo** — vista, no segundo cálculo. 74 de 249 grupos (29,7%) esconden una
   filial en riesgo; 85 (34,1%) tienen tendencias opuestas dentro.

No mezclar recuentos: **1.111** es alerta de nivel o cola (recall); **624** es
giro alguna vez; **420** es la lista de llamadas (giro y `score_final` ≥ 55).

### COMP_0009 (el ejemplo del log)

- 2026-03: `burn_rate` = **8,0** (antes 179×; un mes así no puede mandar).
- `runway_meses` solo en 2026-08: la foto de caja no se copia al pasado.
- NaN en morosidad 2024-09→2025-06 = **sin evidencia**, no “paga bien”.
- Score **60,13 ESTABLE**, giro *bache* 1,33σ desde 2025-03.

---

## Moneda

No se fuerza todo a EUR. En transacciones el `exchange_rate` es 1 en el 64% de
las cuentas no-EUR: multiplicar inventa euros. El score compara **ratios**
(flujo/ingresos, burn, morosidad). Las facturas sí se llevan a
`accounting_currency` cuando el tipo está en `[0,001, 2500]`. Detalle en
`docs/LIMPIEZA.md`.

---

## Entrega del reto

| Qué pide el track | Dónde está |
|---|---|
| Puntuar empresas nunca vistas | `model/pctl_reference.json` + `prior_contraccion.json` |
| Señal en las dos direcciones | `tendencia` MEJORANDO / DETERIORANDO |
| Trayectoria, no foto | Media exponencial 25 meses + eje trayectoria 18% |
| Explicación | `score_explanations.json`, `motivo_cambio_*` |
| Producto encima del score | Lista de llamadas + monitor + plan / agente |
| Demo navegable | `dashboard/index.html` vía `python -m src.brief_server` |
| Anticipación medida | `anticipation_report.csv` |
| Monitor que avisa | `data/features/alerts.csv` |

`model/` viaja con el sistema. Borrarlo recalibra en silencio. `data/` está en
`.gitignore`: son el dataset y las salidas regenerables.
