### Análisis de Datos, Ingeniería de Variables y Motor de Scoring
### HackSpain 2026 · Reto Embat (X-Ray)
Este documento recoge la arquitectura completa de la fase de datos: qué hace cada componente del pipeline, cómo se transforman los datos crudos, qué fórmulas matemáticas rigen el motor de scoring, y cómo garantizamos que no haya data leakage temporal ni distorsiones aritméticas.

El principio rector del proyecto: ninguna transformación se aplica sin dejar constancia numérica de lo que descarta. Un dataset sintético con trampas premia al equipo que documenta y gestiona los sesgos, no al que los esconde para obtener una curva perfecta.

## 1. Arquitectura del Pipeline y Archivos
El sistema está diseñado en cuatro fases secuenciales e inmutables (ningún script modifica los CSV crudos, todo ocurre en memoria).

config.py             → Único punto de verdad: fechas, pesos, umbrales y mapeos.
explore_data.py       → data_quality_report.txt
build_features.py     → master_panel.csv + feature_audit.json
validate_features.py  → Guardián de integridad (falla con exit 1 si hay errores)
score_engine.py       → scores_mensuales.csv + scores_finales.csv + score_explanations.json

Funciones de cada script:
- config.py: Centraliza parámetros críticos. Si el jurado pide ajustar el peso de la morosidad o la ventana temporal, se cambia una línea aquí y se reejecuta todo.
- explore_data.py: Audita los CSV crudos sin unirlos. Detecta fechas en el año 6913, líneas de crédito sin límite, y evalúa la disponibilidad de columnas clave.
- build_features.py: El motor de ingeniería de datos. Resuelve multidivisa, mapea facturas a sus meses correctos (emisión vs. vencimiento), calcula saldos reales, genera las sumas móviles y ensambla el panel maestro de 25 meses estrictos por empresa.
- validate_features.py: Validador lógico. Antes de puntuar, comprueba matemáticamente que flujo = ingresos - gastos, que los ratios de morosidad están en [0, 100], y que los saldos actuales no se han propagado al pasado.
- score_engine.py: Aplica reglas expertas sobre las variables escala-libre para generar un score de 0 a 100, gestionando dinámicamente la falta de información y emitiendo justificaciones en lenguaje natural.

## 2. Artefactos Generados (Qué se crea y para qué sirve)
- master_panel.csv (El Tablero de Juego)
Es un panel de 1.286 empresas × 25 meses = 32.150 filas exactas. Si una empresa no operó en un mes, la fila existe con volúmenes a 0 y ratios a NaN. Esto garantiza que un rolling(3) significa literalmente 3 meses de calendario.

Columnas Absolutas: caja_ingresos, caja_gastos, flujo_neto, volumen_ventas, volumen_compras.

Columnas Relativas: pct_clientes_morosos_3m, pct_impagos_prov_3m, burn_rate, flujo_relativo.

Columnas de Snapshot: caja_real, deuda_viva. (Solo aparecen en el mes actual).

Columnas de Metadatos: mes_activo (booleano), peso_cubierto (% de factores con datos), confianza (alta/media/baja).

- scores_mensuales.csv
Añade la puntuación temporal a cada fila del panel.

score_mensual: Puntuación 0-100 del mes.

n_componentes_validos: Cuántos factores aportaron al score de ese mes. (Si el peso total es < 55%, el score cae a NaN).

- scores_finales.csv
El output consolidado para el leaderboard y la tabla principal del frontend.

score_final: Agregación ponderada de todo el histórico de la empresa.

clasificacion: Etiqueta de negocio (SALUDABLE, ESTABLE, EN RIESGO, FRÁGIL, CRÍTICO).

tendencia: MEJORANDO, ESTABLE, DETERIORANDO o SIN DATOS.

cobertura_media y confianza: Indicadores de cuán robusta es la nota.

- score_explanations.json
El puente hacia el producto final (Frontend/Agente LLM). Un diccionario por empresa que contiene el "por qué" exacto de su puntuación en el último mes evaluable, factor por factor (ej. "Runway crítico (1.2 meses de gasto cubiertos)"), junto con alertas pre-calculadas para el CFO.

