
"""
Punto único de verdad para ventana temporal, umbrales y detección de esquema.
Ningún script escribe sobre los CSV RAW.
"""

from pathlib import Path
import pandas as pd

DATA_DIR = Path("data")
OUT_DIR = DATA_DIR / "features"
PANEL_PATH = OUT_DIR / "master_panel.csv"
AUDIT_PATH = OUT_DIR / "feature_audit.json"
QUALITY_PATH = OUT_DIR / "data_quality_report.txt"
SCORES_PATH = OUT_DIR / "scores_finales.csv"
SCORES_MENSUAL_PATH = OUT_DIR / "scores_mensuales.csv"
EXPLAIN_PATH = OUT_DIR / "score_explanations.json"

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

# Solo se conserva como referencia diagnóstica; el score usa burn_rate sin
# recortarlo artificialmente.
BURN_RATE_CAP = 5.0

DIAS_MADURACION = 45
HALF_LIFE_MONTHS = 6.0

# Evidencia mínima para emitir un score mensual.
MIN_PESO_CUBIERTO_SCORE = 0.55

PESOS = {
    "liquidez": 0.22,
    "runway": 0.18,
    "eficiencia": 0.12,
    "morosidad_prov": 0.18,
    "morosidad_clientes": 0.12,
    "tendencia": 0.13,
    "apalancamiento": 0.05,
}

UMBRALES_CLASIFICACION = [
    (80, "SALUDABLE"),
    (60, "ESTABLE"),
    (40, "EN RIESGO"),
    (20, "FRÁGIL"),
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
}
VALORES_PAYABLE = {
    "payable", "payables", "ap", "purchase", "purchases", "bought", "received",
    "incoming", "supplier", "vendor", "compra", "compras", "recibida",
    "proveedor", "pago", "false", "0",
}
VALORES_RECTIFICATIVA = {
    "credit_note", "creditnote", "credit note", "debit_note", "debitnote",
    "abono", "nota_credito", "nota de credito", "rectificativa", "correction",
    "adjustment", "ajuste", "refund", "devolucion", "devolución",
}
TIPOS_CAJA = {"checking", "current", "savings", "deposit", "cash", "account",
              "corriente", "ahorro", "cuenta"}

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
