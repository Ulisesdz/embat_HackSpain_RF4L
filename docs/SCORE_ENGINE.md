# Motor de scoring — diseño final

Documenta `score_engine.py`, `screen_signals.py` y `evaluate_anticipation.py`.
Diccionario de features: `FEATURES.md`. Pipeline: `README_Data_Analysis.md`.

El dataset no trae etiqueta de salud (impago real, concurso, default). El motor
es un sistema de reglas sobre ratios, con pesos medidos (AUC / lift) y
estimadores pensados para series cortas: Theil-Sen, z-score propio, percentil
del mes y contracción hacia el prior. Cada número se puede explicar.

---

## 1. Arquitectura

```
master_panel.csv
   │
   ├─ 6 EJES  → score mensual 0-100 (media ponderada)
   │     cada eje con CASCADA de fuentes (precisa → disponible)
   │
   ├─ MODULADORES (corrigen, no puntúan)
   │     concentración · apalancamiento · volatilidad · antigüedad del impago
   │
   ├─ AGREGACIÓN   media exponencial (recencia × confianza × cobertura)
   │     + CONTRACCIÓN hacia el prior según evidencia
   │
   ├─ TRES SEÑALES
   │     NIVEL        el problema ya está aquí
   │     COLA         anticipación contra eventos de severidad
   │     GIRO PROPIO  "de 82 a 68": se torció respecto a sí misma
   │
   └─ VISTA DE GRUPO   agregación encima, nunca al revés
```

Calibraciones en `model/`: `pctl_reference.json` y `prior_contraccion.json`.
Borrarlas recalibra el sistema.

Salidas: `scores_mensuales.csv`, `scores_finales.csv`, `scores_grupo.csv`,
`score_explanations.json`, `anticipation_report.csv`.

---

## 2. Pesos

| Eje | Peso | Por qué |
|---|---|---|
| `deuda_comercial` | 0,20 | Predictor más fuerte: AUC 0,83 y lift 4,11 en su decil adverso sobre impago severo. No pagar a un proveedor es decisión propia. |
| `liquidez` | 0,18 | Flujo / tamaño. Normalizado por `ingresos_12m_avg`. |
| `colchon` | 0,18 | Meses que aguanta. Absorbe la volatilidad (mejor predictor único de asfixia, AUC 0,71). |
| `eficiencia` | 0,14 | `burn_rate`: 1,0 es el equilibrio. Lift 3,46 sobre asfixia. |
| `cobro_clientes` | 0,12 | Contagio: que no te paguen anticipa que no pagues (AUC 0,72). Pesa menos que proveedores. |
| `trayectoria` | 0,18 | Dirección para MEJORANDO / DETERIORANDO. AUC 0,49 sobre eventos: no se presenta como predictor. |

`screen_signals.py` calcula AUC y lift sobre filas donde el nivel aún es
aceptable, horizonte 12 meses. Los números de la tabla salen de ahí.

**Apalancamiento no es eje.** El snapshot de deuda cubre el 1,2% de las filas.
Es un modulador de ±8 puntos: primero `debt_service` (718 empresas, todos los
meses); si no hay pagos, la foto de `deuda_sobre_ingresos` solo el mes del
snapshot. `caja_negativa_flag` resta 4 puntos **solo** cuando vale 1. NaN no
es negativo.

Los z-scores no disparan alerta (AUC 0,44–0,57). Describen “fuera de lo
habitual” en la trayectoria y en las explicaciones.

---

## 3. Cascadas

Cada eje usa la fuente más precisa que exista. Solo se apaga si no hay ninguna.

| Eje | 1ª opción | 2ª | 3ª |
|---|---|---|---|
| `liquidez` | `flujo_relativo_3m` | `flujo_relativo` del mes | — |
| `colchon` | `colchon_flujo_meses` | `runway_meses` | — |
| `deuda_comercial` | `pct_impagos_prov_3m` | `stock_prov_sobre_ingresos` | “ha comprado y no debe nada vencido” |
| `cobro_clientes` | `pct_clientes_morosos_3m` | `stock_clientes_sobre_ingresos` | “ha vendido y no le deben nada vencido” |
| `eficiencia` | `burn_rate_3m_avg` | `burn_rate` del mes | — |
| `trayectoria` | ≥1 de 4 señales direccionales | — | — |

Stock cero con historial de compras/ventas es un dato, no un hueco. Por eso
existen `compras_acum` y `ventas_acum`.

Resultado: mediana de 19 meses evaluados de 25; 67,6% de filas-mes con score;
peso cubierto medio 0,685; 6 empresas NO EVALUABLE; 1.169 aptas para ranking.

Si el peso cubierto queda bajo 0,55, el mes es `NaN`. No se imputa 50.

---

## 4. Eje de trayectoria

Cada señal se convierte en intensidad `[-1, +1]` dividiéndola por su saturación.

