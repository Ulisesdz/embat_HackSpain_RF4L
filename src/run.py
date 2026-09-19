"""Ejecuta el pipeline completo en orden, desde la raíz del repo.

    python -m src.run
"""

import runpy
import sys


PASOS = [
    "src.build_features",
    "src.validate_features",
    "src.score_engine",
    "src.evaluate_anticipation",
    "src.monitor",
    "src.build_dashboard",
]


def main():
    for paso in PASOS:
        print(f"\n######## {paso} ########\n")
        try:
            runpy.run_module(paso, run_name="__main__")
        except SystemExit as exc:
            code = exc.code if isinstance(exc.code, int) else (0 if exc.code is None else 1)
            if code:
                print(f"\nFALLO en {paso} (exit {code}). Se detiene el pipeline.")
                sys.exit(code)
    print("\nPipeline completo. Abre dashboard/index.html")


if __name__ == "__main__":
    main()
