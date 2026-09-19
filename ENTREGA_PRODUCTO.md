# Entrega a Producto — Motor de score de salud financiera

Documento de traspaso. Explica **qué devuelve el sistema, qué significa cada cosa y
qué pondera cada factor**, sin necesidad de leer el código.

Los documentos técnicos están en `docs/`: `SCORE_ENGINE.md` (motor),
`FEATURES.md` (variables), `LIMPIEZA.md` (fechas, suciedad, moneda) y
`README_Data_Analysis.md` (pipeline). El código vive en `src/`. Este documento
es autosuficiente para decidir qué construir encima.

---

## 1. Qué hace el sistema en una frase

Lee 25 meses del rastro financiero de 1.286 empresas —movimientos de banco, facturas
emitidas y recibidas, comportamiento de pago, deuda— y devuelve, **por empresa y por
mes**, una puntuación de 0 a 100, la dirección en la que se mueve, y la explicación
de por qué.

Lo que lo diferencia de un rating: no es una foto, es una trayectoria, y cada número
viene con su motivo. No hay caja negra en ninguna parte del recorrido.

La limpieza queda auditada en `data/features/cleaning_log.json`: vencimientos
imposibles se reparan, los ceros y los outliers no entran, y un mes anterior al
alta de la empresa es NaN (sin evidencia), no un 0 silencioso. Si falta un eje, se
apaga: **nunca se imputa un 50**.

---

## 2. Qué pondera cada cosa

### 2.1 Los seis ejes del score

Esta es la tabla que hay que conocer. Los pesos **no son una opinión**: se fijaron
después de medir, para cada señal, su capacidad de anticipar problemas reales a 12
meses (AUC y lift, calculados por `screen_signals.py`).

| Eje | Peso | Qué pregunta responde | Por qué ese peso |
|---|---|---|---|
| **Deuda comercial** | **20%** | ¿Paga a sus proveedores? | El predictor más fuerte del sistema (AUC 0,83). No pagar es una **decisión** de la empresa, casi siempre porque no puede: es asfixia ya materializada |
| **Liquidez** | **18%** | ¿Genera caja en relación a su tamaño? | Normalizado por ingresos, hace comparable una pyme con un grupo |
| **Colchón** | **18%** | ¿Cuántos meses aguanta? | Incluye la penalización por volatilidad, que resultó el mejor predictor único de asfixia de caja (AUC 0,71) |
| **Trayectoria** | **18%** | ¿Hacia dónde va? | Pesa por lo que el negocio necesita, no por lo que predice: su AUC es 0,49, o sea nula. Se mantiene alto porque alimenta MEJORANDO/DETERIORANDO, que es producto |
| **Eficiencia** | **14%** | ¿Gasta más de lo que ingresa? | Su referencia no hay que calibrarla: 1,0 es el equilibrio exacto |
| **Cobro de clientes** | **12%** | ¿Le pagan a ella? | Canal de **contagio**: que no te paguen anticipa que no pagues (AUC 0,72). Pesa menos que proveedores porque es en parte riesgo de un tercero |

Dos cosas que conviene poder explicar a un cliente:

- **Proveedores pesa más que clientes** (20% vs 12%) y no es arbitrario: que una
  empresa no pague es su propia falta de caja; que no le paguen es, en parte, el
  problema de otro.
- **La trayectoria pesa 18% aun sabiendo que no predice eventos.** Es una decisión
  de producto declarada, no un descuido: el cliente necesita dirección, y esa señal
  la da bien. Lo que no se hace es presentarla como capacidad predictiva.

### 2.2 Los moduladores (corrigen, no puntúan)

No son ejes. Ajustan un score ya calculado, siempre con tope, y solo donde tienen
sentido económico.

| Modulador | Tope | Cuándo actúa |
|---|---|---|
| Volatilidad del flujo | −14 pts | Un flujo errático exige más colchón que uno estable |
| Antigüedad del impago | −15 pts | Deuda envejecida es impago, no retraso de gestión |
| Runway real | ±12 pts | Solo en el mes con foto de caja, y por percentil |
| Concentración de contraparte | −10 pts | **Solo si el eje ya está por debajo de 60.** Penalizar a una empresa sana por tener pocos proveedores sería castigar su modelo de negocio |
| Apalancamiento | ±8 pts | Solo en el mes con foto de deuda |

