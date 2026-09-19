"""Anticipación medida: ¿cuántos meses antes de un evento real levanta la mano una regla de alerta, y con qué precisión?

Uso: python3 src/anticipation.py [scores.parquet] [informe.json]   (por defecto data/clean/scores.parquet y anticipation_report.json)

Diseño anti-circularidad:
  - la alerta en el mes t usa solo columnas del score en t (que solo ve datos <= t); el evento se define con meses > t;
  - el evento es un ONSET: la empresa NO está en el estado malo en t (así no se premia predecir lo que ya pasó);
  - dos familias de eventos: (a) sobre el propio score y (b) sobre resultados observables del panel bruto (caja, morosidad,
    recibos devueltos, ingresos), que no son el score aunque sus señales alimenten el score;
  - cada regla se compara con una alerta ALEATORIA con la misma tasa y la misma persistencia (cadena de Markov) y con dos reglas
    ingenuas (flujo neto del mes < 0 / caja < 0);
  - los umbrales de abajo se fijaron a priori (mirando solo la distribución marginal del panel, no el resultado); no se han ajustado.
"""
import json
import sys
import warnings
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.metrics import roc_auc_score

warnings.filterwarnings("ignore", category=RuntimeWarning)   # medias de rebanadas vacías (meses sin dato)
D = Path("data/clean")
SCORES, OUT = D / "scores.parquet", D / "anticipation_report.json"

# ---- umbrales (constantes, fijados a priori) ----
H = 6              # horizonte: el evento ocurre en (t, t+H] meses
SUST = 3           # meses que debe mantenerse un estado para ser "sostenido" (<= 2 meses y revierte = bache)
DEBOUNCE = 3       # una alerta es nueva si no hubo alerta en los DEBOUNCE meses anteriores
MIN_SCORED = 6     # se excluyen empresas con menos meses puntuados (ruido)
CUT_LOW, CUT_HIGH = 40, 70        # cruces de score (= score.CUTS[0] y CUTS[2] en modo abs)
DELTA = 15                        # puntos de caída/subida sostenida
RUNWAY_LOW, RUNWAY_OK = 0.5, 2.0  # meses de caja: agotada / recuperada
AR_JUMP, AR_HIGH, AR_LOW = 0.30, 0.50, 0.30   # morosidad de clientes: salto, nivel alto, nivel normalizado
REFUND_HIGH = 0.05                # recibos devueltos / cobros (3m) ~ percentil 95
INFLOW_DRY, INFLOW_UP = 0.5, 1.5  # ingresos (media 2m) vs base 6m
# reglas de alerta (deterioro; la mejora es la simétrica)
DELTAS, GAP_STRONG, D3 = (7, 12), 5, 8   # alerta cuando el score está a 7 o 12 puntos del umbral del evento
BLOCKS = ('liquidez', 'pago', 'financiacion', 'ingresos')
RNG = np.random.default_rng(0)
NSIM = 30


# ---------- datos como matrices empresa x mes ----------
def load(path):
    s = pd.read_parquet(path)
    p = pd.read_parquet(D / "panel.parquet")
    ids, months = sorted(p.company_id.unique()), sorted(p.month.unique())
    M = lambda df, c: df.pivot(index="company_id", columns="month", values=c).reindex(index=ids, columns=months).to_numpy(float)
    roll = lambda X, w, mp, f="mean": getattr(pd.DataFrame(X.T).rolling(w, min_periods=mp), f)().to_numpy().T
    d = {c: M(s, c) for c in ["score", "score_fast", "gap", "d3", "d6", *BLOCKS]}
    d["struct"] = M(s.assign(v=(s.label == "deteriorando").astype(float)), "v")
    d["improv"] = M(s.assign(v=(s.label == "mejorando").astype(float)), "v")
    inflow, outflow, cash = M(p, "inflow"), M(p, "outflow"), M(p, "cash_end")
    out3 = roll(outflow, 3, 2)
    d["runway"] = cash / np.where(out3 > 0, out3, np.nan)
    d["cash"] = cash
    d["net"] = (inflow - outflow) / np.where(inflow + outflow > 0, inflow + outflow, np.nan)
    d["ar"] = M(p, "ar_overdue_ratio")
    coll = roll(M(p, "collections"), 3, 2, "sum")
    d["refund"] = roll(M(p, "returned_receipts"), 3, 2, "sum") / np.where(coll > 0, coll, np.nan)
    d["inflow2"] = roll(inflow, 2, 2)
    base = roll(inflow, 6, 4)
    d["base"] = np.where(base > 0, base, np.nan)
    hist = np.isfinite(d["score"]).sum(1) >= MIN_SCORED
    for k in d:
        d[k][~hist] = np.nan
    return d, ids, months


