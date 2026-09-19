
"""
Punto único de verdad para ventana temporal, umbrales y detección de esquema.
Ningún script escribe sobre los CSV RAW.
"""

from pathlib import Path
import pandas as pd

DATA_DIR = Path("data")
OUT_DIR = DATA_DIR / "features"
# Artefactos de MODELO, no de datos. Viven fuera de data/ a propósito: data/ está
# en .gitignore (contiene el dataset y las salidas regenerables), y la referencia
# de percentiles no es regenerable sin perder la calibración. Si se fuera con el
# resto, un clon limpio la recrearía contra otra población y el score dejaría de
# ser comparable sin que nada avisara.
MODEL_DIR = Path("model")
PANEL_PATH = OUT_DIR / "master_panel.csv"
AUDIT_PATH = OUT_DIR / "feature_audit.json"
QUALITY_PATH = OUT_DIR / "data_quality_report.txt"
SCORES_PATH = OUT_DIR / "scores_finales.csv"
SCORES_MENSUAL_PATH = OUT_DIR / "scores_mensuales.csv"
EXPLAIN_PATH = OUT_DIR / "score_explanations.json"
SCORES_GRUPO_PATH = OUT_DIR / "scores_grupo.csv"
ANTICIPATION_PATH = OUT_DIR / "anticipation_report.csv"
CLEANING_LOG_PATH = OUT_DIR / "cleaning_log.json"
ALERTS_PATH = OUT_DIR / "alerts.csv"
DASHBOARD_PATH = Path("dashboard") / "index.html"
# Distribución de referencia de los percentiles. Se congela en la primera
# ejecución sobre la población completa y se reutiliza siempre: es lo que hace
# que puntuar 70 empresas nuevas dé el mismo resultado que puntuarlas dentro de
# las 1.286. Borrar este archivo recalibra el sistema, y es una decisión
# deliberada, no un efecto secundario de volver a ejecutar el pipeline.
PCTL_REF_PATH = MODEL_DIR / "pctl_reference.json"
USAR_REFERENCIA_PCTL = True

# El prior de la contracción empírica también es calibración, no dato. Medido:
# congelando solo los percentiles, el score_bruto de 70 empresas sueltas sale
# EXACTO, pero el score_final se desviaba 1,13 puntos de media y 6 de cada 70
# cambiaban de clasificación, porque el prior se recalculaba con 49 empresas
# (47,74) en lugar de con la población de referencia (56,08).
PRIOR_REF_PATH = MODEL_DIR / "prior_contraccion.json"
USAR_REFERENCIA_PRIOR = True

START_DATE = pd.Timestamp("2024-09-01")
END_DATE = pd.Timestamp("2026-09-30")
EXTRACTION_DATE = pd.Timestamp("2026-09-18")
MONTH_START = START_DATE.to_period("M")
MONTH_END = END_DATE.to_period("M")
MONTHS = pd.period_range(MONTH_START, MONTH_END, freq="M")
PARTIAL_MONTHS = [EXTRACTION_DATE.to_period("M")]
EXCLUIR_MES_PARCIAL_DEL_SCORE = True

ROLL_SHORT = 3
ROLL_LONG = 6
MIN_FACTURAS_RATIO = 2
MIN_FACTURAS_RATIO_LARGO = 3
MIN_MESES_HISTORIA = 12

# El runway principal exige 3 meses reales de gasto para evitar explosiones
# artificiales por un primer mes con gasto casi cero.
MIN_MESES_RUNWAY = 3

DIAS_MADURACION = 45
HALF_LIFE_MONTHS = 6.0

# Antigüedad a partir de la cual un impago deja de ser un retraso de gestión.
DIAS_STOCK_ANTIGUO = 90

