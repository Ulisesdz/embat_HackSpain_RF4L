"""Tendencia PREDICTIVA: cambio esperado del score a h meses (score_{t+h} - score_t), calculado solo con datos <= t.

Uso: python3 src/trend.py [scores.parquet]   reajusta coeficientes, valida (origen móvil + partición por grupo), escribe
                                              data/clean/trend_report.json y pasa los asserts.
     from trend import predict_change;  predict_change(scores, h=3)   -> company_id, month, exp_change, from_gap, ...

Por qué la tendencia antigua (d6 = score_t - score_{t-6}) no predice: el score son medias de ventana 6m con mucho ruido
mensual, así que un salto reciente es ruido que revierte (correlación -0,45 con el cambio siguiente). Lo que SÍ es
predecible, y es lo que modela esto con 3 variables y una regresión lineal (OLS) interpretable:
  1. reversión al nivel propio: (media histórica de la empresa, encogida hacia 50 según su historia) - score_t
  2. reversión global: score_t - 50 (el score está estandarizado a media 50)
  3. salida de ventana ("gap"): score_fast - score = los 3 últimos meses frente a los 6 de la ventana. Si el último
     trimestre es mejor que la ventana, al salir los 3 meses más antiguos el score sube casi mecánicamente.
Con h=6 las ventanas ya no se solapan y casi todo es (1)+(2). Probado sin ganancia y descartado: pendientes/deltas de
señales (overdue, runway, deuda...), bloques, d1/d3/d6, tiempo, longitud de historia, medias exponenciales y
gradient boosting (no supera a la lineal).
"""
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

D = Path("data/clean")
REP = D / "trend_report.json"
MU = 50.0          # el score está estandarizado a media 50 (score.py): destino de la reversión global
K = 3              # "meses de historia" que pesa el a priori (50) frente a la media propia; probado k=0,5..24: casi igual
COLS = ["s50", "dev", "gap"]
CUTS = {3: ["2025-06", "2025-09", "2025-12", "2026-03"], 6: ["2025-10", "2025-12", "2026-01"]}  # orígenes de ajuste (mes T)
UMBRAL = {3: 5.0, 6: 8.0}   # puntos de cambio esperado para decir "mejorando"/"deteriorando" (ver validación)
MODELO = "MODELO (s50+dev+gap)"


def features(sc, h=None):
    """Features por empresa-mes con score (solo datos <= t); si h, añade y = score_{t+h} - score_t (solo para ajustar/validar)."""
    piv = lambda c: sc.pivot(index="company_id", columns="month", values=c)
    S = piv("score")
    months = pd.period_range(S.columns.min(), S.columns.max(), freq="M").astype(str)
    S = S.reindex(columns=months)
    A = S.to_numpy(float)
    F = piv("score_fast").reindex(index=S.index, columns=months).to_numpy(float) if "score_fast" in sc else np.full_like(A, np.nan)
    cnt = np.cumsum(~np.isnan(A), axis=1)
    mean = np.cumsum(np.nan_to_num(A), axis=1) / np.maximum(cnt, 1)   # media histórica propia (expansiva: solo pasado)
    w = cnt / (cnt + K)
    own = w * mean + (1 - w) * MU                                    # encogida hacia 50 con poca historia
    f = pd.DataFrame({"s": A.ravel(), "s50": (A - MU).ravel(), "dev": (own - A).ravel(), "dev0": (mean - A).ravel(),
                      "gap": np.nan_to_num(F - A).ravel()})
    f.insert(0, "month", np.tile(months, len(S)))
    f.insert(0, "company_id", np.repeat(S.index.values, len(months)))
    if h:
        y = np.full_like(A, np.nan)
        y[:, :-h] = A[:, h:] - A[:, :-h]
        f["y"] = y.ravel()
    return f[f.s.notna()].reset_index(drop=True)


def _ols(d, cols):
    X = np.column_stack([np.ones(len(d)), d[cols].to_numpy()])
    return np.linalg.lstsq(X, d.y.to_numpy(), rcond=None)[0]


def fit(f):
    """OLS y ~ 1 + s50 + dev + gap sobre las filas con y conocida."""
    d = f.dropna(subset=["y"])
    b = _ols(d, COLS)
    resid = d.y - b[0] - d[COLS].to_numpy() @ b[1:]
    return {"b0": b[0], **dict(zip(COLS, b[1:])), "resid_sd": float(resid.std()), "n": len(d)}


def apply(f, c):
    x = f[COLS].to_numpy() * np.array([c[k] for k in COLS])
    return c["b0"] + x.sum(axis=1), x[:, COLS.index("gap")]