# ---------- eventos ----------
def shift(X, j):
    """X[:, t+j] con relleno NaN al final."""
    return np.pad(X, ((0, 0), (0, j)), constant_values=np.nan)[:, j:]


def sustained(B, n):
    """B en {1,0,nan} -> 1 si B[k..k+n-1] son todos 1, 0 si alguno es 0 (ya descartado), nan si no se sabe."""
    X = np.stack([shift(B, j) for j in range(n)])
    return np.where((X == 1).all(0), 1.0, np.where((X == 0).any(0), 0.0, np.nan))


def event(bfun, ok, sust=SUST):
    """E[i,t]=1 si aparece un estado malo sostenido con inicio en (t,t+H], 0 si seguro que no, nan si no se sabe o si en t ya
    estaba en el estado (ok=False). K[i,t] = mes de inicio del primer evento."""
    n, T = ok.shape
    E, K = np.full((n, T), np.nan), np.full((n, T), np.nan)
    for t in range(T):
        S = np.pad(sustained(bfun(t), sust), ((0, 0), (0, H + 1)), constant_values=np.nan)[:, t + 1:t + 1 + H]
        hit, none = (S == 1).any(1), (S == 0).all(1)
        E[:, t] = np.where(hit, 1.0, np.where(none, 0.0, np.nan))
        K[:, t] = np.where(hit, t + 1 + np.argmax(S == 1, 1), np.nan)
    return np.where(ok, E, np.nan), np.where(ok, K, np.nan)


def b(cond, *known):
    """condición booleana -> {1,0,nan} (nan donde algún dato no se conoce)."""
    out = cond.astype(float)
    for k in known:
        out = np.where(np.isfinite(k), out, np.nan)
    return out


def col(X, t):
    return X[:, [t]]


def build_events(d):
    """{(dirección, nombre): (E, K)} en las dos direcciones."""
    sc, ok = d["score"], np.isfinite(d["score"])
    ev = {}
    # (a) sobre el propio score
    ev["deterioro", "a1 score cae >=15 pts (3m)"] = event(lambda t: b(sc <= col(sc, t) - DELTA, sc), ok)
    ev["deterioro", f"a2 score <{CUT_LOW} sostenido"] = event(lambda t: b(sc < CUT_LOW, sc), ok & (sc >= CUT_LOW))
    ev["mejora", "a1 score sube >=15 pts (3m)"] = event(lambda t: b(sc >= col(sc, t) + DELTA, sc), ok)
    ev["mejora", f"a2 score >{CUT_HIGH} sostenido"] = event(lambda t: b(sc > CUT_HIGH, sc), ok & (sc <= CUT_HIGH))
    # (b) sobre resultados observables
    rw, ar, rf, i2, ba = d["runway"], d["ar"], d["refund"], d["inflow2"], d["base"]
    okr, oka = np.isfinite(rw) & ok, np.isfinite(ar) & ok
    ev["deterioro", "b1 caja agotada (runway<0,5m)"] = event(lambda t: b(rw < RUNWAY_LOW, rw), okr & (rw >= RUNWAY_LOW))
    ev["deterioro", "b2 morosidad clientes se dispara"] = event(
        lambda t: b((ar >= col(ar, t) + AR_JUMP) & (ar >= AR_HIGH), ar), oka & (ar < AR_HIGH), 2)
    ev["deterioro", "b3 recibos devueltos >=5%"] = event(lambda t: b(rf >= REFUND_HIGH, rf), np.isfinite(rf) & ok & (rf < REFUND_HIGH), 2)
    ev["deterioro", "b4 ingresos se secan (<50% base)"] = event(
        lambda t: b(i2 <= INFLOW_DRY * col(ba, t), i2, col(ba, t)), np.isfinite(ba) & ok)
    ev["mejora", "b1 caja se recupera (runway>=2m)"] = event(lambda t: b(rw >= RUNWAY_OK, rw), okr & (rw < 1))
    ev["mejora", "b2 morosidad clientes se normaliza"] = event(
        lambda t: b((ar <= col(ar, t) - AR_JUMP) & (ar <= AR_LOW), ar), oka & (ar >= AR_HIGH), 2)
    ev["mejora", "b4 ingresos crecen (>=150% base)"] = event(
        lambda t: b(i2 >= INFLOW_UP * col(ba, t), i2, col(ba, t)), np.isfinite(ba) & ok)
    for dr in ("deterioro", "mejora"):  # b: cualquiera de los eventos observables
        parts = [v for (k, n), v in ev.items() if k == dr and n[0] == "b"]
        Es, Ks = np.stack([p[0] for p in parts]), np.stack([p[1] for p in parts])
        hit = (Es == 1).any(0)
        E = np.where(hit, 1.0, np.where((Es == 0).sum(0) >= 2, 0.0, np.nan))  # 0 si >=2 tipos evaluables sin evento
        ev[dr, "b* cualquier evento observable"] = (E, np.where(hit, np.nanmin(np.where(Es == 1, Ks, np.inf), 0), np.nan))
    return ev


