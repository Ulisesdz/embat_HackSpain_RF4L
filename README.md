# HackSpain 2026 · X-Ray — Reto de Embat

Score de salud financiera sobre 1.286 empresas y 25 meses. Lee banco, facturas,
pagos y deuda, y responde las seis preguntas del reto **empresa a empresa y mes
a mes**, con explicación y sin caja negra.

```
src/          código (paquete Python)
data/         CSV crudos + salidas en data/features/
model/        percentiles y prior congelados (viajan con el sistema)
dashboard/    demo navegable (un HTML, sin servidor)
docs/         diccionario, motor, limpieza
```

---

## Por dónde empezar

| Si quieres saber... | Lee |
|---|---|
| Qué se entrega y a quién se vende | [`ENTREGA_PRODUCTO.md`](ENTREGA_PRODUCTO.md) |
| Limpieza, fechas rotas y **moneda** | [`docs/LIMPIEZA.md`](docs/LIMPIEZA.md) |
| Cómo se calcula el score | [`docs/SCORE_ENGINE.md`](docs/SCORE_ENGINE.md) |
| Qué es cada variable | [`docs/FEATURES.md`](docs/FEATURES.md) |
| Pipeline y sesgos | [`docs/README_Data_Analysis.md`](docs/README_Data_Analysis.md) |

---

## Las seis preguntas

| Pregunta | Campo | Resultado (última corrida) |
|---|---|---|
| **Quién está sano** | `clasificacion` | 139 SALUDABLE · 510 ESTABLE · 349 EN RIESGO · 191 FRÁGIL · 91 CRÍTICO · 6 NO EVALUABLE |
| **Quién está mejorando** | `tendencia` | 262 MEJORANDO · 398 DETERIORANDO · 611 ESTABLE |
| **Quién empieza a torcerse** | `senal_giro` + `score_final` ≥ 55 | **337 llamadas** (351 tuvieron el giro aún sanas; 14 ya bajaron de 55) |
| **Bache o caída** | `naturaleza_caida` | Bache +4,81 pts a 6 meses (53% recupera); caída estructural −1,76 (34% sigue cayendo) |
| **Por qué ha cambiado** | `motivo_cambio`, `aporte_*` | 17.744 filas-mes; solo el 5,5% lo mueve un dato nuevo, no el comportamiento |
| **Cuándo se vio venir** | `meses_anticipacion` | Cola vs nivel: +2 meses en asfixia (22 eventos solo ella), +1 en impago |

El dashboard (`dashboard/index.html`) responde las **seis preguntas** del reto
con gráficas: mapa nivel × dirección, corrientes observadas, lista de giros
aún sanos, y en cada ficha una curva con la dirección reciente (no es
predicción de quiebra).

---

## Entrega del reto

| Qué pide el track | Dónde está | Estado |
|---|---|---|
| Puntuar empresas nunca vistas | `model/pctl_reference.json` + `prior_contraccion.json` | Obligatorio |
| Señal en las dos direcciones | `tendencia` MEJORANDO / DETERIORANDO + monitor | Obligatorio |
| Trayectoria, no foto | Media exponencial 25 meses + eje trayectoria 18% | Obligatorio |
| Explicación | `score_explanations.json`, `motivo_cambio_*` | Obligatorio |
| Producto encima del score | Lista de llamadas + monitor en `dashboard/index.html` | Obligatorio |
| Comprador | Embat (quien entrega los datos). Usuario: riesgo / tesorería | Obligatorio |
| Demo navegable | `dashboard/index.html` (doble clic) | Obligatorio |
| Anticipación medida | `anticipation_report.csv` | Bonus |
| Monitor que avisa | `data/features/alerts.csv` + pestaña Monitor | Bonus |

No hay ML: no existe etiqueta de quiebra. Entrenar contra una `y` nuestra
aprendería la heurística con ruido y perdería la explicación.

---

## Cómo se ejecuta

```bash
pip install -r requirements.txt
python -m src.run
```

Un solo comando: features → validador → score → anticipación → monitor → dashboard.
Si lanzas un paso suelto: `python -m src.validate_features` (el flag es `-m`, no `3-m`).

`evaluate_anticipation` va **después** del motor: mira al futuro de cada mes.
Si viviera dentro, el archivo del score dejaría de ser causal.

---

## Moneda

No se fuerza todo a EUR. En transacciones el `exchange_rate` es 1 en el 64% de
las cuentas no-EUR: multiplicar inventa euros. El score compara **ratios**
(flujo/ingresos, burn, morosidad). Las facturas sí se llevan a
`accounting_currency` cuando el tipo está en `[0,001, 2500]`. El razonamiento
completo está en `docs/LIMPIEZA.md` §2.