### 2.3 Cómo se combinan los meses

El score de empresa no es el del último mes: es una media exponencial de los 25, con
semivida de 6 meses. El peso de cada mes es `recencia × confianza × cobertura`, así
que **un mes antiguo con datos completos pesa más que uno reciente con datos
dudosos**.

Encima va una corrección importante para producto: si una empresa tiene poca
evidencia, su score se acerca al comportamiento típico (51,04) en lugar de afirmar un
extremo. Sin esto, una empresa con **un solo mes** de datos salía con 95,0 y
encabezaba el ranking. Ahora ese caso cae a ~60 solo, sin filtros manuales.

---

## 3. Qué archivos se entregan y cómo se leen

| Archivo | Grano | Para qué sirve en producto |
|---|---|---|
| `scores_finales.csv` | 1 fila por empresa | La tabla principal y el ranking |
| `scores_mensuales.csv` | 1 fila por empresa y mes | Gráficos de evolución y detalle temporal |
| `scores_grupo.csv` | 1 fila por grupo (249) | Vista de holding |
| `score_explanations.json` | 1 entrada por empresa | El "por qué", listo para UI o para un agente LLM |
| `anticipation_report.csv` | 1 fila por empresa y evento | Sostener la afirmación "lo vimos N meses antes" |

### 3.1 Cómo se lee una empresa

**Nunca con un solo número.** Cuatro campos juntos:

1. **`score_final`** (0-100) y su **`clasificacion`** — el nivel.
2. **`tendencia`** — la dirección. Una empresa en 48 y MEJORANDO puede ser mejor
   apuesta que una en 62 y DETERIORANDO. El reto lo pide explícitamente y es
   probablemente el mayor diferencial comercial.
3. **`confianza`** y **`apto_ranking`** — si la nota se sostiene. El sistema dice
   cuándo no sabe, en lugar de rellenar el hueco con un 50.
4. **`motivo_cambio_ultimo_mes`** — por qué se movió.

### 3.2 Las clasificaciones

| Clase | Umbral | Empresas |
|---|---|---|
| SALUDABLE | ≥ 68 | 139 |
| ESTABLE | 52 – 68 | 510 |
| EN RIESGO | 42 – 52 | 349 |
| FRÁGIL | 33 – 42 | 191 |
| CRÍTICO | < 33 | 91 |
| NO EVALUABLE | sin evidencia suficiente | 6 |

Los umbrales son **absolutos a propósito**. Un percentil calculado sobre el conjunto
que toque evaluar clasificaría distinto a la misma empresa según con quién la
comparen, y eso es indefendible ante un cliente.

Que nadie saque 0 ni 100 es correcto: el score agrega 25 meses, así que los extremos
exigen consistencia y no un mes excepcional. Distribución real: media **52,1**,
mediana **52,2**, recorrido 13,45–84,18 (el suelo bajó al filtrar transferencias
que inflaban ingresos).

### 3.3 Los campos que dan producto, no solo score

Estos son los que permiten construir algo que alguien firme:

| Campo | Qué permite |
|---|---|
| `giro_detectado`, `giro_sigmas`, `primer_giro` | La lista de empresas que **se están torciendo mientras siguen pareciendo sanas** |
| `naturaleza_caida` | Separar `bache` de `caida_estructural`: evita la llamada innecesaria |
| `cambio_real` vs `cambio_cobertura` | Distinguir "ha empeorado" de "ahora la vemos mejor" |
| `aporte_*` (por eje) | Descomposición exacta del cambio, sin residuo |
| `meses_anticipacion`, `meses_ganados_a_nivel` | El argumento de venta cuantificado |
| `agregado_esconde_problema` (grupo) | Avisar de que la media del holding no basta |

---

## 4. Las seis preguntas del reto y su respuesta medida

