# Análisis de Datos, Ingeniería de Variables y Motor de Scoring
## HackSpain 2026 · Reto Embat (X-Ray)

Este documento recoge la metodología completa de la fase de datos: qué encontramos en el dataset, qué decisiones de limpieza tomamos y por qué, qué sesgos hemos corregido, cuáles hemos sido incapaces de corregir, y cómo se traduce todo eso en un score de 0 a 100 explicable.

El principio que hemos seguido en todo el pipeline: **ninguna transformación se aplica sin dejar constancia numérica de lo que descarta**. Un dataset sintético con trampas premia al equipo que las documenta, no al que las esconde.

---

## 1. Pipeline

```
explore_data.py       → data/features/data_quality_report.txt
build_features.py     → data/features/master_panel.csv  +  feature_audit.json
validate_features.py  → verificación de invariantes (falla con exit 1)
score_engine.py       → scores_finales.csv + scores_mensuales.csv + score_explanations.json
config.py             → ventana, umbrales, pesos y detección de esquema
```

Orden de ejecución:

```bash
python3 -m data_analysis.explore_data
python3 -m data_analysis.build_features
python3 -m data_analysis.validate_features
python3 -m data_analysis.score_engine
```

`config.py` es el único punto donde se tocan la ventana temporal, los umbrales de negocio y los pesos del score. Si el jurado pregunta "¿y si ponderaras distinto la morosidad?", la respuesta es cambiar una línea y volver a ejecutar.

---

## 2. Hallazgos del análisis exploratorio

Al auditar los datos crudos detectamos varias anomalías que habrían arruinado cualquier modelo estándar:

- **Fechas imposibles.** Registros en el año 6913 y 2050, y facturas zombis arrastradas desde 2018 que figuraban como vencidas, produciendo ratios de morosidad del 100% antes del periodo evaluable.
- **Líneas de crédito ciegas.** 534 de 536 líneas tienen el límite concedido a `0`, lo que provoca divisiones por cero al calcular utilización. Descartamos ese ratio y medimos el apalancamiento como deuda viva sobre ingresos anuales.
- **Rectificativas.** Facturas con importe negativo que distorsionan los ratios y pueden generar porcentajes por encima del 100%.
- **El riesgo real es comercial, no bancario.** El 54,3% del volumen facturado está atrapado en estado `overdue`. Estas pymes no se asfixian por su deuda con el banco, sino porque sus clientes no les pagan.

---

## 3. Decisiones de limpieza y por qué

### 3.1 Ventana temporal: 25 buckets, no 24

Respetamos literalmente la ventana declarada por el reto (2024-09-01 → 2026-09-30). Eso son **25 buckets mensuales inclusivos**, no 24. No recortamos el calendario por nuestra cuenta.

Ahora bien: la extracción es de mediados de septiembre de 2026, así que **2026-09 es un mes parcial** con los flujos truncados. Lo conservamos en el panel marcado con `mes_parcial = 1` y lo **excluimos del score agregado**. Puntuar un mes al 60% de sus días hunde artificialmente justo el tramo que más pesa en la valoración de salud actual.

### 3.2 Fechas sucias

Conversión con `errors="coerce"` y filtrado a la ventana. La diferencia respecto a la versión inicial es que ahora **contamos** lo que se va: `feature_audit.json` registra filas crudas, fechas inválidas y filas retenidas para transacciones y facturas, y el informe de calidad desglosa cuántas empresas pierden más del 20% y del 50% de sus registros. Si una empresa pierde la mitad de su historia, su score no puede tener la misma credibilidad que el de otra completa.

### 3.3 Clasificación de facturas: nunca por el signo

La versión inicial usaba `is_receivable = amount > 0`. Eso mete cada rectificativa de venta (importe negativo) en el bloque de compras, contaminando el denominador de la morosidad de proveedores, que es precisamente nuestro indicador más grave.

Ahora resolvemos la dirección por columna semántica, con **coincidencia exacta** sobre el valor normalizado. Descartamos deliberadamente la coincidencia por subcadena: buscar `"in"` u `"out"` dentro del valor hace match con `invoice`, `pending` o `outstanding` y clasifica al revés medio dataset. Si no hay columna utilizable, caemos al signo y el script lo avisa por consola y lo deja escrito en la auditoría como limitación.

