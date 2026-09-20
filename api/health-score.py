import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from api._shared import JsonHandler, artifacts, company_id_from, health_score_payload


class handler(JsonHandler):
    def do_GET(self):
        cid = company_id_from(self)
        if not cid.startswith("COMP_"):
            self._json(400, {"error": "company_id inválido"})
            return
        try:
            exp, fin = artifacts()
            self._json(200, health_score_payload(cid, exp, fin))
        except KeyError:
            self._json(404, {"error": f"sin ficha para {cid}"})
        except Exception as exc:
            self._json(500, {"error": str(exc)})
