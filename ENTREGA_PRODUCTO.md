# Entrega a Producto — Motor de score de salud financiera

Qué devuelve el sistema, qué significa cada campo y qué pondera cada factor.
El diseño del motor está en `docs/SCORE_ENGINE.md`. El diccionario de variables
está en `docs/FEATURES.md`.

---

## 1. Qué hace

Lee 25 meses del rastro financiero de 1.286 empresas —banco, facturas, pagos,
deuda— y devuelve, **por empresa y por mes**, una nota 0–100, la dirección y
el motivo.

No es un rating estático. Si falta un eje, se apaga: **nunca se imputa un 50**.
La limpieza queda en `data/features/cleaning_log.json`.

---

## 2. Qué pondera

### 2.1 Los seis ejes

Los pesos se fijaron midiendo, para cada señal, su capacidad de anticipar
problemas a 12 meses (`screen_signals.py`).

| Eje | Peso | Pregunta | Por qué ese peso |
|---|---|---|---|
| **Deuda comercial** | 20% | ¿Paga a proveedores? | Predictor más fuerte (AUC 0,83). No pagar es decisión propia: asfixia ya materializada |
| **Liquidez** | 18% | ¿Genera caja frente a su tamaño? | Normalizado por ingresos; comparable entre pymes y grupos |
| **Colchón** | 18% | ¿Cuántos meses aguanta? | Incluye la penalización por volatilidad (AUC 0,71 sobre asfixia) |
| **Trayectoria** | 18% | ¿Hacia dónde va? | Pesa porque el producto necesita dirección. AUC 0,49 sobre eventos: no se vende como predictor |
| **Eficiencia** | 14% | ¿Gasta más de lo que ingresa? | Referencia 1,0 = equilibrio, sin calibrar |
| **Cobro de clientes** | 12% | ¿Le pagan a ella? | Contagio (AUC 0,72). Pesa menos que proveedores: es en parte riesgo de un tercero |

### 2.2 Moduladores (corrigen, no puntúan)

| Modulador | Tope | Cuándo actúa |
|---|---|---|
| Volatilidad del flujo | −14 pts | Flujo errático exige más colchón |
| Antigüedad del impago | −15 pts | Deuda envejecida es impago, no retraso |
| Runway real | ±12 pts | Solo el mes con foto de caja, por percentil |
| Concentración de contraparte | −10 pts | Solo si el eje ya está por debajo de 60 |
| Apalancamiento + caja negativa | ±8 pts (caja −4) | `debt_service` todos los meses; foto de deuda y `caja_negativa_flag==1` solo con snapshot. NaN no penaliza |

### 2.3 Cómo se combinan los meses

Media exponencial de los 25 meses, semivida 6. Peso de cada mes =
`recencia × confianza × cobertura`. Encima, contracción hacia el prior **54,41**
si hay poca evidencia: un solo mes no saca 95.

---

## 3. Archivos de salida

| Archivo | Grano | Uso |
|---|---|---|
| `scores_finales.csv` | 1 fila por empresa | Ranking y tabla principal |
| `scores_mensuales.csv` | empresa × mes | Curva y detalle temporal |
| `scores_grupo.csv` | 1 fila por grupo (249) | Vista de holding |
| `score_explanations.json` | 1 entrada por empresa | El “por qué”, listo para UI o agente |
| `anticipation_report.csv` | empresa × evento | “Lo vimos N meses antes” |
| `alerts.csv` | avisos del monitor | Pestaña Monitor |

### Cómo se lee una empresa

Cuatro campos juntos, nunca uno solo:

1. **`score_final`** y **`clasificacion`** — el nivel.
2. **`tendencia`** — la dirección. 48 MEJORANDO puede ser mejor apuesta que 62 DETERIORANDO.
3. **`confianza`** / **`apto_ranking`** — si la nota se sostiene.
4. **`motivo_cambio_ultimo_mes`** — por qué se movió.

| Clase | Umbral | Empresas |
|---|---|---|
| SALUDABLE | ≥ 68 | 229 |
| ESTABLE | 52 – 68 | 538 |
| EN RIESGO | 42 – 52 | 315 |
| FRÁGIL | 33 – 42 | 132 |
| CRÍTICO | < 33 | 66 |
| NO EVALUABLE | sin evidencia | 6 |

Umbrales **absolutos**. Media 55,4, mediana 55,5, recorrido 16,22–87,81.
Nadie saca 0 ni 100: el agregado exige consistencia.

Campos de producto, no solo de score:

| Campo | Qué permite |
|---|---|
| `giro_detectado`, `giro_sigmas`, `primer_giro` | Quién se tuerce mientras sigue pareciendo sana |
| `naturaleza_caida` | `bache` vs `caida_estructural` |
| `cambio_real` vs `cambio_cobertura` | “Ha empeorado” vs “ahora la vemos mejor” |
| `aporte_*` | Descomposición del Δscore, sin residuo |
| `meses_anticipacion`, `meses_ganados_a_nivel` | Antelación cuantificada |
| `agregado_esconde_problema` | La media del holding no basta |

---

## 4. Las seis preguntas

