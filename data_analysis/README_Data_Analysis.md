# Análisis de Datos e Ingeniería de Variables (HackSpain Embat)

Este documento resume el trabajo realizado en la carpeta `data_analysis`. El objetivo de esta fase ha sido auditar los datos sintéticos proporcionados, limpiar las anomalías (trampas del dataset) y construir un **Panel Maestro** de características (*features*) robustas, basado en lógica financiera real, que alimentará nuestro motor de scoring.

## 1. Descubrimientos del Análisis Exploratorio (`explore_data.py`)

Al analizar los datos crudos, detectamos varias anomalías críticas que habrían arruinado cualquier modelo predictivo estándar:

*   **Fechas Imposibles (Dirty Data):** Existían registros con fechas en el año 6913, 2050 y "facturas zombis" pendientes desde 2018. 
*   **Líneas de crédito "Ciegas":** 534 de las 536 líneas de crédito reportadas tenían un límite concedido de `0`. Esto provocaba divisiones por cero (`inf%`), por lo que descartamos usar el consumo de crédito bancario como métrica principal.
*   **El verdadero riesgo es la Morosidad Comercial:** Descubrimos que la media del volumen facturado atrapado en estado `overdue` es del **54.3%** (más de 6.000 millones de euros en el dataset). Las empresas de este reto no mueren por sus deudas bancarias, sino porque **sus clientes no les pagan**.

## 2. Construcción del Panel Maestro (`build_features.py`)

Para cumplir con el requisito del jurado de evaluar **"Trayectorias y no fotos fijas"** y distinguir un **"Bache vs Caída estructural"**, procesamos las transacciones y facturas para crear `master_panel_clean.csv` (24.335 registros mensuales limpios).

### Reglas de Limpieza Aplicadas:
1.  **Time Windowing Estricto:** Filtramos los datos exclusivamente a la ventana de 24 meses evaluable (Sept 2024 - Sept 2026).
2.  **Valores Absolutos y Rectificativas:** Usamos valores absolutos para evitar que las facturas rectificativas (importes negativos) rompieran los porcentajes de morosidad generando ratios del 300%.

### Variables Creadas (Features):

*   **Flujo Neto Mensual (`flujo_neto`):** Ingresos reales vs Gastos reales en caja.
*   **Burn Rate (`burn_rate`):** Ratio de `Gastos / Ingresos`. Si una empresa gasta pero no ingresa nada, se le asigna un valor penalizador de 5.0 (quema pura de caja).
*   **Morosidad Bifurcada:** Separamos el riesgo en dos direcciones:
    *   `pct_clientes_morosos`: % de ventas del mes que los clientes no han pagado (Falta de liquidez entrante).
    *   `pct_impagos_prov`: % de compras del mes que la empresa no ha podido pagar (Síntoma de asfixia interna).
*   **Tendencias Temporales (Medias Móviles 3M):** 
    *   `flujo_neto_3m_avg`, `impagos_prov_3m_avg`, `clientes_morosos_3m_avg`.
    *   *Por qué es clave:* Permite al motor de scoring tener "memoria". Si una empresa tiene un mes fantástico de cobros, pero la media de 3 meses indica que no está pagando a proveedores, el modelo sabrá que es un bache positivo temporal, no una empresa sana.

## 3. Próximos Pasos

Con el archivo `master_panel_clean.csv` generado, tenemos un dataset 100% limpio y explicable. El siguiente paso es desarrollar el `score_engine.py`, que tomará estas tendencias y asignará una puntuación de salud financiera de 0 a 100 evaluando tanto el deterioro como la mejora estructural.