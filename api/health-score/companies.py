import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from api._shared import JsonHandler, artifacts, list_companies


class handler(JsonHandler):
    def do_GET(self):
        try:
            exp, _fin = artifacts()
            self._json(200, list_companies(exp))
        except Exception as exc:
            self._json(500, {"error": str(exc)})
