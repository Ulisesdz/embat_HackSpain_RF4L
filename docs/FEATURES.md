# Diccionario de Features · `master_panel.csv`

Referencia de las columnas del panel maestro: qué mide cada una, con qué fórmula
se calcula, qué cobertura real tiene sobre el dataset y para qué sirve en el motor
de scoring.

Versión final: **69 columnas**. De 150 se podó lo que nadie leía; se adoptaron
dos señales del otro enfoque del equipo (`refund_rate`, `debt_service`) y se
restringió el flujo a tesorería operativa. La 69ª es `observado`: la máscara de
limpieza. **Producto solo necesita las ~25 de `ENTREGA_PRODUCTO.md` §8.**

- **Grano:** una fila por `company_id` × `year_month`. 1.286 empresas × 25 meses = 32.150 filas exactas.
- **Ventana:** 2024-09 → 2026-09. El último bucket (2026-09) es parcial y queda fuera del score.
- **Regla de oro:** `NaN` significa "sin evidencia", `0` significa "medido y vale cero". Nunca se imputan.
- **Tope de cordura:** `burn_rate` se recorta a 8×. Sin eso, COMP_0009 en 2026-03
  salía a 179× y envenenaba la media 3m del eje de eficiencia. `runway_meses` solo
  existe el mes de la foto de caja (2026-08). La tabla que imprime el pipeline es
  el ejemplo para defender ambas reglas.
- **Limpieza:** cada corrección (fechas, ceros, winsor, saldos extremos, ventana) se cuenta en `data/features/cleaning_log.json`.
- La columna `nan%` es la cobertura medida en la última ejecución. Un `nan%` alto no
  es un defecto en sí: indica cuánta evidencia existe realmente, y el motor lo usa
  para decidir si puede puntuar el mes.

---

## 1. Claves y dimensiones

| Columna | nan% | Qué es |
|---|---|---|
| `company_id` | 0% | Clave de empresa. Estable en todos los CSV del dataset. |
| `year_month` | 0% | Periodo mensual (`Period[M]` serializado como `YYYY-MM`). |
| `group_id` | 0% | Grupo empresarial. Necesario para detectar facturación intragrupo (pendiente). |
| `observado` | 0% | `True` entre el primer mes completo y el último con tx o factura. Fuera, los volúmenes son NaN, no 0. |

`sector` no existe en este dataset: `companies.csv` solo trae `country`, `currency`,
`erp` y `created_at`. Cualquier normalización sectorial tendría que derivarse del
`erp` o del país, y no se ha hecho.

---

## 2. Flujos de caja bancarios (`transactions.csv`)

Todo se agrega por mes de `date` (fecha contable). Signo según el diccionario de
datos: negativo = salida, positivo = entrada.

| Columna | nan% | Fórmula |
|---|---|---|
| `caja_ingresos` | >0% fuera de ventana | `sum(amount)` de flujos **operativos** en cuentas de tesorería. 0 si hay ventana y no hubo movimiento; NaN si el mes no está observado |
| `caja_gastos` | >0% fuera de ventana | Igual, salidas |
| `flujo_neto` | >0% fuera de ventana | `caja_ingresos − caja_gastos` |
| `refund_rate` / `refund_rate_3m` | ~36% / 36% | `collection_refund / cobros` (recibos devueltos) |
| `debt_service` / `debt_service_3m` | ~32% / 32% | `(debt_repayment + interest_charge) / ingresos` |

**Qué cuenta como flujo operativo.** Cuentas `checking`, `saving`, `wallet`,
`tpv`, `expensesPlatform`. Fuera: `card` (el cargo llega después a la corriente),
cuentas de deuda, y las categorías `transfer` (152 k), `investment_*` (7 k) y
`debt_repayment` / `interest_charge` (31 k, esas van a `debt_service`). Sin el
filtro, un traspaso entre cuentas propias inflaba ingresos. El validador sigue
comprobando `flujo_neto = caja_ingresos − caja_gastos` sobre el set filtrado.

**Uso en el score:** no se usan en bruto. Un gasto de 400.000 € es normal para un
grupo y letal para un taller, así que solo entran normalizados (sección 6).

---

## 3. Actividad facturada (`invoices.csv`)

### 3.1 Qué filas cuentan como factura

`invoices.csv` no es un fichero de facturas puro. De 897.894 filas se descartan:

| Motivo | Filas | Por qué |
|---|---|---|
| `document_type` no comercial | 121.695 | `paymentDocument`, `note`, `deposit`, `deliveryNote`, `purchaseOrder`, `other`, `cheque`. Un pedido o un albarán no genera derecho de cobro; un documento de pago no es la factura. |
| `status = cancel` | 12.107 | Una factura anulada no es ni volumen ni deuda. |
| `amount = 0` | (ver `cleaning_log`) | Un documento a cero no es derecho de cobro ni de pago. |

Quedan `invoice` + `invoiceGroup` + `refund` con importe distinto de 0. El set está en
`cfg.TIPOS_DOC_COMERCIAL`, así que la decisión es reversible en una línea, y el
desglose de lo excluido queda en `inv_doc_excluidos_por_tipo` de la auditoría.

**Reparaciones de fecha e importe** (contadas en `cleaning_log.json`):

- `due_date` NaT, anterior a la emisión o con plazo > 730 días → `issuance_date + 30d`. Sin esto, un vencimiento en el año 2000 metía la factura como impago desde el primer mes del panel.
- `fecha_cobro` de una cobrada (pendiente liquidado) posterior a la extracción o anterior a emitir → recorte. La verdad del cobro sigue siendo `pending_amount`, no `status == paid`.
- Winsor p99 por empresa y dirección: una factura de 6e10 no puede dominar el ratio.
- Facturas vencidas antes de 2024-09 que siguen con pendiente se recuperan para el stock. `payment_date` sola las expulsaba porque en overdue viene rellenada con el vencimiento.

### 3.2 Dos calendarios distintos, a propósito

Una factura tiene dos fechas relevantes y cada una responde a una pregunta:

- **`issuance_date` → `volumen_*`**: cuánto negocio generó la empresa ese mes.
- **`due_date` → `volumen_vencido_*`**: cuánto le tocaba cobrar o pagar ese mes.

Mezclarlos fue el error original del pipeline: dividir impagos que vencen en marzo
entre facturas emitidas en marzo da ratios por encima del 100%.

