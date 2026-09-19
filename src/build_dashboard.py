"""Empaqueta scores + alertas + casos en un único HTML sin dependencias: dashboard/index.html.

Uso: python3 src/build_dashboard.py       (requiere haber corrido clean, features, score, anticipation y monitor)
Abre dashboard/index.html con doble clic; funciona sin internet ni servidor.
"""
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

_argv, sys.argv = sys.argv, ["x"]
import score as S  # noqa: E402  (pesos, señales, etiquetas)

sys.argv = _argv
D, OUT = Path("data/clean"), Path("dashboard")
OUT.mkdir(exist_ok=True)
MONTHS = pd.period_range("2024-09", "2026-08", freq="M").astype(str).tolist()
SIGS = list(S.SIGNALS)
C = S.CUTS
DIR = {"mejorando": 1, "deteriorando": 2, "bache puntual": 3}

sc = pd.read_parquet(D / "scores.parquet")
raw = S.signals(pd.read_parquet(D / "panel.parquet"), S.SLOW)  # valores en unidades reales (meses de caja, % vencido...)
al = pd.read_parquet(D / "alerts.parquet")
co = pd.read_parquet(D / "companies.parquet").set_index("company_id")
gs = pd.read_parquet(D / "scores_group.parquet")
trend = json.loads((D / "trend_report.json").read_text())
ant = json.loads((D / "anticipation_report.json").read_text())

sc = sc.merge(raw[["company_id", "month"] + SIGS], on=["company_id", "month"], suffixes=("", "_raw"))
sc["dir"] = sc.label.map(DIR).fillna(0)
ids = sorted(sc.dropna(subset=["score"]).company_id.unique())
sc = sc[sc.company_id.isin(ids)]


def piv(col, nd):
    p = sc.pivot(index="company_id", columns="month", values=col).reindex(index=ids, columns=MONTHS).round(nd)
    return p.astype(object).where(p.notna(), None).values.tolist()


S_, F_, E_, DIR_, CF_ = piv("score", 1), piv("score_fast", 1), piv("exp_change3", 1), piv("dir", 0), piv("confidence", 2)
BL = {b: piv(b, 1) for b in S.BLOCKS}
Z = {k: piv(k, 2) for k in SIGS}
R = {k: piv(k + "_raw", 3) for k in SIGS}
DIR_ = [[None if v is None else int(v) for v in r] for r in DIR_]

companies = []
for i, c in enumerate(ids):
    r = co.loc[c]
    companies.append({"id": c, "g": r.group_id, "cur": r.currency, "inv": bool(r.has_invoices),
                      "s": S_[i], "f": F_[i], "e": E_[i], "d": DIR_[i], "cf": CF_[i],
                      "B": [BL[b][i] for b in S.BLOCKS], "Z": [Z[k][i] for k in SIGS], "R": [R[k][i] for k in SIGS]})
idx = {c: i for i, c in enumerate(ids)}

# ---- alertas
al = al[al.company_id.isin(idx)].copy()
al["i"] = al.month.map({m: i for i, m in enumerate(MONTHS)})
alerts = [{"c": r.company_id, "i": int(r.i), "d": "d" if r.direccion == "deterioro" else "m", "t": r.tipo,
           "sv": int(r.severidad == "critica"), "b": r.bloque or "", "tx": r.texto} for r in al.itertuples()]

byid_c = lambda i: companies[idx[i]]

# ---- casos "cuándo se vio venir": el score cruza un umbral tras un tramo claramente distinto (evento) y
# se mira si hubo aviso ESTRICTAMENTE anterior (en los 6 meses previos) del monitor en esa dirección.
by = {}
for a in alerts:
    by.setdefault((a["c"], a["d"]), []).append(a["i"])
