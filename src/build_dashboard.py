"""Publica la UI en dashboard/ y la proyección Theil-Sen de la ficha."""
from pathlib import Path
from shutil import copy2, copytree

import numpy as np
import pandas as pd

import src.config as cfg


def _theil_sen(x, y):
    """Pendiente y origen por mediana de pares. Robusta al mes atípico."""
    x = np.asarray(x, float)
    y = np.asarray(y, float)
    n = len(y)
    slopes = [(y[j] - y[i]) / (x[j] - x[i])
              for i in range(n) for j in range(i + 1, n) if x[j] != x[i]]
    if not slopes:
        return float(y[-1]), 0.0
    b = float(np.median(slopes))
    a = float(np.median(y - b * x))
    return a, b


def _walkforward_fc(months, values, min_train=6, horizon=3, max_win=12):
    """Proyección del score a +3 meses, con banda p80 del error walk-forward."""
    xs, ys, ms = [], [], []
    for m, v in zip(months, values):
        if v is None:
            continue
        try:
            p = pd.Period(str(m), freq="M")
        except (ValueError, TypeError):
            continue
        xs.append(int(p.year) * 12 + int(p.month))
        ys.append(float(v))
        ms.append(p)
    n = len(ys)
    if n < min_train:
        return None
    x0 = xs[0]
    x = [v - x0 for v in xs]
    err1, err3 = [], []
    for t in range(min_train, n):
        i0 = max(0, t - max_win)
        _, b_t = _theil_sen(x[i0:t], ys[i0:t])
        err1.append(ys[t] - (ys[t - 1] + b_t))
        if t + 2 < n:
            err3.append(ys[t + 2] - (ys[t - 1] + b_t * 3))
    i0 = max(0, n - max_win)
    _, b = _theil_sen(x[i0:], ys[i0:])
    mae = float(np.mean(np.abs(err1))) if err1 else None
    p80 = float(np.percentile(np.abs(err1), 80)) if len(err1) >= 4 else (mae * 1.6 if mae else 6.0)
    p80_3 = float(np.percentile(np.abs(err3), 80)) if len(err3) >= 4 else p80 * 1.8
    yhat, lo, hi, fut = [], [], [], []
    last_y = ys[-1]
    last_p = ms[-1]
    for h in range(1, horizon + 1):
        pred = float(np.clip(last_y + b * h, 0, 100))
        w = p80 if h == 1 else p80 + (p80_3 - p80) * min(h - 1, 2) / 2
        yhat.append(round(pred, 1))
        lo.append(round(float(np.clip(pred - w, 0, 100)), 1))
        hi.append(round(float(np.clip(pred + w, 0, 100)), 1))
        fut.append(str(last_p + h))
    return {
        "y": yhat, "lo": lo, "hi": hi, "m": fut,
        "mae": round(mae, 1) if mae is not None else None,
        "p80": round(p80, 1),
        "b": round(b, 2),
        "n": len(err1),
    }


def build():
    """Copia la UI a dashboard/ (lo que publica Vercel)."""
    src = Path(__file__).resolve().parent.parent / "frontend"
    dest = cfg.DASHBOARD_PATH.parent
    if not (src / "index.html").is_file():
        raise SystemExit(f"Falta la UI en {src}")
    dest.mkdir(parents=True, exist_ok=True)
    copy2(src / "index.html", dest / "index.html")
    copy2(src / "embat.css", dest / "embat.css")
    assets_src = src / "assets"
    assets_dest = dest / "assets"
    if assets_dest.exists():
        for old in assets_dest.iterdir():
            if old.is_file():
                old.unlink()
    copytree(assets_src, assets_dest, dirs_exist_ok=True)
    leftover = dest / "styles.css"
    if leftover.exists():
        leftover.unlink()
    print(f"Dashboard: {dest / 'index.html'} (UI Health Score)")


if __name__ == "__main__":
    build()