| Pregunta | Campo | Resultado |
|---|---|---|
| Quién está sano | `clasificacion` | 139 SALUDABLE, 510 ESTABLE, 349 EN RIESGO, 191 FRÁGIL, 91 CRÍTICO, 6 NO EVALUABLE |
| Quién está mejorando | `tendencia` | 262 MEJORANDO (y 398 DETERIORANDO) |
| Quién empieza a torcerse | `giro_detectado` + `score_final` ≥ 55 | **337 llamadas ahora** (351 tuvieron el giro aún sanas; 14 ya cayeron) |
| Bache o caída | `naturaleza_caida` | Bache: +4,81 pts a 6 meses (53% recupera). Caída estructural: −1,76 (34% sigue) |
| Por qué ha cambiado | `motivo_cambio`, `aporte_*` | 17.744 filas-mes; 5,5% lo mueve un dato nuevo |
| Cuándo se vio venir | `meses_anticipacion` | **+2 meses** vs nivel en asfixia; +1 en impago |

**Tres recuentos que no se mezclan en una demo.** `alerta_temprana` = 1.122
(nivel o cola: recall, no prioridad). `giro_detectado` = 550 (se torció contra
sí misma). Lista de llamadas = **337** (giro y **sigue** ≥ 55). El giro no se
vende como predictor de asfixia (lift 0,78): se vende como el caso «82→68».

**La tercera merece contexto porque es la que el enunciado plantea de forma más
explícita** ("de 82 a 68 sigue pareciendo sana"). La primera versión del sistema la
contestaba peor que el azar: la alerta saltaba en el 2,7% de esos casos frente al
5,0% de la población general. El motivo era estructural: las alertas disparaban por
percentil adverso, y una empresa que cae de 82 a 68 no está en el peor quintil de
nada. Hizo falta un detector que mide la caída contra **la propia volatilidad
histórica de esa empresa**, no contra la cohorte. Cobertura del caso: 2,7% → 30,4%.

---

## 5. Empresa o grupo: qué se vende

El cálculo es **por empresa** y la vista de grupo va encima. Nunca al revés, porque
agregar es una proyección que no se deshace: puntuando las 1.286, el grupo es una
suma; puntuando los 249 grupos, no hay forma de bajar a la empresa.

Los datos, por si surge la pregunta comercial:

| Medida | Valor | Lectura |
|---|---|---|
| Grupos | 249 | Vista, no segundo cálculo |
| Grupos con tendencias opuestas dentro | 85 (34,1%) | Una media las cancelaría |
| Grupos donde el agregado **esconde** una empresa en riesgo | **79 (31,7%)** | En 1 de cada 3 grupos, agregar borra la señal que el cliente paga por ver |
| Dispersión interna (mediana) | 5,4 pts | El holding «parece» estable y una filial no |

**Sobre el toggle empresa/grupo en producto: sí, pero como toggle de vista, no de
cálculo.** Si fuera configurable en el cálculo habría que mantener dos calibraciones
—umbrales, percentiles y prior son distintos con 250 unidades que con 1.286— y
explicar por qué la misma empresa cambia de nota según el modo. Con una sola
calibración, la vista de grupo es una agregación y no una segunda verdad.

---

## 6. Qué garantiza el sistema, y qué no

### 6.1 Determinismo sobre empresas nuevas (verificado)

El criterio de evaluación más exigente del reto es que el score "aguante en las 60-80
empresas que vuestro sistema no ve nunca". Está **probado, no asumido**: se
reconstruyó el pipeline completo con 70 empresas y solo 70, y se comparó con lo que
sacaron dentro de las 1.286.

| Salida | Desviación |
|---|---|
| `score_final` | **0,0000** |
| `clasificacion` | **0 de 70 cambian** |
| `tendencia` | **0 de 70 cambian** |

Esto no salía gratis. Requirió congelar dos calibraciones en `model/`: la
distribución de percentiles de referencia y el prior de contracción. Sin el segundo,
la desviación era de 1,13 puntos de media y **6 de cada 70 empresas cambiaban de
clasificación**. Para producto la implicación es concreta: **la carpeta `model/` viaja
con el sistema**. Borrarla lo recalibra en silencio.

### 6.2 Lo que hay que decir con honestidad

Estas limitaciones deberían aparecer en cualquier material comercial, porque
sostenerlas es más defendible que esconderlas:

1. **No es validación contra impagos reales.** El dataset no trae ninguna etiqueta de
   desenlace (ni impago confirmado, ni concurso, ni default). Lo que medimos es
   **adelanto frente a un umbral de severidad definido sobre el propio
   comportamiento**, no capacidad predictiva frente a un hecho externo.