cases, base = [], {"d": [0, 0], "m": [0, 0]}
for c in companies:
    s = c["s"]
    for kind, hit in (("d", lambda x, w: x < C[0] and max(w) >= C[0] + 10), ("m", lambda x, w: x >= C[2] and min(w) <= C[1])):
        ev = None
        for i in range(1, len(s)):
            w = [v for v in s[max(0, i - 6):i] if v is not None]
            if s[i] is not None and w and hit(s[i], w):
                ev = i
                break
        prior = [i for i in by.get((c["id"], kind), []) if ev is not None and ev - 6 <= i < ev]
        if ev is not None:
            first = min(prior) if prior else None
            cases.append({"c": c["id"], "k": kind, "i": ev, "s0": max(w) if kind == "d" else min(w), "s1": s[ev],
                          "first": first, "lead": None if first is None else ev - first})
        # tasa base: fracción de empresas-mes SIN evento con algún aviso de esa dirección en los 6 meses previos
        for i in range(6, len(s)):
            if s[i] is not None and i != ev:
                base[kind][1] += 1
                base[kind][0] += any(i - 6 <= j < i for j in by.get((c["id"], kind), []))
# caso destacado para la demo: caída clara con aviso temprano, serie suave y con facturas conectadas
def rough(c):
    v = [x for x in c["s"] if x is not None]
    return np.mean(np.abs(np.diff(v))) if len(v) > 1 else 99
cands = [x for x in cases if x["k"] == "d" and x["lead"] and x["lead"] >= 3 and x["s0"] >= C[1] + 5 and x["s1"] < C[0]
         and byid_c(x["c"])["inv"] and sum(v is not None for v in byid_c(x["c"])["s"]) >= 18]
best = min(cands or [x for x in cases if x["k"] == "d"], key=lambda x: rough(byid_c(x["c"])))
featured, featured_mi = best["c"], best["i"]

# ---- grupos
gp = gs.pivot(index="group_id", columns="month", values="score").reindex(columns=MONTHS).round(1)
members = co.reset_index().groupby("group_id").company_id.apply(lambda s: [x for x in s if x in idx]).to_dict()
groups = [{"id": g, "m": members.get(g, []), "s": gp.loc[g].astype(object).where(gp.loc[g].notna(), None).tolist()}
          for g in gp.index if members.get(g)]

# ---- cifras validadas (informe de anticipación) para la pestaña de método
prec = ant["monitor"]["precision"]
pick = lambda k: {f: prec[k].get(f) for f in ("alertas", "precision_observable", "base_observable", "precision_emparejado", "base_emparejado",
                                               "rebota_2m", "recall_observable", "antelacion_mediana_observable")}
kev = ant["eventos"][f"deterioro: a2 score <{C[0]} sostenido"]
kr = kev["reglas"][f"score < {C[0] + 7}"]
data = {
    "months": MONTHS, "blocks": S.BLOCKS, "mode": S.MODE, "cuts": list(C), "featured": featured, "featuredMi": featured_mi,
    "sig": [{"k": k, "block": S.BLOCK[k], "w": float(S.W[k]), "label": S.LABEL[k]} for k in SIGS],
    "kpt": S.kpt(),          # z ponderado -> puntos de score
    "trendSd": trend["coefs"]["3"]["resid_sd"],
    "co": companies, "al": alerts, "cases": cases, "groups": groups,
    "baseAlert": {k: v[0] / v[1] for k, v in base.items()},
    "valid": {"score": {"precision": kr["precision"], "aleatoria": kr["aleatoria"]["precision"], "recall": kr["recall"], "antel": kr["antelacion_mediana"]},
              "ingresos_baja": pick("deterioro | bloque ingresos"), "liquidez_sube": pick("mejora | bloque liquidez")},
}
html = Path("dashboard/template.html").read_text().replace("/*DATA*/null", json.dumps(data, separators=(",", ":"), allow_nan=False))
(OUT / "index.html").write_text(html)
print(f"dashboard/index.html  {len(html) / 1e6:.1f} MB | {len(ids)} empresas, {len(alerts)} alertas, {len(cases)} casos, {len(groups)} grupos | destacada: {featured}")
