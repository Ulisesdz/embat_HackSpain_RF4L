"""Traductor de la ficha. Lo lanza la UI, no la terminal.

Una sola lectura del score, tres apartados. El LLM no recalcula.
"""
from __future__ import annotations

import json
import re

import pandas as pd

import src.config as cfg

EJES = (
    ("deuda_comercial", "pagos a proveedores"),
    ("liquidez", "flujo de caja del trimestre"),
    ("colchon", "colchón frente a un mes malo"),
    ("trayectoria", "dirección de los últimos meses"),
    ("eficiencia", "cuánto gastáis por cada euro que entra"),
    ("cobro_clientes", "si os pagan a vosotros"),
)

ACCION = {
    "deuda_comercial": (
        "Revisad la cola de pagos a proveedores: dejar de pagar es una "
        "decisión vuestra, casi siempre porque no hay caja."
    ),
    "liquidez": (
        "El flujo operativo del trimestre no aguanta el tamaño. Adelantar "
        "cobros o recortar salidas que no sean de la actividad."
    ),
    "colchon": (
        "El colchón es fino o muy volátil. Priorizad tener un mes de gasto "
        "en cuenta corriente antes de nueva deuda."
    ),
    "trayectoria": (
        "El problema es la dirección, no un mes suelto. Un ingreso puntual "
        "no cambia la pendiente."
    ),
    "eficiencia": (
        "Entráis menos de lo que sale. El burn ya está topado: un mes loco "
        "no explica una quema sostenida."
    ),
    "cobro_clientes": (
        "Os pagan tarde o poco. Cobrar no se arregla pagando vosotros antes."
    ),
}

SISTEMA_LLM = """Eres el traductor de un score de tesorería para el dueño de una pyme.
NO recalculas. NO inventas ejes, meses ni puntos. NO eres un comité de agentes.

Usa SOLO el JSON de la ficha. Responde ÚNICAMENTE un JSON con tres claves de texto:
{
  "situacion": "qué está pasando: nivel, dirección, giro (bache vs caída). Vosotros.",
  "tesoreria": "qué mirar en caja/cobro/pago. Movimientos económicos, NUNCA 'subid el score'.",
  "limites": "qué no afirmamos: confianza, no es inversión, no maquillar el número."
}
Si un campo de la ficha es null, no lo menciones. No llames EBITDA a la caja.
Si naturaleza es bache, di que en la cartera suele rebotar. Si es caida_estructural, que suele sostenerse.
Máximo 70 palabras por clave. Castellano, vosotros. Sin markdown.
"""


def _num(v, nd=2):
    if v is None:
        return None
    try:
        if pd.isna(v):
            return None
    except (TypeError, ValueError):
        pass
    if hasattr(v, "item"):
        v = v.item()
    if isinstance(v, bool):
        return v
    if isinstance(v, int):
        return int(v)
    if isinstance(v, float):
        return round(float(v), nd)
    return v


def ficha_cerrada(company_id, exp=None, fin=None):
    if exp is None:
        exp = json.loads(cfg.EXPLAIN_PATH.read_text(encoding="utf-8"))
    if fin is None:
        fin = pd.read_csv(cfg.SCORES_PATH).set_index("company_id")
    cid = str(company_id)
    if cid not in exp:
        raise KeyError(f"Sin explicación para {cid}")
    e = exp[cid]
    row = fin.loc[cid] if cid in fin.index else None
    factores = []
    for clave, etiqueta in EJES:
        f = (e.get("factores") or {}).get(clave) or {}
        if not f.get("aplicable") or f.get("score") is None:
            continue
        factores.append({
            "eje": clave,
            "etiqueta": etiqueta,
            "score": _num(f.get("score")),
            "razon": (f.get("razon") or "")[:220],
        })
    factores.sort(key=lambda x: (x["score"] is None, x["score"] if x["score"] is not None else 99))
    giro = e.get("giro") or {}
    cambio = e.get("cambio_vs_mes_anterior") or {}
    return {
        "company_id": cid,
        "group_id": (None if row is None or pd.isna(row.get("group_id"))
                     else str(row.get("group_id"))),
        "score": _num(e.get("score_final")),
        "clasificacion": e.get("clasificacion"),
        "tendencia": e.get("tendencia"),
        "confianza": e.get("confianza"),
        "meses_evaluados": (None if row is None else _num(row.get("meses_evaluados"))),
        "motivo_cambio": cambio.get("explicacion") or "",
        "delta_ultimo_mes": _num(cambio.get("delta_score")),
        "giro": bool(giro.get("detectado")),
        "naturaleza": giro.get("naturaleza") or "",
        "giro_por_que": giro.get("por_que") or "",
        "ejes_debiles": [x for x in factores if x["score"] is not None and x["score"] < 55][:3],
        "ejes_fuertes": [x for x in factores if x["score"] is not None and x["score"] >= 70][:2],
        "alertas": list(e.get("alertas") or [])[:4],
    }