2. **Los lifts son moderados** (1,4-1,5 sobre tasas base del 12-34%). La señal
   informa y prioriza, pero no separa limpiamente. No es un semáforo infalible.
3. **La deuda es casi ciega**: hay un único mes con foto de deuda, así que no se puede
   penalizar a quien se sobreapalancó hace un año.
4. **No se filtra la facturación entre empresas del mismo grupo**, así que parte del
   "crecimiento" puede ser tesorería interna.
5. **No hay sector.** El dataset no lo trae, así que los percentiles comparan a toda
   la muestra entre sí, y una constructora no cobra como una consultora.

### 6.3 Por qué no hay machine learning

Es una pregunta que va a surgir, y la respuesta es defendible: **no hay etiqueta que
aprender**. Entrenar contra un objetivo definido por nosotros produciría un modelo
que aprende nuestra propia heurística con ruido encima, perdiendo la explicabilidad,
que es justo lo que hace vendible el producto. Prophet tampoco encaja: con 24 puntos
mensuales hay un único ciclo incompleto, y además no necesitamos predecir el flujo de
caja de marzo, necesitamos saber en qué dirección se mueve.

Lo que sí hay es estadística adecuada al problema: estimador de Theil-Sen para la
pendiente (resistente al mes atípico), z-scores contra la propia historia de la
empresa, percentiles dentro del mes y contracción empírica.

Donde ML sí tendría sentido, si se consigue el dato, está en `SCORE_ENGINE.md` §12.
El resumen: el techo no lo pone el algoritmo, lo pone el dato.

---

## 7. Dónde está el producto

El motor está terminado, medido y explicable. Lo que aún no existe es la capa que
alguien paga. La señal con más valor comercial y que nadie más tiene es esta
combinación:

> **337 empresas que se están torciendo mientras siguen puntuando por encima de 55**,
> separadas entre las que históricamente rebotan (`bache`) y las que no
> (`caida_estructural`), cada una con el motivo del cambio y los meses de antelación.

Eso no es un dashboard: es una **lista de llamadas priorizada** con el argumento ya
escrito. El comprador evidente es la propia empresa que entrega los datos, porque ya
tiene la relación con esas empresas y hoy no dispone de ese orden de prioridad.

Tres formas de empaquetarlo, de menos a más compromiso:

1. **Alerta para el equipo de riesgo**: quién revisar este mes y por qué, ordenado
   por antelación y severidad.
2. **Scoring como servicio**: puntuar carteras de terceros, apoyado en el
   determinismo verificado del §6.1.
3. **Precio ajustado al riesgo**: usar `naturaleza_caida` y `meses_anticipacion` para
   diferenciar condiciones, que es donde el score se convierte en margen.

---

## 8. Mapa canónico: qué lee el producto (y qué no)

Producto no necesita las 73 columnas del panel. Necesita **estas**, y están
todas justificadas: o mueven el número, o explican un cambio, o disparan un aviso.

### 8.1 Lo que hay que pintar

| Superficie | Campos | De dónde salen |
|---|---|---|
| Ranking / cartera | `company_id`, `group_id`, `score_final`, `clasificacion`, `tendencia`, `confianza`, `apto_ranking` | `scores_finales.csv` |
| Quién se tuerce estando sana | `giro_detectado`, `naturaleza_caida`, `giro_sigmas`, `primer_giro`, `caida_score_3m` | idem |
| Por qué este número | `factores.*.score`, `factores.*.razon`, `factores.*.peso_efectivo` | `score_explanations.json` |
| Por qué ha cambiado | `motivo_cambio_ultimo_mes`, `cambio_real`, `cambio_cobertura`, `aporte_*` | json + finales |
| Cuándo se vio | `meses_anticipacion`, `meses_ganados_a_nivel`, `primera_alerta` | finales (tras `evaluate_anticipation`) |
| Grupo | `score_grupo`, `score_peor`, `empresa_peor`, `agregado_esconde_problema` | `scores_grupo.csv` |
| Curva mensual | `year_month`, `score_mensual`, `score_trayectoria`, `alerta_tipo`, `senal_giro` | `scores_mensuales.csv` |

### 8.2 Los seis ejes (el equivalente a “las 13 métricas”)

