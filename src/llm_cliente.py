"""Llamada a Gemini. Solo redacta; no toca el score.

Key en la UI o GEMINI_API_KEY. SDK: google-genai (interactions.create).
El prefijo no importa (AIza…, AQ.…, etc.).
"""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.parse
import urllib.request

GEMINI_MODEL = "gemini-3-flash-preview"
GEMINI_FALLBACK = ("gemini-2.5-flash", "gemini-2.0-flash")
GEMINI_REST = (
    "https://generativelanguage.googleapis.com/v1beta/models/"
    "gemini-2.0-flash:generateContent"
)


def clave_env():
    return (
        os.environ.get("GEMINI_API_KEY")
        or os.environ.get("GOOGLE_API_KEY")
        or os.environ.get("LLM_API_KEY")
    )


def hay_clave(key=None):
    return bool((key or "").strip() or clave_env())


def _gemini_texto(interaction):
    text = getattr(interaction, "output_text", None)
    if text:
        return str(text)
    steps = getattr(interaction, "steps", None) or []
    if steps:
        last = steps[-1]
        return str(getattr(last, "text", None) or getattr(last, "output_text", None) or last)
    raise RuntimeError("Gemini no devolvió texto.")


def _gemini_sdk(key, sistema, user, model):
    from google import genai
    client = genai.Client(api_key=key)
    interaction = client.interactions.create(
        model=model,
        system_instruction=sistema or None,
        input=user,
        generation_config={"temperature": 0.2, "max_output_tokens": 2048},
    )
    return _gemini_texto(interaction)


def _gemini_rest(key, sistema, user):
    body = {
        "systemInstruction": {"parts": [{"text": sistema}]},
        "contents": [{"role": "user", "parts": [{"text": user}]}],
        "generationConfig": {"temperature": 0.2},
    }
    url = GEMINI_REST + "?key=" + urllib.parse.quote(key)
    req = urllib.request.Request(
        url,
        data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=45) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    parts = data["candidates"][0]["content"]["parts"]
    return "".join(p.get("text") or "" for p in parts)


def completar(messages, key=None, url=None, model=None):
    """Devuelve el texto de Gemini. url se ignora (queda por compatibilidad)."""
    key = (key or clave_env() or "").strip()
    if not key:
        raise RuntimeError("Falta la API key de Gemini.")
    sistema = " ".join(m["content"] for m in messages if m["role"] == "system")
    user = "\n\n".join(m["content"] for m in messages if m["role"] != "system")
    model = model or os.environ.get("LLM_MODEL")
    modelos = [m for m in ([model] if model else [GEMINI_MODEL, *GEMINI_FALLBACK]) if m]
    last_err = None
    try:
        from google import genai  # noqa: F401
    except ImportError:
        last_err = ImportError("Falta google-genai. pip install -r requirements.txt")
    else:
        for m in modelos:
            try:
                return _gemini_sdk(key, sistema, user, m)
            except Exception as exc:
                last_err = exc
    try:
        return _gemini_rest(key, sistema, user)
    except urllib.error.HTTPError as exc:
        err = exc.read().decode("utf-8", errors="replace")[:240]
        raise RuntimeError(f"HTTP {exc.code} (gemini): {err}") from exc
    except Exception as exc:
        raise RuntimeError(f"Gemini falló ({last_err}); REST: {exc}") from exc