# Topes de cordura para ratios con denominador pequeño. No son cosmética: con
# ingresos_12m_avg cercanos a cero, stock/ingresos llegaba a 1.105.696 y el
# runway a 351.490 meses, lo que rompe cualquier media o percentil.
CAP_STOCK_SOBRE_INGRESOS = 24.0
CAP_RUNWAY_MESES = 120.0
# Un flujo mensual de 12x los ingresos medios anuales no es información, es un
# denominador roto. Sin este tope la volatilidad llegaba a 515.466 y la pendiente
# a 446.406, lo que amortiguaba la trayectoria de TODAS las empresas al entrar en
# la distribución transversal.
CAP_FLUJO_RELATIVO = 12.0

# Z-score contra la propia historia (base excluyendo el mes corriente).
Z_VENTANA = 12
Z_MIN_PERIODOS = 6
# Una desviación típica casi nula genera z de 1e16. Más allá de 10 sigmas el
# valor exacto no aporta: ya es "fuera de su normal" con la máxima intensidad.
Z_CLIP = 10.0

# Un crecimiento del 500% ya es extremo; por encima solo hay ruido de base
# pequeña. El suelo es -1 por construcción (no se puede caer más del 100%).
CAP_MOMENTUM = 5.0
CAP_COLCHON_MESES = 24.0
# Un mes con ingreso casi nulo produce burn 179. A 8x el eje de eficiencia
# ya está en suelo; el 3m no debe arrastrar tres meses por un denominador roto.
CAP_BURN_RATE = 8.0

# Antigüedad máxima creíble de un impago. Hay facturas con due_date corrupta
# que producían edades medias de 8.529 días (año 1993).
CAP_DIAS_IMPAGO = 720

# Reparación de vencimientos imposibles (año 2000/2050, plazo negativo o >2 años).
# Se sustituyen por emisión + 30 días. Decisión auditada en cleaning_log.json.
MAX_PLAZO_FACTURA_DIAS = 730
PLAZO_REPARACION_DIAS = 30

# Primer mes de actividad: si el primer movimiento cae después del día 3, ese
# mes está incompleto y no cuenta como observado.
DIA_MES_COMPLETO = 3

# Saldos |x| >= 1e9 son basura del origen (p. ej. 9.99e10), no tesorería real.
BALANCE_EXTREMO = 1e9

# Transacciones aún no asentadas: no son caja. DISCARDED se deja (es etiqueta
# de conciliación, no "este movimiento no existió").
TX_STATUS_EXCLUIDOS = {"pending"}

# Variantes de país en companies.csv. No entran al score; se normalizan por si
# producto las pinta. 82% del campo es nulo.
COUNTRY_NORMALIZE = {
    "ESPAÑA": "ES", "ESPANYA": "ES", "SPAIN": "ES",
    "PORTUGAL": "PT", "ITALIA": "IT", "ALEMANIA": "DE",
    "MALAYSIA": "MY",
}

# Monitor: meses mínimos entre dos avisos del mismo tipo, y calentamiento.
ALERT_MIN_GAP = 6
ALERT_WARMUP = 3

# Tipos de cambio fuera de este rango se tratan como no convertibles.
# Cubre pares tipo IDR/VND y descarta centinelas (0.0002, 20303, ...).
EXCHANGE_RATE_MIN = 0.001
EXCHANGE_RATE_MAX = 2500.0

# Evidencia mínima para emitir un score mensual.
MIN_PESO_CUBIERTO_SCORE = 0.55

# Pesos vigentes (v3). El histórico v1 → v2 → v3 y el porqué de cada movimiento
# están en SCORE_ENGINE.md §2. Resumen: se fijaron DESPUÉS de medir AUC/lift.
# Deuda comercial es el predictor más fuerte (0,20). Trayectoria pesa 0,18 por
# lo que pide el reto (dirección), no por lo que predice (AUC 0,49). El
# apalancamiento no es eje: con 1,2% de cobertura un peso fijo bloqueaba meses.
PESOS = {
    "liquidez": 0.18,
    "colchon": 0.18,
    "deuda_comercial": 0.20,
    "eficiencia": 0.14,
    "cobro_clientes": 0.12,
    "trayectoria": 0.18,
}