No hay 13 notas independientes que producto tenga que entender. Hay **6 ejes**
con cascada. Si falta la fuente precisa, el eje no se inventa un 50: usa la
siguiente fuente o se apaga.

| Eje | Peso | Fuente 1 | Fuente 2 | Fuente 3 |
|---|---|---|---|---|
| Deuda comercial | 20% | `% impagos proveedores 3m` | stock vencido / ingresos | “ha comprado y no debe” |
| Liquidez | 18% | flujo relativo 3m | flujo del mes | — |
| Colchón | 18% | colchón de flujo 6m | runway (solo si hay foto de caja) | — |
| Trayectoria | 18% | pendiente Theil-Sen + momentum + z + persistencia | — | — |
| Eficiencia | 14% | burn rate 3m | burn rate del mes | — |
| Cobro clientes | 12% | `% vencimientos sin cobrar 3m` | stock clientes / ingresos | “ha vendido y no le deben” |

Un dato ausente **no cuenta como 50**. Eso inflaría a quien no tiene facturas.
El peso se reparte entre los ejes que sí tienen evidencia.

### 8.3 Qué se ha podado y por qué no volver a meterlo

El panel pasó de 150 a **69** columnas. Lo retirado no lo leía ningún eje,
modulador ni canal: DSO/DPO, HHI, `flujo_yoy`, flags y percentiles huérfanos,
rectificativas como columnas, deltas de recuperaciones muertas, conteos internos
y el andamiaje (`flag_*` crudos, `*_fuente`, `*_topado`, `mes_idx`).

Si en producto aparece la tentación de “añadir DSO al dashboard”, la respuesta
es `edad_media_stock_prov_dias`: misma idea, mejor cobertura, y sí alimenta
explicaciones.

### 8.4 Qué se tomó del score de 13 métricas, y qué no

Se comparó el otro enfoque del equipo (13 métricas, 4 bloques, nota 50 si falta
el dato, caja reconstruida, runway al 24%) contra el nuestro, idea por idea.
Tres cosas suyas **sí** mejoraban el dato y están dentro:

| Idea suya | Cómo la integramos | Por qué gana |
|---|---|---|
| Flujos solo operativos (sin transfer / inversión / deuda) | `caja_ingresos` / `caja_gastos` salen de cuentas de tesorería y categorías operativas | 152 k transferencias y 31 k pagos de deuda inflaban ingresos. Tras el filtro el prior congelado es **51,04** |
| `debt_service` de categorías bancarias | Modulador mensual (718 empresas, 68% de filas) | Su `leverage` era una foto de septiembre. El nuestro también; el servicio de deuda existe todos los meses |
| `refund_rate` (recibos devueltos) | Modulador del eje de cobro (427 empresas, 64% de filas) | Señal de pago que no está en las facturas y no es look-ahead |

Y estas **no** se copian:

| Ellos | Nosotros | Por qué no |
|---|---|---|
| Dato ausente = nota 50 | El eje se apaga | 502 empresas sin facturas conectarían un 50 falso en pago |
| Caja reconstruida hacia atrás | Snapshot solo en el último mes; el resto usa `colchon_flujo` | Reconstruir deja ~20% de cuentas en negativo. Es look-ahead |
| `leverage` de 2026-09 en todos los meses | Snapshot solo el mes de la foto; el resto usa `debt_service` | Aplicar la foto final al pasado es look-ahead |
| Runway 24% del score | Colchón 18%; runway corrige si existe | Runway cubre el 3,8% de las filas |
| `zero_months` al 13% | `mes_sin_ingresos` tumba eficiencia a 5; la persistencia ya pesa en trayectoria | Un eje nuevo al 13% sin medir repetiría el error de la v1 |
| Curvas fijas 0–100 y `score_fast − score` | Escalones medidos + giro en sigmas propias | El gap de ventanas es mecánico; el giro cierra el caso “82→68” |
| Score relativo opcional | Absoluto; percentiles solo en alertas | El cliente pregunta “¿está sana?”, no “¿es el percentil 40?” |

---

La demo navegable es `dashboard/index.html` (`python -m src.build_dashboard`).
Cartera, ficha, grupos, quién se mueve, **monitor que avisa** y método. El
producto que se vende es la **lista de llamadas priorizada** (giro estando sana,
bache vs caída, motivo, antelación), no el HTML en sí.