| Pregunta | Campo | Resultado |
|---|---|---|
| Quién está sano | `clasificacion` | 229 / 538 / 315 / 132 / 66 / 6 |
| Quién está mejorando | `tendencia` | 262 MEJORANDO · 398 DETERIORANDO |
| Quién empieza a torcerse | `giro_detectado` + `score_final` ≥ 55 | **420 llamadas** |
| Bache o caída | `naturaleza_caida` | Bache +4,69 a 6 m (52% recupera). Caída −1,66 (33% sigue) |
| Por qué ha cambiado | `motivo_cambio`, `aporte_*` | 17.744 filas-mes; 5,5% lo mueve un dato nuevo |
| Cuándo se vio venir | `meses_anticipacion` | +2 meses vs nivel en asfixia; +1 en impago |

Tres recuentos que no se mezclan: `alerta_temprana` = 1.111 (nivel o cola);
`giro_detectado` = 624; lista de llamadas = **420**. El giro no se vende como
predictor de asfixia (lift 0,90): se vende como el caso «82→68».

El detector mide la caída contra **la propia volatilidad histórica** de esa
empresa. Un percentil de cohorte no ve a quien cae de 82 a 68: sigue mejor que
la mayoría.

---

## 5. Empresa o grupo

El cálculo es **por empresa**. La vista de grupo va encima. Nunca al revés.

| Medida | Valor |
|---|---|
| Grupos | 249 |
| Tendencias opuestas dentro | 85 (34,1%) |
| El agregado esconde una empresa en riesgo | 74 (29,7%) |
| Dispersión interna (mediana) | 5,4 pts |

El toggle empresa/grupo es de **vista**, no de cálculo. Dos calibraciones
cambiarían la nota de la misma empresa según el modo.

---

## 6. Garantías y límites

Puntuar 70 empresas aisladas, con `model/` congelado, da la misma
`clasificacion` y `tendencia` que dentro de las 1.286 (`score_final` desviación
0,0000). Borrar `model/` recalibra en silencio.

Límites que hay que decir:

1. No hay etiqueta de impago real ni concurso. Se mide adelanto frente a un
   umbral de severidad del propio comportamiento.
2. Lifts 1,4–1,5 sobre tasas base 12–34%. Informa; no es un semáforo infalible.
3. Un solo mes de foto de deuda. No se castiga un sobreapalancamiento de hace
   un año.
4. No se filtra facturación intragrupo.
5. No hay sector: los percentiles comparan a toda la muestra.

---

## 7. Qué lee el producto

No hacen falta las 69 columnas del panel. Estas sí:

| Superficie | Campos | Origen |
|---|---|---|
| Ranking | `company_id`, `group_id`, `score_final`, `clasificacion`, `tendencia`, `confianza`, `apto_ranking` | `scores_finales.csv` |
| Quién se tuerce sana | `giro_detectado`, `naturaleza_caida`, `giro_sigmas`, `primer_giro`, `caida_score_3m` | idem |
| Por qué este número | `factores.*.score`, `factores.*.razon`, `factores.*.peso_efectivo` | `score_explanations.json` |
| Por qué ha cambiado | `motivo_cambio_ultimo_mes`, `cambio_real`, `cambio_cobertura`, `aporte_*` | json + finales |
| Cuándo se vio | `meses_anticipacion`, `meses_ganados_a_nivel`, `primera_alerta` | finales |
| Grupo | `score_grupo`, `score_peor`, `empresa_peor`, `agregado_esconde_problema` | `scores_grupo.csv` |
| Curva | `year_month`, `score_mensual`, `score_trayectoria`, `alerta_tipo`, `senal_giro` | `scores_mensuales.csv` |

Cada eje tiene cascada. Si falta la fuente precisa, usa la siguiente o se apaga.

| Eje | Peso | Fuente 1 | Fuente 2 | Fuente 3 |
|---|---|---|---|---|
| Deuda comercial | 20% | `% impagos proveedores 3m` | stock vencido / ingresos | “ha comprado y no debe” |
| Liquidez | 18% | flujo relativo 3m | flujo del mes | — |
| Colchón | 18% | colchón de flujo 6m | runway (solo foto de caja) | — |
| Trayectoria | 18% | Theil-Sen + momentum + z + persistencia | — | — |
| Eficiencia | 14% | burn rate 3m | burn rate del mes | — |
| Cobro | 12% | `% vencido sin cobrar 3m` | stock clientes / ingresos | “ha vendido y no le deben” |

---

## 8. Lo que hay construido encima del score

`python -m src.brief_server` sirve `dashboard/index.html`:

- Cartera, ficha, grupos, quién se mueve, monitor y método.
- **Plan de acciones** — ficha cerrada + RAG (`docs/TEORIA_PYME.md`) + catálogo
  (`src/playbook_acciones.py`). Sin red.
- **Agente + LLM** — Gemini redacta las secciones de la ficha
  (situación, tesorería, límites, acciones). El impacto es el eje de hoy, no
  un score futuro inventado.

El producto que se vende es la **lista de 420 llamadas** (giro estando sana,
bache vs caída, motivo, antelación). El comprador es Embat; quien firma es
riesgo / tesorería del cliente.

Tres preguntas que la UI ya contesta sobre cualquier empresa:

1. ¿Está sana, o se está torciendo aunque el número aún se vea bien?
2. ¿Es un bache o una caída que se va a sostener?
3. ¿Qué eje se movió, y cuántos meses hace que el sistema lo vio?