# Sub-pesos del eje de trayectoria. Cada componente devuelve una intensidad
# firmada en [-1, +1], donde +1 es la mejora máxima reconocible.
PESOS_TRAYECTORIA = {
    "pendiente_flujo": 0.35,
    "deuda_comercial_dir": 0.30,
    "ingresos_momentum": 0.25,
    "persistencia": 0.10,
}

# Saturaciones de cada señal de trayectoria: el valor a partir del cual la
# intensidad ya es +-1. Evitan que un outlier domine la dirección.
SAT_PENDIENTE_FLUJO = 0.10      # 10 pp de ingresos por mes
SAT_RECUPERACION_STOCK = 0.50   # medio mes de ingresos de deuda vencida
SAT_MOMENTUM = 0.30             # +-30% de variación trimestral

# Amortiguación por volatilidad: una serie errática no puede sostener una
# afirmación fuerte de dirección. Es el control de falsos positivos.
# La referencia se sitúa por encima de la volatilidad típica (mediana 0,47) para
# que la amortiguación castigue lo excepcional, no lo normal, y nunca baja de
# AMORTIGUACION_MIN: por muy errática que sea la serie, la dirección informa.
VOLATILIDAD_REFERENCIA = 1.50
AMORTIGUACION_MIN = 0.50

# Moduladores acotados (no son ejes: corrigen, no puntúan por sí solos).
MOD_CONCENTRACION_PUNTOS = 10.0
MOD_CONCENTRACION_UMBRAL = 0.50
MOD_APALANCAMIENTO_PUNTOS = 8.0
MOD_RUNWAY_PUNTOS = 12.0
MOD_VOLATILIDAD_PUNTOS = 14.0
MOD_ANTIGUEDAD_PUNTOS = 15.0
MOD_REFUND_PUNTOS = 12.0
CAP_DEBT_SERVICE = 2.0
CAP_REFUND_RATE = 1.0

# Contracción empírica hacia la media: con poca evidencia el score se acerca al
# comportamiento típico en lugar de afirmar un 95 o un 11 sobre un solo mes.
SHRINKAGE_EVIDENCIA = 0.75

# Alerta en DOS CAPAS, y la separación es el hallazgo central de la calibración.
#
# Medido contra eventos de severidad, un simple "score mensual bajo" batía a
# cualquier señal de dirección en recall, precisión y antelación. No es que la
# dirección no sirva: es que el evento SE DEFINE por nivel, así que una señal de
# nivel lo predice casi por construcción. Comparar las dos en el mismo cajón
# mide una tautología, no capacidad de anticipación.
#
# Capa NIVEL: el problema ya está encima. Alta cobertura, sirve para actuar hoy.
# Capa ANTICIPACIÓN: la empresa TODAVÍA no está mal, pero su dirección se ha
#   girado de forma sostenida. Es la única capa que puede comprar tiempo, y solo
#   se puede evaluar sobre empresas que aún no han caído de nivel.
ALERTA_NIVEL_CRITICO = 42.0      # capa NIVEL: score mensual ya en zona de riesgo
ALERTA_MESES_SOSTENIDO = 2       # evita el falso positivo de un mes raro