# ---------- reglas de alerta y predictores continuos (mayor = más riesgo/oportunidad) ----------
def rules(d):
    """{dirección: {regla: (alerta bool, predictor y)}}; y mayor = más riesgo (deterioro) o más mejora."""
    r = {}
    for dr, sg in (("deterioro", -1), ("mejora", 1)):
        y = lambda k: sg * d[k]  # deterioro: score bajo = riesgo alto
        lo, up = ("<", "-") if sg < 0 else (">", "+")
        cuts = [sg * (CUT_LOW + d if sg < 0 else CUT_HIGH - d) for d in DELTAS]
        r[dr] = {
            **{f"score {lo} {abs(c)}": (y("score") > c, y("score")) for c in cuts},
            f"score_fast {lo} {abs(cuts[0])}": (y("score_fast") > cuts[0], y("score_fast")),
            f"gap {lo} 0": (y("gap") > 0, y("gap")),
            f"gap {lo}= {up}{GAP_STRONG}": (y("gap") >= GAP_STRONG, y("gap")),
            f"d3 {lo}= {up}{D3}": (y("d3") >= D3, y("d3")),
            **{f"bloque {b_} {lo} {abs(cuts[0])}": (y(b_) > cuts[0], y(b_)) for b_ in BLOCKS},
            "label estructural/mejorando (d6)": (d["struct" if sg < 0 else "improv"] == 1, y("d6")),
            "NAIVE flujo neto mes " + lo + " 0": (y("net") > 0, y("net")),
        }
    r["deterioro"]["NAIVE caja < 0"] = (d["cash"] < 0, -d["runway"])
    return r


def markov(A, U):
    """Alerta aleatoria con la misma tasa y persistencia (P(on|off), P(on|on)) que la regla A."""
    prev, cur, both = A[:, :-1], A[:, 1:], U[:, :-1] & U[:, 1:]
    p11 = cur[both & prev].mean() if (both & prev).any() else 0
    p01 = cur[both & ~prev].mean() if (both & ~prev).any() else 0
    R = np.zeros_like(A)
    R[:, 0] = RNG.random(A.shape[0]) < A[U].mean()
    for t in range(1, A.shape[1]):
        R[:, t] = RNG.random(A.shape[0]) < np.where(R[:, t - 1], p11, p01)
    return R


def evaluate(A, E, K, tmask=None):
    """Métricas de una alerta A (bool n x T) frente al evento (E,K). Universo U: filas con evento conocible."""
    n, T = A.shape
    U = np.isfinite(E)
    if tmask is not None:
        U = U & tmask[None, :]
    A = A.astype(bool)
    prev = np.zeros_like(A)
    for j in range(1, DEBOUNCE + 1):
        prev[:, j:] |= A[:, :-j]
    O = A & ~prev & U                                   # alertas nuevas
    if not U.any():
        return {}
    k_star = np.where(U & (E == 1), K, np.inf).min(1)  # primer evento de cada empresa
    tt = np.arange(T)[None, :]
    win = U & A & (tt >= k_star[:, None] - H) & (tt < k_star[:, None])
    has = np.isfinite(k_star)
    det = win.any(1) & has
    lead = (k_star - np.argmax(win, 1))[det]
    Eo = E[O]
    return {"filas": int(U.sum()), "eventos": int(has.sum()), "tasa_base": float(np.nanmean(E[U])),
            "tasa_alerta": float(A[U].mean()), "alertas_nuevas": int(O.sum()),
            "precision": float(Eo.mean()) if len(Eo) else np.nan,
            "recall": float(det.sum() / has.sum()) if has.any() else np.nan,
            "falsas_alarmas_por_empresa_anio": float((Eo == 0).sum() / (U.sum() / 12)),
            "antelacion_mediana": float(np.median(lead)) if len(lead) else np.nan,
            "antelacion_p25_p75": [float(np.percentile(lead, 25)), float(np.percentile(lead, 75))] if len(lead) else None,
            "antelacion_media": float(lead.mean()) if len(lead) else np.nan,
            "lift_precision": float(Eo.mean() / np.nanmean(E[U])) if len(Eo) else np.nan}