| Componente | Peso | Señal | Saturación |
|---|---|---|---|
| `pendiente_flujo` | 0,30 | `flujo_pendiente_robusta_6m` (Theil-Sen) | 10 pp de ingresos/mes |
| `deuda_comercial_dir` | 0,25 | `recuperacion_stock_prov` | 0,5 meses de ingresos |
| `ingresos_momentum` | 0,20 | `ingresos_momentum_3m` | ±30% trimestral |
| `anomalia` | 0,15 | `z_caja_ingresos`, `z_stock_prov_sobre_ingresos` | 2 σ |
| `persistencia` | 0,10 | flags sostenidos 3 meses | solo penaliza |

`score_trayectoria = 50 + 50 × dirección × amortiguación`, amortiguación
0,50–1,00 según volatilidad. Simétrico: misma sensibilidad a mejora y a
deterioro.

La persistencia no activa el eje sola (los flags existen en el 100% de las
filas). Hace falta al menos una de las cuatro señales informativas.

La etiqueta `tendencia` es la media de 3 meses de `score_trayectoria`:
\>58 MEJORANDO, \<42 DETERIORANDO. No es el delta del score compuesto: un
dato nuevo movería el compuesto sin que la empresa haya cambiado de rumbo.

---

## 5. Moduladores

| Modulador | Tope | Lógica |
|---|---|---|
| Concentración | −10 pts | Solo si el eje ya está bajo 60 |
| Antigüedad del impago | −15 pts | Proporcional a `share_stock_*_antiguo` |
| Volatilidad del flujo | −14 pts | Sobre el colchón |
| Runway real | ±12 pts | Sobre el colchón, **por percentil** (mediana de runway = 0,49 meses) |
| Apalancamiento | ±8 pts | Sobre el score final; snapshot o `debt_service` |

---

## 6. Agregación y contracción

Peso mensual = recencia (semivida 6 meses) × confianza × cobertura.

```
score_final = (evidencia × score_bruto + k × prior) / (evidencia + k)
```

`k = 0,75`, prior = **54,41** (mediana de empresas con ≥12 meses, 798 casos).
`evidencia` es la suma de pesos mensuales, tope ~7,5. `score_bruto` se guarda
para auditar cuánto contrajo cada caso.

Un mes único dejaba un 95 SALUDABLE. Con la contracción cae a ~60.

### Umbrales (absolutos)

| Clase | Umbral | Población |
|---|---|---|
| SALUDABLE | ≥ 68 | 229 |
| ESTABLE | 52 – 68 | 538 |
| EN RIESGO | 42 – 52 | 315 |
| FRÁGIL | 33 – 42 | 132 |
| CRÍTICO | < 33 | 66 |
| NO EVALUABLE | sin evidencia | 6 |

Media 55,4, mediana 55,5, recorrido 16,22–87,81. Nadie llega a 0 ni a 100:
el agregado exige consistencia.

---

## 7. Tres señales, no una alerta

- **Nivel** — `score_mensual < 42`. Actuar hoy. No anticipa.
- **Cola** — la empresa **aún no** ha caído (`score_mensual ≥ 42`) y acumula
  disparadores de percentil adverso. Es la capa que compra tiempo.
- **Giro** — movimiento contra la volatilidad propia del score (mediana móvil
  de 3 meses, disparo en σ propias). Cierra el caso «82→68».

Los disparadores de cola salen de `screen_signals.py`. Percentil, no umbral
absoluto: varias señales no son monótonas (`flujo_relativo_3m` AUC 0,52 y
lift 3,26 en el decil adverso).

**Canal de impago comercial** (AUC 0,767, lift 3,88):

| Disparador | Umbral | Peso |
|---|---|---|
| `pctl_stock_prov_sobre_ingresos` | ≤ 0,20 | 3,0 |
| `pctl_stock_clientes_sobre_ingresos` | ≤ 0,20 | 2,0 |
| `pctl_recuperacion_stock_prov` | ≤ 0,10 | 2,0 |
| `pctl_clientes_morosos_3m` | ≤ 0,20 | 1,5 |
| `persistente_flag_stock_prov_antiguo` | binario | 1,5 |

**Canal de asfixia de caja** (AUC 0,680, lift 3,03):

| Disparador | Umbral | Peso |
|---|---|---|
| `pctl_flujo_volatilidad_6m` | ≤ 0,20 | 3,0 |
| `pctl_burn_rate_3m` | ≤ 0,20 | 2,5 |
| `pctl_flujo_relativo_3m` | ≤ 0,10 | 2,0 |
| `pctl_colchon_flujo_meses` | ≤ 0,20 | 2,0 |
| `pctl_flujo_pendiente_robusta_6m` | ≤ 0,10 | 1,5 |

Un canal dispara al superar el 55% del peso **disponible** en esa fila, y se
exige sostenimiento 2 meses.

`evaluate_anticipation.py`, horizonte 12 meses, evento = 3 meses consecutivos
por encima del umbral de severidad:

**Asfixia de caja** (tasa base 12,3%)

| Señal | Se activa en | Recall | Precisión | Lift | Antelación |
|---|---|---|---|---|---|
| Nivel | 53,9% | 62,7% | 16,7% | 1,36 | 4,0 m |
| Cola | 39,7% | 44,9% | 18,6% | 1,52 | 3,0 m |
| Combinada | 64,4% | 88,6% | 17,6% | 1,44 | 4,0 m |