def bloques_vacios():
    return {"situacion": "", "tesoreria": "", "limites": "", "workspace": ""}


def render_plantilla(f):
    out = bloques_vacios()
    if f["score"] is None or f["clasificacion"] == "NO EVALUABLE":
        out["situacion"] = (
            "No hay evidencia suficiente para afirmar una salud financiera. "
            "Faltan meses o los ejes están apagados. No es que estéis bien: no se puede puntuar."
        )
        out["limites"] = "Sin ficha no hay plan ni oferta de inversión."
        out["workspace"] = "Perfil no publicable: sin score."
        return out

    sit = [f"Estáis en {f['clasificacion']} ({f['score']:.0f}/100), tendencia {f['tendencia']}."]
    if f["confianza"] == "baja":
        sit.append("Confianza baja: pocos meses o facturas huecas.")
    if f["giro"] and f["naturaleza"] == "caida_estructural":
        sit.append(
            "Hay un giro que se parece a una caída que se sostiene "
            "(a 6 meses suele seguir bajando). " + (f["giro_por_que"] or "")
        )
    elif f["giro"] and f["naturaleza"] == "bache":
        sit.append(
            "Hay un giro que se parece a un bache "
            "(más de la mitad recupera a 6 meses). " + (f["giro_por_que"] or "")
        )
    if f["motivo_cambio"]:
        d = f["delta_ultimo_mes"]
        pref = f"Último mes ({d:+.1f} pts): " if d is not None else "Último mes: "
        sit.append(pref + f["motivo_cambio"] + ".")
    out["situacion"] = " ".join(p.strip() for p in sit if p.strip())

    tes = []
    if f["ejes_debiles"]:
        tes.append("Hoy tira hacia abajo: " +
                   ", ".join(x["etiqueta"] for x in f["ejes_debiles"]) + ".")
        for x in f["ejes_debiles"]:
            if x.get("razon"):
                tes.append(x["razon"].rstrip(".") + ".")
            if x["eje"] in ACCION:
                tes.append(ACCION[x["eje"]])
    elif f["ejes_fuertes"]:
        tes.append("Lo que aguanta: " +
                   ", ".join(x["etiqueta"] for x in f["ejes_fuertes"]) + ".")
    else:
        tes.append("No hay un eje flojo claro este mes.")
    out["tesoreria"] = " ".join(tes)

    out["limites"] = (
        "Esto no es valoración ni promesa de inversión. "
        "No maquilléis el número: el score lee caja y facturas. "
        f"Confianza {f['confianza']}."
    )

    razones = []
    for x in (f["ejes_debiles"] or [])[:2]:
        if x.get("razon"):
            razones.append(x["razon"])
    giro = ""
    if f["giro"]:
        giro = "bache" if f["naturaleza"] == "bache" else "caída que se sostiene"
    out["workspace"] = (
        f"{f['clasificacion']} · {f['score']:.0f}/100 · {f['tendencia']}"
        + (f" · giro: {giro}" if giro else "")
        + (". " + " ".join(razones) if razones else ".")
        + " Sin extracto ni nombres de clientes."
    )
    return out


def _parse_bloques(raw):
    if isinstance(raw, dict):
        data = raw
    else:
        text = str(raw).strip()
        text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text, flags=re.I)
        data = json.loads(text)
    out = bloques_vacios()
    for k in ("situacion", "tesoreria", "limites"):
        out[k] = str(data.get(k) or "").strip()
    if not out["situacion"]:
        raise ValueError("JSON sin 'situacion'")
    return out


def render_llm(f, key=None, url=None, model=None):
    import src.llm_cliente as llm
    raw = llm.completar(
        [
            {"role": "system", "content": SISTEMA_LLM},
            {"role": "user", "content": json.dumps(f, ensure_ascii=False)},
        ],
        key=key, url=url, model=model,
    )
    bloques = _parse_bloques(raw)
    bloques["workspace"] = render_plantilla(f)["workspace"]
    return bloques


def hay_clave_llm(key=None):
    import src.llm_cliente as llm
    return llm.hay_clave(key)


def brief_api(company_id, usar_llm=True, exp=None, fin=None, api_key=None):
    """La UI llama aquí. El valor está en las herramientas, no en el párrafo."""
    import src.agente_pyme as agente
    return agente.plan(company_id, usar_llm=usar_llm, exp=exp, fin=fin, api_key=api_key)
