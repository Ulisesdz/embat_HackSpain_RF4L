# Motor de scoring — diseño, pesos y evidencia

Documenta `score_engine.py`, `screen_signals.py` y `evaluate_anticipation.py`.
Para el diccionario de features, ver `FEATURES.md`. Para el pipeline de datos,
`README_Data_Analysis.md`.

---

## 1. La pregunta que hay que responder primero: ¿modelo o reglas?

Planteabas meter Prophet, XGBoost o algo de series temporales para la trayectoria.
La respuesta corta es que **no, y el motivo no es preferencia por las reglas, es
que ninguno de los dos resuelve el problema que tenemos**. El motivo largo:

**XGBoost necesita una `y` y no la tenemos.** El dataset no trae ninguna etiqueta
de salud financiera: ni impago real, ni concurso, ni default. Si entrenamos contra
un objetivo que definimos nosotros, el modelo aprende nuestra propia heurística
con ruido encima y pierde la explicabilidad, que el reto puntúa de forma explícita.
Sería un ejercicio circular presentado como aprendizaje automático.

**Prophet resuelve otro problema.** Está diseñado para *forecasting* de una serie
larga con estacionalidad, y necesita al menos dos ciclos completos para separar
tendencia de estacionalidad. Aquí hay 24 puntos mensuales por empresa: un único
ciclo incompleto. Sus changepoints no son identificables con esos datos, ajustaría
ruido, y aun funcionando nos daría lo que no necesitamos. No hace falta predecir
el valor del flujo de caja de marzo: hace falta saber **en qué dirección se mueve
y con cuánta confianza**, que es un problema de estimación, no de predicción.

**Lo que sí es un problema estadístico bien planteado** es estimar la dirección de
una serie corta y ruidosa. Para eso el motor usa herramientas específicas de ese
problema, no de forecasting:

| Herramienta | Qué resuelve |
|---|---|
| Pendiente de Theil-Sen | Con 6 puntos de pyme, mínimos cuadrados queda dominado por los extremos y un mes atípico invierte el signo. La mediana de pendientes por pares necesita que se corrompa media serie para moverse. |
| Z-score autorreferenciado | Compara cada empresa contra su propia base histórica, no contra un umbral universal que no existe. |
| Percentil transversal dentro del mes | No envejece con la deriva del dataset y permite decir "peor quintil de su cohorte". |
| Amortiguación por volatilidad | Una serie errática no puede sostener una afirmación fuerte de dirección. Control de falsos positivos. |
| Contracción empírica hacia la media | Con poca evidencia, el score se acerca al comportamiento típico en lugar de afirmar un 95 sobre un mes. |

**Dónde sí encajaría ML, si quieres ir más allá.** Existe una formulación honesta:
autosupervisada, con objetivo = **valor futuro observado de la propia serie**
(p. ej. `stock_prov_sobre_ingresos` a t+3). Esa `y` sale de los datos, no de
nuestro criterio, y se puede evaluar con corte temporal estricto. Pero solo merece
la pena si bate al estimador robusto, y la decisión de construirlo se toma
midiendo, no antes. `screen_signals.py` es precisamente la infraestructura que
haría falta para esa comparación. Hoy la conclusión de esa medición es que las
señales fuertes son pocas y muy interpretables, así que un modelo añadiría
opacidad sin margen claro de mejora.

---

## 2. Arquitectura

```
master_panel.csv
   │
   ├─ 6 EJES DE NIVEL Y DIRECCIÓN  → score mensual 0-100 (media ponderada)
   │     cada eje con CASCADA de fuentes, de más precisa a más disponible
   │
   ├─ MODULADORES (no puntúan solos, corrigen)
   │     concentración · apalancamiento · volatilidad · antigüedad del impago
   │
   ├─ AGREGACIÓN TEMPORAL   media exponencial (recencia × confianza × cobertura)
   │     + CONTRACCIÓN hacia el prior según evidencia efectiva
   │
   ├─ ALERTA EN TRES SEÑALES SEPARADAS
   │     capa NIVEL           el problema ya está aquí
   │     canales de COLA      anticipación contra eventos de severidad
   │     GIRO PROPIO          "de 82 a 68": se torció respecto a sí misma
   │
   └─ VISTA DE GRUPO          agregación encima, nunca al revés
         score_grupo + score_peor + agregado_esconde_problema
```

Calibraciones congeladas en `model/`: `pctl_reference.json` y
`prior_contraccion.json`. Viajan con el sistema: borrarlas lo recalibra en silencio.

Salidas: `scores_mensuales.csv`, `scores_finales.csv`, `scores_grupo.csv`,
`score_explanations.json`, `anticipation_report.csv`.

---

## 3. Pesos: cuánto y por qué

| Eje | Peso | Por qué ese peso |
|---|---|---|
| `deuda_comercial` | **0,20** | El predictor más fuerte del panel: AUC 0,83 y lift 4,11 en su decil adverso sobre impago severo futuro. Además no pagar a un proveedor es una **decisión** de la empresa, casi siempre porque no puede: es asfixia ya materializada, no riesgo ajeno. |
| `liquidez` | **0,18** | El flujo relativo al tamaño es el eje que responde "¿genera caja?". Normalizado por `ingresos_12m_avg` absorbe la estacionalidad y hace comparable una pyme con un grupo. |
| `colchon` | **0,18** | Cuántos meses aguanta. Absorbe la penalización por volatilidad, que resultó el mejor predictor único de asfixia de caja (AUC 0,71). |
| `eficiencia` | **0,14** | `burn_rate` tiene un punto de referencia económico que no hay que calibrar: 1,0 es el equilibrio. Lift 3,46 en su decil adverso sobre asfixia. |
| `cobro_clientes` | **0,12** | Canal de **contagio**: que no te paguen anticipa que no pagues (AUC 0,72 sobre impago severo). Pesa menos que proveedores porque que te deban es en parte riesgo de tu cliente; no pagar tú es tu propia falta de caja. |
| `trayectoria` | **0,18** | Mide dirección, que el reto pide de forma explícita y que alimenta la etiqueta MEJORANDO/DETERIORANDO. Bajó desde 0,25 tras medir: su AUC sobre eventos es 0,49, es decir nula. Sostener un cuarto del score con algo que no predice habría sido una decisión estética. |

