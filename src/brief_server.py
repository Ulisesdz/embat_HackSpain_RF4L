"""Sirve la interfaz. POST /api/brief usa la clave que pega el usuario en la UI.

    python -m src.brief_server
    http://127.0.0.1:8765/
"""
from __future__ import annotations

import json
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

import pandas as pd

import src.brief_cliente as brief
import src.config as cfg

HOST = "127.0.0.1"
PORT = int(os.environ.get("BRIEF_PORT", "8765"))
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
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        path = urlparse(self.path).path
        if path in ("/", "/index.html", "/dashboard/", "/dashboard/index.html"):
            self._file(cfg.DASHBOARD_PATH, "text/html; charset=utf-8")
            return
        self.send_error(404)

    def do_POST(self):
        if urlparse(self.path).path != "/api/brief":
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
    if not cfg.DASHBOARD_PATH.exists():
        raise SystemExit("Falta dashboard/index.html. python -m src.build_dashboard")
    if not cfg.EXPLAIN_PATH.exists():
        raise SystemExit("Falta score_explanations.json.")
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
    print("POST /api/brief · ficha + RAG + catálogo. La key es opcional.", flush=True)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nCerrado.", flush=True)


if __name__ == "__main__":
    main()