# Canales de anticipación. Los disparadores y sus pesos NO son intuición: salen
# de medir, sobre filas donde el nivel aún es aceptable, el lift de cada señal
# para que ocurra un evento en los 12 meses siguientes. Lo calcula
# screen_signals.py; el detalle de cada canal está en SCORE_ENGINE.md §7.
#
# Cada disparador es una condición de COLA (percentil adverso dentro del mes), no
# un umbral absoluto, por dos razones: varias señales resultaron NO monótonas
# (flujo_relativo_3m tiene AUC 0,49 pero lift 2,99 en su decil adverso, así que
# informa en la cola y no en el medio), y un percentil no envejece con la deriva
# del dataset.
#
# Canal de impago comercial. El disparador de clientes es el más valioso porque
# es el único no tautológico: mide contagio de un problema ajeno.
DISPARADORES_IMPAGO = [
    ("pctl_stock_prov_sobre_ingresos", 0.20, 3.0, "deuda vencida con proveedores en el quintil adverso"),
    ("pctl_stock_clientes_sobre_ingresos", 0.20, 2.0, "impago de sus clientes en el quintil adverso (contagio)"),
    ("pctl_recuperacion_stock_prov", 0.10, 2.0, "la deuda vencida crece, no se recupera"),
    ("pctl_clientes_morosos_3m", 0.20, 1.5, "morosidad de clientes en el quintil adverso"),
]
# Canal de asfixia de caja. La volatilidad del flujo es el mejor predictor único
# del panel para este evento (AUC 0,71): un flujo errático precede al colapso, y
# antes se usaba solo para amortiguar la trayectoria, tirando la señal a la basura.
DISPARADORES_ASFIXIA = [
    ("pctl_flujo_volatilidad_6m", 0.20, 3.0, "flujo de caja errático frente a su cohorte"),
    ("pctl_burn_rate_3m", 0.20, 2.5, "gasta por encima de sus ingresos de forma persistente"),
    ("pctl_flujo_relativo_3m", 0.10, 2.0, "flujo trimestral en el decil adverso"),
    ("pctl_colchon_flujo_meses", 0.20, 2.0, "colchón de flujo en el quintil adverso"),
    ("pctl_flujo_pendiente_robusta_6m", 0.10, 1.5, "pendiente del flujo en el decil adverso"),
]
# Disparadores con peso pero sin percentil: son ya binarios.
DISPARADORES_BINARIOS_IMPAGO = [
    ("persistente_flag_stock_prov_antiguo", 1.5, "impago envejecido sostenido"),
]
# Umbral de disparo como fracción del peso máximo del canal. Calibrado con el
# barrido de screen_signals.py: la alerta tiene que ser SELECTIVA, porque una
# señal que se activa en media muestra no puede tener precisión sobre la tasa
# base por bien construida que esté. 0,55 recorta la activación del 49% al 40%
# conservando 41 de los 43 eventos de asfixia que la capa de nivel no ve.
UMBRAL_CANAL = 0.55

# --- Detector de giro autorreferenciado -------------------------------------
# Cierra el caso "de 82 a 68 sigue pareciendo sana", que los canales de cola no
# pueden ver por construcción: una empresa que cae de 82 a 68 no está en el
# quintil adverso de nada. Medido antes de esto, la alerta se activaba en el 2,7%
# de esos casos, por debajo del 5,0% de la población general.
#
# El score mensual de una empresa mediana recorre 41,7 puntos entre su máximo y
# su mínimo, así que una caída de 14 puntos cabe en el ruido normal. Por eso el
# disparo es en SIGMAS DE LA PROPIA EMPRESA y no en puntos absolutos.
GIRO_VENTANA = 3                 # meses entre el nivel de referencia y el actual
GIRO_SUAVIZADO = 3               # mediana móvil: mata el mes atípico aislado
GIRO_VOL_VENTANA = 12            # base para medir la volatilidad propia del score
GIRO_VOL_MIN = 3.0               # suelo de sigma: evita dividir por casi nada
GIRO_SIGMAS = 1.25               # intensidad mínima de la caída, en sigmas propias
GIRO_PUNTOS_MIN = 6.0            # y además un mínimo absoluto, para no avisar por ruido
GIRO_NIVEL_MIN = 45.0            # por debajo de esto ya lo cubre la capa de nivel