Los pesos se fijaron **después** de medir, no antes. `screen_signals.py` calcula,
sobre las filas donde el nivel aún es aceptable, el AUC y el lift de cada señal
para que ocurra un evento de severidad en los 12 meses siguientes. Los números de
la tabla salen de ahí y son reproducibles.

### 3.1 Cómo cambiaron los pesos: las tres calibraciones

Esta tabla es el historial completo. Importa porque el criterio de reparto cambió
de naturaleza entre la primera y la tercera columna: se pasó de repartir por
**importancia conceptual** a repartir por **poder predictivo medido**.

| Eje | v1 · intuición | v2 · dirección | v3 · evidencia (actual) |
|---|---|---|---|
| Liquidez | 0,22 | 0,20 | **0,18** |
| Colchón / Runway | 0,18 | 0,18 | **0,18** |
| Deuda comercial (proveedores) | 0,18 | 0,18 | **0,20** |
| Cobro de clientes | 0,12 | 0,12 | **0,12** |
| Eficiencia | 0,12 | 0,12 | **0,14** |
| Trayectoria | 0,13 | 0,25 | **0,18** |
| Apalancamiento | 0,05 | — (modulador) | — (modulador) |

**v1 — reparto por criterio experto.** Los pesos se pusieron antes de medir nada,
por importancia económica aparente. Dos problemas que solo se vieron al ejecutarlo:
el eje de runway leía `runway_meses`, que existe en el **3,8%** de las filas, y el
apalancamiento en el **1,2%**. Un 23% del peso estaba apagado en el 96% de los
meses, y como el score exige cubrir el 55% del peso para no devolver `NaN`, la
mediana de meses evaluados era **6 de 25**. Los pesos eran defendibles sobre el
papel y no funcionaban sobre los datos.

**v2 — la dirección sube, el apalancamiento sale.** La trayectoria pasó de 0,13 a
0,25 porque el reto evalúa dirección y bidireccionalidad de forma explícita, y el
apalancamiento dejó de ser eje para convertirse en modulador acotado: con 1,2% de
cobertura, un peso fijo no penaliza a quien está apalancado, bloquea el score de
todos los demás.

**v3 — el reparto se somete a la medición.** Aquí entra `screen_signals.py`, que
calcula el AUC y el lift de cada señal sobre eventos de severidad a 12 meses. Tres
cambios, todos contra la intuición previa:

- **Deuda comercial 0,18 → 0,20.** Resultó el predictor más fuerte del panel
  (AUC 0,83, lift 4,11 en su decil adverso). Era el mejor eje y no era el que más
  pesaba.
- **Eficiencia 0,12 → 0,14.** El `burn_rate` tiene lift 3,46 y, a diferencia del
  resto, un punto de referencia económico que no hay que calibrar: 1,0 es el
  equilibrio.
- **Trayectoria 0,25 → 0,18.** El recorte más incómodo y el más necesario: su AUC
  sobre eventos es **0,49**, o sea indistinguible del azar. Mantiene un peso alto
  porque el reto pide dirección de forma explícita y porque alimenta la etiqueta
  MEJORANDO/DETERIORANDO, pero sostener un cuarto del score con algo que no
  predice habría sido una decisión estética. La liquidez cede 0,02 por el mismo
  motivo, más débil: AUC 0,52, aunque con lift 3,26 en el decil adverso, que es lo
  que justifica que siga pesando 0,18.

La lección que queda registrada: **v1 y v2 no eran erróneos, eran no verificados.**
La diferencia entre v2 y v3 no está tanto en los números, que se mueven 2-7
centésimas, como en que ahora cada uno se puede reproducir ejecutando un script en
lugar de defenderse con una opinión.

### 3.2 Lo que se cayó, y por qué

**El apalancamiento dejó de ser eje.** El snapshot de deuda existe en 1 de cada 25
meses: con 1,2% de cobertura, un peso fijo del 5% secuestraba el umbral de
evidencia. Ahora es un **modulador acotado** de ±8 puntos alimentado primero por
`debt_service` (pagos e intereses, 718 empresas, todos los meses) y, si no hay
pagos, por la foto de `deuda_sobre_ingresos` solo en el mes del snapshot.
`caja_negativa_flag` resta 4 puntos **solo** cuando vale 1 (saldo < 0 con foto).
NaN no es negativo: `bool(float('nan'))` es True, y esa línea llegó a aplicar
el −4 al 91% de las filas con score. El motor compara `== 1` y aplica la
penalización aunque no haya snapshot de deuda. Los tests sintéticos y un
conteo sobre el panel abortan si el texto "saldo bancario en negativo" aparece
en una fila sin foto.

**Los z-scores salieron del disparo de la alerta.** Medidos, tienen AUC entre 0,44
y 0,57 y varios apuntan al lado contrario del esperado. Se mantienen como
componente de la trayectoria y en las explicaciones, porque describen bien "esta
empresa está fuera de su comportamiento habitual", pero no deciden nada.

**La volatilidad pasó de descuento a señal.** Era el error de diseño más caro:
`flujo_volatilidad_6m` solo se usaba para *amortiguar* la trayectoria, es decir,
para tirar a la basura el mejor predictor de asfixia del panel (AUC 0,71). Ahora
entra como penalización del colchón, donde tiene sentido económico: un flujo
errático exige más buffer que uno estable para el mismo nivel de seguridad.

---

## 4. Cascadas: por qué la cobertura dejó de ser el cuello de botella

El problema original era que el score exigía cubrir el 55% del peso y las métricas
más precisas tienen poca cobertura, así que **la mediana de meses evaluados era 6
de 25** y 615 empresas salían con tendencia SIN DATOS.

Cada eje resuelve ahora una cascada ordenada de más precisa a más disponible, y
solo se apaga si ninguna fuente tiene dato:

