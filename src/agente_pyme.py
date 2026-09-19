"""Agente de la pyme: herramientas, no un LLM suelto.

Herramientas:
  leer_ficha      JSON cerrado (ya calculado)
  buscar_teoria   RAG sobre docs/TEORIA_PYME.md
  proponer_acciones  catálogo empresa / Embat / partner
  estimar_impacto    eje hoy → qué movería; cero puntos prometidos

El LLM, si hay clave, solo redacta con lo que devolvieron las herramientas.
No puede inventar un id de acción ni un delta de score.
"""
from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.request
from pathlib import Path

import src.brief_cliente as brief
import src.playbook_acciones as playbook

TEORIA_PATH = Path("docs") / "TEORIA_PYME.md"

SISTEMA = """Eres un agente de Embat. Te está preguntando el dueño de una pyme
(vosotros), no un fondo ni un analista.

## Health score
Es la métrica de salud de tesorería de Embat. No es valoración, no predice
quiebra y no es un rating de crédito. Se calcula con reglas, no con un modelo
opaco: media ponderada de 6 ejes (deuda comercial 20%, liquidez 18%, colchón
18%, trayectoria 18%, eficiencia 14%, cobro a clientes 12%), suavizada unos
25 meses y contraída hacia el comportamiento típico si hay poca evidencia.
Si falta la fuente, el eje se apaga: nunca se inventa un 50. El nivel
(SALUDABLE / ESTABLE / EN RIESGO / FRÁGIL / CRÍTICO) no cancela la dirección
(MEJORANDO / ESTABLE / DETERIORANDO). Un giro es que se tuerce contra su
propia historia (bache vs caída estructural). TÚ NO RECALCULAS. El número
de este caso ya viene en la ficha.

## Herramientas (ya se han ejecutado; no pidas más)
- leer_ficha: JSON cerrado del motor (score, ejes, giro, confianza).
- buscar_teoria: fragmentos de docs/TEORIA_PYME.md que encajan con esta ficha.
- proponer_acciones: tipos del catálogo (empresa / Embat / partner). No hay marketplace.
- estimar_impacto: eje de hoy y qué comportamiento lo movería. Cero puntos prometidos.

## Acciones que puedes tomar
Solo ids del catálogo que te pasan. No inventes un préstamo, un producto ni
un delta de score. Si la acción es de un partner, Embat presenta y el partner
decide. Una línea de partner solo encaja si naturaleza es bache. En
caída estructural no se tapa con más deuda.

## Cómo se lo cuentas
Analiza la ficha con las herramientas y las acciones. Explícaselo al dueño
para que se entienda: concreto, sin jerga de rating, sin "subid el score".

## Secciones del frontend
El dashboard pinta tu respuesta en estos bloques. Responde SOLO un JSON
con estas claves, ni una más:
{
  "situacion": "bloque 'Qué está pasando': nivel, dirección, giro y porqué de los ejes flojos. Usa el número de este caso; no lo redondees a otro.",
  "tesoreria": "bloque 'Qué mirar en tesorería': caja, cobro, pago, pendiente. Movimientos económicos.",
  "limites": "bloque 'Qué no afirmamos': confianza, no es inversión, no maquillar un mes.",
  "acciones": [
    {"id": "id_del_catalogo", "para_la_pyme": "cómo se lo cuentas a ellos, 1-2 frases"}
  ]
}

Reglas:
- acciones[].id SOLO de los que te pasaron. Si no encaja, lista vacía.
- No prometas puntos ni un score futuro. Di qué eje se movería y que hace falta meses.
- Si un campo de la ficha es null, no lo menciones.
- No llames EBITDA a la caja.
- Castellano, vosotros. Máximo 90 palabras por situacion / tesoreria / limites; 40 en para_la_pyme.
- Sin markdown.
"""


def _fmt_score(f):
    s = f.get("score")
    if s is None:
        return "sin score (NO EVALUABLE)"
    return f"{s:.0f}/100"


def prompt_usuario(f, pack):
    """Mensaje de este caso: score, herramientas ya corridas, acciones del catálogo."""
    deb = f.get("ejes_debiles") or []
    deb_txt = "; ".join(
        f"{x.get('etiqueta')} {x.get('score'):.0f}"
        + (f" ({x.get('razon')})" if x.get("razon") else "")
        for x in deb
    ) or "ninguno por debajo de 55"
    giro = "no"
    if f.get("giro"):
        giro = f.get("naturaleza") or "sí"
        if f.get("giro_por_que"):
            giro += f" — {f['giro_por_que']}"
    acciones = [
        {
            "id": a["id"],
            "titulo": a["titulo"],
            "quien": a["quien"],
            "ejes": a.get("ejes_objetivo") or a.get("ejes"),
            "hace": a["hace"],
        }
        for a in pack.get("acciones") or []
    ]
    return (
        f"## Este caso\n"
        f"Empresa {f.get('company_id')}. Health score {_fmt_score(f)}, "
        f"clasificación {f.get('clasificacion')}, tendencia {f.get('tendencia')}, "
        f"confianza {f.get('confianza')}. "
        f"Meses evaluados: {f.get('meses_evaluados')}. "
        f"Giro: {giro}. "
        f"Ejes que tiran hacia abajo: {deb_txt}.\n"
        f"Analiza la situación con las herramientas y las acciones de abajo. "
        f"Cuéntaselo a la pyme para que se entienda en los bloques del frontend "
        f"(Qué está pasando / Qué mirar en tesorería / Qué no afirmamos / Acciones).\n\n"
        f"## Ficha (leer_ficha)\n"
        f"{json.dumps(f, ensure_ascii=False)}\n\n"
        f"## Teoría citada (buscar_teoria)\n"
        f"{json.dumps(pack.get('teoria') or [], ensure_ascii=False)}\n\n"
        f"## Acciones que puedes tomar (proponer_acciones)\n"
        f"{json.dumps(acciones, ensure_ascii=False)}\n\n"
        f"## Impacto estimado (estimar_impacto)\n"
        f"{json.dumps(pack.get('impacto') or [], ensure_ascii=False)}\n"
    )


