# Score de salud financiera · Cómo funciona

Documento técnico del score: qué datos entran, de qué CSV salen, cómo se limpian, cómo se calcula cada métrica y cómo se compone el número final. Todo lo de aquí está en el código (`src/`); las cifras salen de las ejecuciones sobre el dataset de la hackathon (datos sintéticos).

**En una frase:** para cada empresa y mes se calculan 13 métricas a partir de los movimientos bancarios, las facturas, los saldos y la deuda; cada métrica se puntúa de 0 a 100 con una curva económica fija; y el score es la media ponderada de esas notas, agrupadas en cuatro bloques (liquidez, pago, financiación e ingresos).

## Índice

1. [Cómo ejecutarlo](#1-cómo-ejecutarlo)
2. [Qué CSV se usan y cuáles no](#2-qué-csv-se-usan-y-cuáles-no)
3. [Limpieza de datos](#3-limpieza-de-datos)
4. [Panel mensual empresa × mes](#4-panel-mensual-empresa--mes)
5. [Las 13 métricas](#5-las-13-métricas)
6. [Cómo se compone el score](#6-cómo-se-compone-el-score)
7. [Etiquetas y tendencia](#7-etiquetas-y-tendencia)
8. [Monitor de avisos](#8-monitor-de-avisos)
9. [Anticipación medida](#9-anticipación-medida)
10. [Qué se probó y se descartó](#10-qué-se-probó-y-se-descartó)
11. [Validación y límites](#11-validación-y-límites)
12. [Dashboard](#12-dashboard)
13. [Ficheros del repositorio](#13-ficheros-del-repositorio)

---

## 1. Cómo ejecutarlo

Desde la raíz del repo (unos 75 segundos en total):

```bash
pip install -r requirements.txt
python3 src/clean.py          # CSV crudos -> parquet limpio en data/clean/
python3 src/features.py       # panel mensual empresa x mes
python3 src/score.py          # score, tendencia y etiquetas (la 1ª vez ajusta la tendencia solo)
python3 src/anticipation.py   # mide la anticipación
python3 src/monitor.py        # genera los avisos
python3 src/build_dashboard.py  # dashboard/index.html
python3 src/test_pipeline.py  # comprobaciones mínimas del score
```

`python3 src/score.py explain COMP_0001 [2026-08]` explica el score de una empresa: qué señales suman y restan y qué cambió respecto al mes anterior y a hace 6 meses.

Para regenerar todo desde cero: `rm -rf data/clean` y repetir los pasos. Si cambias los pesos o las curvas, borra antes `data/clean/trend_report.json` (la tendencia se calibra sobre el score).

---

## 2. Qué CSV se usan y cuáles no

| CSV (en `data/`) | Se usa | Columnas usadas | Para qué |
|---|---|---|---|
| `transactions.csv` (2,56 M filas) | **Sí, es la base** | `company_id`, `product_id`, `date`, `amount`, `category` | Entradas y salidas de caja, cobros, devoluciones, servicio de deuda, caja reconstruida |
| `invoices.csv` (898 k filas) | **Sí** | `amount` (su signo da la dirección), `document_type`, `status`, `issuance_date`, `due_date`, `payment_date`, `counterparty_id` | Morosidad de clientes y proveedores, días de retraso, dependencia del mayor cliente |
| `balances.csv` | **Sí** | `product_id`, `balance` | Saldo final de cada cuenta: ancla para reconstruir la caja de cada mes |
| `banking_products.csv` | **Sí** | `product_id`, `company_id`, `type` | Distinguir cuentas de tesorería (checking, tpv, wallet…) del resto |
| `debt_products.csv` | **Sí** | `company_id`, `type`, `outstanding` | Deuda viva de préstamos, hipotecas, leasing, renting y líneas de crédito |
| `companies.csv` | **Sí** | `company_id`, `group_id`, `currency` | Clave de empresa, agrupación por grupo y moneda (informativo) |
| `groups.csv` | No | — | Solo aporta el ERP del grupo (64 % nulo), sin uso en el score |
| `debt_schedule_config.csv` | Se limpia, **no se usa** | — | Solo 87 préstamos con cuadro de amortización; el tipo de interés no está para el resto |
| `data_dictionary.md` | Referencia | — | — |

### Columnas descartadas y por qué

| Columna | Motivo |
|---|---|
| `exchange_rate` (transacciones y facturas) | No es fiable: mediana 1 incluso en CLP. Por eso todo son **ratios por empresa**, nunca importes convertidos a euros |
| `value_date` | Tiene valores absurdos (hasta 26.889 días de desfase); se usa `date` |
| `description`, `concept` | Texto libre con placeholders; la categoría ya recoge lo útil (p. ej. recibo devuelto) |
| `transactions.counterparty_id` | 90 % nulo (en facturas sí se usa) |
| `accounting_status`, `status` (transacciones) | Sin señal de salud |
| `country`, `erp` | 82 % y 42 % nulos |
| `available`, `countable`, `granted`, `liquidity` (balances) | `available` 100 % nulo; el resto casi vacío. En líneas de crédito `granted` vale 0 en 534 de 536, así que no se puede calcular utilización |

---

## 3. Limpieza de datos

`src/clean.py` deja parquet tipado en `data/clean/` y un registro de lo que modifica (`cleaning_log.json`). Nada se descarta en silencio.

| Problema detectado | Decisión | Filas afectadas |
|---|---|---|
| Importes en moneda local (COP, CLP, AOA…), con valores de hasta ±3.000 M | Solo ratios por empresa; nada se convierte | — |
| `payment_date` en facturas **no pagadas** es un relleno igual al vencimiento | Solo se usa si `status == paid` | — |
| Vencimientos imposibles (año 2000 o 2050, anteriores a la emisión, a más de 2 años) | Se sustituyen por emisión + 30 días | 15.870 |
| Facturas pagadas con fecha de pago futura | Se recortan a la fecha de extracción (2026-09-01) | 17.988 |
| Facturas pagadas antes de emitirse | Pago = emisión | 16.927 |
| La dirección de la factura no viene en ningún campo | El signo del importe la da: positivo = emitida (cobrar, **AR**), negativo = recibida (pagar, **AP**). Coincide con el signo del cobro o pago en banco en el 97,6 % de los casos | — |
| Tipos de documento que no son cobro/pago real (albaranes, pedidos, depósitos, notas…), canceladas e importes 0 | Se quedan solo `invoice` e `invoiceGroup` no canceladas | 897.894 → 761.114 |
| Transferencias entre cuentas propias, inversión y deuda contaminan la actividad | Clasificadas como `internal`, `investment` y `financing`; **no** cuentan como cobros ni pagos operativos | — |
| Movimientos de cuentas de deuda (línea de crédito, préstamos…) duplicarían flujos | Se excluyen de la tesorería (`is_cash_account = False`) | 183.653 |
| Saldos absurdos (9,99 e10) | Se marcan `balance_extreme` (≥ 1e9) y no se usan | 4 |
| Deuda con signo positivo (el origen usa negativo = deuda) | Se trabaja en valor absoluto | 145 |
| 108.853 filas idénticas con `transaction_id` distinto | **No se eliminan**: concentradas en importes pequeños (TPV, comisiones), son repeticiones legítimas | 108.853 |
| Mes 2026-09 (solo trae 1 día) | Fuera del panel | — |

---

## 4. Panel mensual empresa × mes

`src/features.py` construye `data/clean/panel.parquet`: 24 meses (2024-09 a 2026-08) × 1.286 empresas = 30.864 filas, de las cuales **20.928 están observadas**.

**Ventana observada.** Cada empresa se observa desde su primer mes completo (el mes de alta se descarta si empieza después del día 3) hasta el último mes con movimientos. Fuera de esa ventana el valor es **NaN, no 0**: un mes sin observar no es un mes sin actividad. Dentro de la ventana, un mes sin movimientos sí vale 0. La media es de 17 meses de historia por empresa.

**Caja reconstruida hacia atrás.** No hay serie de saldos, solo la foto del 2026-09-01. El saldo de cada cuenta de tesorería (checking, saving, wallet, tpv, expensesPlatform) al cierre de cada mes se reconstruye así:

```
saldo[mes] = saldo_final − Σ flujo neto de los meses posteriores
```

y se suma por empresa. Es la señal más frágil del score (ver [límites](#11-validación-y-límites)).

**Facturas «as-of».** Cada mes se reconstruye con las fechas reales de cobro y pago, no con el `status` de hoy. Con el estado actual, los meses recientes parecerían peores solo por el corte temporal.

---

## 5. Las 13 métricas

Todas se calculan sobre una **ventana suavizada**: la lenta (6 meses) da el score y la rápida (3 meses) sirve para detectar baches. Todas son ratios sin unidades.

| Bloque | Métrica | Qué mide | Fórmula | CSV | Peso |
|---|---|---|---|---|---:|
| **Liquidez** | `runway` | Meses de gasto que cubre la caja | `caja_fin_de_mes / media mensual de salidas` (recortado −3..12) | transactions + balances + banking_products | **24 %** |
| | `net_margin` | Generación de caja | `(Σ entradas − Σ salidas) / (Σ entradas + Σ salidas)` en la ventana, sobre flujos operativos | transactions | 7 % |
| **Pago** | `ar_overdue` | Clientes que no pagan a vencimiento | Importe de facturas emitidas vencidas en los últimos 90 días **aún sin cobrar** al cierre del mes / importe vencido en ese periodo (mín. 3 facturas) | invoices | 10 % |
| | `ap_overdue` | La empresa no paga a proveedores | Igual, con facturas recibidas | invoices | 10 % |
| | `ar_days_late` | Retraso de cobro | Media ponderada por importe de `pago − vencimiento` (−30..180 días) de lo cobrado ese mes (mín. 3 facturas) | invoices | 4 % |
| | `ap_days_late` | Retraso de pago | Igual, con facturas recibidas | invoices | 3 % |
| | `refund_rate` | Recibos devueltos | `Σ collection_refund / Σ cobros` (recortado 0..1) | transactions | 6 % |
| **Financiación** | `debt_service` | Peso del servicio de deuda | `Σ (amortización + intereses) / Σ entradas` (categorías `debt_repayment`, `interest_charge`; recortado 0..2) | transactions | 5 % |
| | `leverage` | Apalancamiento | `deuda viva / (12 × media mensual de entradas)` (recortado 0..5) | debt_products + transactions | 4 % |
| **Ingresos** | `inflow_cv` | Volatilidad de ingresos | `desv. típica / media` de las entradas mensuales (recortado 0..3) | transactions | 7 % |
| | `zero_months` | Continuidad | Fracción de meses de la ventana **sin ningún ingreso** | transactions | **13 %** |
| | `top1_customer` | Dependencia de un cliente | Peso del mayor cliente en lo facturado en los últimos 12 meses (mín. 5 facturas con contraparte) | invoices | 3 % |
| | `growth` | Crecimiento | `log(1 + ingresos de la ventana) − log(1 + ingresos de la ventana anterior)` (recortado ±2) | transactions | 4 % |

**Peso por bloque:** pago 33 %, liquidez 31 %, ingresos 27 %, financiación 9 %.

Detalles que importan:

- **Entradas y salidas** son solo flujos operativos de cuentas de tesorería: sin transferencias internas, sin inversión, sin movimientos de deuda. Los cobros son las categorías `collection`, `bulk_collection`, `pos_settlement` y `cash_settlement`.
- **`ar_overdue` y `ap_overdue`** se recortan por empresa al percentil 99 del importe de sus facturas, para que una factura de 6e10 no domine el ratio; se suavizan con la media de la ventana.
- **`leverage`** usa la deuda del 2026-09-01 (única foto disponible) para todos los meses. Solo cambia con el denominador.
- **Sin deuda** (ni deuda viva ni pagos de deuda en la ventana): `debt_service` y `leverage` valen **75 puntos** (riesgo bajo, pero sin historial de crédito).
- **`growth`** exige dos ventanas de datos, por lo que muchas empresas no lo tienen.
- Una empresa **sin facturas conectadas** (502 de 1.286) no tiene señales de pago ni `top1_customer`: esas notas quedan como neutras (50) y la confianza baja.

---

## 6. Cómo se compone el score

### Paso 1 · Cada métrica se puntúa de 0 a 100

Cada métrica se convierte en nota con una **curva fija de criterio económico**: interpolación lineal entre unos nudos `(valor, puntos)`. Fuera de los extremos se queda en el primero o el último. **No depende de ninguna otra empresa**: el score es absoluto e independiente.

| Métrica | Nudos `(valor → puntos)` | Lectura |
|---|---|---|
| `runway` | 0 → 0 · 0,25 → 15 · 0,5 → 30 · 1 → 50 · 2 → 75 · 3 → 90 · 4 → 100 | 4 o más meses de gasto = nota máxima |
| `net_margin` | −0,5 → 0 · −0,2 → 30 · 0 → 60 · 0,15 → 85 · 0,3 → 100 | Cobros = pagos vale 60 |
| `ar_overdue`, `ap_overdue` | 0 → 100 · 0,1 → 90 · 0,3 → 65 · 0,6 → 30 · 0,9 → 0 | |
| `ar_days_late`, `ap_days_late` | 0 → 100 · 10 → 80 · 30 → 50 · 60 → 15 · 90 → 0 | días |
| `refund_rate` | 0 → 100 · 0,5 % → 80 · 2 % → 40 · 5 % → 0 | |
| `debt_service` | 0 → 100 · 10 % → 80 · 25 % → 40 · 50 % → 0 | de los ingresos |
| `leverage` | 0 → 100 · 0,5 → 75 · 1 → 45 · 2 → 15 · 3 → 0 | años de ingresos |
| `inflow_cv` | 0,3 → 100 · 0,7 → 72 · 1,2 → 35 · 2 → 0 | |
| `zero_months` | 0 → 100 · 17 % → 55 · 33 % → 20 · 50 % → 0 | 1 de 6 meses sin ingresos = 55 |
| `top1_customer` | 30 % → 100 · 60 % → 70 · 90 % → 30 · 100 % → 15 | |
| `growth` | −0,7 → 0 · −0,2 → 40 · 0 → 65 · 0,3 → 90 · 0,6 → 100 | log-crecimiento |

Las curvas son **criterio, no medida**: no se ajustan a los datos. Solo la de caja se re-ancló para que discrimine donde viven las empresas (la caja mediana es de 0,7 meses de gasto).

### Paso 2 · Media ponderada

```
score = Σ  peso_k × nota_k          (k = las 13 métricas; los pesos suman 1)
```

Un dato ausente cuenta como **neutro (50)**: sin información no se puntúa ni alto ni bajo. El resultado se recorta a 0–100.

### Paso 3 · Bloques y confianza

- **Nota de cada bloque** = media ponderada de las notas de sus métricas (0–100). Sirve para explicar y para los avisos.
- **Confianza** = suma de los pesos de las métricas realmente observadas (100 % = todas). Media actual: 83 %.
- **Solo se puntúa si la confianza es ≥ 45 %.** Sin caja ni generación de caja no hay base para dar un número.

### Paso 4 · Dos ventanas

El **score** usa la ventana lenta (6 meses). Se calcula además `score_fast` con la ventana de 3 meses. La diferencia `gap = score_fast − score` detecta un trimestre reciente peor (o mejor) que la base: es lo que separa un **bache** de una **caída**.

### Ejemplo real: COMP_1223, agosto de 2026 → **66,9**

| Métrica | Valor | Nota | Peso | Aporta |
|---|---:|---:|---:|---:|
| `runway` | 0,13 meses | 8,0 | 24 % | 1,93 |
| `net_margin` | 0,001 | 60,2 | 7 % | 4,21 |
| `ar_overdue` | 17,1 % | 81,2 | 10 % | 8,12 |
| `ap_overdue` | 17,8 % | 80,3 | 10 % | 8,03 |
| `ar_days_late` | 11,4 días | 77,8 | 4 % | 3,11 |
| `ap_days_late` | 10,3 días | 79,6 | 3 % | 2,39 |
| `refund_rate` | 0,1 % | 96,3 | 6 % | 5,78 |
| `debt_service` | ≈ 0 | 100 | 5 % | 5,00 |
| `leverage` | ≈ 0 | 100 | 4 % | 4,00 |
| `inflow_cv` | 0,56 | 81,7 | 7 % | 5,72 |
| `zero_months` | 0 % | 100 | 13 % | 13,00 |
| `top1_customer` | 9,7 % | 100 | 3 % | 3,00 |
| `growth` | −0,001 | 64,9 | 4 % | 2,60 |
| **Score** | | | | **66,87** |

Bloques: liquidez 19,8 · pago 83,1 · financiación 100 · ingresos 90,1. Es una empresa cómoda en pago, ingresos y deuda, con la caja como único punto débil (0,13 meses de gasto), que le quita ~22 puntos frente a la nota máxima de esa métrica (0,24 × 92).

### Explicación por señal

Cada señal aporta `nota × peso` puntos y la suma de las 13 es exactamente el score. El dashboard lo muestra como una cuenta, agrupada por bloque (nota, peso, puntos y subtotal del bloque) con una fila de total. El cambio entre dos meses se reparte con `peso × (nota_ahora − nota_antes)`, y esos cambios suman la variación del score. Eso da el «por qué este número» y el «por qué ha cambiado». Por línea de comandos, `score.py explain` los expresa frente a una nota neutra de 50 (`peso × (nota − 50)`), que suma `score − 50`.

---

## 7. Etiquetas y tendencia

**Nivel** (según el score):

| Score | Nivel |
|---|---|
| < 40 | frágil |
| 40–55 | débil |
| 55–70 | sana |
| ≥ 70 | sólida |

**Dirección** (una etiqueta por empresa-mes; el orden de prioridad es este):

| Etiqueta | Regla |
|---|---|
| sin datos | Sin score (confianza < 45 %) |
| bache puntual | `gap ≤ −11`: el último trimestre cae 11 puntos o más bajo la base de 6 meses |
| deteriorando | Cambio esperado del score a 3 meses ≤ −5 |
| mejorando | Cambio esperado del score a 3 meses ≥ +5 |
| (nivel) | Si nada de lo anterior, se muestra el nivel |

**Cambio esperado a 3 meses (`exp_change3`)**, en `src/trend.py`. Regresión lineal con tres variables y coeficientes **congelados** (`trend_report.json`):

```
cambio = 0,99 − 0,026·(score − 50) + 0,279·(media_propia − score) + 0,615·gap
```

- `media_propia`: media histórica de la empresa, encogida hacia 50 con poca historia.
- `gap`: efecto mecánico de la ventana. Si el último trimestre es mejor que la base de 6 meses, el score sube casi solo al salir los meses viejos.
- Error típico residual: ±7,2 puntos.

Importante: **es sobre todo reversión a la media**, no una predicción de quiebra. La tendencia antigua (`d6 = score_t − score_{t−6}`) revertía por completo (correlación −0,45 con el cambio siguiente) y se retiró de las etiquetas; `d1`, `d3`, `d6` y `trend` siguen en `scores.parquet` como descripción de lo que pasó.

---

## 8. Monitor de avisos

`src/monitor.py` levanta la mano **solo cuando una empresa se mueve de verdad** y escribe `data/clean/alerts.parquet`. Un aviso lleva el texto de las señales que más cambiaron.

| Aviso | Regla |
|---|---|
| Cruce de umbral (deterioro) | Score por debajo de 47 (aviso) o de 40 (crítica) |
| Cruce de umbral (mejora) | Score por encima de 65 (aviso) o de 70 (crítica) |
| Bloque de **ingresos** a la baja | Nota del bloque < 40 |
| Bloque de **liquidez** al alza | Nota del bloque > 60 |

Con antirrebote: histéresis de 5 puntos, al menos 6 meses entre dos avisos del mismo tipo y dirección, y sin avisos en los primeros 3 meses puntuados de cada empresa. Los avisos por cambio de estado y por movimiento están desactivados: no superaban el azar.

Solo están activos los bloques de ingresos (hacia abajo) y liquidez (hacia arriba) porque son los que la evidencia sostiene; el resto de bloques no supera a una alerta aleatoria. Esa elección se hizo mirando la muestra completa y **no está validada fuera de muestra**.

Salida actual: 1.695 avisos (1,20 por empresa-año puntuado); 712 de 1.283 empresas tienen al menos uno.

---

## 9. Anticipación medida

`src/anticipation.py` mide **cuántos meses antes** avisa el sistema y con qué acierto. Reglas de la medición:

- El score y la alerta en el mes *t* usan solo datos hasta *t*; el evento se define con los meses posteriores (horizonte de 6 meses).
- Solo cuentan eventos que **empiezan** después de *t* (la empresa no está ya en el estado malo).
- Cada regla se compara con una **alerta aleatoria de igual tasa** y con reglas ingenuas (flujo neto negativo, caja negativa).
- Los eventos son de dos familias: sobre el propio score (cae 15 puntos; cruza 40 y se queda; mejora simétrica) y sobre datos crudos **distintos del score** (caja agotada con runway < 0,5; morosidad de clientes que se dispara; recibos devueltos ≥ 5 %; ingresos que caen a menos de la mitad de su base; y sus contrarios).

Resultados (`data/clean/anticipation_report.json`):

| Aviso | Contra qué evento | Acierto | Base / azar | Antelación mediana |
|---|---|---:|---:|---:|
| Score < 47 | Score < 40 sostenido | 15 % (recall 77 %) | 2 % | 2 meses |
| Bloque de ingresos < 40 | Ingresos caen a menos de la mitad (comparación emparejada) | 66 % | 32 % | 2 meses |
| Bloque de liquidez > 60 | Mejora observable (comparación emparejada) | 25 % | 10 % | 3 meses |

**Lectura honesta:**

- El score agregado avisa bien de su propio cruce de 40 (AUC 0,79), pero **no anticipa por sí solo eventos externos** como caja agotada: esa señal vive en los bloques.
- Los avisos por bloque acertan más que el azar, pero capturan pocos casos (recall del 2–4 %): sirven como aviso de prioridad, no como detector completo.
- En liquidez al alza, el 42 % de los avisos rebota en 2 meses.
- La regla del bloque de ingresos y la de liquidez se eligieron mirando toda la muestra.

---

## 10. Qué se probó y se descartó

| Idea | Resultado |
|---|---|
| **Actividad bancaria** (nº de movimientos 3m vs 3m previos) | Persistencia 0,14: ruido. Fuera del score |
| Crecimiento de ingresos | Casi ruido (autocorrelación negativa): se queda con peso 4 % |
| Utilización de líneas de crédito desde los 183.000 movimientos de cuentas de deuda | Sin mejora fuera de muestra |
| Nóminas, impuestos y comisiones sobre ingresos; morosidad grave; concentración de proveedores | Sin mejora fuera de muestra |
| Contracción por historia corta, renormalizar por señales observadas, otras ventanas (3 a 12 meses) | Sin efecto medible |
| Runway suavizado (media de la caja de la ventana) | +0,02 en el índice, pero el score deja de seguir los cambios de caja |
| Modelos no lineales (gradient boosting) para la tendencia | No superan a la regresión lineal |
| Pendientes y deltas de señales, bloques, `d1/d3/d6` como predictores | Sin ganancia |
| Score **relativo** (percentil frente a la cartera → curva normal) | Predice algo mejor (+0,015 de Spearman) pero es relativo: no dice si una empresa está sana en términos absolutos. Se sustituyó por el absoluto |

Los pesos actuales se ajustaron con validación fuera de muestra: se subieron los de `zero_months`, `ar_overdue`, `ap_overdue`, `refund_rate` y `runway` y se bajaron los de `top1_customer`, `leverage`, `debt_service` y `net_margin`, que casi no anticipaban problemas.

---

## 11. Validación y límites

### Cifras de validación

Sin etiquetas ni test disponible, la validación es interna: partición **temporal** (ajuste con meses ≤ T, evaluación en meses > T) y partición **por grupo** (`group_id`) para no mezclar empresas hermanas.

| Medida | Cifra |
|---|---|
| Estabilidad del score (autocorrelación a 1 / 3 / 6 meses) | 0,91 / 0,79 / 0,63 |
| Varianza del score explicada por la empresa (entre empresas) | 73 % |
| Spearman con un índice de deterioro futuro (3 y 6 meses), absoluto | 0,426 / 0,410 |
| Ídem, relativo (referencia) | 0,441 / 0,427 |
| AUC para detectar el 20 % peor a 6 meses | 0,73 |
| Cambio esperado a 3 meses: Spearman / R² fuera de muestra | 0,47 / 0,25 (línea base, media propia encogida: 0,31 / 0,11) |
| Cambio esperado a 6 meses | 0,46 / 0,24 (línea base: 0,45 / 0,20): casi sin ventaja |

El índice de deterioro futuro se construye con 8 variables posteriores (caja, margen, mora, caída de ingresos, devoluciones…), que en parte son las mismas que forman el score: mide «la señal de hoy anticipa el problema de mañana», no acierto contra una etiqueta real.

### Límites conocidos

- **Los pesos y las curvas son criterio**, con ajuste parcial por validación temporal. Sin etiquetas no se pueden medir.
- **La caja reconstruida es ruidosa** y es la señal con más peso (24 %): al reconstruir hacia atrás, ≈20 % de las cuentas salen en negativo en algún mes, señal de movimientos que faltan. La caja mediana (0,7 meses de gasto) puede tener parte de artefacto.
- **La deuda es una foto final** aplicada a todos los meses.
- **Sin facturas conectadas** (502 empresas) puntúan de media 58,1 frente a 63,3 las que sí las tienen (en 2026-08), porque les faltan señales de pago.
- **Empresas no EUR (121 en 2026-08):** puntúan igual de alto de media (61,9 frente a 61,2), pero el score predice peor su deterioro futuro (Spearman 0,36 / 0,33 frente a 0,43 / 0,41); no se corrigió.
- **La tendencia describe el score, no el negocio:** predice el cambio del propio score (sobre todo reversión a la media), no quiebras.
- **La anticipación real está en los bloques** (ingresos, liquidez), no en el score agregado.
- **Datos sintéticos:** ninguna empresa es real.

### Modo relativo

El código conserva el método anterior con `SCORE_MODE=rel python3 src/score.py`: cada señal pasa a percentil frente a una referencia congelada y luego a una z de la curva normal, con `score = 50 + 15·z`. Sirve para comparar. Ojo: `anticipation.py` y el dashboard están ajustados al modo absoluto (cortes 40/70).

---

## 12. Dashboard

`python3 src/build_dashboard.py` genera `dashboard/index.html` (6 MB, un único fichero, sin internet ni servidor; ábrelo con doble clic). Contiene:

- **Cartera:** indicadores, reparto del score, quién se mueve más y tabla de empresas o grupos con búsqueda y orden.
- **Empresa:** trayectoria, cambio esperado, por qué este número y qué cambió (este mes, vs mes anterior, 3 y 6 meses), bloques y acciones sugeridas por las señales más débiles.
- **Avisos:** el monitor con filtros.
- **¿Se vio venir?:** casos reales de caídas y mejoras con los meses de antelación (cifras sobre todos los casos).
- **Oportunidades:** quién lo paga y cinco segmentos de producto calculados sobre el score.
- **Método:** resumen de esto mismo dentro de la herramienta.

El mes de análisis se cambia desde el selector superior; todo se recalcula.

---

## 13. Ficheros del repositorio

```
src/
  clean.py            CSV crudos -> data/clean/*.parquet + cleaning_log.json
  features.py         panel mensual empresa x mes (panel.parquet)
  score.py            métricas, curvas, pesos, score, etiquetas, explicación
  trend.py            cambio esperado a 3 meses (coeficientes congelados)
  monitor.py          avisos (alerts.parquet)
  anticipation.py     medición de la anticipación (anticipation_report.json)
  build_dashboard.py  empaqueta todo en dashboard/index.html
  test_pipeline.py    comprobaciones mínimas del score
dashboard/
  template.html       plantilla del dashboard (index.html se genera)
data/                 CSV originales (no se suben a git)
  clean/              parquet limpio, panel, scores, informes (generado)
```

Salidas principales en `data/clean/`: `panel.parquet` (métricas mensuales), `scores.parquet` (score, bloques, confianza, etiquetas, cambio esperado), `scores_group.parquet` (media del grupo), `alerts.parquet`, `trend_report.json` y `anticipation_report.json`.