def predict_change(scores=None, h=3, coefs=None):
    """Cambio esperado del score a h meses (h=3 o 6) por empresa-mes con score. `scores`: DataFrame o ruta a un parquet con
    las columnas de scores.parquet (por defecto data/clean/scores.parquet). Coeficientes CONGELADOS de trend_report.json
    (no se reajustan con el lote que se puntúa). Devuelve exp_change (puntos), from_gap (parte por salida de ventana),
    band (desv. típica residual del error de predicción, en puntos) y trend_label."""
    sc = scores if isinstance(scores, pd.DataFrame) else pd.read_parquet(scores or D / "scores.parquet")
    coefs = coefs or json.loads(REP.read_text())["coefs"][str(h)]
    f = features(sc)
    f["exp_change"], f["from_gap"] = apply(f, coefs)
    f["band"] = coefs["resid_sd"]
    u = UMBRAL[h]
    f["trend_label"] = np.select([f.exp_change >= u, f.exp_change <= -u], ["mejorando", "deteriorando"], "estable")
    return f[["company_id", "month", "exp_change", "from_gap", "band", "trend_label"]]


# ---------------------------------------------------------------- validación
def _metrics(y, p, ref=None):
    """Spearman y R2 fuera de muestra (vs 'cambio 0'; y vs `ref` si se da), acierto de signo, cambio realizado en decil extremo."""
    from scipy.stats import spearmanr
    o, k = np.argsort(p), max(1, len(p) // 10)
    out = {"n": int(len(y)), "spearman": round(float(spearmanr(p, y)[0]), 3) if p.std() > 0 else None,
           "r2_vs_cero": round(1 - ((y - p) ** 2).sum() / (y ** 2).sum(), 3),
           "acierto_signo": round(float((np.sign(p) == np.sign(y)).mean()), 3) if p.std() > 0 else None,
           "decil_sup_realizado": round(float(y[o[-k:]].mean()), 2) if p.std() > 0 else None,
           "decil_inf_realizado": round(float(y[o[:k]].mean()), 2) if p.std() > 0 else None}
    if ref is not None:
        out["r2_vs_mejor_baseline"] = round(1 - ((y - p) ** 2).sum() / ((y - ref) ** 2).sum(), 3)
    return out


def validate(sc, h):
    """Origen móvil: para cada T se ajusta con filas cuyo objetivo ya era conocido en T (mes+h <= T) y se evalúa en el bloque
    [T, siguiente T) (con t+h <= último mes). Ajuste y evaluación en mitades DISTINTAS de grupos (group_id), y viceversa."""
    f = features(sc, h).join(pd.read_parquet(D / "companies.parquet").set_index("company_id").group_id, on="company_id")
    f = f.merge(sc[["company_id", "month", "d6", "label"]], on=["company_id", "month"], how="left")
    f["d6"] = f.d6.fillna(0)
    g = f.group_id.unique()
    f["fold"] = f.group_id.isin(set(np.random.RandomState(0).permutation(g)[: len(g) // 2]))
    months = sorted(f.month.unique())
    mi = f.month.map({m: i for i, m in enumerate(months)}).to_numpy()
    fam = {"cero": None, "media_propia (sin encoger)": ["dev0"], "media_propia (encogida)": ["dev"],
           "global (score-50)": ["s50"], "tendencia antigua d6 (extrapolada)": "d6", "tendencia antigua d6 (con signo ajustado)": ["d6"],
           MODELO: COLS}
    P = {k: [] for k in fam}
    ys, gs, blk, lab, sl, gc = [], [], [], [], [], []
    cuts = CUTS[h] + ["9999"]
    for a, b in zip(cuts[:-1], cuts[1:]):
        for fo in (True, False):
            tr = f[(mi + h <= months.index(a)) & f.y.notna() & (f.fold == fo)]
            te = f[(f.month >= a) & (f.month < b) & f.y.notna() & (f.fold != fo)]
            if len(tr) < 200 or len(te) < 50:
                continue
            ys.append(te.y.to_numpy()); gs.append(te.group_id.to_numpy()); blk.append(np.full(len(te), a)); lab.append(te.label.to_numpy()); sl.append(te.s.to_numpy())
            for k, cols in fam.items():
                if cols is None or cols == "d6":   # 'cero' y 'seguir la tendencia actual': d6/6 puntos/mes durante h meses
                    P[k].append(np.zeros(len(te)) if cols is None else te.d6.to_numpy() * h / 6)
                    continue
                be = _ols(tr, cols)
                P[k].append(be[0] + te[cols].to_numpy() @ be[1:])
                if cols == COLS:
                    gc.append(te.gap.to_numpy() * be[1 + COLS.index("gap")])
    y, gg, bb, lab, s, gc = (np.concatenate(v) for v in (ys, gs, blk, lab, sl, gc))
    P = {k: np.concatenate(v) for k, v in P.items()}
    naive = [k for k in P if k.startswith(("media", "global"))]
    best = min(naive, key=lambda k: ((y - P[k]) ** 2).sum())   # mejor línea base ingenua (la comparación exigente)
    p = P[MODELO]
    res = {"n_test": int(len(y)), "mejor_baseline": best, "modelos": {k: _metrics(y, P[k], P[best]) for k in P}, "por_origen": {}}
    for a in CUTS[h]:
        m = bb == a
        res["por_origen"][a] = _metrics(y[m], p[m], P[best][m])
    # intervalo 95% (bootstrap por grupo, 200 remuestreos)
    rng, ug = np.random.RandomState(1), np.unique(gg)
    idx = {u: np.flatnonzero(gg == u) for u in ug}
    bs = []
    for _ in range(200):
        i = np.concatenate([idx[u] for u in rng.choice(ug, len(ug))])
        m = _metrics(y[i], p[i], P[best][i])
        bs.append([m["spearman"], m["r2_vs_cero"], m["r2_vs_mejor_baseline"]])
    lo, hi = np.percentile(bs, [2.5, 97.5], axis=0).round(3)
    res["ic95_modelo"] = {"spearman": [lo[0], hi[0]], "r2_vs_cero": [lo[1], hi[1]], "r2_vs_mejor_baseline": [lo[2], hi[2]]}
    q = pd.qcut(p, 10, labels=False, duplicates="drop")
    res["deciles"] = [{"decil": int(d), "pred_media": round(float(p[q == d].mean()), 2), "real_media": round(float(y[q == d].mean()), 2)}
                      for d in range(10)]
    # ¿aporta la parte 'gap' (salida de ventana) DENTRO de cada nivel de score? (Spearman con el cambio realizado) y umbrales por nivel
    from scipy.stats import spearmanr
    nv, u = pd.qcut(s, 3, labels=["bajo", "medio", "alto"]), UMBRAL[h]
    res["por_nivel_de_score"] = {n: {"spearman_modelo": round(float(spearmanr(p[nv == n], y[nv == n])[0]), 3),
                                     "spearman_solo_gap": round(float(spearmanr(gc[nv == n], y[nv == n])[0]), 3),
                                     "real_medio_si_mejorando": round(float(y[(nv == n) & (p >= u)].mean()), 2),
                                     "real_medio_si_deteriorando": round(float(y[(nv == n) & (p <= -u)].mean()), 2)}
                                for n in ["bajo", "medio", "alto"]}
    res["calibracion_pendiente"] = round(float(np.polyfit(p, y, 1)[0]), 3)   # ideal 1
    res["umbral"] = {"puntos": u}
    for nombre, sel in [("mejorando", p >= u), ("deteriorando", p <= -u), ("estable", np.abs(p) < u)]:
        d = {"n": int(sel.sum()), "pct": round(float(sel.mean()), 3), "real_medio": round(float(y[sel].mean()), 2)}
        if nombre != "estable":
            d["acierta_direccion"] = round(float((np.sign(y[sel]) == (1 if nombre == "mejorando" else -1)).mean()), 3)
        res["umbral"][nombre] = d
    res["etiqueta_actual_real_medio"] = pd.DataFrame({"y": y, "label": lab}).groupby("label").y.agg(["size", "mean"]).round(2) \
        .rename(columns={"size": "n", "mean": "real_medio"}).to_dict("index")
    return res


def main(src=None):
    src = src or (sys.argv[1] if len(sys.argv) > 1 else D / "scores.parquet")
    sc = pd.read_parquet(src)
    rep = {"coefs": {}, "validacion": {}}
    for h in (3, 6):
        rep["coefs"][str(h)] = {k: (round(float(v), 4) if k != "n" else int(v)) for k, v in fit(features(sc, h)).items()}
        rep["validacion"][str(h)] = validate(sc, h)
    REP.write_text(json.dumps(rep, indent=1, ensure_ascii=False))
    # ---- asserts
    for h in ("3", "6"):
        v = rep["validacion"][h]
        m, base = v["modelos"][MODELO], v["modelos"][v["mejor_baseline"]]
        assert m["spearman"] > base["spearman"] > 0 and m["r2_vs_cero"] > 0.10 and m["r2_vs_cero"] > base["r2_vs_cero"], f"h={h}: no supera baselines"
        assert m["decil_sup_realizado"] > 0 > m["decil_inf_realizado"], f"h={h}: no funciona en ambas direcciones"
        assert 0.7 < v["calibracion_pendiente"] < 1.3, f"h={h}: mal calibrado"
        assert rep["coefs"][h]["s50"] < 0 or rep["coefs"][h]["dev"] > 0, "debe haber reversión"
    out = predict_change(sc, 3)
    assert out.exp_change.notna().all() and len(out) == sc.score.notna().sum(), "una predicción por empresa-mes con score"
    assert set(out.trend_label) <= {"mejorando", "deteriorando", "estable"}
    # sin fugas: truncar el panel en el tiempo no cambia lo predicho en los meses que quedan
    a = predict_change(sc[sc.month <= "2026-03"], 3).set_index(["company_id", "month"]).exp_change
    assert np.allclose(a, out.set_index(["company_id", "month"]).exp_change.reindex(a.index)), "fuga de información futura"
    print(json.dumps({h: rep["validacion"][h]["modelos"] for h in ("3", "6")}, indent=1, ensure_ascii=False))
    print("ok")


if __name__ == "__main__":
    main()
