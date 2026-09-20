"""Sirve la interfaz del Health Score y las APIs de ficha.

    python -m src.brief_server
    http://127.0.0.1:8775/

La UI es frontend/ (también en dashboard/ para Vercel).
El motor, el RAG y el catálogo siguen en src/.
"""
from __future__ import annotations

import json
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import pandas as pd

import src.brief_cliente as brief
import src.config as cfg
from src.features.client_health_score.api import (
    frontend_asset,
    gemini_summary,
    health_score_payload,
    list_companies,
)

HOST = "127.0.0.1"
PORT = int(os.environ.get("BRIEF_PORT", "8775"))
_EXP = None
_FIN = None


def _cache():
    global _EXP, _FIN
    if _EXP is None:
        _EXP = json.loads(cfg.EXPLAIN_PATH.read_text(encoding="utf-8"))
        _FIN = pd.read_csv(cfg.SCORES_PATH).set_index("company_id")
    return _EXP, _FIN


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        print(f"  {self.address_string()} {fmt % args}")

    def _json(self, code, payload):
        raw = json.dumps(payload, ensure_ascii=False, default=str).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(raw)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(raw)

    def _file(self, path: Path, ctype):
        data = path.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path
        if path == "/api/health-score/companies":
            try:
                exp, _fin = _cache()
                self._json(200, list_companies(exp))
            except Exception as exc:
                self._json(500, {"error": str(exc)})
            return
        if path == "/api/health-score":
            company_id = str(parse_qs(parsed.query).get("company_id", ["COMP_0725"])[0])
            if not company_id.startswith("COMP_"):
                self._json(400, {"error": "company_id inválido"})
                return
            try:
                exp, fin = _cache()
                self._json(200, health_score_payload(company_id, exp, fin))
            except KeyError:
                self._json(404, {"error": f"sin ficha para {company_id}"})
            except Exception as exc:
                self._json(500, {"error": str(exc)})
            return
        asset = frontend_asset(path)
        if asset:
            self._file(*asset)
            return
        self.send_error(404)

    def do_POST(self):
        path = urlparse(self.path).path
        if path not in ("/api/brief", "/api/health-score/summary"):
            self.send_error(404)
            return
        n = int(self.headers.get("Content-Length") or 0)
        try:
            body = json.loads(self.rfile.read(n).decode("utf-8") or "{}")
        except json.JSONDecodeError:
            self._json(400, {"error": "JSON inválido"})
            return
        cid = str(body.get("company_id") or "")
        if not cid.startswith("COMP_"):
            self._json(400, {"error": "company_id inválido"})
            return
        key = body.get("api_key") or None
        if key:
            key = str(key).strip()
            if key.lower().startswith("bearer "):
                key = key[7:].strip()
            key = key or None
        if path == "/api/health-score/summary":
            try:
                exp, fin = _cache()
                out = gemini_summary(cid, exp=exp, fin=fin, api_key=key)
            except KeyError:
                self._json(404, {"error": f"sin ficha para {cid}"})
                return
            except ValueError as exc:
                self._json(400, {"error": str(exc)})
                return
            except RuntimeError as exc:
                self._json(502, {"error": str(exc)})
                return
            self._json(200, out)
            return
        try:
            exp, fin = _cache()
            out = brief.brief_api(
                cid,
                usar_llm=bool(body.get("llm", True)),
                exp=exp,
                fin=fin,
                api_key=key,
            )
        except KeyError:
            self._json(404, {"error": f"sin ficha para {cid}"})
            return
        except Exception as exc:
            self._json(500, {"error": str(exc)})
            return
        self._json(200, out)


def main():
    if not cfg.EXPLAIN_PATH.exists():
        raise SystemExit("Falta score_explanations.json.")
    if not cfg.SCORES_PATH.exists():
        raise SystemExit("Falta scores_finales.csv.")
    ui = frontend_asset("/")
    if not ui:
        raise SystemExit(
            "Falta la UI en frontend/. python -m src.build_dashboard"
        )
    httpd = None
    port = PORT
    for candidate in range(PORT, PORT + 10):
        try:
            httpd = ThreadingHTTPServer((HOST, candidate), Handler)
            port = candidate
            break
        except OSError:
            continue
    if httpd is None:
        raise SystemExit(f"Puertos {PORT}-{PORT+9} ocupados. Cierra el servidor viejo.")
    print(f"Interfaz: http://{HOST}:{port}/", flush=True)
    print("GET /api/health-score · POST /api/health-score/summary · POST /api/brief", flush=True)
    print("LLM: Gemini. La key se pega en la UI o va en GEMINI_API_KEY.", flush=True)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nCerrado.", flush=True)


if __name__ == "__main__":
    main()