| Columna | nan% | Fórmula |
|---|---|---|
| `volumen_ventas` | >0% fuera de ventana | `sum(|amount|)` de facturas cobrables, por mes de **emisión**. NaN fuera de la ventana observada |
| `n_fact_ventas` | 0% | Número de facturas cobrables emitidas |
| `volumen_vencido_ventas` | 0% | `sum(|amount|)` de facturas cobrables, por mes de **vencimiento** |
| `n_fact_vencidas_ventas` | 0% | Número de facturas cobrables que vencen |
| `atrapado_ventas` | 0% | `sum(|amount|)` de las vencidas ese mes que seguían impagadas a fin de mes |
| `volumen_compras`, `n_fact_compras`, `volumen_vencido_compras`, `n_fact_vencidas_compras`, `atrapado_compras` | 0% | Idénticas, para facturas pagables |

Las rectificativas (`document_type = refund`) quedan **fuera** de `volumen_*`,
`volumen_vencido_*` y `atrapado_*`: un abono no es actividad comercial nueva ni
un cobro pendiente. No se emiten columnas propias (nadie las leía).

### 3.3 La dirección de la factura (venta vs compra)

`invoices.csv` **no tiene columna de dirección**. Las columnas son `operation_id`,
`company_id`, `document_type`, las tres fechas, `amount`, `pending_amount`,
`currency`, `accounting_currency`, `exchange_rate`, `status`, `concept` y
`counterparty_id`. Hay que deducirla, y el pipeline lo intenta en cascada:

1. Columna explícita de dirección → no existe.
2. `client_id` / `supplier_id` → no existen.
3. **Flujo bancario por `counterparty_id`**: `counterparty_id` es el mismo espacio de IDs en facturas y transacciones. Si el neto bancario de la empresa con esa contraparte es positivo, es un cliente. Solo cubre el **48,9%** de las facturas, por debajo del umbral del 80%, así que se descarta como método principal.
4. **Texto de `concept`**: solo clasifica sin ambigüedad el **6,1%**. Descartado (el umbral es 95%).
5. **Signo de `amount`**: positivo = cobrable, negativo = pagable. Es el método en uso.

Esa cascada no es un fallback ciego: el paso 3 se usa como **validación cruzada**
del paso 5. En el 48,9% de facturas donde ambos métodos opinan, coinciden en el
**93,6%** de los casos (`direccion_acuerdo_contraparte_vs_signo`). Los repartos
también son coherentes (38%/62% por contraparte, 41%/59% por signo). Es la mejor
evidencia disponible de que la convención de signo del dataset es
receivable(+) / payable(−).

### 3.4 El impago se reconstruye as-of, y `payment_date` no basta

Este es el punto más delicado del pipeline, y donde estaba el bug que dejaba toda
la morosidad a cero.

`payment_date` está poblada en el **99,99%** de las filas, **incluidas las 192.554
con `status = overdue` y `pending_amount = amount`**. Para una factura no cobrada
es una fecha *prevista*, no un cobro. Al tratarla como cobro real, toda factura que
vencía parecía cobrada el mismo día y `atrapado_* = 0` en todo el panel.

Criterio actual: una factura está cobrada solo si su pendiente está liquidado.

```
cobrada        = pending_amount <= TOLERANCIA_COBRO (0,01)
fecha_cobro    = payment_date  si cobrada,  NaT en caso contrario
is_overdue(m)  = due_date <= fin_de_mes(m)  AND  (fecha_cobro es NaT  OR  fecha_cobro > fin_de_mes(m))
```

Resultado: 566.294 facturas cobradas y 197.785 abiertas al cierre. Esto **no** es
look-ahead: para cada mes solo se usa información disponible a fin de ese mes. Una
factura cobrada con 40 días de retraso figura como impagada en la foto del mes en
que venció y como cobrada después, que es lo que ocurrió en realidad.

**Importe del impago:** se usa el nominal (`|amount|`), no `pending_amount`.
`pending_amount` es el saldo *en la extracción*, así que usarlo como numerador
histórico anula retrospectivamente cualquier impago que acabara cobrándose. Solo
5.954 facturas están parcialmente pagadas, así que el sesgo de usar el nominal es
menor que el de borrar el historial.

### 3.5 Stock vivo de impago

El stock no se acumula con deltas (`cumsum` de entradas menos salidas), porque
cualquier desajuste de signo se arrastra para siempre y no puede representar
facturas ya vencidas antes del inicio de la ventana.

Cada factura impagada **ocupa explícitamente su tramo de meses**, del mes de
vencimiento al mes anterior a su cobro (o hasta el fin de ventana si nunca se
cobra). El stock de un mes es la suma de los tramos vivos en ese mes. Se incluyen
las facturas con `due_date` anterior a 2024-09 que seguían abiertas.

| Columna | nan% | Qué es |
|---|---|---|
| `stock_overdue_clientes` | 0% | Importe impagado por clientes, vivo a fin de mes |
| `stock_overdue_prov` | 0% | Importe que la empresa debe a proveedores, vivo a fin de mes |
| `stock_clientes_antiguo` | 0% | Parte del stock con más de 90 días vencida |
| `stock_prov_antiguo` | 0% | Igual, frente a proveedores |

**Uso en el score:** `stock_overdue_prov` es la señal más incriminatoria del panel.
Un ratio mensual puede ser un pico; un stock que crece mes a mes es asfixia.

### 3.5.1 Antigüedad del impago

El mismo importe atrapado no significa lo mismo con 20 días que con 200. La
antigüedad es lo que separa un retraso de gestión de un impago estructural, y se
degrada de forma gradual, lo que la hace útil para anticipar.

| Columna | Cobertura | Fórmula |
|---|---|---|
| `edad_media_stock_prov_dias` | 43,7% | `sum(importe × días_vencido) / sum(importe)`, sobre el stock vivo |
| `share_stock_prov_antiguo` | 43,7% | `stock_prov_antiguo / stock_overdue_prov` |
| `edad_media_stock_clientes_dias` | 36,3% | Igual, cohorte de clientes |
| `share_stock_clientes_antiguo` | 36,3% | Igual |

Los días se acotan a `CAP_DIAS_IMPAGO` (720). Sin el tope, facturas con `due_date`
corrupta producían edades medias de 8.529 días (año 1993).

