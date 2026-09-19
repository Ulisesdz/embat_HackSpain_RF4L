### Análisis de Datos, Ingeniería de Variables y Motor de Scoring
### HackSpain 2026 · Reto Embat (X-Ray)
Este documento recoge la arquitectura completa de la fase de datos: qué hace cada componente del pipeline, cómo se transforman los datos crudos, qué fórmulas matemáticas rigen el motor de scoring, y cómo garantizamos que no haya data leakage temporal ni distorsiones aritméticas.

El principio rector del proyecto: ninguna transformación se aplica sin dejar constancia numérica de lo que descarta. Un dataset sintético con trampas premia al equipo que documenta y gestiona los sesgos, no al que los esconde para obtener una curva perfecta.

**Cómo explicar los números de la última corrida** (sin mezclar recuentos) está en
el `README.md` raíz, sección «Cómo se explica cada métrica». Resumen: 1.111 es
alerta de nivel/cola; 624 es giro alguna vez; **420** es la lista de llamadas
(giro + score actual ≥ 55). 417 es el mismo giro contado en el mes en que aún
parecían sanas. Validación: 0 errores. Prior congelado 54,41. Monitor: 3.050
avisos (sin el cruce ruidoso por ESTABLE).

## 1. Arquitectura del Pipeline y Archivos
El sistema son seis scripts secuenciales sobre datos inmutables: ningún script modifica los CSV crudos, todo ocurre en memoria.

```
src/config.py                 → Único punto de verdad: fechas, pesos, umbrales y mapeos.
src/explore_data.py           → data/features/data_quality_report.txt
src/build_features.py         → master_panel.csv + feature_audit.json + cleaning_log.json
src/validate_features.py      → Guardián (exit 1 si rompe una invariante)
src/score_engine.py           → scores_mensuales / finales / grupo + explanations
src/evaluate_anticipation.py  → anticipation_report.csv
src/monitor.py                → alerts.csv (avisa solo cuando se mueve)
src/build_dashboard.py        → dashboard/index.html
src/screen_signals.py         → AUC y lift (opcional)
```

Orden de ejecución, desde la raíz del repositorio:

```
pip install -r requirements.txt
python -m src.run                   # pipeline completo
python -m src.explore_data          # opcional: audita los CSV crudos
```

La limpieza (fechas, ceros, ventana, moneda) está en `docs/LIMPIEZA.md`.

`evaluate_anticipation.py` va **después** de `score_engine.py` a propósito, y no dentro: calcula la antelación mirando hacia el futuro de cada mes, así que si viviera en el motor metería información futura en un archivo que tiene que ser causal. Se ejecuta aparte y devuelve solo el resultado agregado por empresa.

Funciones de cada script:
- config.py: Centraliza parámetros críticos. Si el jurado pide ajustar el peso de la morosidad o la ventana temporal, se cambia una línea aquí y se reejecuta todo.
- explore_data.py: Audita los CSV crudos sin unirlos. Detecta fechas en el año 6913, líneas de crédito sin límite, y evalúa la disponibilidad de columnas clave.
- build_features.py: El motor de ingeniería de datos. Resuelve multidivisa, mapea facturas a sus meses correctos (emisión vs. vencimiento), calcula saldos reales, genera las sumas móviles y ensambla el panel maestro de 25 meses estrictos por empresa.
- validate_features.py: Validador lógico. Antes de puntuar, comprueba matemáticamente que flujo = ingresos - gastos, que los ratios de morosidad están en [0, 100], y que los saldos actuales no se han propagado al pasado.
- score_engine.py: Aplica reglas expertas sobre las variables escala-libre para generar un score de 0 a 100, gestionando dinámicamente la falta de información y emitiendo justificaciones en lenguaje natural. Su diseño completo (pesos, cascadas, moduladores, contracción y alerta en dos capas) está en `SCORE_ENGINE.md`.
- screen_signals.py: Mide, sobre las filas donde el nivel aún es aceptable, el AUC y el lift de cada señal del panel para que ocurra un evento de severidad en los 12 meses siguientes. Es lo que convierte los pesos del motor en una decisión medida en lugar de una opinión.
- evaluate_anticipation.py: Mide cuántos meses antes avisa la alerta, comparándola con la capa de nivel a igualdad de volumen de avisos. Sin esta comparación, cualquier señal que se active mucho parece anticipar.

## 2. Artefactos Generados (Qué se crea y para qué sirve)
- master_panel.csv (El Tablero de Juego)
Es un panel de 1.286 empresas × 25 meses = 32.150 filas exactas. El calendario se conserva entero para que un rolling(3) sean 3 meses de calendario. **Dentro de la ventana observada** de cada empresa (primer mes completo → último movimiento), un mes sin actividad es 0. **Fuera de esa ventana** los volúmenes son NaN: no se finge un histórico de ceros antes de que la empresa exista en el dataset. `cleaning_log.json` cuenta cada corrección.