def _tok(s):
    return set(re.findall(r"[a-záéíóúñü0-9_]{3,}", (s or "").lower()))


def _chunks():
    if not TEORIA_PATH.exists():
        return []
    raw = TEORIA_PATH.read_text(encoding="utf-8")
    parts = re.split(r"\n## ", raw)
    out = []
    for p in parts:
        p = p.strip()
        if not p or p.startswith("# "):
            continue
        lines = p.splitlines()
        titulo = lines[0].strip()
        tags = ""
        cuerpo = []
        for line in lines[1:]:
            if line.lower().startswith("tags:"):
                tags = line.split(":", 1)[1]
                continue
            cuerpo.append(line)
        texto = " ".join(x.strip() for x in cuerpo if x.strip())
        out.append({"id": titulo, "tags": tags, "texto": texto[:700]})
    return out


_CHUNKS = None


def buscar_teoria(query, k=3):
    global _CHUNKS
    if _CHUNKS is None:
        _CHUNKS = _chunks()
    q = _tok(query)
    scored = []
    for ch in _CHUNKS:
        bag = _tok(ch["id"] + " " + ch["tags"] + " " + ch["texto"])
        n = len(q & bag)
        if n:
            scored.append((n, ch))
    scored.sort(key=lambda x: -x[0])
    return [c for _, c in scored[:k]]


def query_ficha(f):
    bits = [f.get("clasificacion") or "", f.get("tendencia") or "",
            f.get("naturaleza") or "", f.get("confianza") or ""]
    bits += [x.get("eje") or "" for x in (f.get("ejes_debiles") or [])]
    bits += [x.get("etiqueta") or "" for x in (f.get("ejes_debiles") or [])]
    if f.get("giro"):
        bits.append("giro")
    return " ".join(bits)


def herramientas(f):
    teoria = buscar_teoria(query_ficha(f))
    acciones = playbook.proponer(f)
    return {
        "teoria": teoria,
        "acciones": acciones,
        "impacto": playbook.impacto(f, acciones),
        "herramientas": [
            "leer_ficha",
            "buscar_teoria:" + ",".join(t["id"] for t in teoria),
            f"proponer_acciones:{len(acciones)}",
            "estimar_impacto",
        ],
    }


def _aplicar_acciones_llm(parsed, pack):
    allowed = {a["id"]: a for a in pack.get("acciones") or []}
    rows = parsed.get("acciones")
    if not isinstance(rows, list) or not rows:
        rows = [{"id": i} for i in (parsed.get("acciones_ids") or [])]
    keep = []
    for row in rows:
        if isinstance(row, str):
            row = {"id": row}
        if not isinstance(row, dict):
            continue
        aid = row.get("id")
        if aid not in allowed:
            continue
        item = dict(allowed[aid])
        txt = str(row.get("para_la_pyme") or "").strip()
        if txt:
            item["hace"] = txt
        keep.append(item)
    if keep:
        ids = {a["id"] for a in keep}
        pack["acciones"] = keep
        pack["impacto"] = [i for i in pack["impacto"] if i["id"] in ids]


def _llm_redacta(f, pack, key, url=None, model=None):
    url = url or os.environ.get("LLM_URL", "https://api.openai.com/v1/chat/completions")
    model = model or os.environ.get("LLM_MODEL", "gpt-4o-mini")
    body = {
        "model": model,
        "temperature": 0.2,
        "messages": [
            {"role": "system", "content": SISTEMA},
            {"role": "user", "content": prompt_usuario(f, pack)},
        ],
    }
    req = urllib.request.Request(
        url,
        data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json",
                 "Authorization": f"Bearer {key}"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=45) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        err = exc.read().decode("utf-8", errors="replace")[:240]
        raise RuntimeError(f"HTTP {exc.code}: {err}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"LLM no disponible: {exc}") from exc
    raw = data["choices"][0]["message"]["content"]
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", str(raw).strip(), flags=re.I)
    parsed = json.loads(text)
    bloques = brief._parse_bloques(parsed)
    _aplicar_acciones_llm(parsed, pack)
    return bloques


def plan(company_id, usar_llm=True, exp=None, fin=None, api_key=None):
    f = brief.ficha_cerrada(company_id, exp=exp, fin=fin)
    pack = herramientas(f)
    base = brief.render_plantilla(f)
    aviso = ""
    fuente = "plantilla+herramientas"
    if usar_llm and brief.hay_clave_llm(api_key):
        try:
            bloques = _llm_redacta(f, pack, key=api_key)
            base.update(bloques)
            fuente = "agente"
        except (RuntimeError, ValueError, json.JSONDecodeError, KeyError) as exc:
            aviso = f"El LLM falló ({exc}). Quedan plantilla + herramientas."
    elif usar_llm:
        aviso = "Sin API key: plantilla + herramientas locales (RAG y catálogo)."
    return {
        **base,
        "acciones": pack["acciones"],
        "teoria": pack["teoria"],
        "impacto": pack["impacto"],
        "herramientas": pack["herramientas"],
        "fuente": fuente,
        "aviso": aviso,
    }
