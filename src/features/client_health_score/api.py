"""Read-only API and static assets for the isolated client Health Score view."""
from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.request
from functools import lru_cache
from pathlib import Path
from typing import Any

import pandas as pd

import src.brief_cliente as brief
import src.config as cfg
from src.build_dashboard import _walkforward_fc

FRONTEND_DIR = Path(__file__).parent / "frontend"

_MIME_TYPES = {
    ".css": "text/css; charset=utf-8",
    ".html": "text/html; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
    ".json": "application/json; charset=utf-8",
    ".svg": "image/svg+xml",
    ".woff2": "font/woff2",
}

_AXES = (
    ("deuda_comercial", "Deuda comercial"),
    ("liquidez", "Liquidez"),
    ("colchon", "Colchón"),
    ("trayectoria", "Trayectoria"),
    ("eficiencia", "Eficiencia"),
    ("cobro_clientes", "Cobros"),
)

_FACT_SKIP = re.compile(r"percentil|cohorte|datos nuevos", re.I)
_FACT_PTS = re.compile(r"\s*\([+-]?\d+(?:\.\d+)?\s*pts\)")
_FACT_MONTHS = re.compile(r"\(([\d.,]+)\s*meses\)", re.I)
_FACT_MEDIA = re.compile(r"\s*\(media\s+\d+\s*d\)", re.I)
_MOD_PTS = re.compile(r"\(([+-]?\d+(?:\.\d+)?)\s*pts\)")

_GEMINI_SYSTEM = """Eres el asistente de inteligencia financiera de Embat.
Redactas para el CFO o responsable de tesorería de la empresa analizada.
Usa exclusivamente los datos del Health Score recibido: no recalcules, no
inventes importes, productos, clientes ni predicciones. El score no es una
valoración ni un rating de crédito.

Responde en español, con tono ejecutivo, directo y sereno. Evita jerga técnica,
alarmismo y frases como "subir el score". Devuelve únicamente JSON con:
- situation: lectura breve del nivel, tendencia y señal prioritaria.
- treasury: una recomendación concreta y accionable de tesorería.
- limits: una frase clara sobre los límites del indicador.
Máximo 55 palabras por campo."""


@lru_cache(maxsize=1)
def _score_history() -> pd.DataFrame:
    """Load only the two columns needed by this view, once per server process."""
    if not cfg.SCORES_MENSUAL_PATH.exists():
        return pd.DataFrame(columns=["company_id", "year_month", "score_suavizado"])
    cols = pd.read_csv(cfg.SCORES_MENSUAL_PATH, nrows=0).columns
    score_col = "score_suavizado" if "score_suavizado" in cols else "score_mensual"
    frame = pd.read_csv(
        cfg.SCORES_MENSUAL_PATH,
        usecols=["company_id", "year_month", score_col],
    )
    if score_col != "score_suavizado":
        frame = frame.rename(columns={score_col: "score_suavizado"})
    return frame


def _forecast_payload(points: list[dict]) -> dict | None:
    """Theil-Sen walk-forward to +3 months, with a p80 error band."""
    raw = _walkforward_fc(
        [item["period"] for item in points],
        [item["score"] for item in points],
    )
    if not raw:
        return None
    slope = raw["b"]
    if slope > 0.15:
        direction = "up"
    elif slope < -0.15:
        direction = "down"
    else:
        direction = "flat"
    return {
        "horizon": len(raw["y"]),
        "slope": slope,
        "direction": direction,
        "mae": raw["mae"],
        "p80": raw["p80"],
        "points": [
            {
                "period": raw["m"][index],
                "score": raw["y"][index],
                "low": raw["lo"][index],
                "high": raw["hi"][index],
            }
            for index in range(len(raw["y"]))
        ],
    }


def _number(value: Any, digits: int = 1) -> float | None:
    if value is None or pd.isna(value):
        return None
    return round(float(value), digits)


def _tone(score: float | None) -> str:
    if score is None:
        return "muted"
    if score >= 70:
        return "positive"
    if score >= 55:
        return "warning"
    return "critical"


def _cap(text: str) -> str:
    text = text.strip()
    if not text:
        return ""
    return text[0].upper() + text[1:] if text[0].islower() else text