### 3.4 El impago se mide as-of, no con el snapshot

Este es el cambio de fondo más importante y no estaba en el planteamiento original.

`status == "overdue"` es el estado **en el momento de la extracción**, no el estado del mes evaluado. Una factura que venció en octubre de 2024 y se pagó con cuarenta días de retraso figura hoy como pagada, de modo que nuestro histórico la ve sana. El efecto es sistemático: la morosidad del pasado queda subestimada y la reciente sobrerrepresentada, y **toda empresa aparenta un deterioro que en realidad es un artefacto del corte temporal**. Un motor que detecte "trayectoria descendente" sobre eso está detectando el sesgo, no el negocio.

Si el dataset trae fecha de pago, la reconstruimos correctamente: una factura está impagada en el mes M si venció antes del cierre de M y no se cobró antes de ese cierre. Eso además nos da **DSO y DPO reales en días**, que es una variable mucho más rica que un porcentaje. Si no la trae, usamos `status` y dejamos el sesgo declarado en `feature_audit.json` bajo `overdue_metodo`.

### 3.5 Censura a la derecha

Simétricamente al punto anterior: las facturas vencidas en los últimos 45 días todavía no han tenido tiempo de entrar en mora. Los meses afectados se marcan con `morosidad_censurada = 1` y ven reducida su etiqueta de `confianza`.

### 3.6 Balances: un snapshot por producto, y el signo se respeta

En el EDA inicial cruzábamos `balances` con `banking_products` con la intención de quedarnos solo con cuentas corrientes y de ahorro, pero el filtro por `type` nunca llegaba a aplicarse: el merge solo hacía de inner join. De ahí salía el saldo medio de 83,7 millones, imposible para una pyme.

Corregido en tres frentes:

1. Si `balances` es una serie temporal, tomamos el **último snapshot por producto**, no la fecha máxima global: los productos no reportan todos el mismo día.
2. Filtramos de verdad por tipo de producto, y registramos en la auditoría qué tipos entraron.
3. **No aplicamos valor absoluto al saldo.** Una caja negativa es la información más valiosa que tenemos sobre una empresa; convertirla en positiva la esconde. Conservamos el signo y añadimos `caja_negativa_flag`.

En deuda sí usamos magnitud (`deuda_viva = |outstanding|`) porque el signo del RAW es una convención contable que no podemos verificar, y lo dejamos anotado con `deuda_signo_negativo_flag`.

---

## 4. Variables del panel maestro

### Bloque A — Caja y eficiencia

- `flujo_neto`, `caja_ingresos`, `caja_gastos`, `n_tx`
- `burn_rate` = gastos / ingresos. **Ya no forzamos el 5.0.** Ese centinela era un número mágico dentro de una variable continua: contaminaba medias móviles y hacía que un salto de 0,02 a 5,0 pareciera un empeoramiento de 250x cuando en realidad es otra categoría. Ahora el ratio queda a `NaN` cuando no hay ingresos y la situación se captura en `mes_sin_ingresos`, más una versión `burn_rate_cap` winsorizada para el score.
- `runway_meses` = caja real / gasto medio de 3 meses. Es la variable más explicable que podemos ponerle delante a un CFO: no "tu score es 43", sino "te quedan 2,4 meses de caja".

### Bloque B — Morosidad bifurcada

Mantenemos la separación que ya teníamos, porque las dos direcciones del riesgo cuentan historias distintas:

- `pct_clientes_morosos`: porcentaje de las ventas que no se ha cobrado (riesgo entrante).
- `pct_impagos_prov`: porcentaje de las compras que la empresa no ha podido pagar (síntoma de asfixia ya materializada).

Dos correcciones:

- **Ratio sin denominador es `NaN`, no 0.** Antes, una empresa sin ventas ese mes obtenía morosidad 0, que el score leería como excelente. Una empresa muerta y una sana puntuaban igual. Ahora hay `ventas_disponible`, `compras_disponible` y `tx_disponible` para que el motor decida.
- **Ratio sobre sumas móviles con mínimo de facturas.** En la verificación original, COMP_1240 alternaba 0 → 79,35 → 0 → 79,35. Un valor que se repite exacto es la huella de una única factura dominando el mes: no medíamos morosidad, medíamos si esa factura concreta caía ahí. Ahora el ratio de 3 meses se calcula como suma de numeradores sobre suma de denominadores (no media de ratios, que pondera igual un mes de 500 € y uno de 500.000 €) y exige al menos dos facturas en la ventana.