| Eje | 1ª opción | 2ª | 3ª |
|---|---|---|---|
| `liquidez` | `flujo_relativo_3m` | `flujo_relativo` del mes | — |
| `colchon` | `colchon_flujo_meses` | `runway_meses` | — |
| `deuda_comercial` | `pct_impagos_prov_3m` | `stock_prov_sobre_ingresos` | "ha comprado y no debe nada vencido" |
| `cobro_clientes` | `pct_clientes_morosos_3m` | `stock_clientes_sobre_ingresos` | "ha vendido y no le deben nada vencido" |
| `eficiencia` | `burn_rate_3m_avg` | `burn_rate` del mes | — |
| `trayectoria` | ≥1 de 4 señales direccionales | — | — |

El tercer escalón es el que más cobertura aporta y conviene entenderlo: **stock
cero no es ausencia de dato, es un dato excelente**. Antes, una empresa con
historial de compras y sin un euro vencido era indistinguible de una empresa sin
información. Por eso se añadieron `compras_acum` y `ventas_acum` al panel: permiten
afirmar "ha comprado y no debe nada", que es una observación, no un hueco.

Resultado medido:

| | Antes | Ahora |
|---|---|---|
| Mediana de meses evaluados | 6 | **19** |
| Filas-mes con score | — | 67,6% |
| Peso cubierto medio | — | 0,685 |
| Empresas NO EVALUABLE | 87 | **5** |
| Empresas aptas para ranking | — | 1.271 de 1.286 |

---

## 5. El eje de trayectoria

Cada señal se convierte en una intensidad firmada en `[-1, +1]` dividiéndola por su
**saturación**: el valor a partir del cual ya es máxima. Así un outlier no domina
la dirección, y la escala es la misma para todas las señales.

| Componente | Peso | Señal | Saturación |
|---|---|---|---|
| `pendiente_flujo` | 0,30 | `flujo_pendiente_robusta_6m` (Theil-Sen) | 10 pp de ingresos/mes |
| `deuda_comercial_dir` | 0,25 | `recuperacion_stock_prov` | 0,5 meses de ingresos |
| `ingresos_momentum` | 0,20 | `ingresos_momentum_3m` | ±30% trimestral |
| `anomalia` | 0,15 | `z_caja_ingresos`, `z_stock_prov_sobre_ingresos` | 2 sigmas |
| `persistencia` | 0,10 | flags sostenidos 3 meses | solo penaliza |

`score_trayectoria = 50 + 50 × dirección × amortiguación`, con la amortiguación
entre 0,50 y 1,00 según la volatilidad de la serie. Es simétrico por construcción:
la misma sensibilidad a mejora que a deterioro, que es la bidireccionalidad que
pide el reto.

Dos decisiones que importan:

**La persistencia no puede activar el eje sola.** Los flags existen en el 100% de
las filas, así que si contaran como señal disponible el eje entraría siempre con su
peso completo devolviendo un 50 neutro sin información. Se exige al menos una de
las cuatro señales informativas.

**`recuperacion_stock_prov` se añadió al panel para este eje.** La señal
equivalente que ya existía, `recuperacion_prov`, depende de `pct_impagos_prov_3m` y
falta en el 69% de las filas. Sobre el stock normalizado la misma información está
disponible en el 69%, y con lift 3,45 en su decil adverso.

---

## 6. Moduladores

No son ejes: corrigen un score ya calculado, con tope, y solo donde tienen sentido.

| Modulador | Tope | Lógica |
|---|---|---|
| Concentración | −10 pts | Solo amplifica si el eje ya está por debajo de 60. Un impago del 40% duele distinto si viene de un proveedor o de veinte, pero penalizar a una empresa sana por tener pocos proveedores sería castigar su modelo de negocio. |
| Antigüedad del impago | −15 pts | Proporcional a `share_stock_*_antiguo`. Deuda envejecida es impago, no retraso de gestión. |
| Volatilidad del flujo | −14 pts | Sobre el colchón. Flujo errático exige más buffer. |
| Runway real | ±12 pts | Sobre el colchón, y **por percentil, no por umbral absoluto**: la mediana de `runway_meses` en este dataset es 0,49 meses, así que un umbral fijo penalizaría a casi toda la muestra por igual en lugar de discriminar. |
| Apalancamiento | ±8 pts | Sobre el score final, solo en el mes con snapshot de deuda. |

---

## 7. Agregación temporal y contracción

El score de empresa es una media exponencial de los meses, con peso
`recencia × confianza × cobertura`: un mes antiguo con datos completos pesa más que
uno reciente con datos dudosos. La semivida es de 6 meses.

Encima va una **contracción empírica hacia el prior**:

```
score_final = (evidencia × score_bruto + k × prior) / (evidencia + k)
```

con `k = 0,75` y `prior` = mediana de las empresas con ≥12 meses evaluados
(**54,41**, calibrado sobre 798 empresas con ≥12 meses tras corregir `bool(nan)`
en `caja_negativa_flag`). La `evidencia` es la suma de los pesos
mensuales, con un máximo de ~7,5.

El prior está **congelado en `model/prior_contraccion.json`**, y no es un detalle
de implementación: era la última fuente de no-determinismo del sistema. Ver §9.5.

Esto resuelve un problema concreto que teníamos: una empresa con **un solo mes** de
datos salía con 95,0 y clasificada como SALUDABLE. La media ponderada de un punto
no es una estimación, es ese punto. Con la contracción, ese caso cae a ~60 y deja
de contaminar el ranking, sin necesidad de filtrarlo a mano. Una empresa con 20
meses sólidos apenas se mueve.

`score_bruto` se conserva en la salida para poder auditar cuánto contrajo cada caso.

### 7.1 Umbrales de clasificación

Están calibrados sobre la población de referencia de 1.286 empresas y son
**absolutos a propósito**: un percentil calculado sobre el conjunto de evaluación
clasificaría distinto a la misma empresa según con quién la comparen, y con 60-80
empresas de test esos percentiles serían inestables.

| Clase | Umbral | Población |
|---|---|---|
| SALUDABLE | ≥ 68 | 229 |
| ESTABLE | 52 – 68 | 538 |
| EN RIESGO | 42 – 52 | 315 |
| FRÁGIL | 33 – 42 | 132 |
| CRÍTICO | < 33 | 66 |
| NO EVALUABLE | sin evidencia | 6 |