---

## Cómo se explica cada métrica

No mezclar estos cuatro recuentos. Miden cosas distintas:

| Número | Qué es | Qué no es |
|---|---|---|
| **1.122** alerta temprana | Capa de **nivel o cola** alguna vez activa. Recall alto (casi toda la cartera) | La lista de ventas. Avisar a 1.122 de 1.286 no prioriza |
| **550** giro detectado | La empresa se movió contra **su propia** volatilidad | Que hoy esté sana, ni que vaya a asfixiarse (lift 0,78 ahí) |
| **351** giro + score mensual ≥ 55 | Algún mes tuvo el giro y **ese mes** aún parecía sana | El radar de hoy: 14 de esas ya bajaron de 55 |
| **337** lista de llamadas | Giro + **`score_final` ≥ 55 ahora** | Lo que pinta el dashboard y lo que se vende |

El giro no predice asfixia ni impago. Predice “esta caída se sostiene”: el bache
rebota (+4,8 pts a 6 meses) y la caída estructural no (−1,8). Por eso van
separados de la capa de cola.

### Los seis ejes (qué leerle a un cliente)

| Eje | Peso | En cristiano | Si falta el dato |
|---|---|---|---|
| Deuda comercial | 20% | ¿Paga a proveedores? (mejor predictor, AUC 0,83) | Se apaga. Nunca un 50 |
| Liquidez | 18% | Flujo / tamaño, media 3 meses | Se apaga |
| Colchón | 18% | Meses de gasto cubiertos por el flujo 6m; runway solo si hay foto de caja | Se apaga |
| Trayectoria | 18% | ¿Va a mejor o a peor? Pesa por producto, no porque prediga (AUC 0,49) | Se apaga |
| Eficiencia | 14% | Gasto / ingreso. 1,0 = equilibrio. Topado a 8× para que un mes loco no envenene | Se apaga |
| Cobro | 12% | ¿Le pagan a ella? Contagio, no decisión propia | Se apaga |

Pesos medidos en `screen_signals.py`, no opinados. Si cubren menos del 55% del
peso, el mes es `NaN` (NO EVALUABLE), no un 50 inventado.

### Cómo se lee una ficha

1. **`score_final`** (0–100) — media exponencial de 25 meses, contraída al prior
   **51,04** si hay poca evidencia. Media de cartera 52,1. Umbrales absolutos:
   SALUDABLE ≥68, ESTABLE ≥52, EN RIESGO ≥42, FRÁGIL ≥33, CRÍTICO <33.
2. **`tendencia`** — dirección. Un 48 MEJORANDO puede ser mejor apuesta que un 62
   DETERIORANDO.
3. **`confianza` / `apto_ranking`** — 47,9% de filas-mes son confianza baja
   (primeros meses + facturas huecas). 1.169 empresas son aptas para ranking.
4. **`motivo_cambio_ultimo_mes`** — qué eje empujó el último mes. Si va vacío,
   el giro fue antes: se usa el texto de `naturaleza_caida`.
5. **Grupo** — vista, no segundo cálculo. 79 de 249 grupos (31,7%) esconden una
   filial en riesgo; 85 (34,1%) tienen tendencias opuestas dentro.

### El ejemplo del log: COMP_0009

Sale en cada corrida a propósito. Tras el tope de burn:

- 2026-03: `burn_rate` = **8,0** (antes 179×; un mes así no puede mandar).
- `runway_meses` solo en 2026-08: la foto de caja no se copia al pasado.
- NaN en morosidad 2024-09→2025-06 = **sin evidencia**, no “paga bien”.
- Score **56,51 ESTABLE**, giro *bache* 1,33σ desde 2025-03, visto 1 mes antes.
  Colchón 0 y eficiencia 5 (quema); cobro 100 y deuda comercial 85 (paga).

### WARN que se defienden en demo

| WARN del pipeline | Por qué no se “arregla” |
|---|---|
| Contraparte 48,9% / concept 6,1% | Se usa el signo. Donde hay banco, **acuerda el 93,7%** |
| Confianza baja 47,9% | El eje se apaga. Imputar 50 hincharía a quien no tiene facturas |
| Morosidad no fiable 65% / 57% | Mismo criterio: sin denominador de vencimiento no hay ratio |
| No forzar EUR | El `exchange_rate` es 1 en el 64% de cuentas no-EUR; multiplicar inventa euros |

No recongelar `model/`. El prior local (51,00) ya coincide con el congelado (51,04).