Columnas Absolutas: caja_ingresos, caja_gastos, flujo_neto, volumen_ventas, volumen_compras (por mes de EMISIÓN), volumen_vencido_ventas, volumen_vencido_compras (por mes de VENCIMIENTO), atrapado_ventas, atrapado_compras, stock_overdue_clientes, stock_overdue_prov.

Columnas Relativas: pct_clientes_morosos_3m, pct_impagos_prov_3m, burn_rate, flujo_relativo.

Columnas de Snapshot: caja_real, deuda_viva. (Solo aparecen en el mes actual).

Columnas de Metadatos: `observado` (ventana real de la empresa), peso cubierto (% de factores con datos), confianza (alta/media/baja; 47,9% de filas son baja y el eje se apaga).

- scores_mensuales.csv
Añade la puntuación temporal a cada fila del panel.

score_mensual: Puntuación 0-100 del mes.

n_componentes_validos: Cuántos factores aportaron al score de ese mes. (Si el peso total es < 55%, el score cae a NaN).

- scores_finales.csv
El output consolidado para el leaderboard y la tabla principal del frontend: 1.286 filas × 33 columnas, una por empresa. Las que importan:

| Columna | Qué dice |
|---|---|
| `score_final` | Agregación ponderada de todo el histórico, contraída hacia el prior según evidencia |
| `score_bruto` | La misma agregación **sin** contraer, para auditar cuánto se movió cada caso |
| `clasificacion` | SALUDABLE, ESTABLE, EN RIESGO, FRÁGIL, CRÍTICO o NO EVALUABLE |
| `tendencia` | MEJORANDO, ESTABLE, DETERIORANDO o SIN DATOS |
| `giro_detectado`, `giro_sigmas`, `primer_giro` | El detector autorreferenciado: si se ha torcido, con qué intensidad y desde cuándo |
| `naturaleza_caida` | `bache` o `caida_estructural` |
| `cambio_real_ultimo_mes` vs `cambio_cobertura_ultimo_mes` | Cuánto del último movimiento es comportamiento y cuánto es dato nuevo |
| `motivo_cambio_ultimo_mes` | La explicación en texto del cambio respecto al mes anterior |
| `meses_anticipacion`, `meses_ganados_a_nivel` | Antelación medida, inyectada por `evaluate_anticipation.py` |
| `cobertura_media`, `confianza`, `evidencia_efectiva`, `apto_ranking` | Cuán robusta es la nota y si la empresa debe aparecer en un ranking |

- scores_grupo.csv
Vista agregada de los **249** grupos. No publica una media y se calla: publica `score_grupo` junto a `score_peor` / `empresa_peor`, `dispersion_interna`, `tendencias_opuestas` y el flag `agregado_esconde_problema`, que salta en **74 de 249** (29,7%). El razonamiento empresa vs. grupo está en `SCORE_ENGINE.md` §10.

- score_explanations.json
El puente hacia el producto final (Frontend/Agente LLM). Un diccionario por empresa que contiene el "por qué" exacto de su puntuación en el último mes evaluable, factor por factor (ej. "Runway crítico (1.2 meses de gasto cubiertos)"), junto con alertas pre-calculadas para el CFO.

- anticipation_report.csv
Una fila por empresa y tipo de evento (`impago_severo`, `asfixia_de_caja`) con, para cada una de las cuatro señales (`nivel`, `canales_cola`, `giro_propio`, `combinada`), si detectó el evento y con cuántos meses de antelación. Es el archivo que sostiene cualquier afirmación sobre "lo vimos N meses antes".

- pctl_reference.json
La distribución de referencia congelada: una rejilla de 101 cuantiles por columna y mes. Existe para que puntuar las 60-80 empresas de test dé el mismo resultado que puntuarlas dentro de la población completa. Sin esto, los percentiles compararían las empresas de test entre ellas. Verificado: la desviación baja de ~0,045 a ~0,005.

## 3. Fórmulas Matemáticas Clave
El score no utiliza umbrales absolutos en euros (un límite de 50.000€ castiga a una multinacional y premia a un taller local). Todo opera sobre variables escala-libre:

1. Flujo Relativo: flujo_neto / ingresos_12m_avg

Propósito: Mide si el dinero que entra/sale es relevante para el tamaño de la empresa. Absorbe la estacionalidad al dividir por la media anual.

2. Burn Rate: gastos / ingresos

Propósito: Velocidad operativa de quema. Si los ingresos son 0, la variable es NaN y levanta el flag mes_sin_ingresos, penalizando a través de reglas lógicas en lugar de inventar infinitos.

3. Morosidad Móvil (Ej. Clientes 3M): sum(impagado_as_of_3m) / sum(facturas_que_vencen_3m)

Propósito: Protege contra meses de bajo volumen. Hacer la media de los ratios mensuales daría el mismo peso a un mes de 500€ que a uno de 500.000€.

Cohorte: numerador y denominador son la MISMA cohorte de vencimiento. El denominador es `volumen_vencido_*` (facturas cuyo `due_date` cae en el mes), no `volumen_*` (emisión). No se aplica `.clip(0, 100)`: si el ratio se sale del rango es un error de cohorte, y recortarlo lo esconde. El validador falla a propósito en ese caso.