Distribución resultante: media 55,4, mediana 55,5, recorrido 16,22 – 87,81
(tras quitar el −4 fantasma de `bool(nan)` en caja negativa). Que ninguna empresa llegue
a 0 ni a 100 es esperado y correcto: el
score de empresa es una media de 25 meses contraída hacia el prior, así que los
extremos exigen consistencia, no un mes excepcional.

Los umbrales anteriores (80/60/40/20) estaban puestos para la escala del score
mensual, no para la de empresa. El score agregado revierte a la media por
construcción: para bajar de 33 hay que estar en la cola mala **todos** los meses.
Con la escala vieja no había ninguna empresa SALUDABLE ni ninguna CRÍTICA.

---

## 8. Alerta en dos capas

Este fue el hallazgo que más cambió el diseño, y conviene contarlo entero porque el
primer intento estaba mal.

**Primer intento:** una alerta que exigía NIVEL en el peor cuartil **y** DIRECCIÓN
adversa **y** PERSISTENCIA. Resultado medido: precisión 87,8% pero detección del
6,6% y **1 mes** de antelación. El fallo era de diseño, no de umbral: exigir que el
nivel ya estuviera en el peor cuartil garantiza avisar cuando el problema ya está
ahí.

**Segundo intento:** disparar por dirección sostenida. Resultado: **lift 0,90**, es
decir, peor que el azar. Y un baseline trivial ("el score mensual está bajo") batía
a la alerta en recall, precisión y antelación.

**El diagnóstico.** El baseline ganaba porque **el evento se define por nivel**, así
que cualquier señal de nivel lo predice casi por construcción. Comparar las dos en
el mismo cajón mide una tautología. La pregunta útil no es "¿podemos predecir el
evento?" sino **"¿podemos avisar antes de que el nivel se deteriore?"**. De ahí la
separación en dos capas:

- **Capa NIVEL** — `score_mensual < 42`. Alta cobertura, útil para actuar hoy, pero
  no anticipa: cuando salta, el problema es presente.
- **Capa ANTICIPACIÓN** — la empresa **aún no** ha caído de nivel y sin embargo
  acumula disparadores de cola. Es la única capa que compra tiempo, y por eso exige
  explícitamente `score_mensual >= 42`: en cuanto el nivel cae, la observación deja
  de ser una anticipación.

### 8.1 Los dos canales

Los disparadores y sus pesos salen de `screen_signals.py`, no de intuición. Cada
uno es una condición de **cola** (percentil adverso dentro del mes) y no un umbral
absoluto, por dos razones: varias señales resultaron **no monótonas** —
`flujo_relativo_3m` tiene AUC 0,52 pero lift 3,26 en su decil adverso, o sea que
informa en el extremo y no en el medio — y un percentil no envejece con la deriva
del dataset.

**Canal de impago comercial** (`riesgo_impago_comercial`, AUC 0,767, lift 3,88):

| Disparador | Umbral | Peso |
|---|---|---|
| `pctl_stock_prov_sobre_ingresos` | ≤ 0,20 | 3,0 |
| `pctl_stock_clientes_sobre_ingresos` | ≤ 0,20 | 2,0 |
| `pctl_recuperacion_stock_prov` | ≤ 0,10 | 2,0 |
| `pctl_clientes_morosos_3m` | ≤ 0,20 | 1,5 |
| `persistente_flag_stock_prov_antiguo` | binario | 1,5 |

El disparador de clientes es el más valioso porque es el único **no tautológico**:
mide contagio de un problema ajeno, no una versión suavizada del propio evento.

**Canal de asfixia de caja** (`riesgo_asfixia_caja`, AUC 0,680, lift 3,03):

| Disparador | Umbral | Peso |
|---|---|---|
| `pctl_flujo_volatilidad_6m` | ≤ 0,20 | 3,0 |
| `pctl_burn_rate_3m` | ≤ 0,20 | 2,5 |
| `pctl_flujo_relativo_3m` | ≤ 0,10 | 2,0 |
| `pctl_colchon_flujo_meses` | ≤ 0,20 | 2,0 |
| `pctl_flujo_pendiente_robusta_6m` | ≤ 0,10 | 1,5 |

Los canales compuestos **baten a sus componentes** en el criterio conjunto: el
`burn_rate` solo tiene mejor lift (3,46) pero AUC de 0,60, y la volatilidad sola
mejor AUC (0,71) pero lift de 2,44. El canal combina ambos y además cubre 15.175
filas frente a las 12-13.000 de sus partes.

Un canal dispara al superar el 55% del peso **disponible** en esa fila. Normalizar
por el peso disponible y no por el total evita que a una empresa con pocos datos le
baje el riesgo por el simple hecho de faltarle columnas. Se exige además que el
disparo se sostenga 2 meses, sobre el canal y no sobre el nivel: es lo que separa
un giro real de un mes atípico.

### 8.2 Resultados medidos

`evaluate_anticipation.py`, horizonte de 12 meses, evento = 3 meses consecutivos
por encima del umbral de severidad:

**Asfixia de caja** (tasa base 12,3%)

| Señal | Se activa en | Recall | Precisión | Lift | Antelación |
|---|---|---|---|---|---|
| Capa nivel (baseline) | 53,9% | 62,7% | 16,7% | 1,36 | 4,0 m |
| Capa anticipación | 39,7% | 44,9% | **18,6%** | **1,52** | 3,0 m |
| Combinada | 64,4% | **88,6%** | 17,6% | 1,44 | 4,0 m |

La capa de anticipación **gana 2 meses de mediana** a la capa de nivel y detecta
**41 eventos que la capa de nivel no ve nunca**, activándose en menos empresas que
ella (39,7% frente a 53,9%). Eso es lo que buscábamos.

**Impago severo** (tasa base 34,1%)

| Señal | Se activa en | Recall | Precisión | Lift | Antelación |
|---|---|---|---|---|---|
| Capa nivel (baseline) | 53,9% | 50,1% | 59,7% | 1,75 | 3,0 m |
| Capa anticipación | 39,7% | 16,2% | 49,4% | 1,45 | 4,0 m |
| Combinada | 64,4% | 52,8% | 50,8% | 1,49 | 3,0 m |