La cola gana **2 meses de mediana** al nivel y ve 41 eventos que el nivel no
ve nunca.

**Impago severo** (tasa base 34,1%): el nivel es mejor (el evento se define
sobre el mismo stock). La cola aporta +1 mes y 12 eventos únicos.

El giro **no** se fusiona con los canales: metido dentro, el lift de cola
caía de 1,52 a 1,04. Responde a otra pregunta (“¿esta caída se sostiene?”)
y se valida contra el score futuro, no contra asfixia.

---

## 8. Las seis preguntas

| Pregunta | Dónde | Estado |
|---|---|---|
| Quién está sano | `clasificacion` | 229 / 538 / 315 / 132 / 66 / 6 |
| Quién está mejorando | `tendencia` | 262 MEJORANDO · 398 DETERIORANDO · 611 ESTABLE |
| Quién empieza a torcerse | `senal_giro` | 624 con giro; **420 llamadas** (`score_final` ≥ 55) |
| Bache o caída | `naturaleza_caida` | Bache +4,69 a 6 m (52% recupera); caída −1,66 (33% sigue) |
| Por qué ha cambiado | `motivo_cambio`, `aporte_*` | 17.744 filas-mes; 5,5% dominado por dato nuevo |
| Cuándo se vio venir | `meses_anticipacion` | Cola vs nivel: +2 m asfixia, +1 m impago |

`alerta_temprana` (1.111) es nivel **o** cola: recall, no la lista de ventas.
El dashboard pinta 420.

### Giro autorreferenciado

La empresa mediana recorre 41,7 puntos entre máximo y mínimo. “Ha caído 14”
solo significa algo contra su propia σ. Se suaviza con mediana móvil de 3
meses. Cobertura del caso 82→68: 30,4% (base poblacional 4,9%).

### Bache o caída

Desenlace = ¿el score suavizado sigue igual o peor 6 meses después?
Tasa base de no recuperación 38,5%. Criterios: volatilidad propia baja,
`cambio_real` muy negativo, deuda comercial vencida viva. No se usan
`score_mensual` ni `colchon_flujo_meses`: predicen por reversión a la media
y sesgarían contra las sanas.

| Clase | n | Δ +3 m | Δ +6 m | Recupera | Sigue cayendo |
|---|---|---|---|---|---|
| `bache` | 1.256 | +4,65 | +5,28 | 54,8% | 18,2% |
| `caida_estructural` | 270 | −1,93 | −2,54 | 33,3% | 36,3% |

### Atribución

```
efecto_nivel  = w_i,t-1 * (s_i,t - s_i,t-1)
efecto_mezcla = (w_i,t - w_i,t-1) * s_i,t
```

`cambio_real` es comportamiento; `cambio_cobertura` es dato nuevo. Sin
separarlos, “ha mejorado” sería “empezamos a verla”.

### Determinismo sobre empresas nuevas

La rejilla de 101 cuantiles (`pctl_reference.json`) y el prior congelado
hacen que 70 empresas aisladas saquen el mismo `score_final`, clase y
tendencia que dentro de las 1.286. Empates en percentil: punto medio, como
`rank()`.

`model/` vive fuera de `data/` porque `data/` está en `.gitignore`. Un clon
limpio no debe recalibrar en silencio.

---

## 9. Empresa o grupo

Cálculo por empresa. El grupo es un `groupby`.

| Medida | Valor |
|---|---|
| Varianza del score explicada por el grupo | 61,9% |
| Recorrido máx–mín interno (mediana / p75) | 15,4 / 22,0 pts |
| Grupos con MEJORANDO y DETERIORANDO a la vez | 85 (34,1%) |
| El agregado esconde una filial en riesgo | 74 (29,7%) |

`scores_grupo.csv` publica `score_grupo`, `score_peor` / `empresa_peor`,
`dispersion_interna` y `agregado_esconde_problema`. Toggle de vista, no de
cálculo.

---

## 10. Limitaciones

1. No es validación fuera de muestra. El evento se define sobre las mismas
   variables que alimentan la alerta.
2. Lifts 1,4–1,5. Informa; no separa limpiamente.
3. La deuda es casi ciega: un snapshot. `debt_service` cubre 718 empresas
   todos los meses, pero no dice cuánto queda. `guarantee` / `confirming`
   inflan la foto.
4. Morosidad no fiable en el 55–61% de las filas (documentos que no son
   factura). Por eso existen las cascadas.
5. Prior y percentiles congelados sobre esta población. Recalibrar es
   borrar `model/` a propósito.

---

## 11. Producto encima del motor

El agente (`src/agente_pyme.py`) no inventa un score. Corre herramientas:
ficha cerrada, RAG sobre `docs/TEORIA_PYME.md` y catálogo de acciones
(empresa / Embat / partner). El impacto es el eje de hoy. Una línea de
partner solo encaja en bache. Se lanza desde la ficha
(`python -m src.brief_server`).