4. Runway: caja_real / gasto_medio_3m

Propósito: Meses de supervivencia teórica. Exige un mínimo de 3 meses reales de actividad (min_periods=3) para evitar explosiones artificiales en empresas recién nacidas con gasto casi cero.

5. Score Agregado (Puntuación Final):

Media exponencial (vida media = 6 meses) ponderada por tres ejes:
Peso_mes = Decaimiento_Temporal × Confianza × Cobertura

Propósito: Los meses recientes pesan más, pero un mes antiguo con datos perfectos (100% cobertura) retiene influencia frente a un mes reciente con datos dudosos (ej. censura a la derecha).

## 4. Decisiones Críticas de Limpieza y Control de Sesgos
4.1 El Impago se mide "As-Of", evitando Look-Ahead Bias
El campo status == "overdue" del CSV indica el estado hoy (septiembre 2026). Si lo usáramos, una factura de 2024 que se pagó con 40 días de retraso figuraría históricamente como sana. Esto crea un artefacto: el pasado parece idílico y el presente desastroso.
Solución: Comparamos due_date contra payment_date al cierre exacto de cada mes. Si payment_date es mayor al fin de ese mes (o nula), estaba impagada en esa foto.

4.2 Snapshots (Caja y Deuda) No se Backfillean
balances.csv y debt_products.csv representan una foto estática actual, no un histórico.
Solución: La caja real y la deuda viva se inyectan únicamente en el último mes completo evaluable (2026-08). Propagarlas al pasado habría generado un runway ficticio en 2024.

4.3 Multidivisa (Multicurrency)
El dataset mezcla monedas. Sumar facturas en USD con facturas en GBP arruina la magnitud.
Solución: Solo normalizamos a accounting_currency cuando existe un exchange_rate dentro de `[EXCHANGE_RATE_MIN, EXCHANGE_RATE_MAX]` = [0.001, 2500]. Un `>0` a secas aceptaba tipos de 0.0002 y 20.303, que por sí solos torcían el volumen y los ratios de una empresa entera. Las filas fuera de rango o sin tipo se declaran nulas para cálculos financieros, priorizando perder una fila a sumar peras con manzanas.

La misma regla se aplica a `debt_products`: antes se sumaba `outstanding` en divisas distintas sin convertir. Ahora la deuda se lleva a EUR cuando hay tipo válido, y si ningún producto de la empresa es convertible, `deuda_viva` queda NaN (con `deuda_conversion_incompleta` como flag) en vez de devolver una magnitud inventada.

4.4 Censura a la Derecha y Meses Parciales
Mes Parcial (2026-09): La extracción ocurre el 18 de septiembre. Puntuar un mes al 60% castiga el volumen absoluto. Se conserva en el panel, pero se excluye del scoring general.

Maduración (Censura): Las facturas de los últimos 45 días aún no han tenido tiempo estadístico para entrar en mora. Esos meses se marcan con morosidad_censurada = 1, lo que rebaja la fiabilidad del último score.

4.5 Rectificativas y Signos
Una rectificativa no es simplemente amount < 0. El pipeline usa coincidencia exacta en las columnas de tipo de documento o conceptos. El signo se usa solo como último recurso de fallback para deducir la dirección de la factura, nunca para asumir que es una corrección contable pura.

Las rectificativas quedan FUERA de `volumen_*`, `volumen_vencido_*`, `atrapado_*` y del stock de impago. Un abono no es actividad comercial ni una deuda que se cobra; mezclarlo inflaba el denominador de morosidad.

La cascada de dirección es: columna de dirección → `client_id`/`supplier_id` → `document_type` → texto de `concept` → signo del importe. El paso de `concept` solo se acepta si clasifica de forma inequívoca ≥95% de las filas (`direccion_concept_cobertura` en la auditoría); si no, se descarta. Un heurístico textual que cubre el 3% de las filas dejaría el 97% restante etiquetado como compra.

4.6 El Stock de Impago se calcula As-Of, no por acumulación de deltas
Antes el stock vivo era un `cumsum` de entradas (vencimientos) menos salidas (pagos). Ese enfoque arrastra cualquier desajuste de signo para siempre y no puede representar facturas ya vencidas antes del inicio de la ventana.
Solución: cada factura impagada ocupa explícitamente el tramo de meses que va de su mes de vencimiento al mes anterior a su pago (o hasta el fin de la ventana si nunca se paga). El stock de un mes es la suma de los tramos vivos en ese mes. Además se incorporan las facturas con `due_date` anterior a 2024-09 que seguían abiertas al inicio, que antes desaparecían del stock.

`pending_amount` se acota al nominal de la factura: hay filas con `|pending| > |amount|` que, sin recortar, generaban ratios de morosidad por encima del 100%.