Aquí la capa de nivel es mejor, y tiene sentido: el impago severo **se define**
sobre el mismo stock de deuda que la alimenta, así que el nivel lo predice casi por
construcción. La anticipación aporta +1 mes y 12 eventos únicos. No inflo esta
cifra: es un resultado modesto.

El umbral de 0,55 se eligió con un barrido. Frente a 0,45 recorta la activación del
49% al 40% conservando 41 de los 43 eventos únicos de asfixia: mismo valor, mucho
menos ruido.

---

## 9. Las seis preguntas del reto, una por una

| Pregunta | Dónde se contesta | Estado (corrida vigente) |
|---|---|---|
| Quién está sano | `clasificacion` sobre `score_final` | 229 SALUDABLE, 538 ESTABLE, 315 EN RIESGO, 132 FRÁGIL, 66 CRÍTICO, 6 NO EVALUABLE |
| Quién está mejorando | `tendencia` + `score_trayectoria` | 262 MEJORANDO, 398 DETERIORANDO, 611 ESTABLE |
| Quién empieza a torcerse | `senal_giro`, `naturaleza_caida` | 624 con giro; **420 llamadas** (score_final ≥ 55 ahora). 417 lo tuvieron aún sanas ese mes |
| Bache o caída | `naturaleza_caida` | Bache +4,69 pts a 6 m (52% recupera); caída −1,66 (33% sigue) |
| Por qué ha cambiado | `motivo_cambio`, `aporte_*`, `cambio_real` vs `cambio_cobertura` | 17.744 filas-mes; 5,5% dominado por dato nuevo |
| Cuándo se vio venir | `primer_giro`, `meses_anticipacion`, `meses_ganados_a_nivel` | Cola vs nivel: +2 m asfixia, +1 m impago |

**Cómo no mezclar recuentos.** `alerta_temprana` (1.111) es nivel **o** cola:
recall, no la lista de ventas. El giro no se fusiona con esa capa: su lift sobre
asfixia es 0,90. Lo que afirma es «esta caída se sostiene», y se valida contra
el score futuro (tabla de bache vs caída). El dashboard pinta 420, no 417: tres
empresas entran por `score_final` ≥ 55 con el giro mensual entre 45 y 55
(`GIRO_NIVEL_MIN`).

### 9.1 "Quién empieza a torcerse": el giro autorreferenciado