def random_baseline(A, E, K, tmask=None):
    U = np.isfinite(E)
    rs = [evaluate(markov(A, U), E, K, tmask) for _ in range(NSIM)]
    return {k: float(np.nanmedian([x[k] for x in rs])) for k in ("precision", "recall", "falsas_alarmas_por_empresa_anio", "antelacion_mediana")}


def auc(x, E, ids_idx, boots=100):
    """AUC de x (mayor = más riesgo) para E en (t,t+H], con IC 90% por bootstrap de empresas."""
    U = np.isfinite(E) & np.isfinite(x)
    if len(np.unique(E[U])) < 2:
        return None
    a = roc_auc_score(E[U], x[U])
    bs = []
    for _ in range(boots):
        s = RNG.choice(E.shape[0], E.shape[0])
        m = U[s]
        y, z = E[s][m], x[s][m]
        if len(np.unique(y)) == 2:
            bs.append(roc_auc_score(y, z))
    return [float(a), float(np.percentile(bs, 5)), float(np.percentile(bs, 95))]


# ---------- bache vs caída ----------
def episodes(B):
    """Episodios de B=1 que empiezan en k (B[k-1]=0) -> (i, k, duración, revierte). Duración conocida solo si termina en 0."""
    out = []
    for i in range(B.shape[0]):
        r = B[i]
        for k in range(1, len(r)):
            if r[k] == 1 and r[k - 1] == 0:
                e = k
                while e < len(r) and r[e] == 1:
                    e += 1
                rev = e < len(r) and r[e] == 0
                if rev or e - k >= SUST:
                    out.append((i, k, e - k, rev))
    return out


def bache_report(d):
    """Sobre episodios de caja agotada / morosidad alta / ingresos secos: los de <=2 meses que revierten son baches, los de >=3 caídas.
    Compara qué fracción de cada tipo marca como 'caída' el score lento (6m) frente al rápido (3m), a igual tasa de alertas."""
    rw, ar, i2, ba = d["runway"], d["ar"], d["inflow2"], d["base"]
    Bs = {"caja agotada": b(rw < RUNWAY_LOW, rw), "morosidad clientes >=0,5": b(ar >= AR_HIGH, ar),
          "ingresos <50% base": b(i2 <= INFLOW_DRY * ba, i2, ba)}
    q = 0.10  # ambas versiones alertan en el 10% peor de su propia caída a 3 meses
    lag3 = lambda X: np.pad(X, ((0, 0), (3, 0)), constant_values=np.nan)[:, :-3]
    chg = {"lento": d["score"] - lag3(d["score"]), "rapido": d["score_fast"] - lag3(d["score_fast"])}
    al = {k: v <= np.nanquantile(v, q) for k, v in chg.items()}
    win3 = lambda A: np.nanmean([A[:, i:i + 3].any(1)[np.isfinite(d["score"][:, i:i + 3]).all(1)].mean() for i in range(A.shape[1] - 3)])
    res = {}
    for name, B in Bs.items():
        eps = episodes(B)
        r = {"baches": sum(1 for e in eps if e[2] <= 2 and e[3]), "sostenidas": sum(1 for e in eps if e[2] >= SUST)}
        for v, A in al.items():
            fire = lambda e: A[e[0], e[1]:e[1] + 3].any()  # alerta en los 3 primeros meses del episodio
            bc = [fire(e) for e in eps if e[2] <= 2 and e[3]]
            sc_ = [fire(e) for e in eps if e[2] >= SUST]
            r[v] = {"baches_marcados_como_caida": float(np.mean(bc)) if bc else None,
                    "sostenidas_marcadas": float(np.mean(sc_)) if sc_ else None}
        res[name] = r
    res["tasa_alerta_en_3m_cualquiera"] = {v: float(win3(A)) for v, A in al.items()}
    return res