4.7 Reparaciones de suciedad (el sponsor las pide)
El otro enfoque del equipo (`data_analysis_compañero/clean.py`) deja constancia de cada fila que toca. Aquí se adoptan las reparaciones que no introducen look-ahead, y se escriben en `data/features/cleaning_log.json`:

- Vencimientos imposibles (NaT, plazo < 0 o > 730 días) → emisión + 30 días. Un `due_date` en el año 2000 dejaba la factura como impago desde 2024-09.
- `amount == 0` se excluye. Winsor p99 por empresa y dirección.
- Fechas de cobro de facturas **cobradas** (pendiente liquidado) posteriores a la extracción o anteriores a emitir se recortan.
- Saldos `|x| ≥ 1e9` se anulan (basura del origen, p. ej. 9.99e10), además de los centinelas ya conocidos.
- Typo `cash_settlements` → `cash_settlement`. Duplicados exactos con `transaction_id` distinto se cuentan y se dejan (TPV/comisiones).
- Ventana observada: primer mes completo (si el alta es después del día 3, ese mes no cuenta) hasta el último movimiento. Fuera = NaN.

4.8 Qué no se copia del otro enfoque
Esas ideas empeoran el score o inventan historia:

| Idea del compañero | Por qué no |
|---|---|
| Imputar 50 si falta un bloque | Falsa neutralidad. Aquí el eje se apaga |
| Reconstruir caja hacia atrás desde el saldo final | Look-ahead: el saldo de 2026 "explica" 2024 |
| Backfill de deuda/caja a todos los meses | Snapshot actual no es histórico |
| `status == paid` como verdad del cobro | `payment_date` está llena en overdue; `pending_amount` es el estado real |
| Incluir `card` en flujos de tesorería | El cargo se duplica cuando llega el recibo a la corriente |
| Runway al 24% del score | Un snapshot no puede pesar tanto |

Sí se adoptaron de ese enfoque: filtro operativo de flujos, `refund_rate`, `debt_service` mensual, y el log de limpieza.

## 5. El Motor de Scoring: Por qué Reglas Expertas
No hemos utilizado XGBoost ni Random Forest porque no existe ground truth. Entrenar un modelo para predecir un target sintético creado por nosotros mismos hace que el modelo aprenda nuestra heurística pero con ruido, perdiendo la explicabilidad (caja negra). El razonamiento completo, incluido por qué Prophet tampoco encaja y dónde sí cabría ML de forma honesta, está en `SCORE_ENGINE.md` §1.

El motor implementado pondera **6 ejes**, con los pesos fijados después de medir el AUC y el lift de cada señal:

| Eje | Peso |
|---|---|
| Deuda comercial (proveedores) | 0,20 |
| Liquidez | 0,18 |
| Colchón | 0,18 |
| Trayectoria | 0,18 |
| Eficiencia | 0,14 |
| Cobro de clientes | 0,12 |

El apalancamiento **ya no es un eje**: con 1,2% de cobertura, un peso fijo no penalizaba a quien estaba apalancado, bloqueaba el score de todos los demás. Pasó a modulador acotado de ±8 puntos. El histórico de las tres calibraciones de peso (v1 intuición → v2 dirección → v3 evidencia medida) está en `SCORE_ENGINE.md` §3.1.

Tres principios de diseño:

- **No imputa la ignorancia a la media.** Si un mes no tiene ventas, el eje de cobro de clientes se apaga y su peso se reparte entre los demás, en lugar de asignarle un 50 neutro.
- **Cada eje resuelve una cascada de fuentes**, de la más precisa a la más disponible. El tercer escalón es el que más cobertura aporta: "ha comprado y no debe nada vencido" es una observación, no un hueco. Gracias a las cascadas la mediana de meses evaluados pasó de 6 a **19** y las empresas NO EVALUABLE de 87 a **5**.
- **Cobertura mínima (0,55).** Si aun con las cascadas faltan demasiados ejes, el mes devuelve NaN. Es mejor decir "NO EVALUABLE" que devolver un 50 aleatorio.

Encima del score mensual van dos capas más: una **contracción empírica hacia el prior** según la evidencia acumulada (que resuelve el caso de la empresa con un solo mes puntuando 95) y una **alerta en dos capas** con un detector de giro autorreferenciado. Todo ello en `SCORE_ENGINE.md` §7 y §8.

## 6. Limitaciones Declaradas
Un modelo robusto documenta lo que no puede resolver. Estas son las que siguen abiertas:

**Operaciones Intragrupo.** No hemos filtrado la facturación entre empresas del mismo `group_id`. Algunas métricas de "crecimiento" pueden ser simples movimientos internos de tesorería.

**Puntos Ciegos de Deuda.** Como la deuda no tiene histórico, no podemos penalizar a una empresa que se sobreapalancó hace 12 meses; el motor solo la considera en la foto final. Es la limitación con más margen de mejora si se consiguiera el dato.

**No hay validación fuera de muestra.** Los eventos de severidad contra los que medimos la anticipación se definen con reglas sobre las mismas variables que alimentan la alerta. Lo que medimos es **adelanto frente a un umbral de severidad**, no capacidad predictiva frente a un desenlace externo (impago real, concurso). Esa etiqueta no existe en el dataset.