### Bloque C — Stock vivo de impago

Incorporación nueva: además del ratio de cohorte por mes de vencimiento, acumulamos el **stock de dinero atrapado** que sigue vivo. Lo implementamos como eventos contables (entra el pendiente en el mes de vencimiento, sale en el mes de cobro) más una suma acumulada, en lugar de un producto cartesiano factura × mes que explota en memoria. Sin fecha de pago el stock no tiene evento de salida y funciona como cota superior, lo cual está documentado.

`stock_prov_sobre_ingresos` y `stock_clientes_sobre_ingresos` son la versión normalizada: cuántos meses de facturación lleva la empresa atrapados.

### Bloque D — Trayectoria

Aquí está el "no es una foto fija" que pide el reto:

- `*_3m_avg` y `*_6m_avg` con `min_periods` **estricto**. Un rolling de 3 meses que devuelve valor en el primer mes no es un rolling de 3 meses.
- `*_3m_vs_prev3m`: media del último trimestre menos la del trimestre anterior. Distingue el bache del deterioro estructural mejor que un delta mes a mes.
- `flujo_pendiente_6m`: regresión lineal sobre el flujo relativo. La media móvil dice dónde estás; la pendiente dice hacia dónde vas.
- `flujo_volatilidad_6m`: separa un negocio estacional de uno que se está rompiendo.
- `flujo_yoy`: con 24 meses tenemos comparación interanual real. Diciembre contra diciembre separa el calendario de lo estructural.
- `recuperacion_clientes`, `recuperacion_prov`, `recuperacion_flujo`: señales con el signo invertido donde "más alto es peor", para que el motor pueda **premiar la mejora**, no solo castigar la caída.
- Flags de estrés con conteo de persistencia a 3 y 6 meses (`persistente_flag_estres_prov`, etc.). Tres meses seguidos por encima del 30% de impagos a proveedores no es lo mismo que un mes malo.

### Calendario completo

El panel se construye sobre el producto cartesiano **empresa × 25 meses**. Sin esto, un `rolling(3)` sobre un panel con huecos promedia febrero, abril y mayo creyendo que son consecutivos. La malla completa es lo que hace que las medias móviles signifiquen algo. El validador comprueba que ninguna empresa tenga un calendario distinto.

### Confianza

Cada fila lleva `confianza` (alta / media / baja) según meses de historia acumulados, censura de morosidad y mes parcial. El score la arrastra hasta la salida final: una empresa con seis meses de datos no merece la misma credibilidad que una con veinticinco.

---

## 5. Motor de scoring

### Por qué reglas expertas y no XGBoost

**No hay etiqueta.** Entrenar un modelo supervisado sobre "variables sintéticas de riesgo" construidas a partir de las propias features es circular: el modelo aprende nuestra heurística con más varianza y menos explicabilidad, y perdemos exactamente el requisito que el jurado ha puesto por escrito. Optamos por reglas expertas ponderadas sobre variables escala-libre.

Si queremos validar que las features son predictivas y no meramente descriptivas, el camino honesto es construir un target futuro real (¿entra esta empresa en estrés en t+3?), entrenar con datos hasta t y validar con split temporal, nunca aleatorio. Queda como extensión, no como motor principal.

### El error que había que evitar: umbrales en euros

Un umbral del tipo "flujo neto > 20.000 → score 100" puntúa con la misma vara a una pyme que factura 50k al mes y a un grupo que factura 5M. **Todos nuestros factores operan sobre magnitudes escala-libre**: flujo como fracción de los ingresos, meses de runway, porcentajes de morosidad, deuda sobre ingresos anuales. Así el score es comparable entre empresas de tamaños distintos sin necesidad de rankings forzados.

### Factores y pesos