def labels_report(path, d, ev):
    """Validación de las etiquetas del score: tras 'bache puntual' el score rápido debería recuperarse y tras 'deteriorando' no."""
    s = pd.read_parquet(path)
    L = np.full(d["score"].shape, "", dtype=object)
    ids = sorted(pd.read_parquet(D / "panel.parquet").company_id.unique())
    months = sorted(pd.read_parquet(D / "panel.parquet").month.unique())
    L[s.company_id.map({c: i for i, c in enumerate(ids)}).values, s.month.map({m: i for i, m in enumerate(months)}).values] = s.label.values
    E = ev["deterioro", "b* cualquier evento observable"][0]
    out = {}
    for lb in ("bache puntual", "deteriorando", "mejorando", "sólida", "sana", "débil", "frágil"):
        m = L == lb
        f = lambda X: float(np.nanmean(np.where(m, shift(X, 3) - X, np.nan)))
        out[lb] = {"n": int(m.sum()), "delta_score_3m": f(d["score"]), "delta_score_rapido_3m": f(d["score_fast"]),
                   "p_evento_observable_deterioro_6m": float(np.nanmean(E[m])) if np.isfinite(E[m]).any() else None}
    return out


def run(path=SCORES, out=OUT):
    d, ids, months = load(path)
    T = len(months)
    ev = build_events(d)
    R = rules(d)
    half = np.arange(T) <= months.index("2025-09")   # mitad temprana / tardía de meses de alerta (solo informativo)
    rep = {"config": {"H": H, "SUST": SUST, "DEBOUNCE": DEBOUNCE, "MIN_SCORED": MIN_SCORED, "scores": str(path)}, "eventos": {}}
    for (dr, name), (E, K) in ev.items():
        e = {"tasa_base": float(np.nanmean(E)), "filas": int(np.isfinite(E).sum()), "reglas": {}, "auc": {}}
        for rn, (A, x) in R[dr].items():
            A = np.nan_to_num(A.astype(float)).astype(bool) & np.isfinite(d["score"])
            m = evaluate(A, E, K)
            if not m:
                continue
            m["aleatoria"] = random_baseline(A, E, K)
            m["mitad_temprana"] = {k: v for k, v in evaluate(A, E, K, half).items() if k in ("precision", "recall", "antelacion_mediana", "eventos")}
            m["mitad_tardia"] = {k: v for k, v in evaluate(A, E, K, ~half).items() if k in ("precision", "recall", "antelacion_mediana", "eventos")}
            e["reglas"][rn] = m
            e["auc"][rn] = auc(np.where(np.isfinite(d["score"]), x, np.nan), E, None)
        rep["eventos"][f"{dr}: {name}"] = e
    rep["baches"] = bache_report(d)
    rep["etiquetas"] = labels_report(path, d, ev)
    if Path(out).exists():                                   # conserva la sección que escribe monitor.py
        rep = {**{k: v for k, v in json.loads(Path(out).read_text()).items() if k == "monitor"}, **rep}
    Path(out).write_text(json.dumps(rep, ensure_ascii=False, indent=1, default=lambda o: None))
    return rep


def show(rep):
    f = lambda v, p=2: "  -  " if v is None or (isinstance(v, float) and np.isnan(v)) else f"{v:.{p}f}"
    for en, e in rep["eventos"].items():
        print(f"\n== {en} | base {e['tasa_base']:.1%} | filas {e['filas']}")
        print(f"{'regla':38s} prec  (alea) recall (alea) FA/emp-año antel_med(alea) p25-p75  AUC[IC90]")
        for rn, m in e["reglas"].items():
            a, au = m["aleatoria"], e["auc"].get(rn)
            q = m["antelacion_p25_p75"]
            print(f"{rn:38s} {f(m['precision'])}  ({f(a['precision'])}) {f(m['recall'])}  ({f(a['recall'])}) {f(m['falsas_alarmas_por_empresa_anio'])}       "
                  f"{f(m['antelacion_mediana'], 1)} ({f(a['antelacion_mediana'], 1)})  {q and f'{q[0]:.0f}-{q[1]:.0f}'}  "
                  f"{au and f'{au[0]:.2f}[{au[1]:.2f},{au[2]:.2f}]'}  n_ev={m['eventos']} n_al={m['alertas_nuevas']}")
    print("\n== baches vs caídas", json.dumps(rep["baches"], ensure_ascii=False, indent=1))
    print("\n== etiquetas", json.dumps(rep["etiquetas"], ensure_ascii=False, indent=1))


if __name__ == "__main__":
    a = sys.argv[1:]
    show(run(Path(a[0]) if a else SCORES, Path(a[1]) if len(a) > 1 else OUT))