**Los lifts son moderados** (1,4–1,5 sobre tasas base del 12–34%). La señal informa, pero no separa limpiamente. No conviene presentarla como más de lo que es.

**Morosidad no fiable en el 55-61% de las filas.** Es consecuencia directa de filtrar documentos que no son factura y facturas anuladas (§4.6). Las cascadas del motor existen precisamente para cubrir ese hueco.

**Denominadores pequeños.** La mediana de facturas vencidas por mes es 0 y el p75 es 2. Con `MIN_FACTURAS_RATIO = 2`, una sola factura impagada produce un 100% de morosidad.

### 6.1 Limitaciones ya cerradas
Se dejan anotadas porque figuraban como abiertas en versiones anteriores de este documento:

- ~~Concentración de riesgo sin penalizar~~ → resuelto en la iteración 3 con `hhi_*` y `top1_*_share`, y aplicado en la iteración 4 como modulador acotado de −10 puntos que solo amplifica si el eje ya está por debajo de 60.
- ~~Falsos positivos por juventud (empresas con 1 mes puntuando 95,0)~~ → resuelto con la contracción empírica hacia el prior. Ese caso cae ahora a ~60 sin necesidad de filtrarlo a mano, y `apto_ranking` marca explícitamente quién tiene evidencia suficiente.
- ~~Percentiles invertidos en deuda, impagos y edad~~ → era un bug real en `pctl_mes`; corregido en la iteración 4 exigiendo orientación explícita (`mas_es_mejor`).

## 7. Registro de Cambios (Iteración de Features)
Se documenta cada corrección para poder justificar ante el jurado qué sesgo resolvía.

### Iteración 1 · Corrección de cohortes y divisas
Motivación: la validación fallaba con 4 errores de ratios fuera de [0, 100] y el score solo evaluaba una mediana de 6 meses de 24, lo que hace imposible demostrar anticipación.

- `config.py`: añadido `EXCHANGE_RATE_MIN` / `EXCHANGE_RATE_MAX`. Ampliados los mapeos de dirección (`sales_invoice`, `purchase_invoice`, `bill`, ...).
- `build_features.py`:
  - Morosidad sobre cohorte de vencimiento (`volumen_vencido_*` como denominador). Causa raíz de los 4 FAIL.
  - `impago_abs` acotado al nominal de la factura.
  - Rectificativas excluidas de volúmenes, vencimientos e impagos.
  - `stock_asof_mensual()` sustituye el `cumsum` de deltas; incorpora impagos abiertos previos a la ventana.
  - Tipos de cambio fuera de rango tratados como no convertibles; deuda convertida a EUR.
  - Cascada de dirección ampliada, con umbral de cobertura del 95% para el heurístico de `concept`.
  - La confianza baja a "media" cuando la morosidad se sostiene solo con ventana de 6 meses.
- `validate_features.py`: nuevas invariantes `atrapado_* <= volumen_vencido_*` y denominador de vencimiento. `volumen_vencido_*` y `stock_overdue_*` pasan a columnas obligatorias.

Nuevas claves de auditoría: `inv_tipo_cambio_fuera_de_rango`, `inv_pending_mayor_que_amount`, `direccion_concept_cobertura`, `direccion_reparto`, `deuda_productos_sin_eur`, `deuda_productos_no_convertibles`.

Resultado: los 4 FAIL de ratios pasaron a 2, y los 2 restantes eran ruido de coma flotante (exceso máximo 8e-11), no error de cohorte. Pero la morosidad seguía saliendo 0,0 en todo el panel, lo que llevó a la iteración 2.

### Iteración 2 · `payment_date` no es la fecha de cobro
Motivación: con las cohortes ya correctas, `pct_clientes_morosos_3m` y `pct_impagos_prov_3m` seguían valiendo 0,0 en todas las empresas y meses. Un 30% del peso del score (morosidad de clientes + proveedores) estaba regalando un 100/100 a todo el mundo.

Causa raíz, encontrada al leer `data/data_dictionary.md` y cruzarlo con los CSV: `payment_date` está poblada en el 99,99% de las filas, **incluidas las 192.554 con `status = overdue` y `pending_amount = amount`**. Para una factura no cobrada es una fecha prevista, no un cobro. El pipeline la tomaba como cobro real, así que toda factura parecía cobrada el día de su vencimiento.