| Factor | Peso | Variable |
|---|---|---|
| Liquidez | 0,22 | `flujo_relativo_3m` |
| Runway | 0,18 | `runway_meses` |
| Eficiencia | 0,12 | `burn_rate_3m_avg` |
| Morosidad proveedores | 0,18 | `impagos_prov_3m_avg` |
| Morosidad clientes | 0,12 | `clientes_morosos_3m_avg` |
| Tendencia | 0,13 | pendiente 6m + señales de recuperación |
| Apalancamiento | 0,05 | `deuda_sobre_ingresos` + caja negativa |

La morosidad de proveedores pesa más que la de clientes porque no es un riesgo, es un síntoma de asfixia ya materializada: cuando una empresa deja de pagar a sus proveedores, el problema ya ocurrió.

### Redistribución de pesos

Un factor sin datos **no se imputa a 50**. Se excluye y su peso se reparte proporcionalmente entre los factores que sí tienen información, y la salida registra `peso_cubierto` para que se vea qué fracción del modelo estaba operativa. Imputar a la mitad premia la falta de información en las empresas malas y castiga a las buenas.

### Agregación temporal

Media exponencial con vida media de 6 meses sobre los scores mensuales: los meses recientes pesan más, pero el pasado no desaparece. Eso es literalmente lo que pide el enunciado con "trayectoria y no foto fija". La etiqueta de tendencia compara la media de los últimos 3 meses con la de los 3 anteriores: MEJORANDO / ESTABLE / DETERIORANDO.

### Explicabilidad

`score_explanations.json` devuelve, por empresa, el desglose factor a factor del último mes válido: score parcial, peso efectivo, si era aplicable y una razón en lenguaje natural, más una lista de alertas accionables. Ejemplo real de salida:

```json
"runway":    { "score": 0,    "peso_efectivo": 0.2195, "razon": "Caja en negativo (-3.7 meses)" },
"eficiencia":{ "score": 100,  "peso_efectivo": 0.1463, "razon": "Gasta 0.53x lo que ingresa (muy eficiente)" },
"morosidad_prov": { "score": null, "aplicable": false, "razon": "Sin compras suficientes para medir impagos" }
```

Eso es lo que alimenta directamente el agente para el CFO: no un número, sino una frase que dice qué está pasando y por qué.

---

## 6. Validación

`validate_features.py` falla con código 1 si se rompe alguna invariante:

1. Cada empresa tiene exactamente 25 buckets mensuales.
2. El calendario coincide exactamente con el esperado.
3. No hay duplicados `company_id + year_month`.
4. Se cumple la identidad `flujo_neto = ingresos − gastos`.
5. Todos los ratios de morosidad están en [0, 100] o son NA.
6. Las variables de volumen y stock no son negativas.
7. Ningún rolling estricto tiene valor antes de completar su ventana.
8. No hay ratios calculados donde no había denominador.
9. No hay identificadores nulos.

Un panel que no pasa estas pruebas invalida cualquier score construido encima, así que el validador se ejecuta siempre antes de puntuar.

---

## 7. Limitaciones que declaramos abiertamente

Estas no las escondemos; llevarlas a la presentación nos da más credibilidad que ignorarlas.

1. **Look-ahead en el estado de impago** si el dataset no incluye fecha de pago. Queda registrado en `feature_audit.json → overdue_metodo`.
2. **Censura a la derecha** en los últimos 45 días: la morosidad reciente está estructuralmente subestimada.
3. **Stock de impago como cota superior** cuando no hay evento de cobro.
4. **Transacciones intragrupo.** El dataset agrupa 1.286 empresas en 250 grupos. Si A factura a su matriz B, ese ingreso no es demanda de mercado y esa morosidad no es riesgo real. Tenemos `group_id` en el panel; el cruce por contraparte queda como siguiente mejora y es un diferenciador que probablemente nadie más mire.
5. **Concentración de clientes.** Si el 70% de las ventas está en un cliente que empieza a pagar tarde, eso es riesgo existencial y no un ratio del 70%. Requiere columna de contraparte.
6. **Sin ground truth**, el score es una heurística argumentada, no un modelo validado. La honestidad sobre esto es parte del producto.

---

## 8. Próximo paso

Con `scores_finales.csv` y `score_explanations.json` generados, la demo (Streamlit) puede consumirlos directamente: buscador de empresa, evolución del score mensual, desglose por factor del último mes y panel de alertas tempranas. La explicabilidad ya viene resuelta desde el motor, así que la interfaz solo tiene que renderizarla.