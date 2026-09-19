"""Monitor que avisa solo cuando una empresa se mueve de verdad.

Recorre scores_mensuales mes a mes, con datos <= t. No alerta la primera vez
que se ve a una empresa ya en zona: eso no es un movimiento, es el estado
inicial. Antirrebote de 6 meses y 3 meses de calentamiento.

Tipos (bidireccionales):
  giro_sana     se tuerce y el score sigue >= 55 (el caso 82→68)
  cruce_abajo   entra en FRÁGIL / CRÍTICO
  cruce_arriba  entra en SALUDABLE
  mejora        el score cruza hacia arriba el umbral de ESTABLE
"""

import numpy as np
import pandas as pd

import src.config as cfg


def _armar(y, thr, gap, warmup):
    """Dispara al entrar en zona estando armado. Rearma al salir."""
    n, t = y.shape
    fired = np.zeros((n, t), dtype=bool)
    armed = np.ones(n, dtype=bool)
    seen = np.zeros(n, dtype=bool)
    last = np.full(n, -10**6)
    for i in range(t):
        ok = np.isfinite(y[:, i])
        zone = ok & (y[:, i] >= thr)
        nuevo = ok & ~seen
        armed = np.where(nuevo, ~zone, armed)
        seen |= ok
        fire = armed & zone & ((i - last) >= gap) & (i >= warmup)
        fired[:, i] = fire
        last = np.where(fire, i, last)
        armed = np.where(zone, False, armed)
        armed = np.where(ok & ~zone, True, armed)
    return fired


def _nivel(score):
    """0 CRÍTICO … 4 SALUDABLE. NaN si no hay score."""
    out = np.full(score.shape, np.nan)
    ok = np.isfinite(score)
    out[ok] = 0
    out[ok & (score >= 33)] = 1
    out[ok & (score >= 42)] = 2
    out[ok & (score >= 52)] = 3
    out[ok & (score >= 68)] = 4
    return out


def run():
    if not cfg.SCORES_MENSUAL_PATH.exists():
        raise FileNotFoundError("Falta scores_mensuales.csv. Ejecuta score_engine.")

    men = pd.read_csv(cfg.SCORES_MENSUAL_PATH)
    men = men.sort_values(["company_id", "year_month"])
    ids = men["company_id"].drop_duplicates().tolist()
    months = sorted(men["year_month"].astype(str).unique())

    def mat(col):
        p = men.pivot(index="company_id", columns="year_month", values=col)
        return p.reindex(index=ids, columns=months)

    sc = mat("score_mensual").to_numpy(dtype=float)
    giro = mat("senal_giro").to_numpy(dtype=float)
    giro = np.where(np.isfinite(giro), giro, 0.0)
    nivel = _nivel(sc)

    gap, warm = cfg.ALERT_MIN_GAP, cfg.ALERT_WARMUP
    filas = []

    def emit(mask, tipo, direccion, severidad, motivo):
        for i, j in zip(*np.where(mask)):
            filas.append({
                "company_id": ids[i],
                "year_month": months[j],
                "tipo": tipo,
                "direccion": direccion,
                "severidad": severidad,
                "score": None if not np.isfinite(sc[i, j]) else round(float(sc[i, j]), 2),
                "motivo": motivo,
            })

    zona = np.where(np.isfinite(sc) & (giro >= 1) & (sc >= 55), 1.0, 0.0)
    emit(_armar(zona, 1.0, gap, warm), "giro_sana", "deterioro", "aviso",
         "El score sigue >= 55 pero el comportamiento ya se ha torcido.")

    emit(_armar(np.where(np.isfinite(nivel) & (nivel <= 1), 1.0, 0.0), 1.0, gap, warm),
         "cruce_abajo", "deterioro", "aviso",
         "Entra en zona frágil o crítica.")

    emit(_armar(np.where(np.isfinite(nivel) & (nivel >= 4), 1.0, 0.0), 1.0, gap, warm),
         "cruce_arriba", "mejora", "aviso",
         "Entra en SALUDABLE.")

    out = pd.DataFrame(filas)
    if out.empty:
        out = pd.DataFrame(columns=[
            "company_id", "year_month", "tipo", "direccion",
            "severidad", "score", "motivo",
        ])
    else:
        out = out.sort_values(["year_month", "direccion", "tipo", "company_id"])

    cfg.ALERTS_PATH.parent.mkdir(parents=True, exist_ok=True)
    out.to_csv(cfg.ALERTS_PATH, index=False)
    print(f"Monitor: {len(out):,} avisos → {cfg.ALERTS_PATH}")
    if len(out):
        print(out["tipo"].value_counts().to_string())
        print(out["direccion"].value_counts().to_string())
    return out


if __name__ == "__main__":
    run()