- `config.py`: `TIPOS_DOC_COMERCIAL`, `ESTADOS_ANULADOS`, `TOLERANCIA_COBRO`, `MAX_DIAS_RETRASO`. `TIPOS_CAJA` corregido: el valor real en `banking_products.csv` es `saving`, no `savings`, así que las cuentas de ahorro estaban excluidas de la caja.
- `build_features.py`:
  - `marcar_impago()` distingue cobro real (pendiente liquidado) de fecha prevista. `fecha_cobro` sustituye a `payment_date` en el cálculo as-of y en el stock.
  - Filtrado de documentos que no son factura (121.695 filas: `paymentDocument`, `note`, `deposit`, `deliveryNote`, `purchaseOrder`, `other`, `cheque`) y de 12.107 facturas anuladas.
  - `dias_retraso` acotado a [0, 365]: hay `payment_date` en el año 6913 y retrasos de −26.783 días (83.235 filas afectadas).
  - `direccion_por_contraparte()`: usa el neto bancario por `counterparty_id` como validación cruzada del signo del importe.
- `validate_features.py`: tolerancia de 1e-6 en el rango de ratios, con el exceso reportado en el mensaje de fallo.

Evidencia sobre la convención de signo: `counterparty_id` cubre el 48,9% de las facturas y, donde ambos métodos opinan, coinciden en el **93,6%**. Es la mejor prueba disponible de que la convención es receivable(+) / payable(−). Queda auditada en `direccion_acuerdo_contraparte_vs_signo`.

Resultado: validación en 0 errores y morosidad con distribución real (mediana 47% clientes, 41% proveedores) en lugar de 0,0 constante. La distribución de clasificaciones se desplazó de forma coherente: `EN RIESGO` 276 → 579 y `SALUDABLE` 74 → 25, porque antes la morosidad inflaba el score de todas las empresas.

Pendiente de entonces, y cómo se cerró: (1) `stock_prov_sobre_ingresos` entró como
cascada del eje de deuda; (2) DSO/DPO se midieron y **no entraron** (se solapan
con `edad_media_stock_*`); (3) la contracción empírica + `apto_ranking` resolvió
el ranking por evidencia; (4) `MIN_PESO_CUBIERTO_SCORE` se quedó en 0,55; (5)
concentración como modulador `top1_*_share_3m`. Intragrupo y deuda contingente
siguen abiertos: el techo lo pone el dato.

### Iteración 3 · Métricas de anticipación
Motivación: con la morosidad ya funcionando, el cuello de botella pasó a ser la antelación. Casi la mitad del peso del score (morosidad 30% + runway 18%) vive en señales retrasadas, que solo confirman el daño.

Criterio aplicado: una métrica anticipa si (1) se mueve antes que el impago, (2) existe en la mayoría de los meses, (3) está normalizada contra la propia empresa, (4) distingue persistencia de ruido, y (5) está acotada.

Añadido (panel de 98 → 137 columnas):
- **Antigüedad del impago**: `edad_media_stock_*_dias`, `share_stock_*_antiguo`, `stock_*_antiguo`. El mismo importe con 200 días no es el mismo riesgo que con 20.
- **Colchón de flujo**: `colchon_flujo_meses` = `suma(flujo_neto, 6m) / gastos_3m_avg`. Responde a la pregunta del runway con un 63,3% de cobertura frente al 3,8% de `runway_meses`.
- **Momentum y tijera**: `ingresos_momentum_3m`, `gastos_momentum_3m`, `flag_tijera` (ingresos cayendo y gastos subiendo). Visible antes de que el flujo neto se vuelva negativo.
- **Z-scores autorreferenciados**: `z_flujo_relativo`, `z_burn_rate`, `z_caja_ingresos`, `z_stock_prov_sobre_ingresos`. La base excluye el mes corriente (`shift(1)`) para que un mes anómalo no se diluya a sí mismo.
- **Percentiles transversales**: 7 columnas `pctl_*`. Umbrales estables frente a la deriva del agregado.
- **Concentración de contraparte**: `hhi_*`, `top1_*_share`, `n_contrapartes_*` y sus versiones `_3m`. Cierra una de las limitaciones declaradas.
- **Flags nuevos**: `flag_stock_prov_antiguo`, `flag_tijera`, con sus `_3m`, `_6m` y `persistente_*`.

Topes de cordura añadidos, todos auditables: `stock_*_sobre_ingresos` llegaba a 1.105.696 y `runway_meses` a 351.490 meses; los z-scores a 7×10¹⁶ por desviaciones típicas casi nulas; la edad media a 8.529 días por `due_date` corruptas. Sin acotar, un solo valor así destruye cualquier media, percentil o desviación posterior y contamina a las demás empresas al distorsionar la distribución transversal.

Eliminado: `burn_rate_cap` (duplicaba `burn_rate` recortado y nadie la leía).

`validate_features.py` comprueba ahora el rango declarado de 25 métricas acotadas y que `stock_*_antiguo <= stock_overdue_*`. Validación en 0 errores.

Pendiente: el `score_engine` todavía no lee ninguna de las métricas nuevas, así que la distribución de scores no ha cambiado en esta iteración. El orden de cambios propuesto está en la sección 11.4 de `FEATURES.md`.

El diccionario completo del panel, con fórmulas, cobertura medida, metodología de anticipación y el resumen de features prioritarias por origen, está en `FEATURES.md`. El recuento vigente es el de la última ejecución de `build_features`.

### Iteración 4 · Motor de scoring sobre evidencia medida