La cobertura es del 37–44% porque la edad solo existe si hay stock (`NaN` cuando
el stock es cero, que es lo correcto: una empresa sin impagos no tiene "edad de
impago"). La mediana es de **95 días** y el p90 de **316**: en este dataset, cuando
hay impago, tiende a ser antiguo.

### 3.6 Días de retraso (calculados y retirados)

`dso_dias` / `dpo_dias` se calcularon (media de `fecha_cobro − due_date`, acotada
a [0, 365]) y **no entraron al motor**: se solapan con `edad_media_stock_*`, que
tiene mejor cobertura y no depende de fechas de cobro fiables. 83.235 filas
tienen `payment_date` corrupta (`inv_retraso_corrupto_recortado`). No se vuelven
a emitir.

---

## 4. Multidivisa

El dataset mezcla monedas (38.763 facturas con `currency != accounting_currency`).
Los importes se normalizan a `accounting_currency`:

```
amount_reporting = amount                  si currency == accounting_currency
                 = amount * exchange_rate  si EXCHANGE_RATE_MIN <= rate <= EXCHANGE_RATE_MAX
                 = NaN                     en cualquier otro caso
```

El rango es `[0.001, 2500]`. Con un simple `rate > 0` entraban tipos de 0,0002 y
20.303 que por sí solos torcían el volumen de una empresa entera. Tras el filtro,
el máximo observado baja a 1.110,24. 511 filas quedan no convertibles y se
declaran nulas para cálculos financieros: mejor perder una fila que sumar peras
con manzanas.

La misma regla se aplica a `debt_products.csv`, donde antes se sumaba `outstanding`
en divisas distintas sin convertir.

---

## 5. Ratios operativos

| Columna | nan% | Fórmula | Nota |
|---|---|---|---|
| `burn_rate` | 37,0% | `caja_gastos / caja_ingresos`, topado a 8× | `NaN` si no hay ingresos, nunca infinito. El tope evita que un mes 179× envenene la media 3m |
| `mes_sin_ingresos` | 0% | `1` si `caja_ingresos == 0` y `caja_gastos > 0` | Convierte el `NaN` del burn rate en una señal explícita |
| `pct_clientes_morosos` | 67,4% | `100 × atrapado_ventas / volumen_vencido_ventas` | Mismo mes de vencimiento en numerador y denominador |
| `pct_impagos_prov` | 59,1% | `100 × atrapado_compras / volumen_vencido_compras` | |

Sin `.clip(0, 100)`. Si el ratio se sale del rango es un error de cohorte, y
recortarlo lo esconde. El validador falla a propósito en ese caso, con una
tolerancia de 1e-6 para el ruido de coma flotante (una suma móvil donde numerador
y denominador coinciden devuelve `100.00000000000004`).

### 5.1 Morosidad sobre sumas móviles

La mediana de facturas que vencen en un mes es 0, y el percentil 75 son 2. Hacer
la media de ratios mensuales daría el mismo peso a un mes de 500 € que a uno de
500.000 €, así que se suman numerador y denominador antes de dividir:

```
ratio_3m = 100 × sum(atrapado, 3 meses) / sum(volumen_vencido, 3 meses)
```

Si la ventana de 3 meses no llega a `MIN_FACTURAS_RATIO` (2) facturas vencidas, se
intenta con 6 meses y `MIN_FACTURAS_RATIO_LARGO` (3). Si tampoco, `NaN`.

| Columna | nan% | Qué es |
|---|---|---|
| `pct_clientes_morosos_3m` | 64,3% | Morosidad de clientes ponderada por importe |
| `pct_impagos_prov_3m` | 56,6% | Morosidad frente a proveedores |
| `pct_clientes_morosos_3m_fuente` | 0% | `3m` / `6m` / `sin_datos`: qué ventana sostiene el dato |
| `pct_impagos_prov_3m_fuente` | 0% | Igual |

Las columnas `_fuente` existen para que la confianza sea auditable: un dato
sostenido por 6 meses es más débil que uno de 3, y el panel baja la confianza de
`alta` a `media` en ese caso.

Distribución actual (mediana ≈ 47% clientes, ≈ 41% proveedores, con el 75%
percentil cerca del 100%): la morosidad **discrimina**. Antes del arreglo era 0,0
constante, lo que regalaba un 100/100 en el 30% del peso del score a todas las
empresas por igual.

---

## 6. Variables escala-libre

El núcleo del motor. Un umbral en euros castiga a una multinacional y premia a un
taller, así que todo lo que puntúa es un ratio.

| Columna | Cobertura | Fórmula |
|---|---|---|
| `ingresos_3m_avg` | 100% | Media móvil 3m de `caja_ingresos` (`min_periods=1`) |
| `ingresos_12m_avg` | 92% | Media móvil 12m de `caja_ingresos` (`min_periods=3`) |
| `gastos_3m_avg` | 100% | Media móvil 3m de `caja_gastos` |
| `flujo_relativo` | 68,7% | `flujo_neto / ingresos_12m_avg` |
| `flujo_relativo_3m` | 60,7% | Media móvil 3m estricta de `flujo_relativo` |
| `runway_meses` | **3,8%** | `caja_real / media(caja_gastos, 3m)`, acotado a [−12, 120] |
| `deuda_sobre_ingresos` | 1,2% | `deuda_viva / (ingresos_12m_avg × 12)` |
| `stock_prov_sobre_ingresos` | 68,7% | `stock_overdue_prov / ingresos_12m_avg`, acotado a [0, 24] |
| `stock_clientes_sobre_ingresos` | 68,7% | Igual, cohorte de clientes |
| `stock_prov_sobre_ingresos_topado` | 100% | `1` si el valor crudo superaba el tope (500 filas) |
| `stock_clientes_sobre_ingresos_topado` | 100% | Igual (461 filas) |

`flujo_relativo` divide por la media de 12 meses, no por el mes corriente: absorbe
la estacionalidad y evita que un mes flojo infle artificialmente el ratio.

`runway_meses` exige `MIN_MESES_RUNWAY = 3` meses reales de gasto. Con
`min_periods=1`, una empresa recién nacida con un primer mes de gasto casi nulo
obtiene un runway al techo.

**Los topes no son cosmética.** Con `ingresos_12m_avg` cercano a cero,
`stock_prov_sobre_ingresos` llegaba a 1.105.696 y `runway_meses` a 351.490 meses.
Un solo valor así destruye cualquier media, percentil o desviación típica que se
calcule después, y contamina a las demás empresas al distorsionar la distribución
transversal. El flag `_topado` deja constancia de cuántas filas se recortaron, para
que el recorte sea auditable y no un dato inventado en silencio.

### 6.1 Colchón de flujo: el runway que sí existe todos los meses

`runway_meses` cubre el 3,8% de las filas porque `caja_real` es un snapshot de un
único mes. Eso deja el eje de liquidez estructural apagado en el 96% del panel.

| Columna | Cobertura | Fórmula |
|---|---|---|
| `colchon_flujo_meses` | 63,3% | `suma(flujo_neto, 6m) / gastos_3m_avg`, acotado a [−24, 24] |

Mide cuántos meses de gasto ha generado (o quemado) la empresa **por sí misma** en
el último semestre. Negativo significa que está consumiendo colchón. No sustituye
al runway real, pero sí existe en 16 veces más filas, y responde a la misma
pregunta de fondo: cuánto aguanta si nada cambia.

### 6.2 Momentum de flujos

Las transacciones son la única fuente sin huecos, así que aquí viven las señales
que sí existen en los 24 meses.

| Columna | Cobertura | Fórmula |
|---|---|---|
| `ingresos_momentum_3m` | 57,6% | `ingresos_3m_avg / ingresos_3m_avg(t−3) − 1`, acotado a [−1, 5] |
| `gastos_momentum_3m` | 60,0% | Igual para gastos |
| `flag_tijera` | 100% | `1` si ingresos caen >5% y gastos suben >5% simultáneamente |

`flag_tijera` es el patrón de deterioro estructural clásico, y se puede ver **antes**
de que `flujo_neto` se vuelva negativo: cuando las dos curvas se cruzan ya es
tarde, cuando divergen todavía no. Activo en 1.208 filas.

Como todos los flags, genera `flag_tijera_3m` y `persistente_flag_tijera`.
La versión `_6m` se podó: no alimentaba nada.

### 6.3 Concentración de contraparte

`counterparty_id` es el mismo espacio de IDs en facturas y transacciones, lo que
permite medir dependencia comercial. El README la tenía declarada como limitación
pendiente.

| Columna | Cobertura | Fórmula |
|---|---|---|
| `top1_clientes_share` / `top1_prov_share` | 32,2% / 41,2% | Peso de la mayor contraparte del mes |
| `top1_prov_share_3m` | 45,8% | Versión suavizada a 3 meses (la que lee el modulador) |
| `top1_clientes_share_3m` | 37,6% | Igual, cohorte de clientes |

La concentración **no es riesgo por sí misma: es el multiplicador del riesgo.** Un
impago del 40% de las ventas es letal si viene de un cliente y gestionable si viene
de veinte. En este dataset la mediana de `top1_clientes_share` es **0,71**, así que
la dependencia es alta de forma generalizada.

El HHI y el conteo de contrapartes se calcularon y se retiraron: el modulador
solo usa `top1_*_share_3m`.

---

## 7. Tendencia, persistencia y recuperación

Aquí está lo que el reto pide de verdad: dirección del movimiento, no la foto.

| Columna | nan% | Fórmula |
|---|---|---|
| `flujo_neto_3m_avg`, `flujo_neto_6m_avg` | 8,0% / 20,0% | Medias móviles estrictas de `flujo_neto`. La de 6 meses se conserva porque el validador comprueba su estrictez |
| `burn_rate_3m_avg` | 48,0% | Media móvil del burn rate |
| `clientes_morosos_3m_avg` | 69,1% | Suavizado de la morosidad de clientes |
| `impagos_prov_3m_avg` | 61,9% | Suavizado de la morosidad de proveedores |
| `impagos_prov_3m_vs_prev3m` | ~69% | `media(últimos 3m) − media(3m anteriores)` de la morosidad a proveedores |
| `recuperacion_prov` | 69,4% | `−impagos_prov_3m_vs_prev3m`. Fallback del eje de trayectoria |
| `recuperacion_stock_prov` / `recuperacion_stock_clientes` | ~69% / ~26% | Dirección del stock normalizado. Positivo = mejora |
| `flujo_pendiente_6m` | 39,1% | Pendiente de regresión lineal de `flujo_relativo` sobre 6 meses (fallback) |
| `flujo_pendiente_robusta_6m` | 60,9% | Theil-Sen: la que manda |
| `flujo_volatilidad_6m` | 39,1% | Desviación típica de `flujo_relativo` en 6 meses |

El signo de las `recuperacion_*` se invierte a propósito para que, en todas ellas,
**positivo signifique mejora**. Esa simetría es lo que da bidireccionalidad al
motor: la misma variable premia y castiga.

### 7.1 Anomalía contra la propia historia (z-scores)

La primitiva de anticipación más importante del panel.

| Columna | Cobertura | Fórmula |
|---|---|---|
| `z_caja_ingresos` | 59,8% | `(x − media_12m) / desv_12m`, base **excluyendo** el mes corriente |
| `z_stock_prov_sobre_ingresos` | 26,2% | Igual |

Dos detalles de diseño que importan:

1. **La base excluye el mes corriente** (`shift(1)` antes del rolling). Se compara el presente contra el pasado, no contra una media que ya contiene el presente. Sin el desplazamiento, un mes anómalo se diluye a sí mismo y la señal se amortigua justo cuando debería dispararse.
2. **Se acota a ±10 sigmas** (`Z_CLIP`). Con una desviación típica casi nula el cociente llegaba a 7×10¹⁶. Más allá de 10 sigmas el valor exacto no aporta: ya es "fuera de su normal" con la máxima intensidad.

Por qué anticipa: un umbral absoluto solo se dispara cuando el daño ya ocurrió. El
z-score detecta que una empresa se sale de **su** normal mientras sus valores
absolutos siguen pareciendo aceptables. Y hace directamente comparables a la pyme
y al grupo, porque cada una se mide contra su propia escala.

### 7.2 Posición relativa dentro del mes (percentiles)

| Columna | Cobertura |
|---|---|
| `pctl_flujo_relativo_3m` | 60,7% | Canal asfixia |
| `pctl_burn_rate_3m` | 52,0% | Canal asfixia |
| `pctl_clientes_morosos_3m` | 35,7% | Canal impago |
| `pctl_stock_prov_sobre_ingresos` | 68,7% | Canal impago |
| `pctl_stock_clientes_sobre_ingresos` | ~26% | Canal impago (contagio) |
| `pctl_colchon_flujo_meses` | 63,3% | Canal asfixia |
| `pctl_runway_meses` | 3,8% | Modulador del colchón |
| `pctl_flujo_volatilidad_6m` | 60,9% | Canal asfixia + modulador del colchón |
| `pctl_recuperacion_stock_prov` | 68,7% | Canal impago |
| `pctl_flujo_pendiente_robusta_6m` | 60,9% | Canal asfixia |

Rango percentil de cada empresa **dentro de su mes**, calculado sobre las 1.286
empresas. Un umbral absoluto envejece: lo que era morosidad alta en 2024 puede ser
la norma en 2026, y el score se desplazaría entero sin que ninguna empresa haya
cambiado. El rango relativo neutraliza esa deriva agregada y permite expresar
reglas como "peor decil de su cohorte este mes", que es además mucho más fácil de
defender ante un comité de riesgos que un número absoluto.

Contrapartida a tener presente: en una recesión general, los percentiles ocultan
que **todo el mundo** empeora. Por eso conviene combinarlos con el nivel absoluto,
no sustituirlo.

### 7.3 Flags de estrés y persistencia

La clave para separar un bache de un deterioro estructural.

| Columna base | Condición |
|---|---|
| `flag_flujo_negativo` | `flujo_neto < 0` |
| `flag_estres_prov` | `pct_impagos_prov_3m >= 30` |
| `flag_estres_clientes` | `pct_clientes_morosos_3m >= 30` |
| `flag_stock_prov_antiguo` | `share_stock_prov_antiguo >= 0,5` |
| `flag_tijera` | Ingresos cayendo y gastos subiendo |

Cada una genera dos derivadas:

- `*_3m`: cuántos de los últimos 3 meses cumplieron la condición (rolling estricto).
- `persistente_*`: `1` si los **tres** últimos meses la cumplieron.

Un mes con flujo negativo es ruido; tres seguidos es una tendencia.
`flujo_volatilidad_6m` completa la imagen: mucha varianza con media estable es una
empresa cíclica, no una empresa que se hunde.

---

## 8. Snapshots: caja y deuda

`balances.csv` está fechado siempre a 2026-09-01 y `debt_products.csv` no tiene
fecha. Son **fotos actuales, no histórico**, así que se inyectan únicamente en el
último mes completo evaluable (2026-08). Propagarlos al pasado generaría un runway
ficticio en 2024.

| Columna | nan% | Qué es |
|---|---|---|
| `caja_real` | 96,1% | Suma de saldos en cuentas de tesorería |
| `caja_reportada` | 0% | `1` si la empresa tiene saldo visible. Distingue "sin visibilidad" de "cero en caja" |
| `caja_negativa_flag` | 96,1% | `1` si el saldo agregado es negativo. `0` si hay foto y el saldo no es negativo. `NaN` si no hay foto. El motor compara `== 1`; `bool(nan)` es True y convertía "sin visibilidad" en penalización |
| `deuda_viva` | 98,8% | `sum(|outstanding|)` convertido a EUR |
| `n_deudas` | 98,8% | Productos de deuda convertibles |
| `deuda_multimoneda`, `deuda_no_eur` | 98,8% | Flags de riesgo de conversión |
| `deuda_conversion_incompleta` | 98,8% | `1` si algún producto no se pudo convertir |
| `deuda_signo_negativo_flag` | 98,8% | `1` si el `outstanding` bruto venía negativo |
| `snapshot_financiero_disponible` | 0% | `1` si hay caja o deuda en esa fila |

El `nan%` del 96–99% **es correcto por construcción**: 1 mes de 25 con dato equivale
a un 96% de vacío. `caja_real` cubre 1.267 de 1.286 empresas en ese mes.

Tipos incluidos como caja: `checking` y `saving`. Se excluyen a propósito `card`,
`tpv`, `investment` y `expensesPlatform`: no son caja disponible para pagar
nóminas. Dos saldos centinela quedan fuera.

En deuda se agregan 2.239 productos de 8 tipos, incluidos `guarantee` (155) y
`confirming` (229). Son riesgo **contingente**, no dispuesto, así que el
apalancamiento actual está sobreestimado para esas empresas.

---

## 9. Metadatos, disponibilidad y confianza

| Columna | nan% | Qué es |
|---|---|---|
| `tx_disponible`, `ventas_disponible`, `compras_disponible` | 0% | Hay actividad de ese tipo en el mes |
| `mes_activo` | 0% | Alguna de las tres es `1` |
| `meses_activos_acum` | 0% | Meses activos acumulados hasta la fecha |
| `mes_parcial` | 0% | `1` para 2026-09 (extracción a mitad de mes) |
| `morosidad_censurada` | 0% | `1` si el mes cerró hace menos de `DIAS_MADURACION` (45) días |
| `confianza` | 0% | `baja` / `media` / `alta` |

`confianza` se degrada por cuatro motivos acumulativos:

1. `< 6` meses activos → `baja`.
2. `< 12` meses activos → `media`.
3. Morosidad censurada (el impago aún no ha madurado) → rebaja `alta` a `media`.
4. Morosidad sostenida solo por ventana de 6 meses → rebaja `alta` a `media`.
5. Mes parcial → `baja`.

Reparto actual: 14.550 `baja`, 8.848 `media`, 8.752 `alta`.

---

## 10. Cómo alimenta esto al score engine

### 10.1 Mapeo actual eje → feature

Son **6 ejes**, y cada uno resuelve una **cascada** de fuentes ordenada de la más
precisa a la más disponible. El eje solo se apaga si ninguna fuente tiene dato.

| Eje | Peso | 1ª opción | 2ª opción | 3ª opción |
|---|---|---|---|---|
| Deuda comercial | 0,20 | `pct_impagos_prov_3m` | `stock_prov_sobre_ingresos` | "ha comprado y no debe nada vencido" |
| Liquidez | 0,18 | `flujo_relativo_3m` | `flujo_relativo` del mes | — |
| Colchón | 0,18 | `colchon_flujo_meses` | `runway_meses` | — |
| Trayectoria | 0,18 | ≥1 de 4 señales direccionales | — | — |
| Eficiencia | 0,14 | `burn_rate_3m_avg` | `burn_rate` del mes | — |
| Cobro de clientes | 0,12 | `pct_clientes_morosos_3m` | `stock_clientes_sobre_ingresos` | "ha vendido y no le deben nada vencido" |

El **apalancamiento ya no es un eje**. Con 1,2% de cobertura, un peso fijo del 5%
no penalizaba a quien estaba apalancado: bloqueaba el score de todos los demás.
Ahora es un modulador acotado de ±8 puntos.

Un eje sin dato no se imputa a la media: se apaga y su peso se reparte entre los
demás. Si el peso cubierto queda por debajo de `MIN_PESO_CUBIERTO_SCORE` (0,55),
el mes devuelve `NaN`. Es mejor decir "NO EVALUABLE" que un 50 inventado.

El tercer escalón de la cascada merece atención porque es el que más cobertura
aporta: **un stock de impago igual a cero no es ausencia de dato, es un dato
excelente**. Antes, una empresa con historial de compras y sin un euro vencido era
indistinguible de una empresa sin información. Para poder afirmar "ha comprado y no
debe nada" se añadieron `compras_acum` y `ventas_acum` al panel.

### 10.2 Agregación temporal

```
Peso_mes = Decaimiento_exponencial(vida_media = 6 meses) × Confianza × Cobertura
```

Con `PESO_CONFIANZA = {alta: 1,0, media: 0,65, baja: 0,30}`. Los meses recientes
pesan más, pero un mes antiguo con cobertura perfecta retiene influencia frente a
uno reciente con datos dudosos.

### 10.3 El cuello de botella de cobertura, y cómo se resolvió

Este apartado se conserva porque explica el problema que más condicionó el diseño
del motor.

**El diagnóstico.** El runway (18%) y el apalancamiento (5%) solo existen en **un**
mes de 25, así que el 23% del peso estaba apagado en el 96% de las filas. Los ejes
estructuralmente disponibles sumaban:

```
liquidez 0,22 + eficiencia 0,12 + tendencia 0,13 = 0,47  <  0,55
```

Un mes sin morosidad medible **no alcanzaba el mínimo**, aunque tuviera flujos
perfectos. De ahí una mediana de 6 meses evaluados de 25 y 615 empresas con
tendencia `SIN DATOS`. Sin una serie densa de scores mensuales no se puede
demostrar anticipación, que es uno de los tres bloques de evaluación del reto.

**La solución fue la cascada de §10.1**, no bajar el umbral. La diferencia importa:
bajar `MIN_PESO_CUBIERTO_SCORE` habría tolerado la ausencia de evidencia; la
cascada **añade** evidencia usando fuentes con más cobertura y tratando el stock
cero como el dato informativo que es.

| | Antes | Ahora |
|---|---|---|
| Mediana de meses evaluados | 6 | **19** |
| Empresas NO EVALUABLE | 87 | **5** |
| Empresas con tendencia SIN DATOS | 615 | **5** |
| Filas-mes con score | — | 67,6% |
| Peso cubierto medio | — | 0,685 |

`MIN_PESO_CUBIERTO_SCORE` sigue en 0,55, sin tocar. Era la decisión correcta y el
problema no estaba ahí.

### 10.4 Sesgos declarados que siguen abiertos

- **Intragrupo.** `group_id` está en el panel pero no se filtra la facturación entre empresas del mismo grupo. Parte del "crecimiento" puede ser tesorería interna.
- **Deuda sin histórico.** No se puede castigar a quien se sobreapalancó hace 12 meses; solo cuenta la foto final. Y `guarantee`/`confirming` inflan el apalancamiento por ser contingentes.
- **Runway de mediana 0,49 meses.** Con caja mediana de 88.772 € y el gasto observado, casi toda la muestra sale con runway corto. Por eso el modulador de runway actúa **por percentil y no por umbral absoluto**: un umbral fijo penalizaría a casi toda la muestra por igual en lugar de discriminar. Sigue mereciendo revisar si `caja_real` debería incluir `liquidity` o el disponible de las líneas de crédito.
- **Denominadores pequeños.** La mediana de facturas vencidas por mes es 0 y el p75 es 2. Con `MIN_FACTURAS_RATIO = 2`, una sola factura impagada produce un 100% de morosidad. De ahí que el p75 de los ratios esté pegado a 100.

Cerrados desde versiones anteriores de este documento:

- ~~Concentración de contraparte sin penalizar~~ → `top1_*_share_3m` entra como modulador acotado de −10 puntos, que solo amplifica si el eje ya está por debajo de 60. Penalizar a una empresa sana por tener pocos proveedores sería castigar su modelo de negocio.
- ~~Falsos positivos por juventud (95,0 con un solo mes)~~ → la contracción empírica hacia el prior lleva ese caso a ~60, y `apto_ranking` marca quién tiene evidencia suficiente. Ya no hace falta filtrar a mano.

---

## 11. Cómo hacer que las métricas anticipen de verdad

El reto puntúa "cuántos meses antes" detectas el cambio. Eso no se consigue
añadiendo variables, sino cumpliendo cinco condiciones. Una métrica que falla
cualquiera de ellas no anticipa, aunque parezca sofisticada.

### 11.1 Las cinco condiciones

**1. Tiene que ser adelantada, no retrasada.** El impago formal es el final de la
cadena: primero cae la facturación, luego se estira el pago, luego se rompe. Las
señales del panel ordenadas por cuándo se mueven:

```
ingresos_momentum_3m  →  flag_tijera  →  colchon_flujo_meses  →  edad_media_stock_*  →  pct_impagos_prov_3m  →  runway
        adelantada  ·············································· retrasada
```

En la v1 casi la mitad del peso vivía en el extremo retrasado (morosidad 30% +
runway 18%). Hoy la morosidad sigue pesando (deuda comercial 20% + cobro 12%), pero
el runway ya no es eje: el colchón de flujo (18%) se mueve **antes** que el impago
formal, y la volatilidad del flujo —el mejor predictor de asfixia— entra como
penalización de ese colchón. El peso retrasado que queda es consciente, no un
descuido: confirmar el daño también es parte del score.

**2. Tiene que existir en la mayoría de los meses.** Una métrica con un 96% de
`NaN` no puede avisar con antelación porque no hay serie. Este es el criterio que
descarta `runway_meses` y `deuda_sobre_ingresos` como ejes principales, por muy
relevantes que sean conceptualmente.

**3. Tiene que estar normalizada contra la propia empresa.** Un umbral absoluto se
cruza cuando el daño ya está hecho. El z-score se mueve mientras los valores
absolutos siguen pareciendo normales. De ahí `z_*` y los `pctl_*`.

**4. Tiene que distinguir persistencia de ruido.** Sin esto, la anticipación se
paga con falsos positivos, y el reto evalúa explícitamente la "estabilidad
temporal". Las herramientas ya están: `*_3m` / `*_6m`, `persistente_*`,
`flujo_volatilidad_6m` y los bloques `*_3m_vs_prev3m`.

**5. Tiene que estar acotada.** Un valor de 10¹⁶ no es una señal fuerte, es un
denominador roto. Y al entrar en medias, percentiles o desviaciones contamina a
las demás empresas, no solo a la suya.

### 11.2 La regla de disparo que NO funcionó

Este apartado documenta un error, porque la versión anterior de este documento
proponía una regla que después medimos y resultó peor que el azar. Conviene que
quede escrito.

La propuesta era combinar tres condiciones independientes:

```
ALERTA  =  NIVEL preocupante          (pctl_* en el peor decil)
       Y   DIRECCIÓN de deterioro     (z_* > 1,5  o  *_3m_vs_prev3m negativo)
       Y   PERSISTENCIA               (persistente_*  o  *_3m >= 2)
```

Suena razonable y está mal. Medida, esa alerta dio **precisión 87,8% con detección
del 6,6% y 1 mes de antelación**, y una variante disparada por dirección sostenida
dio **lift 0,90**, peor que tirar una moneda. Un baseline trivial ("el score
mensual está bajo") la batía en recall, precisión y antelación a la vez.

**El fallo era de diseño, no de umbral.** Exigir que el nivel ya esté en el peor
decil garantiza avisar cuando el problema ya está aquí: es una definición de alerta
que excluye por construcción la anticipación. Y el baseline ganaba porque el evento
**se define por nivel**, así que cualquier señal de nivel lo predice casi por
tautología.

Lo que lo sustituye es una separación en dos capas, donde la capa de anticipación
exige explícitamente que el nivel **siga siendo aceptable**, más un tercer detector
autorreferenciado para el caso "de 82 a 68". El diseño completo, con los
disparadores de cada canal y sus lifts medidos, está en `SCORE_ENGINE.md` §8 y §9.

### 11.3 Cómo se mide la antelación

No hay ground truth, así que el evento se define sobre el propio panel. Implementado
en `evaluate_anticipation.py`, con dos eventos:

| Evento | Definición | Tasa base |
|---|---|---|
| `impago_severo` | 3 meses consecutivos con deuda comercial vencida por encima del umbral de severidad | 34,1% |
| `asfixia_de_caja` | 3 meses consecutivos de asfixia de flujo sostenida | 12,3% |

Para cada empresa con evento se mide cuántos meses antes se disparó cada una de las
cuatro señales (`nivel`, `canales_cola`, `giro_propio`, `combinada`), y se reportan
recall, precisión, lift y antelación mediana.

**La comparación que de verdad importa no es contra el azar, es contra la capa de
nivel a igualdad de volumen de avisos.** Sin ese contraste, cualquier señal que se
active mucho parece anticipar. El resultado sobre asfixia de caja: la capa de
anticipación gana **2 meses de mediana** a la de nivel y detecta **41 eventos que
esta no ve nunca**, activándose en menos empresas (39,7% frente a 53,9%).

Dos trampas declaradas:

1. Los eventos de los últimos meses de la ventana están **censurados** (no hay
   futuro para confirmarlos), así que la evaluación se restringe a eventos con
   margen posterior suficiente.
2. El evento se construye con las mismas variables que alimentan la alerta, así que
   esto mide **adelanto frente a un umbral de severidad**, no capacidad predictiva
   frente a un desenlace externo. No es validación fuera de muestra y no se presenta
   como tal.

### 11.4 Estado de los cambios propuestos al `score_engine`

Los seis cambios que proponía este documento están **implementados**, y se dejan
listados con su resultado porque tres de ellos no salieron como se esperaba.

| Cambio propuesto | Estado | Resultado real |
|---|---|---|
| 1. Morosidad con respaldo en cascada | Hecho | La palanca principal: mediana de meses evaluados 6 → 19 |
| 2. `colchon_flujo_meses` en lugar de `runway_meses` | Hecho | El runway queda como modulador por percentil, no como eje |
| 3. Separar tendencia en nivel y dirección | Hecho, con matiz | La trayectoria es eje propio con 5 sub-señales, pero su AUC sobre eventos es **0,49**: pesa 0,18 por lo que pide el reto, no por lo que predice |
| 4. Concentración como modulador | Hecho | −10 puntos como tope, y solo si el eje ya está bajo 60 |
| 5. Ranking por evidencia antes que por nota | Resuelto de otra forma | La contracción empírica lo arregla en el propio score; `apto_ranking` lo marca |
| 6. Recalcular `MIN_PESO_CUBIERTO_SCORE` | **No hizo falta** | Sigue en 0,55. La cobertura subió por tener más datos, que era el objetivo |

Se mantiene la arquitectura de reglas expertas. Sin ground truth, un modelo
entrenado sobre un objetivo que uno mismo define solo aprende su propia heurística,
con ruido y sin explicabilidad.

Un cambio que **no** estaba en esta lista y resultó el más importante: `dso_dias` /
`dpo_dias` se proponían como "la señal de anticipación más directa del panel" y no
entraron en el motor. Lo que sí entró, y no estaba previsto, fue
`flujo_volatilidad_6m` como penalización del colchón, tras medir que era el mejor
predictor único de asfixia de caja (AUC 0,71) y que hasta entonces solo se usaba
para *amortiguar* la trayectoria, es decir, para descartarlo.

---

## 12. Resumen: qué features usaremos y de dónde vienen

Clasificación por origen:

- **Original**: columna que viene tal cual en los CSV del dataset.
- **Agregada**: suma o conteo directo de una columna original por empresa y mes.
- **Derivada**: calculada a partir de agregados (ratios, medias móviles, z-scores).
- **Reconstruida**: requiere una decisión metodológica sobre datos ambiguos o engañosos. **Son las más valiosas y las más frágiles**: si la decisión es errónea, la feature miente con buena cara. Las cuatro de esta categoría son el trabajo real del pipeline.

### 12.1 Núcleo del score (usar sí o sí)

| Feature | Origen | Cobertura | Papel |
|---|---|---|---|
| `pct_impagos_prov_3m` | **Reconstruida** | 43,4% | Eje de más peso (0,20). Morosidad ponderada por importe, cohorte de vencimiento. **El predictor más fuerte del panel: AUC 0,83** |
| `stock_prov_sobre_ingresos` | **Reconstruida** | 68,7% | Respaldo del anterior en la cascada, con 25 puntos más de cobertura |
| `flujo_relativo_3m` | Derivada | 60,7% | Liquidez operativa (0,18). AUC 0,52 pero lift 3,26 en su decil adverso: informa en el extremo, no en el medio |
| `colchon_flujo_meses` | Derivada | 63,3% | Eje de colchón (0,18). Sustituye al runway, que existe en el 3,8% de las filas |
| `flujo_volatilidad_6m` | Derivada | 60,9% | Penaliza el colchón. **Mejor predictor único de asfixia de caja: AUC 0,71** |
| `burn_rate_3m_avg` | Derivada | 52,0% | Eficiencia (0,14). Lift 3,46, y su referencia económica no hay que calibrarla: 1,0 es el equilibrio |
| `pct_clientes_morosos_3m` | **Reconstruida** | 35,7% | Cobro de clientes (0,12). Canal de contagio: que no te paguen anticipa que no pagues (AUC 0,72) |
| `flujo_pendiente_robusta_6m` | Derivada | 60,9% | Dirección de la trayectoria por Theil-Sen, no por mínimos cuadrados |
| `recuperacion_stock_prov` | **Reconstruida** | 68,7% | Dirección de la deuda comercial. Lift 3,45 en su decil adverso |
| `share_stock_prov_antiguo` | **Reconstruida** | 43,7% | Modulador de severidad: retraso de gestión vs impago estructural |

Las cuatro **Reconstruidas** dependen de una única decisión: que `payment_date` no
es fecha de cobro si la factura sigue pendiente. Si esa decisión se revierte, las
cuatro vuelven a valer 0,0 y el 30% del peso del score deja de discriminar. Es el
supuesto más importante de todo el pipeline.

### 12.2 Motor de anticipación (lo que aporta la antelación)

| Feature | Origen | Cobertura | Por qué anticipa |
|---|---|---|---|
| `ingresos_momentum_3m` | Derivada | 57,6% | La caída de facturación precede al impago |
| `flag_tijera` (+ `persistente_`) | Derivada | 100% | Divergencia ingresos/gastos, visible antes de que el flujo se vuelva negativo |
| `z_caja_ingresos` | Derivada | 59,8% | Salida de la normalidad propia de ingresos |
| `z_stock_prov_sobre_ingresos` | Derivada | 26,2% | Aceleración del impago, no su nivel |
| `edad_media_stock_prov_dias` | **Reconstruida** | 43,7% | Se degrada gradualmente antes de romperse |
| `persistente_flag_*` | Derivada | 100% | Filtro de falsos positivos. Sin esto, anticipar sale caro |
| `flujo_volatilidad_6m` | Derivada | 60,9% | Separa cíclico de estructural |
| `pctl_*` (10 columnas) | Derivada | 4–69% | Umbrales de cola de los canales de alerta |

### 12.3 Contexto y modulación (no puntúan solas)

| Feature | Origen | Cobertura | Papel |
|---|---|---|---|
| `top1_prov_share_3m` | Derivada | 45,8% | Multiplicador del riesgo de morosidad |
| `top1_clientes_share_3m` | Derivada | 37,6% | Dependencia comercial |
| `refund_rate_3m` | Agregada | 64% de filas | Modulador del cobro: recibos devueltos |
| `debt_service_3m` | Agregada | 68% de filas | Modulador de deuda, todos los meses (no snapshot) |
| `confianza` | Derivada | 100% | Pondera cada mes en la agregación |
| `mes_activo`, `*_disponible` | Agregada | 100% | Distingue inactividad de ausencia de dato |
| `morosidad_censurada`, `mes_parcial` | Derivada | 100% | Evitan puntuar datos inmaduros |
| `group_id` | Original | 100% | Pendiente: filtrar intragrupo |

### 12.4 Snapshot: usar solo como refuerzo del último mes

| Feature | Origen | Cobertura | Aviso |
|---|---|---|---|
| `runway_meses` | Derivada | 3,8% | Un solo mes. Mediana 0,49 → penaliza casi a todos por igual |
| `caja_real`, `caja_negativa_flag` | Agregada | 3,9% | Solo `checking` + `saving` |
| `deuda_sobre_ingresos` | Derivada | 1,2% | Incluye `guarantee` y `confirming`, que son contingentes |

No deben ser ejes con peso fijo: apagados en el 96% de las filas, secuestran el
umbral de cobertura mínima y dejan meses enteros sin puntuar.

### 12.5 Qué se calculó y se retiró

Nada de esto vuelve al panel.

| Feature | Motivo |
|---|---|
| `burn_rate_cap`, `flujo_yoy`, DSO/DPO, HHI, `n_overdue_*`, `flag_burn_alto` | Nadie las leía o se solapaban |
| Percentiles y z-scores huérfanos | No disparaban canal ni eje |
| Andamiaje (`flag_*` crudos, `*_fuente`, `*_topado`, `mes_idx`, conteos) | Se usa dentro de `build_features` y se tira al escribir el panel |
| `zero_months` como eje al 13% (otro enfoque) | Ya cubierto por `mes_sin_ingresos` + persistencia |

### 12.6 Qué lee cada eje (69 columnas)

| Eje | Peso | Fuente 1 | Fuente 2 / 3 | Moduladores |
|---|---|---|---|---|
| Deuda comercial | 20% | `pct_impagos_prov_3m` | `stock_prov_sobre_ingresos` · `compras_acum` + stock 0 | `share_stock_prov_antiguo` · `top1_prov_share_3m` |
| Liquidez | 18% | `flujo_relativo_3m` | `flujo_relativo` | — |
| Colchón | 18% | `colchon_flujo_meses` | `runway_meses` (foto de caja) | `pctl_flujo_volatilidad_6m` · `pctl_runway_meses` |
| Trayectoria | 18% | `flujo_pendiente_robusta_6m` | `recuperacion_stock_prov` · `ingresos_momentum_3m` | `persistente_flag_*` · `flujo_volatilidad_6m` |
| Eficiencia | 14% | `burn_rate_3m_avg` | `burn_rate` · `mes_sin_ingresos` | — |
| Cobro | 12% | `pct_clientes_morosos_3m` | `stock_clientes_sobre_ingresos` · `ventas_acum` + stock 0 | `share_*` · `refund_rate_3m` · `top1_clientes_share_3m` |
| Score | — | media de los 6 | — | `debt_service_3m` · `deuda_sobre_ingresos` · `caja_negativa_flag` |

El resto del panel: claves (`company_id`, `year_month`, `group_id`), numeradores
de las ratios (`caja_*`, `volumen_*`, `atrapado_*`, `stock_overdue_*`), 8
`pctl_*` más de alerta, y `flujo_neto_*_avg` (solo validador).

Se retiró por complejidad inútil: z-scores (AUC ~0,50), pendiente OLS (Theil-Sen
basta), `gastos_momentum` y `recuperacion_stock_clientes` (nadie las puntúa).

### 12.7 De dónde sale todo

De las 69 columnas, solo **2 son originales** (`company_id`, `group_id`). El resto
se construye.

Esto es lo esperable y es el argumento del proyecto: el dataset entrega un rastro
transaccional crudo, sin ninguna etiqueta de salud financiera y con varias trampas
deliberadas (`payment_date` engañosa, documentos que no son facturas, tipos de
cambio imposibles, fechas en el año 6913). El valor no está en las columnas que
vienen dadas, sino en las decisiones documentadas que las convierten en señal, y en
dejar constancia numérica de todo lo que se descarta por el camino.
