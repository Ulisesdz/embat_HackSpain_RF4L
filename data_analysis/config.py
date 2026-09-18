"""Configuración central del pipeline EMBAT / HackSpain 2026.

Punto único de verdad para ventana temporal, umbrales y detección de esquema.
Ningún script escribe sobre los CSV RAW.
"""

from pathlib import Path
import pandas as pd

# =============================================================================
# RUTAS
# =============================================================================

DATA_DIR = Path("data")
OUT_DIR = DATA_DIR / "features"
PANEL_PATH = OUT_DIR / "master_panel.csv"
AUDIT_PATH = OUT_DIR / "feature_audit.json"
QUALITY_PATH = OUT_DIR / "data_quality_report.txt"
SCORES_PATH = OUT_DIR / "scores_finales.csv"
SCORES_MENSUAL_PATH = OUT_DIR / "scores_mensuales.csv"
EXPLAIN_PATH = OUT_DIR / "score_explanations.json"

# =============================================================================
# VENTANA TEMPORAL
# =============================================================================
# Se respeta literalmente la ventana declarada por el reto: 25 buckets
# inclusivos (2024-09 .. 2026-09). No se recorta el calendario.
# 2026-09 se marca como mes parcial y queda EXCLUIDO del score por defecto:
# la extracción es de mediados de septiembre y sus flujos están truncados.

START_DATE = pd.Timestamp("2024-09-01")
END_DATE = pd.Timestamp("2026-09-30")
EXTRACTION_DATE = pd.Timestamp("2026-09-18")

MONTH_START = START_DATE.to_period("M")
MONTH_END = END_DATE.to_period("M")
MONTHS = pd.period_range(MONTH_START, MONTH_END, freq="M")

PARTIAL_MONTHS = [EXTRACTION_DATE.to_period("M")]
EXCLUIR_MES_PARCIAL_DEL_SCORE = True

# =============================================================================
# PARÁMETROS DE NEGOCIO
# =============================================================================

ROLL_SHORT = 3
ROLL_LONG = 6
MIN_FACTURAS_RATIO = 2       # por debajo, el ratio mide una factura, no una tendencia
MIN_MESES_HISTORIA = 12
BURN_RATE_CAP = 5.0
DIAS_MADURACION = 45         # morosidad censurada por debajo de este colchón
HALF_LIFE_MONTHS = 6.0       # decaimiento de la agregación temporal del score

# =============================================================================
# PESOS DEL SCORE (suman 1.0)
# =============================================================================

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
    (80, "SALUDABLE"), (60, "ESTABLE"), (40, "EN RIESGO"), (20, "FRÁGIL"),
]

# =============================================================================
# DETECCIÓN DE ESQUEMA
# =============================================================================

CANDIDATOS = {
    "invoice_date": ["issue_date", "issued_date", "invoice_date", "created_at"],
    "payment_date": ["payment_date", "paid_date", "settled_date", "collection_date",
                     "paid_at", "settlement_date"],
    "direction": ["direction", "invoice_type", "flow", "movement", "kind",
                  "is_receivable", "is_sales", "role", "type", "category"],
    "counterparty": ["counterparty_id", "client_id", "supplier_id", "partner_id",
                     "counterparty"],
    "balance_date": ["date", "balance_date", "snapshot_date", "as_of_date", "period"],
    "sector": ["sector", "industry", "cnae", "activity"],
    "group": ["group_id", "corporate_group_id", "parent_id", "group"],
}

# Coincidencia EXACTA sobre el valor normalizado. No se usa substring:
# "in"/"out" harían match dentro de "invoice" o "pending" y romperían todo.
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

TIPOS_CAJA = {"checking", "current", "savings", "deposit", "cash", "account",
              "corriente", "ahorro", "cuenta"}


def detectar(df, clave):
    """Primer nombre de columna presente para una clave semántica, o None."""
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