Motivación: cerrar el pendiente de la iteración 3, pero eligiendo los pesos **después** de medir qué señales anticipan, no antes. Para eso se añadieron dos scripts: `screen_signals.py` calcula el AUC y el lift de cada señal para que ocurra un evento de severidad en los 12 meses siguientes, y `evaluate_anticipation.py` mide la antelación real de la alerta contra la capa de nivel.

Esa medición cambió tres decisiones de diseño y descubrió un bug:

- **`flujo_volatilidad_6m` era el mejor predictor de asfixia del panel (AUC 0,71) y solo se usaba para amortiguar la trayectoria**, es decir, para descartarlo. Ahora penaliza el colchón, donde tiene sentido económico: un flujo errático exige más buffer.
- **La trayectoria tiene AUC 0,49 sobre eventos**, o sea nula. Mantiene peso (0,18) porque el reto pide dirección de forma explícita, pero bajó desde 0,25: sostener un cuarto del score con algo que no predice habría sido estético.
- **La primera alerta, disparada por dirección sostenida, tenía lift 0,90**: peor que el azar, y un baseline trivial la batía en todo. El diagnóstico es que el evento se define por nivel, así que cualquier señal de nivel lo predice por construcción. De ahí la separación en capa NIVEL y capa ANTICIPACIÓN, que solo se activa mientras el nivel aún es aceptable.
- **Bug en `pctl_mes`**: `rank(pct=True)` ordena por valor crudo, pero el docstring prometía "0 = peor, 1 = mejor". En deuda, impagos y edad el percentil estaba invertido, y la alerta llamaba "peor cuartil" al mejor. La firma exige ahora orientación explícita.

Añadido al panel (137 → 150 columnas): `flujo_pendiente_robusta_6m` (Theil-Sen, resistente al mes atípico que invierte el signo de una pendiente por mínimos cuadrados), `recuperacion_stock_prov` y `recuperacion_stock_clientes` (dirección de la deuda comercial con 69% de cobertura frente al 31% de `recuperacion_prov`), `ventas_acum` y `compras_acum` (permiten afirmar "ha comprado y no debe nada vencido", que es un dato y no un hueco) y 6 percentiles nuevos.

`flujo_relativo` se acotó a ±12: sin tope, la volatilidad llegaba a 515.466 y la pendiente a 446.406, y eso amortiguaba la trayectoria de **todas** las empresas al entrar en la distribución transversal.

Resultado: mediana de meses evaluados 6 → 19, empresas NO EVALUABLE 87 → 5, y la capa de anticipación gana 2 meses de mediana a la de nivel sobre asfixia de caja, detectando 41 eventos que esta no ve nunca. Validación en 0 errores.

El diseño completo del motor —los seis ejes con su peso y su justificación, las cascadas de cobertura, los moduladores, la contracción empírica, los dos canales de alerta con sus lifts medidos, las limitaciones y la respuesta razonada a por qué no Prophet ni XGBoost— está en **`SCORE_ENGINE.md`**.

### Iteración 5 · Las seis preguntas del reto y la granularidad

Motivación: comprobar, una por una, cuáles de las seis preguntas del enunciado contestaba el sistema de verdad. Tres estaban cubiertas y tres no.

**La pregunta 3 no se contestaba en absoluto.** Busqué en los datos el caso literal del enunciado ("de 82 a 68 sigue pareciendo sana"): empresas que venían de un score ≥68, pierden ≥10 puntos y siguen sobre 55. Hay 611. La alerta salía en el 2,7% de ellas, por debajo del 5,0% de la población general, así que el sistema era **peor que la media** en el caso que más importa. Y era estructural: los canales disparan por percentil adverso, y una empresa que cae de 82 a 68 no está en el quintil adverso de nada.

El detector nuevo (`senal_giro`) mide la caída en **sigmas de la propia empresa**, no en puntos ni en posición de cohorte. Hace falta porque el score mensual de la empresa mediana recorre 41,7 puntos, así que "ha caído 14" solo significa algo comparado con su propia variabilidad. Cobertura del caso: 2,7% → 30,4%.

**Bache o caída (pregunta 4)** se resuelve con tres criterios elegidos por lo que predijeron el desenlace observado, no por intuición: mi primer criterio tenía AUC 0,517 y se descartó. El que manda es la volatilidad propia del score, y la separación final es limpia: la caída estructural pierde 2,54 puntos más a 6 meses mientras el bache recupera 5,28.

**Por qué ha cambiado (pregunta 5)** es una descomposición exacta del Δscore por eje, separando lo que se movió por comportamiento de lo que se movió porque llegó dato nuevo. Sin esa separación el sistema diría "ha mejorado" cuando lo que pasó es que empezamos a verla.

Dos lecciones que quedan documentadas porque costaron una iteración cada una:

