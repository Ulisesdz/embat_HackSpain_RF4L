import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from api._shared import JsonHandler, artifacts, company_id_from, gemini_summary


class handler(JsonHandler):
    def do_POST(self):
        try:
            body = self._read_json()
        except Exception:
            self._json(400, {"error": "JSON inválido"})
            return
        cid = company_id_from(self, body)
        if not cid.startswith("COMP_"):
            self._json(400, {"error": "company_id inválido"})
            return
        key = body.get("api_key") or None
        if key:
            key = str(key).strip() or None
        try:
            exp, fin = artifacts()
            self._json(200, gemini_summary(cid, exp, fin, api_key=key))
        except KeyError:
            self._json(404, {"error": f"sin ficha para {cid}"})
        except ValueError as exc:
            self._json(400, {"error": str(exc)})
        except Exception as exc:
            self._json(502, {"error": str(exc)})