# --- Bache o caída ----------------------------------------------------------
# Los criterios están medidos contra el desenlace observado: entre las empresas
# con giro, ¿su score suavizado sigue igual o peor 6 meses después? Tasa base de
# no recuperación 38,5%. El primer criterio que probé (qué fracción de la caída
# venía de los ejes estructurales) tenía AUC 0,517, es decir nada, y se descartó.
#
# Lo que sí discrimina, por orden de fuerza medida:
#
# 1. La VOLATILIDAD PROPIA del score (AUC 0,595 invertida). Es el criterio más
#    limpio y el más intuitivo: si una empresa cuyo score nunca se mueve pierde
#    10 puntos, se ha movido de verdad; si lo pierde una que oscila 40, es ruido.
#    Medido por terciles de volatilidad, la no recuperación va del 47,5% al 29,4%
#    y el rebote mediano a 6 meses de +0,83 a +10,70 puntos.
# 2. `cambio_real` (AUC 0,625), la parte del cambio atribuible al comportamiento
#    y no a la llegada de datos nuevos. Que la atribución construida para explicar
#    el cambio resulte además el mejor predictor de que la caída se sostiene no
#    era el objetivo, pero confirma que separa lo que tenía que separar.
# 3. Deuda comercial viva: si ya hay impago, la caída tiene dónde agarrarse.
#
# Deliberadamente NO se usan `score_mensual` ni `colchon_flujo_meses`, que también
# predicen la no recuperación (AUC 0,556 y 0,628) pero por reversión a la media:
# quien está alto tiene más sitio para caer y menos para rebotar. Eso predice sin
# explicar nada, y metería en el criterio un sesgo contra las empresas sanas.
BACHE_VOL_ESTABLE = 9.75         # tercil inferior de volatilidad del score
BACHE_CAMBIO_REAL = -4.0         # caída atribuible a comportamiento, en puntos
BACHE_STOCK_PROV = 0.10          # meses de ingresos en deuda vencida viva
BACHE_MIN_CRITERIOS = 2          # de los 3 anteriores, para llamarla estructural

# Umbrales calibrados sobre la población de referencia (1.286 empresas). Son
# absolutos a propósito: un percentil calculado sobre el conjunto de evaluación
# clasificaría distinto a la misma empresa según con quién la comparen, y con
# 60-80 empresas de test esos percentiles serían inestables. Al fijar la escala
# aquí, cualquier empresa nueva se mide contra la misma referencia.
#
# El score de empresa es una media ponderada de meses, así que revierte a la
# media por construcción: para bajar de 33 hay que estar en la cola mala TODOS
# los meses. Los umbrales reflejan esa escala, no la del score mensual.
#   >= 68  ~ decil superior       (10%)
#   52-68  ~ banda central alta   (52%)  <- la mediana (56,4) cae aquí
#   42-52  ~ banda central baja   (28%)
#   33-42  ~ cola mala            (9%)
#   < 33   ~ cola extrema         (1%)
# Definición de EVENTO para medir la antelación (evaluate_anticipation.py).
# Los umbrales son deliberadamente severos: con la primera versión más laxa el
# 62% de las empresas "tenía evento", y algo que le pasa a dos de cada tres no es
# un episodio de estrés, es el comportamiento normal de la muestra. Contra una
# tasa base del 62% ninguna métrica de precisión significa nada.
EVENTO_MESES = 3
EVENTO_IMPAGO_PCT = 70.0
EVENTO_IMPAGO_STOCK = 6.0
EVENTO_ASFIXIA_FLUJO = -0.25
EVENTO_ASFIXIA_BURN = 1.5
# Horizonte de anticipación: un aviso 18 meses antes no anticipó nada, coincidió.
HORIZONTE_ANTICIPACION = 12

UMBRALES_CLASIFICACION = [
    (68, "SALUDABLE"),
    (52, "ESTABLE"),
    (42, "EN RIESGO"),
    (33, "FRÁGIL"),
]

CANDIDATOS = {
    "invoice_date": ["issuance_date", "issue_date", "issued_date", "invoice_date", "created_at"],
    "payment_date": ["payment_date", "paid_date", "settled_date", "collection_date",
                     "paid_at", "settlement_date"],
    "direction": ["direction", "invoice_type", "flow", "movement", "kind",
                  "is_receivable", "is_sales", "role", "type", "category"],
    "document_kind": ["document_type", "doc_type", "invoice_kind"],
    "counterparty": ["counterparty_id", "client_id", "supplier_id", "partner_id",
                     "counterparty"],
    "balance_date": ["date", "balance_date", "snapshot_date", "as_of_date", "period"],
    "sector": ["sector", "industry", "cnae", "activity"],
    "group": ["group_id", "corporate_group_id", "parent_id", "group"],
    "debt_type": ["type", "product_type", "label"],
}