- **Fusionar el giro con los canales de cola los degradaba**: el lift caía de 1,52 a 1,04. Son dos señales que contestan preguntas distintas y se validan contra desenlaces distintos, así que viajan separadas.
- **El percentil contra referencia congelada mandaba los empates al borde inferior**, y `stock_prov_sobre_ingresos` vale 0 en el 60% de las filas. Se corrige con el punto medio del empate, como hace `rank()`.

**Granularidad (empresa o grupo).** El cálculo es por empresa y la vista de grupo va encima, nunca al revés: agregar es una proyección que no se deshace. El grupo explica el 61,9% de la varianza del score, así que importa, pero el 24,0% de los grupos tiene a la vez una empresa mejorando y otra deteriorándose, y en el 23,6% el agregado esconde una empresa en riesgo (`GROUP_0102` puntúa 53,58 ESTABLE con una filial a 30,78 CRÍTICA). Por eso `scores_grupo.csv` publica el agregado, la peor filial y el flag `agregado_esconde_problema` a la vez.

Nuevos artefactos: `scores_grupo.csv`, `pctl_reference.json`. Validación en 0 errores.

### Iteración 6 · Limpieza del repositorio y documentación

Motivación: dejar el sistema en un estado que el departamento de producto pueda leer sin acompañamiento, y que la evolución quede registrada en lugar de vivir en el historial de commits.

**Código muerto eliminado.** Una auditoría por AST del paquete encontró, y se han borrado: cuatro constantes huérfanas en `config.py` (`BURN_RATE_CAP`, residuo de una feature retirada en la iteración 3; `ALERTA_Z_DIRECCION` y `ALERTA_PCTL_NIVEL`, que solo usaba la función `motivo_deterioro` desaparecida al reescribir las alertas; y `BACHE_MESES_SOSTENIDO`, sobrante al colapsar la clasificación de caídas a dos clases), dos líneas inertes en la atribución de `score_engine.py` y un `import numpy` sin usar en `explore_data.py`. **Ningún archivo `.py` sobraba**: los siete del paquete están en uso.

**Referencias cruzadas corregidas.** El comentario de `PESOS` en `config.py` apuntaba a una sección de `FEATURES.md` que no existe, y describía la trayectoria en 0,25 cuando vale 0,18. `requirements.txt` estaba vacío.

**Documentación realineada con el sistema actual.** Los markdowns describían en varios puntos un motor que ya no existe:

| Documento | Qué estaba desalineado |
|---|---|
| `README.md` | Solo describía el reto, no lo construido. Reescrito como puerta de entrada con las seis preguntas, los resultados medidos y cómo se lee un score |
| `README_Data_Analysis.md` §5 | Documentaba **7 ejes con los pesos de la v1** (Liquidez 22%, Runway 18%, Apalancamiento 5%). Son 6 ejes desde la iteración 4 |
| `README_Data_Analysis.md` §2 | Faltaban `scores_grupo.csv`, `anticipation_report.csv` y `pctl_reference.json` |
| `README_Data_Analysis.md` §6 | Listaba como abiertas tres limitaciones ya cerradas (concentración, juventud, percentiles invertidos) |
| `FEATURES.md` §10.1 | Mapeo de ejes de la v1, sin las cascadas |
| `FEATURES.md` §10.3 | Presentaba el cuello de botella de cobertura como abierto, cuando la cascada lo resolvió (6 → 19 meses) |
| `FEATURES.md` §11.2 | **Proponía la regla de disparo que luego medimos con lift 0,90**, peor que el azar. Se conserva el apartado documentando el error |
| `FEATURES.md` §11.4 | Lista de seis pendientes, todos ya implementados. Ahora es una tabla de estado con el resultado real de cada uno |
| `FEATURES.md` §12.5 | Daba por retiradas features que siguen en el panel. Ahora distingue "eliminada" de "solo diagnóstico" |
| Recuentos | Panel 98/137 → **150** columnas; población por clasificación reajustada al último run |

**Nuevo en `SCORE_ENGINE.md` §3.1: el histórico de las tres calibraciones de peso** (v1 intuición → v2 dirección → v3 evidencia medida), con el motivo de cada movimiento. Era lo único de la evolución del sistema que no estaba escrito en ninguna parte.

### Iteración 7 · Poda antes de producto

Motivación: no entregar a producto un panel con columnas que nadie lee. Se dejaron
de calcular DSO/DPO, HHI, `flujo_yoy`, `flag_burn_alto`, percentiles y z-scores
huérfanos, rectificativas como columnas propias, deltas de recuperaciones
retiradas y conteos internos. El score no se mueve. El mapa de lo que producto
sí tiene que leer está en `ENTREGA_PRODUCTO.md` §8.

### Iteración 8 · Versión final

Se cruzó el panel con cada consumidor y se contrastó idea por idea con el score
de 13 métricas del equipo. El panel queda en **73 columnas**. Se adoptó el filtro
de flujo operativo, el servicio de deuda mensual y los recibos devueltos. Se
rechazó imputar 50, reconstruir la caja hacia atrás y dar a runway un 24% de
peso. Validación en 0 errores. La referencia de percentiles y el prior se
recalibraron porque cambió la definición de flujo.