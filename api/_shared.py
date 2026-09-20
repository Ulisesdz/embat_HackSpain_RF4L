"""Carga común para las funciones de Vercel. El motor sigue en src/."""
from __future__ import annotations

import json
import sys
from functools import lru_cache
from http.server import BaseHTTPRequestHandler
from pathlib import Path
from urllib.parse import parse_qs, urlparse

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import pandas as pd

import src.config as cfg
from src.features.client_health_score.api import (
    gemini_summary,
    health_score_payload,
    list_companies,
)


@lru_cache(maxsize=1)
def artifacts():
    exp = json.loads(cfg.EXPLAIN_PATH.read_text(encoding="utf-8"))
    fin = pd.read_csv(cfg.SCORES_PATH).set_index("company_id")
    return exp, fin


class JsonHandler(BaseHTTPRequestHandler):
    def log_message(self, *_args):
        return

    def _json(self, code: int, payload: dict):
        raw = json.dumps(payload, ensure_ascii=False, default=str).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(raw)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(raw)

    def _read_json(self) -> dict:
        n = int(self.headers.get("Content-Length") or 0)
        if n <= 0:
            return {}
        return json.loads(self.rfile.read(n).decode("utf-8") or "{}")

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()


def company_id_from(handler: BaseHTTPRequestHandler, body: dict | None = None) -> str:
    if body and body.get("company_id"):
        return str(body["company_id"])
    query = parse_qs(urlparse(handler.path).query)
    return str((query.get("company_id") or [""])[0])