def _client_fact(razon: str, limit: int = 140) -> str:
    """Keep the economic fact; drop calibration wording the client should not see."""
    parts = [piece.strip() for piece in str(razon or "").split(";") if piece.strip()]
    kept: list[str] = []
    for part in parts:
        months = _FACT_MONTHS.search(part)
        if _FACT_SKIP.search(part):
            if months:
                kept.append(f"caja real {months.group(1)} meses")
            continue
        cleaned = _FACT_MEDIA.sub("", _FACT_PTS.sub("", part)).strip(" ,")
        if cleaned:
            kept.append(cleaned)
        if len(kept) == 2:
            break
    text = _cap("; ".join(kept) if kept else (parts[0] if parts else ""))
    return text[:limit].rstrip(" ,;")


def list_companies(exp: dict) -> dict:
    """Compact roster for the client company switcher."""
    companies = []
    for company_id in sorted(exp):
        item = exp[company_id]
        score = _number(item.get("score_final"))
        companies.append(
            {
                "id": company_id,
                "score": score,
                "classification": item.get("clasificacion") or "NO EVALUABLE",
            }
        )
    return {"companies": companies}


def health_score_payload(company_id: str, exp: dict, fin: pd.DataFrame) -> dict:
    """Translate existing score artifacts into a compact client-facing contract."""
    profile = brief.ficha_cerrada(company_id, exp=exp, fin=fin)
    explanation = exp[company_id]
    factors = explanation.get("factores") or {}
    change = explanation.get("cambio_vs_mes_anterior") or {}
    aportes = change.get("aportes") or {}
    giro = explanation.get("giro") or {}

    metrics = []
    for key, label in _AXES:
        factor = factors.get(key) or {}
        score = _number(factor.get("score"))
        applicable = bool(factor.get("aplicable") and score is not None)
        weight = int(round(cfg.PESOS[key] * 100))
        metrics.append(
            {
                "id": key,
                "label": label,
                "weight": weight,
                "score": score if applicable else None,
                "contribution": _number(aportes.get(key)) if applicable else None,
                "applicable": applicable,
                "fact": _client_fact(str(factor.get("razon") or "")),
                "tone": _tone(score) if applicable else "muted",
            }
        )

    weighted = [
        (item["score"] or 0) * item["weight"]
        for item in metrics
        if item["applicable"]
    ]
    total = sum(weighted)
    share_i = 0
    for item in metrics:
        if item["applicable"] and total:
            item["share"] = round(100 * weighted[share_i] / total, 1)
            share_i += 1
        else:
            item["share"] = 0.0

    history = _score_history()
    rows = history.loc[history["company_id"].eq(company_id)].dropna(subset=["score_suavizado"])
    series = [
        {"period": str(row.year_month), "score": _number(row.score_suavizado)}
        for row in rows.itertuples()
        if _number(row.score_suavizado) is not None
    ]
    points = series[-8:]
    forecast = _forecast_payload(series)

    ranked = sorted(
        (item for item in metrics if item["applicable"] and item["score"] is not None),
        key=lambda item: item["score"],
    )
    priorities = [
        {"id": item["id"], "metric": item["label"], "score": item["score"]}
        for item in ranked[:2]
    ]

    drivers = sorted(
        (
            {
                "id": item["id"],
                "label": item["label"],
                "points": item["contribution"],
            }
            for item in metrics
            if item["contribution"] is not None and abs(item["contribution"]) >= 0.5
        ),
        key=lambda item: -abs(item["points"]),
    )[:3]

    mod = factors.get("_apalancamiento") or {}
    mod_razon = str(mod.get("razon") or "")
    mod_pts = _MOD_PTS.search(mod_razon)
    modulator = None
    if mod.get("aplicable") and mod_pts and abs(float(mod_pts.group(1))) >= 0.5:
        modulator = {
            "label": "Apalancamiento",
            "points": round(float(mod_pts.group(1)), 1),
            "fact": _client_fact(_FACT_PTS.sub("", mod_razon)),
        }

    return {
        "company_id": company_id,
        "period": str(explanation.get("year_month") or ""),
        "score": profile["score"],
        "classification": profile["clasificacion"],
        "trend": profile["tendencia"],
        "delta": profile["delta_ultimo_mes"],
        "confidence": profile["confianza"],
        "months_evaluated": profile["meses_evaluados"],
        "metrics": metrics,
        "history": points,
        "forecast": forecast,
        "priorities": priorities,
        "change": {
            "behavior": _number(change.get("por_comportamiento")),
            "coverage": _number(change.get("por_datos_nuevos")),
            "drivers": drivers,
        },
        "modulator": modulator,
        "signal": {
            "active": bool(giro.get("detectado")),
            "kind": str(giro.get("naturaleza") or ""),
            "drop": _number(giro.get("caida_puntos_3m")),
            "explanation": _client_fact(str(giro.get("por_que") or ""), 160),
        },
    }