El comprador es Embat: ya tiene los datos y la relación. Quien firma es riesgo /
tesorería de su cliente.

---

## 9. Next steps (qué construir ahora, y en qué orden)

El motor está cerrado. Lo que falta es lo que el reto llama *construir algo encima*:
un producto que alguien firme. El orden no es estético, es el que más valor desbloquea
con el dato que ya tenemos.

### 9.1 Inmediato — la capa que se vende

**Una lista de llamadas priorizada**, no un dashboard genérico. La señal que nadie
más tiene es esta:

> 337 empresas que se están torciendo **mientras siguen pareciendo sanas**
> (`score_final ≥ 55` + `giro_detectado`), separadas en `bache` vs `caida_estructural`,
> cada una con el motivo del cambio y los meses de antelación.

Pantallas mínimas, en este orden:

1. **Radar de cartera** — ranking de `scores_finales.csv` filtrable por
   `giro_detectado`, `naturaleza_caida`, `tendencia`, `confianza` y `apto_ranking`.
   La cola que importa no es CRÍTICO (eso el cliente ya lo sabe): es SALUDABLE /
   ESTABLE con giro estructural.
2. **Ficha de empresa** — los seis ejes del último mes, el Δscore descompuesto
   (`aporte_*`), y el texto de `score_explanations.json`. Es la respuesta a
   "por qué ha cambiado" y a "por qué este número".
3. **Línea temporal** — `score_mensual` + `senal_giro` + `alerta_tipo` mes a mes.
   Es la respuesta a "cuándo se vio venir": marcar `primer_giro` sobre la curva.
4. **Vista de grupo** — `score_grupo` al lado de `score_peor`, con el flag
   `agregado_esconde_problema` como aviso, no como puntuación alternativa.
   Toggle de **vista**, nunca de cálculo (ver §5).

El comprador evidente es Embat: ya tiene los datos y la relación con esas empresas.
El usuario que firma es el equipo de riesgo / tesorería de su cliente, no el data
scientist que construyó el motor.

### 9.2 Justo después — lo que el motor aún no puede decir

Tres huecos abiertos, por orden de impacto comercial:

| Hueco | Por qué importa | Qué haría falta |
|---|---|---|
| Facturación **intragrupo** | Parte del "crecimiento" puede ser tesorería interna. Distorsiona volumen y morosidad | `group_id` ya está en el panel; falta cruzar `counterparty_id` con el directorio del grupo (hoy viven en espacios de nombres distintos) |
| Deuda **sin histórico** | Un solo mes de snapshot. No se puede castigar a quien se sobreapalancó hace un año | Serie mensual de `debt_products`, no solo la foto de septiembre 2026 |
| **Sector** | Los percentiles comparan a toda la muestra entre sí | Una columna de CNAE / industria. Sin ella, una constructora se mide contra una consultora |

Ninguno de los tres se resuelve con más algoritmo. El techo lo pone el dato.

### 9.3 Lo que NO es el siguiente paso

**No entrenar XGBoost / Prophet sobre este dataset.** No hay etiqueta de desenlace
(impago real, concurso, default). Entrenar contra un objetivo que definimos nosotros
produce un modelo que aprende nuestra heurística con ruido, y pierde la
explicabilidad, que es lo que hace vendible el producto.

Sí hay una `y` honesta **después** de tener producto: "¿caerá esta empresa N puntos
en 3 meses?", derivada del propio score observado, con corte temporal. El listón
ya está alto (la regla de bache vs caída separa +4,81 de −1,76 puntos a 6 meses).
Se hace si bate a esa regla, no antes. La infraestructura para medirlo ya existe
(`screen_signals.py`).

### 9.4 Criterio para saber si el producto está listo

Tres preguntas que un cliente de Embat debería poder responder en menos de un minuto
sobre cualquier empresa de su cartera:

1. ¿Está sana, o se está torciendo aunque el número aún se vea bien?
2. ¿Es un bache o una caída que se va a sostener?
3. ¿Qué eje se movió, y cuántos meses hace que el sistema lo vio?

Si la UI no contesta esas tres, el motor está bien y el producto no.