VALORES_RECEIVABLE = {
    "receivable", "receivables", "ar", "sale", "sales", "sold", "issued",
    "outgoing", "customer", "client", "venta", "ventas", "emitida", "cliente",
    "cobro", "true", "1",
    "sales_invoice", "sale_invoice", "customer_invoice", "ar_invoice",
}
VALORES_PAYABLE = {
    "payable", "payables", "ap", "purchase", "purchases", "bought", "received",
    "incoming", "supplier", "vendor", "compra", "compras", "recibida",
    "proveedor", "pago", "false", "0",
    "purchase_invoice", "supplier_invoice", "vendor_invoice", "ap_invoice",
    "bill",
}
# document_type que cuenta como actividad comercial facturada. purchaseOrder y
# deliveryNote son documentos PREVIOS a la factura (no hay derecho de cobro aún);
# cheque/other/deposit/note/paymentDocument no son la factura en sí y contarlos
# duplicaría volumen. Cambiar este set es la palanca para revisar la decisión.
TIPOS_DOC_COMERCIAL = {"invoice", "invoicegroup"}

# Una factura anulada no es ni volumen ni derecho de cobro.
ESTADOS_ANULADOS = {"cancel", "cancelled", "canceled", "anulada", "void"}

# pending_amount por debajo de esta tolerancia se considera cobro completo.
TOLERANCIA_COBRO = 0.01

# Retrasos por encima de esto son fechas corruptas (hay payment_date en el año
# 6913 y retrasos de -26.783 días), no comportamiento de pago.
MAX_DIAS_RETRASO = 365

VALORES_RECTIFICATIVA = {
    "credit_note", "creditnote", "credit note", "debit_note", "debitnote",
    "abono", "nota_credito", "nota de credito", "rectificativa", "correction",
    "adjustment", "ajuste", "refund", "devolucion", "devolución",
}
# Snapshot de caja (balances): solo lo que se puede usar para pagar mañana.
# Se excluyen card, tpv, investment y expensesPlatform.
TIPOS_CAJA = {"checking", "current", "saving", "deposit", "cash", "account",
              "corriente", "ahorro", "cuenta"}

# Flujos mensuales: tesorería operativa. wallet/tpv/expensesPlatform SÍ mueven
# cobros y pagos reales; card y cuentas de deuda no (contarlas duplicaría el
# cargo cuando llega el recibo a la cuenta corriente).
TIPOS_CAJA_FLUJO = TIPOS_CAJA | {"wallet", "tpv", "expensesplatform"}

# Categorías que no son actividad operativa. Sin este filtro, una transferencia
# entre cuentas propias o una disposición de préstamo inflan ingresos y gastos.
CAT_INTERNAL = {"transfer"}
CAT_INVESTMENT = {"investment_deployment", "investment_return"}
CAT_FINANCING = {"debt_repayment", "interest_charge"}
CAT_COBROS = {"collection", "bulk_collection", "pos_settlement",
              "cash_settlement", "cash_settlements"}
CAT_REFUND = {"collection_refund"}

# Centinelas observados en balances exploratorios.
VALORES_SENTINELA_BALANCE = {
    999999999999.0,
    -999999999999.0,
    999999999.0,
    -999999999.0,
}

PESO_CONFIANZA = {"alta": 1.0, "media": 0.65, "baja": 0.30}


def detectar(df, clave):
    for c in CANDIDATOS[clave]:
        if c in df.columns:
            return c
    return None


def clasificar(score):
    for umbral, etiqueta in UMBRALES_CLASIFICACION:
        if score >= umbral:
            return etiqueta
    return "CRÍTICO"


def asegurar_dirs():
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    MODEL_DIR.mkdir(parents=True, exist_ok=True)