Esta pregunta estaba **sin contestar**, y no por calibración sino por diseño.
Busqué en los datos el caso exacto del enunciado ("de 82 a 68 sigue pareciendo
sana"): empresas que venían de ≥68, pierden ≥10 puntos y siguen sobre 55. Hay 611
empresas y 1.288 filas-mes. La alerta salía en el **2,7%** de ellas, cuando en la
población general salía en el 5,0%: el sistema era **peor que la media** en
exactamente el caso que más importa.

La causa es estructural. Los dos canales disparan por percentil adverso, y una
empresa que cae de 82 a 68 **no está en ningún quintil adverso por definición**,
porque sigue siendo mejor que la mayoría. Era imposible que la viera.

El detector nuevo no mira la posición en la cohorte, mira el movimiento de la
empresa **contra sí misma**, y hacen falta dos cosas:

1. **Suavizar antes de comparar** (mediana móvil de 3 meses), porque el score
   mensual es ruidoso y un mes malo aislado produciría un giro falso.
2. **Normalizar por la volatilidad histórica del propio score.** La empresa
   mediana recorre 41,7 puntos entre su máximo y su mínimo, así que "ha caído 14"
   no significa nada por sí solo: significa mucho si su score nunca se mueve, y
   nada si oscila 40. El disparo es en sigmas propias, no en puntos.

Resultado: el giro se activa en el **30,4%** de esos casos frente al 2,7% de
antes, con una base poblacional del 4,9%. Hoy la lista de llamadas son **420**
empresas con giro y `score_final` ≥ 55. El recuento mensual (giro con
`score_mensual` ≥ 55) es 417.

### 9.2 Por qué el giro NO se fusiona con los canales

Al meterlo dentro de `senal_anticipacion`, el lift de los canales sobre eventos de
severidad se hundía de 1,52 a 1,04 y la activación subía del 40% al 75%. Medido
contra esos eventos, el giro tiene lift 0,93 y 0,65, o sea que no los predice.

Eso **no es un fallo del giro**: es que responde a otra pregunta y hay que
validarlo contra otro desenlace. Los canales predicen "esta empresa llegará a
impago severo o asfixia". El giro predice "esta caída va a sostenerse". Sumarlos
en una sola señal convierte dos señales buenas en una mediocre, así que viajan
separadas y `alerta_tipo` distingue cuál disparó.

### 9.3 "Bache o caída": qué separa de verdad

El desenlace se mide sin etiquetas externas, contra el propio comportamiento
futuro observado: **¿el score suavizado sigue igual o peor 6 meses después?** Tasa
base de no recuperación, 38,5%.

El primer criterio que probé —qué fracción de la caída venía de los ejes
estructurales— tenía **AUC 0,517**, es decir nada. Lo que sí discrimina:

| Criterio | AUC | Lógica |
|---|---|---|
| Volatilidad propia del score baja | 0,595 | Si una empresa cuyo score nunca se mueve pierde 10 puntos, se ha movido de verdad |
| `cambio_real` muy negativo | 0,625 | La caída viene del comportamiento, no de datos nuevos |
| Deuda comercial vencida viva | 0,563 | Si ya hay impago, la caída tiene dónde agarrarse |

Por terciles de volatilidad propia, la no recuperación va del 47,5% al 29,4% y el
rebote mediano a 6 meses de +0,83 a **+10,70** puntos. Es el criterio más limpio y
el más explicable de todo el motor.

Se descartan a propósito `score_mensual` y `colchon_flujo_meses`, que también
predicen la no recuperación (AUC 0,556 y 0,628) pero por **reversión a la media**:
quien está alto tiene más sitio para caer y menos para rebotar. Predicen sin
explicar, y meterían en el criterio un sesgo sistemático contra las empresas sanas.

Resultado, con dos clases:

| Clase | n | Δ score +3 m | Δ score +6 m | Recupera | Sigue cayendo |
|---|---|---|---|---|---|
| `bache` | 1.256 | **+4,65** | **+5,28** | 54,8% | 18,2% |
| `caida_estructural` | 270 | **−1,93** | **−2,54** | 33,3% | 36,3% |

`caida_estructural` es la única clase con mediana negativa. Probé una clase
intermedia ("deterioro_probable", la caída sostenida que no cumple los criterios
estructurales) y se comportaba igual que un bache (+4,71 y 55,1% de recuperación),
así que se eliminó: una etiqueta que suena a aviso sobre casos que se recuperan la
mitad de las veces es peor que no tenerla.

### 9.4 "Por qué ha cambiado": atribución exacta

El score es `sum(w_i/W * s_i)`, así que el cambio se descompone sin residuo:

```
efecto_nivel  = w_i,t-1 * (s_i,t - s_i,t-1)     el eje se movió
efecto_mezcla = (w_i,t - w_i,t-1) * s_i,t       su peso cambió
```

La separación es la trampa que hay que evitar al contestar esta pregunta: cuando
aparece un eje porque llegó dato nuevo, **el score se mueve sin que la empresa haya
cambiado**. Sin distinguirlo, el sistema diría "ha mejorado" cuando lo que pasó es
que empezamos a verla. `cambio_real` es la parte atribuible al comportamiento y
`cambio_cobertura` la atribuible a la información: el 4,1% de los movimientos están
dominados por la segunda.

Que `cambio_real` resultara además el mejor predictor de que una caída se sostiene
(AUC 0,625) no era el objetivo, pero confirma que separa lo que tenía que separar.

### 9.5 Determinismo sobre las 60-80 empresas que no vemos

El reto pide explícitamente que el score "aguante en las 60–80 empresas que vuestro
sistema no ve nunca". Los canales de alerta son **todos percentiles**, así que
había un riesgo real: puntuar 70 empresas las compararía entre ellas y no contra la
población de referencia, y los umbrales se moverían de sitio.

Lo medí antes de arreglarlo: recalculando sobre 70 empresas, los percentiles se
desviaban 0,030-0,050 de media y el 2,6% de las filas cambiaba de lado del umbral.
Menos grave de lo que temía, pero no determinista.

La solución es congelar la distribución de referencia (`pctl_reference.json`, una
rejilla de 101 cuantiles por columna y mes) y medir contra ella siempre. Verificado:

| Columna | Desviación sin referencia | Con referencia |
|---|---|---|
| `stock_prov_sobre_ingresos` | 0,0384 | **0,0036** |
| `colchon_flujo_meses` | 0,0408 | **0,0046** |
| `flujo_volatilidad_6m` | 0,0451 | **0,0050** |
| `burn_rate_3m_avg` | 0,0459 | **0,0044** |
| `flujo_relativo_3m` | 0,0504 | **0,0046** |

Un detalle que costó una iteración: la primera versión empeoraba
`stock_prov_sobre_ingresos` (0,0384 → 0,0907) porque el 60% de sus valores es
exactamente 0, y `rank()` promedia los rangos empatados mientras `searchsorted` los
manda al borde inferior del escalón. Se corrige tomando el punto medio del empate.

#### La prueba de verdad: puntuar 70 empresas aisladas

Medir la desviación de los percentiles no basta, porque no dice si el **score** se
mueve. La prueba real es reconstruir el pipeline completo con 70 empresas y solo 70,
usando la referencia congelada, y comparar contra lo que sacaron dentro de las
1.286. El resultado del primer intento aisló el problema con precisión:

| Salida | Desviación media | Máxima | Cambian de clase |
|---|---|---|---|
| `score_bruto` | **0,0000** | **0,0000** | — |
| `score_final` | 1,13 pts | 2,28 pts | **6 de 70** |
| `tendencia` | — | — | 0 de 70 |

Que `score_bruto` saliera **exacto** confirma que toda la ingeniería de variables y
el score mensual ya eran deterministas: la rejilla de percentiles hacía su trabajo.
Y que `score_final` se desviara señalaba la causa en un único sitio, porque es lo
único que se aplica entre los dos: **la contracción**. El prior se recalculaba con
la población presente, así que con 70 empresas salía **47,74** en lugar de 56,56, y
eso empujaba a todo el mundo hacia abajo. Seis empresas cruzaban un umbral de
clasificación por ese motivo, entre ellas tres que pasaban de SALUDABLE a ESTABLE.

Congelado el prior en `model/prior_contraccion.json`, la misma prueba da:

| Salida | Desviación media | Máxima | Cambian de clase |
|---|---|---|---|
| `score_bruto` | 0,0000 | 0,0000 | — |
| `score_final` | **0,0000** | **0,0000** | **0 de 70** |
| `clasificacion` / `tendencia` | — | — | 0 de 70 |

**El sistema es ahora determinista sobre empresas que no ha visto**, que es
literalmente lo que pide el enunciado. La lección general: todo parámetro estimado
sobre la población es calibración y tiene que viajar con el modelo. Los percentiles
eran evidentes; el prior no lo era, y hacía más daño en clasificación que ellos.

#### Por qué `model/` y no `data/`

Los dos archivos de calibración viven en `model/`, fuera de `data/`, porque `data/`
está en `.gitignore`: contiene el dataset y las salidas regenerables. La referencia
de percentiles y el prior **no son regenerables sin perder la calibración**. Si
viajaran con el resto, un clon limpio los recrearía contra otra población y el score
dejaría de ser comparable sin que nada avisara. Borrarlos recalibra el sistema, y
eso debe ser una decisión deliberada, no el efecto secundario de volver a ejecutar
el pipeline.

---

## 10. Granularidad: empresa o grupo

El cálculo canónico es **por empresa**, y la vista de grupo va encima. Nunca al
revés, y esto no es una preferencia: agregar es una proyección que no se puede
deshacer. Si el motor puntuara los 249 grupos, no habría forma de bajar a la
empresa; puntuando las 1.286, el grupo es un `groupby`.

Lo que dicen los datos:

| Medida | Valor | Lectura |
|---|---|---|
| Varianza del score explicada por el grupo | **61,9%** | El grupo importa: las empresas de un grupo se parecen (desviación interna 5,8 frente a 11,2 global) |
| Recorrido máx-mín dentro del grupo | mediana 15,4 pts, p75 22,0 | Pero el 38% de la varianza es interna |
| Grupos con una empresa MEJORANDO y otra DETERIORANDO | **24,0%** | Una media aritmética las cancelaría |
| Grupos donde el agregado esconde una empresa en riesgo | **23,6%** | El score del grupo diría ESTABLE con una filial CRÍTICA dentro |

Ese último número es el argumento: en uno de cada cuatro grupos, agregar borra
exactamente la señal que el reto pide detectar. `GROUP_0102` puntúa 53,58 (ESTABLE)
con `COMP_0071` dentro a 30,78 (CRÍTICO).

Por eso `scores_grupo.csv` no publica una media y se calla. Publica tres cosas a la
vez, y la tercera es la que hace honesta a la primera:

- `score_grupo` — media ponderada por evidencia, la foto agregada.
- `score_peor` y `empresa_peor` — la peor filial. Para un riesgo de crédito esto
  suele mandar más que la media, porque un grupo responde por sus filiales.
- `dispersion_interna` y `agregado_esconde_problema` — el aviso de que la foto
  agregada no basta para este grupo.

**Sobre el toggle en producto: sí, pero es un toggle de vista, no de cálculo.** Se
calcula siempre por empresa y el usuario elige el nivel de lectura. Hacerlo
configurable en el cálculo obligaría a mantener dos calibraciones (umbrales,
percentiles y prior de contracción son distintos con 250 unidades que con 1.286) y
a explicar por qué la misma empresa cambia de nota según el modo. Con una sola
calibración por empresa, la vista de grupo es una agregación y no una segunda
verdad.

Un matiz de negocio: parte de los 249 grupos tienen una sola empresa, así que para
ellos las dos vistas coinciden y el modo grupo no añade nada.

---

## 11. Limitaciones, dichas claramente

1. **No es validación fuera de muestra.** El evento se define con reglas sobre las
   mismas variables que alimentan la alerta. Mide **adelanto frente a un umbral de
   severidad**, no capacidad predictiva frente a un desenlace externo (impago real,
   concurso). Para eso haría falta una etiqueta que el dataset no incluye.
2. **Los lifts son moderados** (1,4-1,5). Con una tasa base del 12-34%, la señal
   informa pero no separa limpiamente. No conviene presentarla como más de lo que es.
3. **El stock de deuda sigue siendo una foto.** `debt_service` cubre 718 empresas
   todos los meses, pero no dice cuánto queda por pagar. `guarantee` y `confirming`
   siguen inflando el snapshot.
4. **La morosidad depende de reconstruir el vencido histórico.** Está documentado en
   `README_Data_Analysis.md` §4.6; el 55-61% de las filas no tiene morosidad fiable
   y por eso existen las cascadas.
5. **El prior y los percentiles están congelados sobre esta población.** Eso es lo
   que hace determinista el score sobre empresas nuevas. Si el conjunto de
   evaluación tuviera una composición muy distinta, habría que **recalibrar a
   propósito** (borrar `model/` y reejecutar), no dejar que ocurra en silencio.

---

## 12. Qué haría falta para pasar a un modelo

Hay una `y` honesta **sin etiqueta de quiebra**: el propio score futuro. El
dashboard ya lleva un **bonus walk-forward** sobre `score_suavizado`: en cada
origen entrena con los últimos 6–12 meses, predice el siguiente, avanza. La
ventana se amplia hasta 12 y luego se desliza, para que un régimen antiguo no
mande después de un giro. Theil-Sen y banda = p80 del error fuera de muestra.
Eso no entra en el score: es lectura de la ficha.

Para un modelo de verdad, en orden de valor:

1. **Una etiqueta real de desenlace**, aunque sea débil (impago confirmado,
   refinanciación, cierre). Con eso, todo lo anterior se puede validar de verdad y
   un gradient boosting sobre las features ya construidas tendría sentido.
2. **Histórico de deuda financiera**, no solo el snapshot. Desbloquearía el eje de
   apalancamiento y probablemente sería el predictor más fuerte del panel.
3. **Sector y tamaño** para comparar contra la cohorte correcta. Ahora mismo los
   percentiles transversales comparan a toda la muestra entre sí, y una constructora
   no tiene el mismo patrón de cobro que una consultora.

Mientras no haya nada de eso, el techo no lo pone el algoritmo, lo pone el dato.

---

Un matiz que cambió con la iteración 5: el detector de giro **crea** un objetivo
que antes no existía, "¿caerá esta empresa N puntos de aquí a 3 meses?", derivado
del comportamiento observado y no de nuestro criterio. Eso sí es una `y` legítima
para entrenar, con corte temporal estricto. Sigue siendo el paso siguiente y no el
primero, y solo se hace si bate a la regla: hoy la regla de tres criterios separa
+5,28 de −2,54 puntos a 6 meses, que es un punto de partida exigente.

---

## 13. Registro de cambios

### Iteración 8 · Versión final: lo mejor de los dos enfoques

Se auditaron las 112 columnas que quedaban. 32 no las nombraba nadie fuera de
`build_features`: se calculan, se usan y se tiran al escribir el panel.
Quedan **73**, todas con consumidor.

Del otro enfoque del equipo se adoptó lo que mejoraba el dato y se rechazó lo
que introducía look-ahead o un 50 inventado:

- Flujos **operativos** (sin `transfer` / inversión / cuentas de deuda). El prior
  de contracción pasa de 56,6 a **51,9**.
- `debt_service` mensual (718 empresas) como modulador, en lugar de fiarse solo
  de la foto de deuda.
- `refund_rate` como modulador del cobro (427 empresas).
- Recalibración deliberada de `pctl_reference.json` (10 columnas) y
  `prior_contraccion.json`: la definición de flujo cambió, conservar la
  referencia vieja comparaba peras con manzanas.

No se adoptó: nota 50 si falta dato, caja reconstruida hacia atrás, leverage
backfilled, runway al 24%, `zero_months` como eje, ni el gap `score_fast − score`.

Población vigente: 229 SALUDABLE / 538 ESTABLE / 315 EN RIESGO / 132 FRÁGIL /
66 CRÍTICO / 6 NO EVALUABLE. Bache +4,69 vs caída estructural −1,66 a 6 meses.

### Iteración 7 · Poda de residuo antes de producto

Se dejaron de calcular columnas que el motor no leía: DSO/DPO, HHI, n contrapartes,
`flujo_yoy`, `flag_burn_alto`, percentiles huérfanos, z-scores mudos, columnas de
rectificativas, deltas de recuperaciones retiradas y conteos internos.
El score no cambia: esas columnas no entraban en ningún eje, modulador ni alerta.
El mapa de lo que producto sí tiene que leer está en `ENTREGA_PRODUCTO.md` §8.

### Iteración 6 · Limpieza y documentación

- **§3.1 nuevo: el histórico de las tres calibraciones de peso** (v1 intuición → v2
  dirección → v3 evidencia medida). Era lo único de la evolución del motor que no
  estaba escrito en ninguna parte: hasta ahora solo existían los pesos vigentes.
- Código muerto eliminado tras auditar el paquete por AST: `BURN_RATE_CAP`,
  `ALERTA_Z_DIRECCION`, `ALERTA_PCTL_NIVEL` y `BACHE_MESES_SOSTENIDO` habían quedado
  huérfanas al reescribir las alertas y al colapsar la clasificación de caídas a dos
  clases. Ningún archivo `.py` sobraba.
- Referencias cruzadas de `config.py` corregidas: apuntaban a una sección de
  `FEATURES.md` que no existe, y el comentario de `PESOS` describía la trayectoria en
  0,25 cuando vale 0,18.
- Cifras de población de §7.1 reajustadas al último run (632 / 306 / 147 / 27).
- `FEATURES.md` §10 y §11 realineadas: documentaban el motor de 7 ejes y proponían la
  regla de disparo que después medimos con lift 0,90. El apartado se conserva
  documentando el error en lugar de borrarlo.
- Diagrama de §2 actualizado: tres señales de alerta (nivel / cola / giro), vista
  de grupo y calibraciones congeladas en `model/`. El prior ya no se "estima al
  vuelo": viaja congelado junto a los percentiles.
- `FEATURES.md` §7 y §11.1 dejaban listadas columnas `_6m` ya podadas y describían
  los pesos de la v1 (morosidad 30% + runway 18%) como si siguieran vigentes.

### Iteración 5 · Las seis preguntas y la granularidad

- **`senal_giro`**: detector de caída medido en sigmas de la propia empresa. Cierra
  la pregunta 3, que estaba sin contestar: en el caso "de 82 a 68" la alerta pasa
  del 2,7% al 30,4% de cobertura, sobre una base poblacional del 4,9%.
- **`naturaleza_caida`**: bache o caída estructural, con criterios elegidos por lo
  que predijeron el desenlace observado. El criterio inicial (share de deterioro
  estructural) tenía AUC 0,517 y se descartó; manda la volatilidad propia del score.
- **Atribución mes a mes** (`aporte_*`, `cambio_real`, `cambio_cobertura`,
  `motivo_cambio`), separando el movimiento por comportamiento del movimiento por
  llegada de datos nuevos.
- **`pctl_reference.json`**: distribución de referencia congelada. La desviación de
  los percentiles al puntuar 70 empresas sueltas baja de ~0,045 a ~0,005.
- **Bug corregido**: el percentil contra referencia mandaba los empates al borde
  inferior del escalón, y `stock_prov_sobre_ingresos` es 0 en el 60% de las filas.
  Ahora se toma el punto medio del empate, como hace `rank()`.
- **Giro y canales separados**: fusionarlos hundía el lift de los canales de 1,52 a
  1,04. Responden a preguntas distintas y se validan contra desenlaces distintos.
- **`scores_grupo.csv`**: vista de grupo con score agregado, peor filial, dispersión
  interna y el flag `agregado_esconde_problema`, que salta en el 23,6% de los grupos.
- **Antelación por empresa**: `meses_anticipacion` y `meses_ganados_a_nivel` se
  devuelven a `scores_finales.csv` desde `evaluate_anticipation.py`, fuera del motor
  para no meter información futura en un archivo que debe ser causal.

### Iteración 4 · Motor de scoring

- Ejes redefinidos a 6 con cascada de fuentes. Mediana de meses evaluados 6 → 19,
  empresas NO EVALUABLE 87 → 5.
- `apalancamiento` deja de ser eje y pasa a modulador acotado (cobertura 1,2%).
- Nuevas columnas en el panel: `flujo_pendiente_robusta_6m` (Theil-Sen),
  `recuperacion_stock_prov`, `recuperacion_stock_clientes`, `ventas_acum`,
  `compras_acum`, `pctl_runway_meses`, `pctl_flujo_volatilidad_6m`,
  `pctl_stock_clientes_sobre_ingresos`, `pctl_recuperacion_stock_prov`,
  `pctl_flujo_pendiente_robusta_6m`, `pctl_gastos_momentum_3m`.
- **Bug corregido en `pctl_mes`**: `rank(pct=True)` ordena por valor crudo, pero el
  docstring prometía "0 = peor, 1 = mejor". En deuda, impagos y edad el percentil
  estaba invertido y la alerta llamaba "peor cuartil" al mejor. Ahora la firma
  exige orientación explícita (`mas_es_mejor`).
- **`flujo_relativo` acotado** a ±12. Sin tope, la volatilidad llegaba a 515.466 y
  la pendiente a 446.406, lo que amortiguaba la trayectoria de todas las empresas
  al entrar en la distribución transversal.
- Contracción empírica hacia el prior según evidencia efectiva. Resuelve el caso de
  la empresa con 1 mes y score 95.
- Umbrales de clasificación recalibrados (80/60/40/20 → 68/52/42/33) a la escala del
  score de empresa, no a la del mensual.
- Alerta reconstruida en dos capas tras medir que la versión de una sola capa tenía
  lift 0,90. Canales `riesgo_impago_comercial` y `riesgo_asfixia_caja`.
- Volatilidad del flujo reconvertida de amortiguador a señal (penaliza el colchón).
- Nuevos scripts: `screen_signals.py` (AUC y lift por señal, justifica los pesos),
  `evaluate_anticipation.py` (antelación medida contra eventos de severidad).