## 3. Fórmulas Matemáticas Clave
El score no utiliza umbrales absolutos en euros (un límite de 50.000€ castiga a una multinacional y premia a un taller local). Todo opera sobre variables escala-libre:

1. Flujo Relativo: flujo_neto / ingresos_12m_avg

Propósito: Mide si el dinero que entra/sale es relevante para el tamaño de la empresa. Absorbe la estacionalidad al dividir por la media anual.

2. Burn Rate: gastos / ingresos

Propósito: Velocidad operativa de quema. Si los ingresos son 0, la variable es NaN y levanta el flag mes_sin_ingresos, penalizando a través de reglas lógicas en lugar de inventar infinitos.

3. Morosidad Móvil (Ej. Clientes 3M): sum(facturas_impagadas_3m) / sum(facturas_emitidas_3m)

Propósito: Protege contra meses de bajo volumen. Hacer la media de los ratios mensuales daría el mismo peso a un mes de 500€ que a uno de 500.000€. Todos los ratios se acotan a [0, 100] usando .clip(0, 100) para limpiar distorsiones de divisas o recargos.

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
Solución: Solo normalizamos a accounting_currency cuando existe un exchange_rate válido (>0). Las filas con monedas dispares y sin tipo de cambio se declaran nulas para cálculos financieros, priorizando perder una fila a sumar peras con manzanas.

4.4 Censura a la Derecha y Meses Parciales
Mes Parcial (2026-09): La extracción ocurre el 18 de septiembre. Puntuar un mes al 60% castiga el volumen absoluto. Se conserva en el panel, pero se excluye del scoring general.

Maduración (Censura): Las facturas de los últimos 45 días aún no han tenido tiempo estadístico para entrar en mora. Esos meses se marcan con morosidad_censurada = 1, lo que rebaja la fiabilidad del último score.

4.5 Rectificativas y Signos
Una rectificativa no es simplemente amount < 0. El pipeline usa coincidencia exacta en las columnas de tipo de documento o conceptos. El signo se usa solo como último recurso de fallback para deducir la dirección de la factura, nunca para asumir que es una corrección contable pura.

## 5. El Motor de Scoring: Por qué Reglas Expertas
No hemos utilizado XGBoost ni Random Forest porque no existe ground truth. Entrenar un modelo para predecir un target sintético creado por nosotros mismos hace que el modelo aprenda nuestra heurística pero con ruido, perdiendo la explicabilidad (caja negra).

El motor implementado:

Pondera 7 ejes: Liquidez (22%), Runway (18%), Morosidad Proveedores (18%), Tendencia (13%), Morosidad Clientes (12%), Eficiencia (12%), Apalancamiento (5%).

No imputa la ignorancia a la media: Si un mes no tiene ventas, el factor de morosidad clientes se apaga y su peso se reparte entre los demás.

Cobertura Mínima (0.55): Si faltan demasiados factores (ej. sin cuenta bancaria, sin ventas, sin compras), el mes devuelve NaN. Es mejor decir "NO EVALUABLE" que devolver un 50 aleatorio.

## 6. Limitaciones Declaradas
Un modelo robusto documenta lo que no puede resolver:

Concentración de Riesgo: Aunque extrajimos counterparty_id, el score actual no penaliza que el 80% de las ventas dependan de un solo cliente (queda como mejora para el producto final).

Operaciones Intragrupo: No hemos filtrado la facturación entre empresas del mismo group_id. Algunas métricas de "crecimiento" pueden ser simples movimientos internos de tesorería.

Puntos Ciegos de Deuda: Como la deuda no tiene histórico, no podemos penalizar a una empresa que se sobreapalancó hace 12 meses; el motor solo castiga la deuda en la foto final.

Falsos Positivos por Juventud: Empresas que nacen en el mes 24 sin impagos ni deuda, obtienen un score artificialmente alto (95.0) porque los únicos factores aplicables son caja positiva y runway infinito. Hemos mitigado esto pasando la etiqueta meses_evaluados = 1 y confianza = baja para que el frontend las filtre.