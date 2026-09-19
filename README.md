### HackSpain 2026: X Ray - Reto de Embat
## Descripción General
Este repositorio contiene la solución desarrollada para el reto "X Ray" propuesto por Embat en HackSpain 2026. El objetivo principal es construir un motor de scoring de salud financiera basado en el rastro transaccional de empresas y desarrollar un producto comercializable que utilice este score como núcleo.

## El Problema
Los análisis de riesgo financiero tradicionales se basan en fotografías estáticas (cuentas anuales, ratings desactualizados). Este proyecto busca analizar el rastro continuo y diario de la actividad financiera de una empresa (flujos de caja, facturación, deuda) para detectar su trayectoria real y anticipar cambios en su salud financiera antes de que sean evidentes.

## Objetivo del Proyecto
1. El Motor (Score): Un modelo predictivo que lee 24 meses de comportamiento financiero para calcular una puntuación dinámica.

2. El Producto: Una solución de valor construida sobre el score (por ejemplo, un marketplace de crédito, seguro financiero, agente de recomendaciones, etc.) orientada a un comprador claramente identificado.

## Funcionalidades Clave del Sistema
El modelo de scoring desarrollado está diseñado para responder a seis preguntas fundamentales:

- Identificación de salud: Reconocer empresas excepcionalmente sólidas, no solo aquellas en riesgo de quiebra.
- Detección de mejoras: Identificar empresas con métricas actuales mediocres pero con una trayectoria de mejora clara.
- Detección temprana de deterioro: Señalar empresas que parecen sanas pero cuyo comportamiento financiero indica problemas futuros.
- Discriminación de eventos: Distinguir entre un problema temporal de liquidez (bache) y un deterioro estructural.
- Explicabilidad: Justificar qué variables o señales exactas han motivado el cambio en la puntuación de un mes a otro.
- Anticipación: Medir cuántos meses antes del impacto real el sistema es capaz de detectar la anomalía o mejora.

## Conjunto de Datos
El proyecto utiliza un dataset sintético basado en distribuciones estadísticas reales de tesorería de PYMES.

1. Volumen: 1.286 empresas agrupadas en 250 grupos empresariales.

2. Ventana temporal: 24 meses de historia (septiembre 2024 a septiembre 2026).

3. Estructura de datos (archivos CSV):
- groups.csv: Estructura de grupos empresariales y holdings.
- companies.csv: Datos maestros de las empresas.
- banking_products.csv: Cuentas y productos bancarios.
- debt_products.csv: Financiación y líneas de crédito.
- debt_schedule_config.csv: Cuadros de amortización y condiciones de préstamos.
- transactions.csv: Movimientos bancarios históricos.
- invoices.csv: Facturas emitidas y recibidas.
- balances.csv: Saldos a 1 de septiembre de 2026.

## Requisitos de Entrega y Evaluación
La solución aborda los tres bloques de evaluación del reto:

1. Precisión del Modelo (Acierto)
- Generalización: Capacidad de puntuar correctamente un conjunto de test oculto de 60-80 empresas.
- Trayectoria: El modelo capta la dirección del movimiento, no solo el estado actual.
- Bidireccionalidad: Funciona con la misma eficacia para predecir mejoras y deterioros.

2. Anticipación (Llegar a tiempo)
- Tiempo de respuesta: Métrica demostrable de cuántos meses de antelación ofrece el sistema.
- Estabilidad temporal: Reducción de falsos positivos ante variaciones transitorias de caja.

3. Valor de Negocio (El Producto)
- Caso de Uso: Un producto funcional desarrollado sobre el motor de scoring.
- Modelo de Negocio: Comprador identificado y justificación del retorno de inversión.
- Transparencia: Sistema no opaco; las predicciones son completamente explicables.