def _dotenv_value(name: str) -> str:
    """Read one local, git-ignored setting without adding a dotenv dependency."""
    path = Path(".env")
    if not path.is_file():
        return ""
    for line in path.read_text(encoding="utf-8").splitlines():
        clean = line.strip()
        if not clean or clean.startswith("#") or "=" not in clean:
            continue
        key, value = clean.split("=", 1)
        if key.strip() == name:
            return value.strip().strip("\"'")
    return ""


def _gemini_key(provided: str | None = None) -> str:
    key = str(provided or "").strip()
    return key or os.environ.get("GEMINI_API_KEY", "").strip() or _dotenv_value("GEMINI_API_KEY")


def gemini_summary(
    company_id: str,
    exp: dict,
    fin: pd.DataFrame,
    api_key: str | None = None,
) -> dict:
    """Generate the executive summary through Gemini without exposing the key."""
    key = _gemini_key(api_key)
    if not key:
        raise ValueError("Falta GEMINI_API_KEY en el servidor.")

    context = health_score_payload(company_id, exp, fin)
    model = (
        os.environ.get("GEMINI_MODEL", "").strip()
        or _dotenv_value("GEMINI_MODEL")
        or "gemini-3.1-flash-lite"
    )
    url = (
        "https://generativelanguage.googleapis.com/v1beta/models/"
        f"{model}:generateContent"
    )
    body = {
        "system_instruction": {"parts": [{"text": _GEMINI_SYSTEM}]},
        "contents": [{
            "role": "user",
            "parts": [{
                "text": "Redacta el resumen ejecutivo de este Health Score:\n"
                + json.dumps(context, ensure_ascii=False),
            }],
        }],
        "generationConfig": {
            "temperature": 0.2,
            "responseMimeType": "application/json",
            "responseSchema": {
                "type": "OBJECT",
                "properties": {
                    "situation": {"type": "STRING"},
                    "treasury": {"type": "STRING"},
                    "limits": {"type": "STRING"},
                },
                "required": ["situation", "treasury", "limits"],
            },
        },
    }
    request = urllib.request.Request(
        url,
        data=json.dumps(body).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "x-goog-api-key": key,
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=45) as response:
            data = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        try:
            message = json.loads(detail)["error"]["message"]
        except (KeyError, TypeError, json.JSONDecodeError):
            message = detail[:220]
        if exc.code == 429:
            message = "Se ha agotado temporalmente la cuota de Gemini. Inténtalo más tarde."
        elif exc.code == 503:
            message = "Gemini está temporalmente saturado. Inténtalo de nuevo en unos segundos."
        raise RuntimeError(message) from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"Gemini no está disponible: {exc.reason}") from exc

    try:
        raw = data["candidates"][0]["content"]["parts"][0]["text"]
        parsed = json.loads(re.sub(r"^```(?:json)?\s*|\s*```$", "", raw.strip(), flags=re.I))
        result = {
            "situacion": str(parsed["situation"]).strip(),
            "tesoreria": str(parsed["treasury"]).strip(),
            "limites": str(parsed["limits"]).strip(),
            "fuente": "gemini",
            "modelo": model,
        }
    except (KeyError, IndexError, TypeError, json.JSONDecodeError) as exc:
        raise RuntimeError("Gemini devolvió una respuesta sin el formato esperado.") from exc
    return result


def frontend_asset(request_path: str) -> tuple[Path, str] | None:
    """Resolve a feature asset without allowing traversal outside its directory."""
    path = request_path.split("?", 1)[0]
    if path in ("/", "/index.html", "/dashboard", "/dashboard/", "/dashboard/index.html"):
        relative = "index.html"
    elif path.startswith("/client/health-score"):
        relative = path.removeprefix("/client/health-score").lstrip("/") or "index.html"
    elif path.startswith("/dashboard/"):
        relative = path.removeprefix("/dashboard/").lstrip("/") or "index.html"
    else:
        relative = path.lstrip("/")
    candidate = (FRONTEND_DIR / relative).resolve()
    try:
        candidate.relative_to(FRONTEND_DIR.resolve())
    except ValueError:
        return None
    if not candidate.is_file():
        return None
    return candidate, _MIME_TYPES.get(candidate.suffix.lower(), "application/octet-stream")
