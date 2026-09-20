"""Publica la UI del Health Score en dashboard/ y helpers de proyección."""
import json
from pathlib import Path

import numpy as np
import pandas as pd

import src.config as cfg

EJES = [
    ("deuda_comercial", "Deuda comercial", 20),
    ("liquidez", "Liquidez", 18),
    ("colchon", "Colchón", 18),
    ("trayectoria", "Trayectoria", 18),
    ("eficiencia", "Eficiencia", 14),
    ("cobro_clientes", "Cobro", 12),
]


def _num(v, nd=2):
    if v is None or (isinstance(v, float) and (np.isnan(v) or np.isinf(v))):
        return None
    try:
        if pd.isna(v):
            return None
    except (TypeError, ValueError):
        pass
    if isinstance(v, (np.floating, float)):
        return round(float(v), nd)
    if isinstance(v, (np.integer, int)):
        return int(v)
    return v


def _theil_sen(x, y):
    """Pendiente y origen por mediana de pares. Robusta al mes atípico (el bache)."""
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
    """Proyección del score mensual con banda calibrada walk-forward.

    En cada origen t se estima la pendiente Theil-Sen con los últimos
    `max_win` meses (se empieza en 6 y se amplia hasta 12; después la
    ventana se desliza). La proyección no vuelve a la recta: parte del
    último score real y avanza `pendiente × meses`. La banda es el p80
    de ese mismo error walk-forward, más ancha a 3 meses.
    No predice quiebra: predice el propio score. Dos meses no bastan.
    """
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


def payload():
    fin = pd.read_csv(cfg.SCORES_PATH)
    grp = pd.read_csv(cfg.SCORES_GRUPO_PATH)
    men = pd.read_csv(cfg.SCORES_MENSUAL_PATH)
    exp = json.loads(cfg.EXPLAIN_PATH.read_text(encoding="utf-8"))

    ant_col = "meses_anticipacion" if "meses_anticipacion" in fin.columns else None
    companies = []
    for r in fin.itertuples(index=False):
        companies.append({
            "id": r.company_id,
            "g": r.group_id if pd.notna(r.group_id) else "",
            "s": _num(r.score_final),
            "b": _num(r.score_bruto),
            "c": r.clasificacion,
            "t": r.tendencia,
            "giro": int(r.giro_detectado),
            "nat": r.naturaleza_caida if isinstance(r.naturaleza_caida, str) else "",
            "conf": r.confianza,
            "apto": int(r.apto_ranking),
            "d": _num(r.delta_score_ultimo_mes),
            "mot": (r.motivo_cambio_ultimo_mes
                    if isinstance(r.motivo_cambio_ultimo_mes, str) and r.motivo_cambio_ultimo_mes
                    else ""),
            "tr": _num(r.score_trayectoria),
            "last": _num(r.score_ultimo_mes),
            "pg": r.primer_giro if isinstance(r.primer_giro, str) else "",
            "sig": _num(r.giro_sigmas),
            "ant": _num(getattr(r, ant_col), 1) if ant_col else None,
            "gan": _num(getattr(r, "meses_ganados_a_nivel", None), 1),
            "pa": r.primera_alerta if isinstance(getattr(r, "primera_alerta", None), str) else "",
            "caida": _num(getattr(r, "caida_score_3m", None)),
            "al": int(r.alerta_temprana) if pd.notna(r.alerta_temprana) else 0,
            "dir": None,
        })

    groups = []
    for r in grp.itertuples(index=False):
        groups.append({
            "id": r.group_id,
            "n": int(r.n_empresas),
            "s": _num(r.score_grupo),
            "peor": _num(r.score_peor),
            "mejor": _num(r.score_mejor),
            "emp": r.empresa_peor,
            "cg": r.clasificacion_grupo,
            "cp": r.clasificacion_peor,
            "hide": int(r.agregado_esconde_problema),
            "opp": int(r.tendencias_opuestas),
        })

    series = {}
    men = men.sort_values(["company_id", "year_month"])
    men["year_month"] = men["year_month"].astype(str)
    dir_map = {}
    for cid, h in men.groupby("company_id"):
        svals = [_num(v) for v in h["score_mensual"]]
        scored = [v for v in svals if v is not None]
        d6 = None
        if len(scored) >= 2:
            k = min(6, len(scored))
            d6 = _num(float(scored[-1] - scored[-k]))
        dir_map[cid] = d6
        series[cid] = {
            "m": h["year_month"].tolist(),
            "s": svals,
            "g": [int(v) if pd.notna(v) else 0 for v in h["senal_giro"]],
            "fc": _walkforward_fc(h["year_month"].tolist(), svals),
        }
    for c in companies:
        c["dir"] = dir_map.get(c["id"])

    tmap = fin.set_index("company_id")["tendencia"]
    men["_t"] = men["company_id"].map(tmap)
    months = sorted(men["year_month"].unique())
    def _med(mask):
        g = men.loc[mask].groupby("year_month")["score_mensual"].median()
        return [_num(g.get(m)) for m in months]
    flows = {
        "m": months,
        "MEJORANDO": _med(men["_t"] == "MEJORANDO"),
        "DETERIORANDO": _med(men["_t"] == "DETERIORANDO"),
        "ESTABLE": _med(men["_t"] == "ESTABLE"),
    }

    explain = {}
    for cid, e in exp.items():
        facs = {}
        for k, v in (e.get("factores") or {}).items():
            if k.startswith("_"):
                continue
            facs[k] = {
                "s": _num(v.get("score")),
                "w": _num(v.get("peso_efectivo")),
                "ok": bool(v.get("aplicable")),
                "r": (v.get("razon") or "")[:220],
            }
        explain[cid] = {
            "f": facs,
            "mot": (e.get("cambio_vs_mes_anterior") or {}).get("explicacion") or "",
            "giro": (e.get("giro") or {}).get("por_que") or "",
        }

    for c in companies:
        if not c["mot"]:
            c["mot"] = (explain.get(c["id"]) or {}).get("giro") or ""

    ok = fin[fin["score_final"].notna()]
    giro_sanas = [x for x in companies if x["giro"] and x["s"] is not None and x["s"] >= 55]
    featured = sorted(giro_sanas, key=lambda x: ((x["nat"] != "caida_estructural"), -(x["sig"] or 0)))
    featured_id = featured[0]["id"] if featured else companies[0]["id"]

    alerts = []
    if cfg.ALERTS_PATH.exists():
        al = pd.read_csv(cfg.ALERTS_PATH)
        for r in al.itertuples(index=False):
            alerts.append({
                "id": r.company_id,
                "m": str(r.year_month),
                "tipo": r.tipo,
                "dir": r.direccion,
                "s": _num(r.score),
                "mot": r.motivo if isinstance(r.motivo, str) else "",
            })

    llamadas = fin[(fin["giro_detectado"] == 1) & (fin["score_final"] >= 55)]
    nat_l = llamadas["naturaleza_caida"].value_counts() if len(llamadas) else pd.Series(dtype=int)
    nat_m = men.loc[men["senal_giro"] == 1, "naturaleza_caida"].value_counts() if "naturaleza_caida" in men else pd.Series(dtype=int)
    kpis = {
        "n": int(len(fin)),
        "aptas": int(fin["apto_ranking"].sum()),
        "media": _num(ok["score_final"].mean()),
        "giro_sanas": len(giro_sanas),
        "hide": int(grp["agregado_esconde_problema"].sum()),
        "ng": int(len(grp)),
        "mej": int((fin["tendencia"] == "MEJORANDO").sum()),
        "det": int((fin["tendencia"] == "DETERIORANDO").sum()),
        "est": int((fin["tendencia"] == "ESTABLE").sum()),
        "sano": int(ok["clasificacion"].isin(["SALUDABLE", "ESTABLE"]).sum()),
        "clase": {str(k): int(v) for k, v in ok["clasificacion"].value_counts().items()},
        "avisos": len(alerts),
        "featured": featured_id,
        "bache_l": int(nat_l.get("bache", 0)),
        "caida_l": int(nat_l.get("caida_estructural", 0)),
        "bache_n": int(nat_m.get("bache", 0)),
        "caida_n": int(nat_m.get("caida_estructural", 0)),
        "ant_med": _num(fin["meses_anticipacion"].median(), 1) if ant_col else None,
        "gan_med": _num(fin["meses_ganados_a_nivel"].median(), 1) if "meses_ganados_a_nivel" in fin.columns else None,
    }
    from src.playbook_acciones import CATALOGO
    playbook = [{k: a[k] for k in ("id", "titulo", "quien", "ejes", "cuando", "hace", "no_hace")}
                for a in CATALOGO]
    return {"kpis": kpis, "companies": companies, "groups": groups,
            "series": series, "explain": explain,
            "ejes": EJES, "alerts": alerts, "flows": flows, "playbook": playbook}


def build():
    """Copia la UI del Health Score a dashboard/ (lo que se publica en Vercel)."""
    from shutil import copy2, copytree

    src = Path(__file__).resolve().parent / "features" / "client_health_score" / "frontend"
    dest = cfg.DASHBOARD_PATH.parent
    if not (src / "index.html").is_file():
        raise SystemExit(f"Falta la UI en {src}")
    dest.mkdir(parents=True, exist_ok=True)
    copy2(src / "index.html", dest / "index.html")
    copy2(src / "embat.css", dest / "embat.css")
    if (src / "styles.css").is_file():
        copy2(src / "styles.css", dest / "styles.css")
    assets_src = src / "assets"
    assets_dest = dest / "assets"
    if assets_dest.exists():
        for old in assets_dest.iterdir():
            if old.is_file():
                old.unlink()
    copytree(assets_src, assets_dest, dirs_exist_ok=True)
    print(f"Dashboard: {dest / 'index.html'} (UI Health Score)")


TEMPLATE = r"""<!DOCTYPE html>
<html lang="es">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Embat · Health Score</title>
<style>
:root{
  --ink:#050b2c;--muted:#6b7288;--paper:#fff;--surface:#fff;--line:#eceef2;
  --forest:#050b2c;--forest2:#121a42;--lime:#3d6bff;--green:#1f8a6e;--greenSoft:#e5f4ef;
  --blue:#3d6bff;--blueSoft:#e8eeff;--red:#e07a4a;--redSoft:#fdeee6;
  --amber:#c47a1a;--amberSoft:#f6ead4;--radius:12px;
}
*{box-sizing:border-box}
body{margin:0;background:#f3f5f9;color:var(--ink);
  font:14px/1.5 Inter,Arial,Verdana,sans-serif}
button,input,select{font:inherit}button{cursor:pointer}
h1,h2,h3,p{margin-top:0}h1{font-size:28px;font-weight:560;letter-spacing:-.04em}
h2{font-size:18px;font-weight:560;letter-spacing:-.03em}h3{font-size:13px;font-weight:560}
.app{min-height:100vh}
.site-header{position:sticky;top:0;z-index:40;background:rgba(255,255,255,.88);backdrop-filter:saturate(160%) blur(18px);border-bottom:1px solid transparent;transition:box-shadow .25s,border-color .25s}
.site-header.scrolled{border-bottom-color:var(--line);box-shadow:0 10px 30px rgba(5,11,44,.07)}
.header-inner{max-width:1280px;margin:0 auto;height:72px;padding:0 28px;display:flex;align-items:center;gap:22px}
.brand{display:flex;align-items:center;gap:10px;color:var(--ink);text-decoration:none;flex-shrink:0}
.wordmark{height:20px;width:auto;display:block;color:var(--ink)}
.brand-tag{font-size:12px;color:var(--muted);border-left:1px solid var(--line);padding-left:10px;letter-spacing:.01em}
.menu{display:flex;align-items:center;gap:2px;flex:1;min-width:0}
.nav{border:0;background:transparent;color:#3a4158;padding:8px 13px;border-radius:999px;font-weight:560;display:inline-flex;align-items:center;gap:6px;transition:color .2s,background .2s}
.nav:hover{color:var(--ink);background:#f3f5f9}
.nav.active{color:var(--ink);background:#eef1f8}
.nav .count{background:var(--blueSoft);color:var(--blue);border-radius:999px;padding:1px 7px;font-size:10px;font-weight:700}
.header-actions{display:flex;align-items:center;gap:8px;margin-left:auto}
.main{max-width:1280px;margin:0 auto;padding:28px 28px 72px}
.page-head{margin-bottom:20px}
.page-head h1{font-size:32px;margin:0}
.eyebrow{margin:0 0 4px;color:var(--muted);font-size:12px;font-weight:500}
.view{display:none}.view.active{display:block;animation:rise .38s ease}
@keyframes rise{from{opacity:0;transform:translateY(12px)}to{opacity:1;transform:none}}
.card{background:#fff;border:1px solid var(--line);border-radius:16px;padding:20px;box-shadow:0 8px 24px rgba(5,11,44,.04);transition:transform .2s,box-shadow .2s}
.card:hover{transform:translateY(-2px);box-shadow:0 16px 36px rgba(5,11,44,.08)}
.table-card:hover,.list:hover{transform:none}
.btn,.select,.apikey{border:1px solid var(--line);border-radius:999px;background:#fff;color:var(--ink);padding:9px 16px;font-weight:560}
.apikey{min-width:168px;height:38px;border-radius:999px;padding:0 14px;font-size:12px}.key-status{font-size:11px;color:var(--muted);white-space:nowrap}
.btn.needs-key{opacity:.7}
.btn:hover{border-color:#c5cad6}.btn-primary{background:var(--ink);border-color:var(--ink);color:#fff}
.btn-lime{background:var(--blue);border-color:var(--blue);color:#fff}.btn-lime:hover{filter:brightness(1.06)}.btn.ghost{background:#fff}
.pill{display:inline-flex;align-items:center;padding:5px 10px;border-radius:999px;font-size:11px;font-weight:700}
.SALUDABLE,.pill-good{background:var(--greenSoft);color:var(--green)}
.ESTABLE,.pill-blue{background:var(--blueSoft);color:var(--blue)}
.EN-RIESGO,.pill-warn{background:var(--amberSoft);color:#7b4a0e}
.FRAGIL,.CRITICO,.pill-bad{background:var(--redSoft);color:#8b3024}
.NO-EVALUABLE,.pill-ghost{border:1px dashed #c5cad6;color:var(--muted);background:#f6f7f9}
.MEJORANDO,.up{color:var(--green);font-weight:750}.DETERIORANDO,.down{color:var(--red);font-weight:750}
.search-hero{background:linear-gradient(135deg,#050b2c 0%,#0c1440 58%,#1a2a6c 100%);color:#fff;border-radius:20px;padding:40px 40px 34px;margin-bottom:18px;position:relative;overflow:hidden}
.search-hero:before{content:"";position:absolute;width:340px;height:340px;right:-90px;top:-140px;border-radius:50%;background:radial-gradient(circle,rgba(61,107,255,.38),transparent 68%);animation:orb 9s ease-in-out infinite;pointer-events:none}
.search-hero:after{content:"";position:absolute;width:180px;height:180px;left:-50px;bottom:-70px;border-radius:50%;background:radial-gradient(circle,rgba(31,138,110,.22),transparent 70%);animation:orb 11s ease-in-out infinite reverse;pointer-events:none}
@keyframes orb{0%,100%{transform:translate(0,0)}50%{transform:translate(-16px,14px)}}
.search-hero h1{font-size:36px;font-weight:500;margin:0 0 10px}.search-hero p{color:rgba(255,255,255,.62);max-width:650px;line-height:1.5;margin-bottom:22px}
.searchbox{position:relative;z-index:2;display:flex;max-width:840px;background:#fff;border-radius:10px;padding:6px}
.searchbox input{flex:1;border:0;outline:0;min-width:0;color:var(--ink);padding:8px 10px}
.prompt-chips{display:flex;gap:7px;flex-wrap:wrap;margin-top:13px;position:relative;z-index:2}
.chip{border:1px solid rgba(255,255,255,.14);background:rgba(255,255,255,.06);color:rgba(255,255,255,.78);border-radius:999px;padding:7px 12px;font-size:11px;transition:background .2s,transform .2s,color .2s}
.chip:hover,.chip.on{background:rgba(255,255,255,.16);color:#fff;transform:translateY(-1px)}
.stats{display:grid;grid-template-columns:repeat(4,1fr);gap:12px;margin-bottom:16px}
.stat{min-height:118px;overflow:hidden;position:relative}.stat:before{content:"";position:absolute;left:0;top:0;bottom:0;width:4px;background:var(--stat,var(--blue))}
.stat-head{display:flex;justify-content:space-between;color:var(--muted);font-size:12px}
.stat-value{font-size:32px;font-weight:740;letter-spacing:-.05em;margin:14px 0 6px}.stat small{color:var(--muted)}
.workspace{display:grid;grid-template-columns:230px minmax(0,1fr);gap:14px}
.filters{padding:15px}.filter-head{display:flex;justify-content:space-between;align-items:center;margin-bottom:16px}
.filter-head h2{font-size:14px;margin:0}.linkbtn{border:0;background:none;color:var(--green);font-size:10px;font-weight:700;padding:0}
.filter{padding:13px 0;border-top:1px solid var(--line)}.filter label{display:block;font-weight:720;font-size:11px;margin-bottom:8px}
.filter select,.filter input[type=number]{width:100%;border:1px solid var(--line);border-radius:8px;padding:8px;background:#fff}
.range-labels{display:flex;justify-content:space-between;color:var(--muted);font-size:9px;margin-top:4px}
input[type=range]{width:100%;accent-color:var(--forest)}
.toggle-row{display:flex;justify-content:space-between;align-items:center;margin-top:9px;color:var(--muted);font-size:10px}
.toggle{width:30px;height:17px;border-radius:12px;background:#dce1da;padding:2px;border:0}
.toggle:after{content:"";display:block;width:13px;height:13px;border-radius:50%;background:#fff}
.toggle.on{background:var(--green)}.toggle.on:after{transform:translateX(13px)}
.results-head{display:flex;justify-content:space-between;gap:12px;align-items:center;margin-bottom:10px}
.results-head h2{margin:0}.results-head p{color:var(--muted);font-size:10px;margin:4px 0 0}
.table-card{padding:0;overflow:hidden}.table-wrap{overflow:auto}
table{width:100%;border-collapse:collapse}th{text-align:left;padding:11px 14px;color:var(--muted);font-size:10px;letter-spacing:.04em;text-transform:uppercase;font-weight:500;background:#f6f7f9;border-bottom:1px solid var(--line)}
td{padding:13px 14px;border-bottom:1px solid var(--line);font-size:13px}
tbody tr.click,tbody tr[data-id]{cursor:pointer}tbody tr:hover{background:#f7f8fb}
.company-cell{display:flex;gap:10px;align-items:center}
.logo,.profile-logo{width:34px;height:34px;border-radius:9px;background:var(--blueSoft);display:grid;place-items:center;color:var(--ink);font-weight:700}
.company-cell strong{display:block}.company-cell small{color:var(--muted);display:block;margin-top:3px}
.score{font-size:17px;font-weight:780}
.score-cell{min-width:72px}.score-cell b{display:block;font-size:18px;font-weight:750}
.score-cell .track,.mini-track{height:4px;background:#eef0f4;border-radius:99px;overflow:hidden;margin-top:6px}
.score-cell .track i,.mini-track i{display:block;height:100%;border-radius:99px}
.score-ring{width:120px;height:120px;display:block}
.qnav{display:grid;grid-template-columns:repeat(6,1fr);gap:8px;margin:4px 0 14px}
.qnav a{background:#fff;border:1px solid var(--line);border-radius:10px;padding:9px 10px;color:var(--ink);text-decoration:none}
.qnav a b{display:block;font-size:12px}.qnav a span{color:var(--muted);font-size:11px}
.qpack{display:grid;grid-template-columns:repeat(3,1fr);gap:8px;margin:10px 0}
.qcell{background:#f6f7f9;border:1px solid var(--line);border-radius:10px;padding:8px 10px;font-size:13px}
.qcell b{display:block;font-size:10px;color:var(--muted);letter-spacing:.06em;text-transform:uppercase;margin-bottom:3px}
.barseg{display:flex;height:16px;border-radius:8px;overflow:hidden;margin:8px 0}.barseg i{display:block;height:100%}
svg.lg,.ch{width:100%;height:320px;display:block}
.timeline{width:100%;height:240px;display:block}
.legend{display:flex;gap:14px;flex-wrap:wrap;font-size:12px;color:var(--muted);margin-top:6px}
.legend i{display:inline-block;width:9px;height:9px;border-radius:50%;margin-right:5px;vertical-align:middle}
.grid2{display:grid;grid-template-columns:1fr 1fr;gap:12px;align-items:start}
.layout{display:grid;grid-template-columns:280px 1fr;gap:14px}
.list{background:#fff;border:1px solid var(--line);border-radius:var(--radius);overflow:hidden;max-height:78vh;display:flex;flex-direction:column}
.list .rows{overflow:auto;flex:1}
.list input{width:100%;border:0;border-bottom:1px solid var(--line);padding:10px 12px}
.chips{display:flex;gap:6px;padding:8px 10px;flex-wrap:wrap;border-bottom:1px solid var(--line)}
.chips button{background:#f6f7f9;border:1px solid var(--line);color:var(--muted);border-radius:999px;padding:4px 10px;font-size:11px}
.chips button.on{color:var(--ink);border-color:var(--ink);background:var(--blueSoft)}
.row{padding:9px 12px;border-bottom:1px solid var(--line);cursor:pointer;display:flex;justify-content:space-between;gap:8px}
.row:hover,.row.on{background:#f7f8fb}.row small{color:var(--muted);display:block}
.profile-hero{margin-bottom:14px}.profile-title{display:flex;justify-content:space-between;gap:15px;flex-wrap:wrap}
.profile-id{display:flex;gap:13px}.profile-logo{width:52px;height:52px;border-radius:13px;font-size:16px}
.profile-actions{display:flex;gap:7px;align-items:flex-start;flex-wrap:wrap}
.health-strip{display:grid;grid-template-columns:140px 1fr;gap:28px;align-items:center;margin-top:22px}
.big-score{font-size:58px;line-height:.9;font-weight:790;letter-spacing:-.07em}
.score-caption{color:var(--muted);margin-top:9px}.change{font-weight:700;margin-top:10px;font-size:14px}
.profile-summary h2{font-size:26px;margin:12px 0 0;font-weight:560;letter-spacing:-.03em}.profile-summary p{display:none}
.confidence{font-size:10px;color:var(--muted);margin-top:12px}.confidence strong{color:var(--ink)}
.signals{display:grid;grid-template-columns:repeat(3,1fr);gap:12px;margin-bottom:16px}
.signal{padding:20px 22px;min-height:128px}.signal-top{color:var(--muted);font-size:13px;font-weight:600}
.signal-score{font-size:40px;font-weight:740;letter-spacing:-.05em;margin:12px 0 16px}.signal small{display:none}
.signal .track{height:6px;background:rgba(5,11,44,.06);border-radius:99px;overflow:hidden}.signal .track i{display:block;height:100%;border-radius:99px}
.card-head{display:flex;justify-content:space-between;align-items:flex-start;gap:10px;margin-bottom:14px}
.card-head h2{margin-bottom:4px}.card-head p{margin:0;color:var(--muted);font-size:10px}
.brief{margin-top:16px;padding:22px;background:#fff;border:1px solid var(--line);border-radius:16px}
.brief h2{font-size:20px;margin-bottom:10px}.note{color:var(--muted);font-size:13px}
.brief .lede{color:var(--ink);font-size:16px;line-height:1.5;margin:0 0 10px}
.brief-tes{color:var(--muted);font-size:14px;line-height:1.5;margin:0 0 4px}
.acciones{display:grid;grid-template-columns:1fr 1fr;gap:12px;margin-top:16px}
.accion{background:#fff;border:1px solid var(--line);border-radius:12px;padding:16px}
.accion h3{margin:0 0 6px;font-size:15px}.accion p{margin:0;color:var(--muted);font-size:13px;line-height:1.45}
.accion .meta{display:flex;gap:6px;flex-wrap:wrap;margin:8px 0}
.quien-empresa{background:var(--greenSoft);color:var(--green)}
.quien-embat{background:var(--blueSoft);color:var(--blue)}
.quien-partner{background:var(--amberSoft);color:#7b4a0e}
.tools-used{display:flex;gap:6px;flex-wrap:wrap;margin-top:8px}
.tools-used span{border:1px solid var(--line);border-radius:999px;padding:3px 7px;font-size:9px;color:var(--muted)}
.teoria{margin-top:10px;padding:10px 12px;background:#fff;border-radius:10px;border:1px solid var(--line);font-size:11px;color:var(--muted)}
.teoria b{color:var(--ink);display:block;margin-bottom:4px}
.scroll{max-height:62vh;overflow:auto}.kpis{display:grid;grid-template-columns:repeat(auto-fit,minmax(140px,1fr));gap:10px}
.kpi{font-size:26px;font-weight:750}.sub{color:var(--muted);font-size:12px}
.disclosure{margin-top:15px;padding:10px 12px;border:1px solid var(--line);background:#f6f7f9;border-radius:10px;color:var(--muted);font-size:9px;line-height:1.5}
.steps{display:grid;grid-template-columns:repeat(3,1fr);gap:12px;margin:16px 0 4px}
.step{padding:18px 20px}.step b{display:block;font-size:12px;color:var(--blue);margin-bottom:8px}
.step p{margin:0;color:var(--muted);font-size:14px;line-height:1.45}
.metric-grid{display:grid;grid-template-columns:1fr 1fr;gap:14px}
.metric{padding:22px 24px;min-height:auto}
.metric-top{display:flex;justify-content:space-between;align-items:flex-start;gap:12px;margin-bottom:10px}
.metric h3{margin:0;font-size:18px}.metric-w{font-size:28px;font-weight:740;letter-spacing:-.04em}
.metric .track{height:6px;background:#eef0f4;border-radius:99px;overflow:hidden;margin:0 0 14px}
.metric p{margin:0 0 8px;color:var(--muted);font-size:14px;line-height:1.45}
.metric p strong{color:var(--ink);font-weight:650}
.hl{display:flex;gap:8px;flex-wrap:wrap;margin-top:12px}
.hl span{border-radius:999px;padding:5px 10px;font-size:12px;font-weight:600}
.scale{display:flex;height:18px;border-radius:99px;overflow:hidden;margin:14px 0 10px}
.scale i{display:block;height:100%}
.scale-leg{display:flex;justify-content:space-between;gap:8px;flex-wrap:wrap;font-size:12px;color:var(--muted)}
.trio{display:grid;grid-template-columns:repeat(3,1fr);gap:12px}
.demo-say{background:var(--ink);color:#fff;padding:26px 28px;border-radius:16px;margin-bottom:14px}
.demo-say h2{color:#fff;margin-bottom:8px}.demo-say p{margin:0;color:rgba(255,255,255,.78);font-size:16px;line-height:1.5;max-width:820px}
.recipe{display:grid;grid-template-columns:1fr auto 1fr auto 1fr;gap:10px;align-items:stretch;margin-top:16px}
.recipe .card{margin:0}.recipe-op{display:grid;place-items:center;font-size:22px;font-weight:700;color:var(--blue)}
.pipe{display:flex;flex-wrap:wrap;gap:8px;margin:12px 0 0}
.pipe span{background:#f3f5f9;border:1px solid var(--line);border-radius:999px;padding:6px 12px;font-size:13px;font-weight:600}
.ai-button{position:fixed;right:24px;bottom:24px;z-index:80;height:48px;padding:0 20px;border:0;border-radius:999px;background:var(--blue);color:#fff;font-weight:650;display:inline-flex;align-items:center;gap:8px;cursor:pointer;box-shadow:0 12px 28px rgba(61,107,255,.32);pointer-events:auto}
.ai-button span{color:#fff;margin:0}
.ai-panel{position:fixed;right:24px;top:84px;width:min(420px,calc(100vw - 30px));height:min(560px,calc(100vh - 110px));background:#fff;border:1px solid var(--line);border-radius:16px;z-index:70;display:none;flex-direction:column;overflow:hidden;box-shadow:0 18px 50px rgba(5,11,44,.16)}
.ai-panel.open{display:flex}.ai-head{padding:14px 15px;background:var(--ink);color:#fff;display:flex;justify-content:space-between}
.ai-head small{color:rgba(255,255,255,.55);display:block;margin-top:3px}
.ai-close{border:0;background:rgba(255,255,255,.1);color:#fff;border-radius:50%;width:27px;height:27px}
.messages{padding:15px;overflow:auto;flex:1;background:#f7f8fb}
.message{max-width:92%;padding:10px 11px;border-radius:11px;margin-bottom:10px;line-height:1.5;font-size:11px}
.assistant{background:#fff;border:1px solid var(--line)}.user{background:var(--blueSoft);margin-left:auto}
.suggestions{display:flex;gap:5px;flex-wrap:wrap;margin-top:9px}
.suggestions button{border:1px solid var(--line);background:#fff;border-radius:999px;padding:5px 7px;font-size:9px}
.ai-input{display:flex;padding:10px;border-top:1px solid var(--line);gap:7px}
.ai-input input{flex:1;border:1px solid var(--line);border-radius:8px;padding:8px;min-width:0}
.ai-input button{border:0;border-radius:999px;background:var(--blue);color:#fff;padding:8px 14px}
.toast{position:fixed;left:50%;bottom:28px;transform:translate(-50%,12px);background:var(--ink);color:#fff;padding:12px 16px;border-radius:10px;opacity:0;visibility:hidden;pointer-events:none;transition:.2s;z-index:90}
.toast.show{opacity:1;visibility:visible;transform:translate(-50%,0)}
svg circle[data-id]{cursor:pointer}
@media(max-width:980px){.brand-tag,.apikey,.key-status{display:none}.header-inner{padding:0 16px;gap:10px}.menu{overflow:auto}}
@media(max-width:820px){.workspace,.layout,.profile-grid,.grid2,.qnav,.qpack,.signals,.stats{grid-template-columns:1fr 1fr}.filters{display:none}}
@media(max-width:700px){.main{padding:16px 12px}.header-inner{height:64px}.stats,.signals,.health-strip,.acciones,.metric-grid,.steps,.trio,.recipe{grid-template-columns:1fr}}
</style>
</head>
<body>
<div class="app">
<header class="site-header" id="siteHeader">
  <div class="header-inner">
    <a class="brand" href="#cartera" id="brandHome">
      <svg class="wordmark" xmlns="http://www.w3.org/2000/svg" width="93" height="20" viewBox="0 0 93 20" fill="none" aria-label="Embat"><path fill="currentColor" fill-rule="evenodd" d="m0 3.82 4.49 6.178L11.754.001v19.996l7.264-9.999L11.754 0zm0 12.36L11.755 20 4.49 10zM29.866 2.352h10.687v2.337h-7.946v3.865h7.204v2.337h-7.204v4.396h8.027v2.337H29.866zm29.77 7.935v7.335h-2.68v-6.67c0-1.39-.745-2.298-1.994-2.298-1.633 0-2.62 1.492-2.62 4.07v4.897h-2.68v-6.67c0-1.39-.726-2.297-1.996-2.297-1.612 0-2.599 1.471-2.599 4.07v4.897h-2.68V6.458h2.68V7.97c.524-.886 1.814-1.672 3.366-1.672s2.861.766 3.426 2.076c.967-1.41 2.418-2.076 3.869-2.076 2.277 0 3.909 1.592 3.909 3.99Zm4.979 5.904v1.429h-2.68V3.275l2.68-.884v5.495c.685-.967 2.035-1.591 3.526-1.591 3.164 0 5.34 2.236 5.34 5.743s-2.176 5.744-5.38 5.744c-1.471 0-2.8-.624-3.486-1.59Zm6.167-4.154c0 2.056-1.27 3.446-3.084 3.446s-3.083-1.391-3.083-3.447 1.27-3.465 3.083-3.465 3.084 1.41 3.084 3.466m4.127 2.524c0-2.075 1.45-3.324 4.736-3.667l2.499-.282v-.221c0-1.27-.927-2.015-2.277-2.015s-2.237.725-2.378 1.974h-2.58c.283-2.337 2.278-4.05 4.958-4.05 2.881 0 4.937 1.572 4.937 4.393v6.932h-2.66v-1.471c-.523.988-1.854 1.633-3.365 1.633-2.399 0-3.87-1.27-3.87-3.225Zm4.333 1.17c1.713 0 2.902-1.17 2.902-3.144l-2.459.261c-1.431.161-2.096.746-2.096 1.612 0 .745.666 1.27 1.653 1.27Zm8.364-7.091v5.46c0 2.378 1.612 3.668 3.728 3.668.564 0 1.028-.102 1.491-.263V15.25c-.342.12-.785.221-1.128.221-.846 0-1.41-.564-1.41-1.612V8.64h2.398V6.463h-2.399V3.084l-2.68.884v2.495h-1.612V8.64z" clip-rule="evenodd"/></svg>
      <span class="brand-tag">Health Score</span>
    </a>
    <nav class="menu" aria-label="Principal">
      <button class="nav active" data-view="radar">Cartera</button>
      <button class="nav" data-view="empresa">Ficha</button>
      <button class="nav" data-view="monitor">Avisos <span class="count" id="nav-avisos">—</span></button>
      <button class="nav" data-view="grupos">Grupos</button>
      <button class="nav" data-view="metodo">Métricas</button>
    </nav>
    <div class="header-actions">
      <input id="llm-key" class="apikey" type="password" placeholder="API key Gemini" autocomplete="off">
      <span class="key-status" id="llm-key-status">Sin key</span>
      <button type="button" class="btn btn-lime" id="btn-tellme">✦ TellMe</button>
    </div>
  </div>
</header>
<main class="main">
  <div class="page-head"><p class="eyebrow">Treasury</p><h1 id="pageTitle">Cartera · seis preguntas</h1></div>
  <section id="radar" class="view active"></section>
  <section id="empresa" class="view"></section>
  <section id="grupos" class="view"></section>
  <section id="monitor" class="view"></section>
  <section id="metodo" class="view"></section>
</main>
</div>
<aside class="ai-panel" id="aiPanel">
  <div class="ai-head"><div><strong>Agente con herramientas</strong><small>Ficha · RAG de teoría · catálogo de acciones. No recalcula.</small></div><button class="ai-close" id="aiClose">×</button></div>
  <div class="messages" id="messages">
    <div class="message assistant">Agente de Embat. Lee el health score de esta ficha, cita teoría del motor y propone acciones del catálogo (vuestras, Embat o un partner). Te lo cuenta en los mismos bloques de la ficha.
      <div class="suggestions">
        <button data-ai="pyme">Plan de acciones</button>
        <button data-ai="llm">Agente + LLM</button>
        <button data-ai="fondo">Qué vería el fondo</button>
      </div>
    </div>
  </div>
  <div class="ai-input"><input id="aiInput" placeholder="Usa los botones: no inventa productos" disabled><button id="aiSend" type="button">Abrir ficha</button></div>
</aside>
<div class="toast" id="toast"></div>
<script>
const D = __DATA__;
const COLOR = {SALUDABLE:'#1f8a6e',ESTABLE:'#3d6bff','EN RIESGO':'#c47a1a','FRAGIL':'#e07a4a','FRÁGIL':'#e07a4a','CRITICO':'#e07a4a','CRÍTICO':'#e07a4a'};
const slug = c => (c||'').normalize('NFD').replace(/[\u0300-\u036f]/g,'').replace(/\s+/g,'-');
const pill = c => `<span class="pill ${slug(c)}">${c||''}</span>`;
function tone(s){
  if(s==null) return '#9aa1b0';
  if(s>=68) return '#1f8a6e';
  if(s>=52) return '#3d6bff';
  if(s>=42) return '#c47a1a';
  return '#e07a4a';
}
function scoreRing(s){
  const v=s==null?0:Math.max(0,Math.min(100,Number(s)));
  const col=tone(s);
  const r=46, c=2*Math.PI*r, off=c*(1-v/100);
  const label=s==null?'—':Math.round(Number(s));
  return `<svg class="score-ring" viewBox="0 0 120 120" aria-label="Health score ${label}">
    <circle cx="60" cy="60" r="${r}" fill="none" stroke="#edf0f5" stroke-width="10"/>
    <circle cx="60" cy="60" r="${r}" fill="none" stroke="${col}" stroke-width="10"
      stroke-dasharray="${c.toFixed(2)}" stroke-dashoffset="${off.toFixed(2)}" stroke-linecap="round"
      transform="rotate(-90 60 60)"/>
    <text x="60" y="68" text-anchor="middle" font-size="28" font-weight="750" fill="${col}">${label}</text>
  </svg>`;
}
function scoreBar(s){
  const col=tone(s);
  const w=s==null?0:Math.max(0,Math.min(100,Number(s)));
  return `<div class="score-cell"><b style="color:${col}">${s==null?'—':Number(s).toFixed(0)}</b><div class="track"><i style="width:${w}%;background:${col}"></i></div></div>`;
}
function richer(llm, fallback){
  const a=(llm||'').trim(), b=(fallback||'').trim();
  if(a.length>=60) return a;
  if(a && b && a!==b) return (a.replace(/[.]+$/,'')+'. '+b).trim();
  return a||b;
}
const TITLES = {radar:'Cartera · seis preguntas', empresa:'Ficha de empresa', grupos:'Grupos', monitor:'Avisos', metodo:'Métricas del Health Score'};
let CURRENT = D.kpis.featured || (D.companies[0]||{}).id;
function show(tab){
  document.querySelectorAll('.view').forEach(s => s.classList.toggle('active', s.id===tab));
  document.querySelectorAll('.nav[data-view]').forEach(b => b.classList.toggle('active', b.dataset.view===tab));
  const t=document.getElementById('pageTitle'); if(t) t.textContent=TITLES[tab]||'Health Score';
  const ph=document.querySelector('.page-head'); if(ph) ph.hidden = tab==='radar';
  window.scrollTo({top:0,behavior:'smooth'});
}
function toast(txt){
  const el=document.getElementById('toast'); if(!el) return;
  el.textContent=txt; el.classList.add('show');
  clearTimeout(window._tt); window._tt=setTimeout(()=>el.classList.remove('show'),2200);
}
document.querySelectorAll('.nav[data-view]').forEach(b=>b.onclick=()=>show(b.dataset.view));
function logo(id){ return (id||'').replace('COMP_','').slice(-2); }

function chart(id){
  const ser=D.series[id]; if(!ser) return '';
  const w=720,h=240,pl=48,pr=18,pt=18,pb=32;
  const fc=ser.fc;
  const pts=ser.s.map((v,i)=>({x:i,y:v,g:ser.g[i],m:ser.m[i]})).filter(d=>d.y!=null);
  if(!pts.length) return '<p class="note">Sin meses puntuados.</p>';
  const xs=pts.map(d=>d.x), ys=pts.map(d=>d.y);
  const xmin=Math.min(...xs), xmax=Math.max(...xs)+(fc?3:0);
  const extra=fc?[...fc.y,...fc.lo,...fc.hi]:[];
  let ymin=Math.min(...ys,...extra), ymax=Math.max(...ys,...extra);
  ymin=Math.max(0, Math.floor((ymin-8)/10)*10);
  ymax=Math.min(100, Math.ceil((ymax+8)/10)*10);
  if(ymax-ymin<20){ ymin=Math.max(0,ymin-10); ymax=Math.min(100,ymax+10); }
  const X=x=>pl+(x-xmin)/(xmax-xmin||1)*(w-pl-pr);
  const Y=y=>h-pb-(y-ymin)/(ymax-ymin||1)*(h-pt-pb);
  const d=pts.map((pt,i)=>(i?'L':'M')+X(pt.x)+','+Y(pt.y)).join(' ');
  const yTicks=[];
  for(let v=ymin; v<=ymax; v+=10) yTicks.push(v);
  if(ymin<55 && ymax>55 && !yTicks.includes(55)) yTicks.push(55);
  yTicks.sort((a,b)=>a-b);
  const grid=yTicks.map(v=>`<line x1="${pl}" x2="${w-pr}" y1="${Y(v)}" y2="${Y(v)}" stroke="${v===55?'#acb6ae':'#e5e9e3'}" stroke-dasharray="${v===55?'4 4':'none'}"/>
    <text x="${pl-6}" y="${Y(v)+4}" fill="#687571" font-size="10" text-anchor="end">${v}</text>`).join('');
  let ray='';
  if(fc && pts.length){
    const last=pts[pts.length-1];
    const xs2=[last.x, last.x+1, last.x+2, last.x+3];
    const ys2=[last.y, ...fc.y];
    const los=[last.y, ...fc.lo];
    const his=[last.y, ...fc.hi];
    const band=xs2.map((x,i)=>X(x)+','+Y(his[i])).join(' ')+' '+[...xs2].reverse().map((x,i)=>X(x)+','+Y(los[los.length-1-i])).join(' ');
    const col=fc.b>0.15?'#1f8a6e':fc.b<-0.15?'#e07a4a':'#6b7288';
    const mid=ys2.map((y,i)=>(i?'L':'M')+X(xs2[i])+','+Y(y)).join(' ');
    ray=`<polygon points="${band}" fill="${col}" fill-opacity=".12" stroke="none"/>
      <path d="${mid}" fill="none" stroke="${col}" stroke-width="2" stroke-dasharray="6 4"/>
      <text x="${X(xs2[xs2.length-1])-2}" y="${Y(ys2[ys2.length-1])-8}" fill="${col}" font-size="10" text-anchor="end">+3m</text>`;
  }
  const giros=pts.filter(pt=>pt.g);
  let mark=null;
  if(giros.length){
    mark=giros[0];
    for(let i=1;i<giros.length;i++){
      if(giros[i].x-giros[i-1].x>2) mark=giros[i];
    }
  }
  const dots=mark?`<circle cx="${X(mark.x)}" cy="${Y(mark.y)}" r="5" fill="#e07a4a"/>
    <text x="${X(mark.x)+8}" y="${Y(mark.y)-8}" fill="#e07a4a" font-size="10">giro</text>`:'';
  const ticks=pts.filter((_,i)=>i===0||i===pts.length-1||i===Math.floor(pts.length/2))
    .map(pt=>`<text x="${X(pt.x)}" y="${h-10}" fill="#687571" font-size="10">${pt.m}</text>`).join('');
  const last=pts[pts.length-1];
  const area=pts.length?`M${X(pts[0].x)},${Y(pts[0].y)} `+pts.slice(1).map(pt=>`L${X(pt.x)},${Y(pt.y)}`).join(' ')+` L${X(last.x)},${Y(ymin)} L${X(pts[0].x)},${Y(ymin)} Z`:'';
  return `<svg class="timeline" viewBox="0 0 ${w} ${h}">
    ${grid}
    ${(ymin<55 && ymax>55)?`<text x="${w-pr}" y="${Y(55)-5}" fill="#687571" font-size="10" text-anchor="end">55</text>`:''}
    <path d="${area}" fill="rgba(61,107,255,.08)"/>
    <path d="${d}" fill="none" stroke="#3d6bff" stroke-width="3" stroke-linecap="round"/>
    ${ray}${dots}${ticks}
  </svg>
  <div class="legend"><span><i style="background:#3d6bff"></i>score</span>${mark?'<span><i style="background:#e07a4a"></i>giro</span>':''}${fc?'<span><i style="background:#6b7288"></i>+3m</span>':''}</div>`;
}

function qpack(r){
  const ser=D.series[r.id]||{};
  const fc=ser.fc;
  const nat=r.giro?(r.nat==='caida_estructural'?'caída estructural':'bache'):'sin giro';
  const caida=r.caida==null?'':(' · cayó '+Math.abs(r.caida)+' pts entonces');
  const tuerce=r.giro&&r.s>=55?'sí: aún parece sana':r.giro?'giro, ya no parece sana':'sin giro';
  const cuando=r.ant!=null?('visto '+r.ant+' meses antes'):(r.pa?('primera alerta '+r.pa):'aún no hay evento de nivel');
  const proy=fc?`proy. 3m ${fc.y[2]} [${fc.lo[2]}–${fc.hi[2]}]`:(r.dir==null?'—':((r.dir>0?'+':'')+r.dir+' pts en 6m'));
  return `<div class="qpack">
    <div class="qcell"><b>1. Quién está sano</b>${pill(r.c)} · ${r.s??'—'}</div>
    <div class="qcell"><b>2. Quién mejora</b><span class="${r.t}">${r.t||'—'}</span> · ${proy}</div>
    <div class="qcell"><b>3. Quién se tuerce</b>${tuerce}${r.sig!=null?' · '+r.sig+'σ':''}</div>
    <div class="qcell"><b>4. Bache o caída</b>${nat}${caida}</div>
    <div class="qcell"><b>5. Por qué ha cambiado</b>${(r.mot||'sin cambio el último mes').slice(0,110)}</div>
    <div class="qcell"><b>6. Cuándo se vio</b>${cuando}${r.gan!=null?' · +'+r.gan+' m vs nivel':''}</div>
  </div>`;
}

function barsClase(){
  const cl=D.kpis.clase||{}, n=D.kpis.n||1;
  const order=['SALUDABLE','ESTABLE','EN RIESGO','FRÁGIL','CRÍTICO','NO EVALUABLE'];
  const cols={'SALUDABLE':'#1f8a6e','ESTABLE':'#3d6bff','EN RIESGO':'#c47a1a','FRÁGIL':'#e07a4a','FRAGIL':'#e07a4a','CRÍTICO':'#e07a4a','CRITICO':'#e07a4a','NO EVALUABLE':'#9aa1b0'};
  const keys=order.filter(k=>cl[k]!=null).concat(Object.keys(cl).filter(k=>!order.includes(k)));
  return `<div class="barseg">${keys.map(k=>`<i style="width:${100*cl[k]/n}%;background:${cols[k]||'#8b9bb4'}" title="${k} ${cl[k]}"></i>`).join('')}</div>
    <div class="legend">${keys.map(k=>`<span><i style="background:${cols[k]||'#888'}"></i>${k} ${cl[k]}</span>`).join('')}</div>`;
}

function scatter(){
  const w=700,h=340,pl=48,pr=18,pt=22,pb=32;
  const pts=D.companies.filter(x=>x.s!=null && x.dir!=null);
  const xs=pts.map(p=>p.s), ys=pts.map(p=>p.dir);
  const xmin=Math.max(0, Math.min(...xs)-4);
  const xmax=Math.min(100, Math.max(...xs)+4);
  const ymin=Math.min(...ys)-2, ymax=Math.max(...ys)+2;
  const X=x=>pl+(x-xmin)/(xmax-xmin||1)*(w-pl-pr);
  const Y=y=>h-pb-(y-ymin)/(ymax-ymin||1)*(h-pt-pb);
  const dots=pts.map(c=>{
    const col=c.giro&&c.s>=55?'#e07a4a':c.t==='MEJORANDO'?'#1f8a6e':c.t==='DETERIORANDO'?'#c47a1a':'#3d6bff';
    return `<circle data-id="${c.id}" cx="${X(c.s)}" cy="${Y(c.dir)}" r="${c.giro&&c.s>=55?4.2:2.6}" fill="${col}" fill-opacity=".85"><title>${c.id} · ${c.s} · ${c.t} · ${c.dir} pts / 6m</title></circle>`;
  }).join('');
  return `<svg class="lg" viewBox="0 0 ${w} ${h}">
    <line x1="${X(55)}" x2="${X(55)}" y1="${pt}" y2="${h-pb}" stroke="#dde2dc" stroke-dasharray="4 4"/>
    <line x1="${pl}" x2="${w-pr}" y1="${Y(0)}" y2="${Y(0)}" stroke="#dde2dc"/>
    <text x="${X(55)+6}" y="${pt+12}" fill="#687571" font-size="10">55</text>
    <text x="${w-pr}" y="${h-10}" fill="#687571" font-size="10" text-anchor="end">score →</text>
    <text x="8" y="${pt+8}" fill="#687571" font-size="10">mejora</text>
    <text x="8" y="${h-pb+4}" fill="#687571" font-size="10">empeora</text>
    ${dots}</svg>
    <div class="legend"><span><i style="background:#1f8a6e"></i>Mejorando</span><span><i style="background:#c47a1a"></i>Deteriorando</span><span><i style="background:#3d6bff"></i>Estable</span><span><i style="background:#e07a4a"></i>Giro y sigue sana</span></div>`;
}

function flowsChart(){
  const F=D.flows; if(!F||!F.m) return '';
  const w=700,h=340,p=32, n=F.m.length;
  const vals=[...F.MEJORANDO,...F.DETERIORANDO,...F.ESTABLE].filter(v=>v!=null);
  const ymin=Math.min(30,...vals), ymax=Math.max(80,...vals);
  const X=i=>p+i/Math.max(1,n-1)*(w-2*p);
  const Y=y=>h-p-(y-ymin)/(ymax-ymin||1)*(h-2*p);
  const path=(arr,col)=>{
    let d='', on=false;
    arr.forEach((v,i)=>{ if(v==null) return; d+=(on?'L':'M')+X(i)+','+Y(v); on=true; });
    return d?`<path d="${d}" fill="none" stroke="${col}" stroke-width="2"/>`:'';
  };
  const ticks=[0,Math.floor((n-1)/2),n-1].map(i=>`<text x="${X(i)}" y="${h-6}" fill="#687571" font-size="10">${(F.m[i]||'').slice(0,7)}</text>`).join('');
  return `<svg class="lg" viewBox="0 0 ${w} ${h}">
    ${path(F.MEJORANDO,'#1f8a6e')}${path(F.ESTABLE,'#3d6bff')}${path(F.DETERIORANDO,'#e07a4a')}
    ${ticks}</svg>
    <div class="legend"><span><i style="background:#1f8a6e"></i>Mejorando (${D.kpis.mej})</span><span><i style="background:#3d6bff"></i>Estable (${D.kpis.est})</span><span><i style="background:#e07a4a"></i>Deteriorando (${D.kpis.det})</span></div>`;
}

const ACCION={
  deuda_comercial:'Revisad la cola de pagos a proveedores: dejar de pagar es una decisión vuestra, casi siempre porque no hay caja.',
  liquidez:'El flujo operativo del trimestre no aguanta el tamaño. Adelantar cobros o recortar salidas que no sean de la actividad.',
  colchon:'El colchón es fino o muy volátil. Priorizad tener un mes de gasto en cuenta corriente antes de nueva deuda.',
  trayectoria:'El problema es la dirección, no un mes suelto. Un ingreso puntual no cambia la pendiente.',
  eficiencia:'Entráis menos de lo que sale. El burn ya está topado: un mes loco no explica una quema sostenida.',
  cobro_clientes:'Os pagan tarde o poco. Cobrar no se arregla pagando vosotros antes.'
};
const BRIEF_ON={};
function esc(s){ return String(s??'').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;'); }
function bloquesPyme(r){
  const e=D.explain[r.id]||{f:{}};
  if(r.s==null || r.c==='NO EVALUABLE')
    return {situacion:'No hay evidencia suficiente. Faltan meses o los ejes están apagados.', tesoreria:'', limites:'Sin ficha no hay plan ni oferta de inversión.', workspace:'Perfil no publicable: sin score.'};
  const sit=[];
  sit.push(`Estáis en ${r.c} (${Math.round(r.s)}/100), tendencia ${r.t}.`);
  if(r.conf==='baja') sit.push('Confianza baja: pocos meses o facturas huecas.');
  if(r.giro && r.nat==='caida_estructural') sit.push('Giro que se parece a una caída que se sostiene (a 6 meses suele seguir bajando). '+(e.giro||''));
  else if(r.giro && r.nat==='bache') sit.push('Giro que se parece a un bache (más de la mitad recupera a 6 meses). '+(e.giro||''));
  const mot=r.mot||e.mot||'';
  if(mot) sit.push((r.d!=null?`Último mes (${r.d>0?'+':''}${r.d} pts): `:'Último mes: ')+mot+'.');
  const facs=(D.ejes||[]).map(([k,nom])=>({k,nom,s:(e.f[k]||{}).s,r:(e.f[k]||{}).r})).filter(x=>x.s!=null);
  const weak=facs.filter(x=>x.s<55).sort((a,b)=>a.s-b.s).slice(0,3);
  const strong=facs.filter(x=>x.s>=70).slice(0,2);
  const tes=[];
  if(weak.length){
    tes.push('Hoy tira hacia abajo: '+weak.map(x=>x.nom).join(', ')+'.');
    weak.forEach(x=>{ if(x.r) tes.push(String(x.r).replace(/\.+$/,'')+'.'); if(ACCION[x.k]) tes.push(ACCION[x.k]); });
  }
  else if(strong.length) tes.push('Lo que aguanta: '+strong.map(x=>x.nom).join(', ')+'.');
  else tes.push('No hay un eje flojo claro este mes.');
  const giro=r.giro?(r.nat==='bache'?'bache':'caída que se sostiene'):'';
  const razones=weak.filter(x=>x.r).slice(0,2).map(x=>x.r);
  const workspace=`${r.c} · ${Math.round(r.s)}/100 · ${r.t}`+(giro?' · giro: '+giro:'')+(razones.length?'. '+razones.join(' '):'.')+' Sin extracto ni nombres de clientes.';
  return {
    situacion:sit.join(' '),
    tesoreria:tes.join(' '),
    limites:`Esto no es valoración ni promesa de inversión. No maquilléis el número. Confianza ${r.conf}.`,
    workspace,
    acciones:matchAcciones(r, weak),
    impacto:[],
    teoria:[],
    herramientas:['playbook local']
  };
}
function matchAcciones(r, weak){
  const deb=new Set((weak||[]).map(x=>x.k));
  const out=[];
  (D.playbook||[]).forEach(a=>{
    const c=a.cuando||'siempre';
    if(c==='bache' && !(r.giro && r.nat==='bache')) return;
    if(c==='estructural' && !(r.giro && r.nat==='caida_estructural')) return;
    if(c==='cobro_flojo' && !deb.has('cobro_clientes')) return;
    if(c==='confianza_baja' && r.conf!=='baja') return;
    if(c==='trayectoria_floja' && !deb.has('trayectoria')) return;
    if(c==='deteriorando' && r.t!=='DETERIORANDO' && !deb.has('trayectoria')) return;
    const hit=(a.ejes||[]).filter(e=>deb.has(e));
    if(deb.size && !hit.length && !['estructural','confianza_baja','deteriorando','trayectoria_floja'].includes(c)) return;
    out.push(Object.assign({ejes_objetivo:hit.length?hit:a.ejes.slice(0,1)}, a));
  });
  return out.slice(0,4);
}
function htmlAcciones(b){
  const acts=b.acciones||[];
  if(!acts.length) return '';
  const imp={};
  (b.impacto||[]).forEach(i=>{ imp[i.id]=i; });
  return `<div class="acciones">${acts.map(a=>{
    const i=imp[a.id]||{};
    const eje=(a.ejes_objetivo||a.ejes||[])[0]||'';
    return `<article class="accion">
      <h3>${esc(a.titulo)}</h3>
      <div class="meta">
        <span class="pill quien-${esc(a.quien)}">${esc(a.quien)}</span>
        ${eje?`<span class="pill pill-ghost">${esc(eje)}</span>`:''}
      </div>
      <p>${esc(a.hace)}</p>
    </article>`;
  }).join('')}</div>`;
}
function htmlBrief(b){
  const ws=b.vista==='fondo';
  if(ws){
    return `<div class="brief" id="brief-out">
      <h2>Vista fondo</h2>
      <p class="lede">${esc(b.workspace||b.situacion||'')}</p>
      <button type="button" class="btn ghost" id="btn-copy-brief">Copiar</button>
    </div>`;
  }
  return `<div class="brief" id="brief-out">
    <h2>Qué hacer</h2>
    <p class="lede">${esc(b.situacion||'')}</p>
    ${b.tesoreria?`<p class="brief-tes">${esc(b.tesoreria)}</p>`:''}
    ${htmlAcciones(b)}
    ${b.aviso?`<p class="note">${esc(b.aviso)}</p>`:''}
    <button type="button" class="btn ghost" id="btn-copy-brief">Copiar</button>
  </div>`;
}
function textoBrief(b){
  if(b.vista==='fondo') return b.workspace||'';
  const acts=(b.acciones||[]).map(a=>`- [${a.quien}] ${a.titulo}: ${a.hace}`).join('\n');
  return ['Qué está pasando: '+(b.situacion||''),'Tesorería: '+(b.tesoreria||''),'Límites: '+(b.limites||''), acts?'Acciones:\n'+acts:''].filter(Boolean).join('\n');
}
function pintarBrief(r, b){
  const slot=document.getElementById('brief-slot');
  if(!slot) return;
  BRIEF_ON[r.id]=b;
  slot.innerHTML=htmlBrief(b);
  slot.scrollIntoView({behavior:'smooth',block:'nearest'});
  document.getElementById('btn-copy-brief')?.addEventListener('click',()=>{
    navigator.clipboard?.writeText(textoBrief(b)); toast('Brief copiado');
  });
}
function claveUI(){
  const el=document.getElementById('llm-key');
  if(!el) return '';
  let v=(el.value||'').trim();
  if(/^bearer\s+/i.test(v)) v=v.replace(/^bearer\s+/i,'').trim();
  if(v && v!==el.value) el.value=v;
  if(v) try{ sessionStorage.setItem('xray_llm_key', v); }catch(e){}
  const st=document.getElementById('llm-key-status');
  if(st) st.textContent=v?'Key lista en este navegador':'Sin key: el LLM no se llama';
  document.getElementById('btn-brief-llm')?.classList.toggle('needs-key', !v);
  return v;
}
async function lanzarBrief(id, modo){
  const r=D.companies.find(x=>x.id===id);
  const slot=document.getElementById('brief-slot');
  const btn=document.getElementById(modo==='llm'?'btn-brief-llm':modo==='fondo'?'btn-fondo':'btn-brief');
  if(!r||!slot) return;
  if(modo==='llm' && !claveUI()){
    pintarBrief(r, {
      vista:'pyme', src:'sin-clave', situacion:'El LLM no se ha llamado. Pega la API key de Gemini (AI Studio) arriba y pulsa otra vez Agente + LLM.',
      tesoreria:'Plan de acciones es plantilla + catálogo: siempre dirá lo mismo. El modelo solo corre en Agente + LLM, y solo con key.',
      limites:'Sin key no hay red, no hay tokens y no hay redacción nueva.',
      acciones:[], teoria:[], impacto:[], herramientas:[],
      aviso:'Sin API key.'
    });
    document.getElementById('llm-key')?.focus();
    toast('Pega la key de Gemini arriba');
    return;
  }
  if(btn){ btn.disabled=true; btn.textContent=modo==='llm'?'Agente trabajando…':'Generando…'; }
  const plantilla=bloquesPyme(r);
  let b=Object.assign({src:'plantilla', aviso:'', vista:modo==='fondo'?'fondo':'pyme'}, plantilla);
  if(modo!=='fondo'){
    try{
      const res=await fetch('/api/brief',{
        method:'POST',
        headers:{'Content-Type':'application/json'},
        body:JSON.stringify({company_id:id, llm:modo==='llm', api_key:claveUI()})
      });
      if(res.ok){
        const j=await res.json();
        b.situacion=richer(j.situacion, plantilla.situacion);
        b.tesoreria=richer(j.tesoreria, plantilla.tesoreria);
        b.limites=j.limites||b.limites;
        b.workspace=j.workspace||b.workspace;
        if(Array.isArray(j.acciones) && j.acciones.length) b.acciones=j.acciones;
        b.teoria=j.teoria||[];
        b.impacto=j.impacto||[];
        b.herramientas=j.herramientas||b.herramientas;
        b.src=j.fuente||b.src;
        b.aviso=j.aviso||'';
        if(modo==='llm' && j.fuente==='agente') toast('Agente con LLM');
        if(modo==='llm' && j.fuente!=='agente') toast((j.aviso&&j.aviso.indexOf('OpenAI')>=0)?'Servidor viejo: relanza python -m src.brief_server':(j.aviso||'Gemini no se usó'));
      } else if(modo==='llm') b.aviso='El servidor no respondió. python -m src.brief_server';
    }catch(e){
      if(modo==='llm') b.aviso='Sin servidor. python -m src.brief_server y recarga http://127.0.0.1:8775/';
    }
  }
  pintarBrief(r, b);
  if(btn){
    btn.disabled=false;
    btn.textContent=modo==='llm'?'Agente + LLM':modo==='fondo'?'Qué vería el fondo':'Plan de acciones';
  }
}

function ejes(id){
  const e=D.explain[id]; if(!e) return '<p class="note">Sin explicacion.</p>';
  return `<div class="axes">${D.ejes.map(([k,nom,w])=>{
    const f=e.f[k]||{}; const s=f.s;
    const col=s==null?'#9aa1b0': s>=70?'#1f8a6e':s>=55?'#3d6bff':s>=40?'#c47a1a':'#e07a4a';
    return `<div class="axis"><div class="nm">${nom} · ${w}%</div>
      <div class="sc" style="color:${col}">${s??'—'}</div>
      <div class="track"><i style="width:${s??0}%;background:${col}"></i></div>
      <div class="note">${f.ok===false?'Eje apagado (sin dato). ':''}${f.r||''}</div></div>`;
  }).join('')}</div>`;
}

let FILTRO='todas';
function pasa(x){
  if(FILTRO==='sanas') return x.c==='SALUDABLE'||x.c==='ESTABLE';
  if(FILTRO==='mej') return x.t==='MEJORANDO';
  if(FILTRO==='giro') return !!(x.giro && x.s>=55);
  if(FILTRO==='det') return x.t==='DETERIORANDO';
  return true;
}
function filtra(q){
  const qq=(q||'').toLowerCase();
  return D.companies.filter(x=>pasa(x) && (!qq || (x.id+' '+x.g+' '+x.c+' '+x.t).toLowerCase().includes(qq)))
    .sort((a,b)=>(b.s||0)-(a.s||0));
}
function filasLista(sel, q){
  let list=filtra(q);
  const extra=D.companies.find(x=>x.id===sel);
  if(extra) list=[extra, ...list.filter(x=>x.id!==sel)];
  return list.slice(0,80).map(x=>`<div class="row ${x.id===sel?'on':''}" data-id="${x.id}" role="button">
    <div class="company-cell"><div class="logo">${logo(x.id)}</div><div><strong>${x.id}</strong><small>${x.g||'sin grupo'}</small></div></div>
    <div style="text-align:right;min-width:72px">${scoreBar(x.s)}${pill(x.c)}</div>
  </div>`).join('');
}
function titula(r){
  if(r.s==null || r.c==='NO EVALUABLE') return 'Aún no hay nota';
  if(r.giro && r.s>=55 && r.nat==='caida_estructural') return 'Aún parece sana, pero la caída se sostiene';
  if(r.giro && r.s>=55) return 'Aún parece sana, pero hay un bache';
  if(r.c==='SALUDABLE' && r.t==='MEJORANDO') return 'Sólida y mejorando';
  if(r.c==='SALUDABLE') return 'Sólida';
  if(r.t==='DETERIORANDO') return 'La nota aguanta; la dirección no';
  return r.c+' · '+r.t;
}
function signalCards(id){
  const e=D.explain[id]||{f:{}};
  return `<div class="signals">${D.ejes.map(([k,nom])=>{
    const f=e.f[k]||{}; const s=f.s;
    const col=tone(s);
    const bg=s==null?'#fff':s>=68?'#f3faf7':s>=52?'#f4f7ff':s>=42?'#fff8ee':'#fff5f0';
    return `<article class="card signal" style="background:${bg};border-color:${col}33"><div class="signal-top"><span>${nom}</span></div>
      <div class="signal-score" style="color:${col}">${s==null?'—':Number(s).toFixed(0)}</div>
      <div class="track"><i style="width:${s??0}%;background:${col}"></i></div></article>`;
  }).join('')}</div>`;
}
function empresa(id, keepQ){
  const r=D.companies.find(x=>x.id===id)||D.companies[0];
  CURRENT=r.id;
  const q=keepQ? ((document.getElementById('q')||{}).value||'') : '';
  const boxWas=document.getElementById('q');
  const caret=boxWas? boxWas.selectionStart : q.length;
  document.getElementById('empresa').innerHTML=`
  <div class="layout">
    <div class="list">
      <input id="q" class="q" placeholder="Buscar COMP_ o GROUP_…" value="${q.replace(/"/g,'&quot;')}">
      <div class="chips">
        <button data-f="todas" class="${FILTRO==='todas'?'on':''}">Todas</button>
        <button data-f="sanas" class="${FILTRO==='sanas'?'on':''}">Sanas</button>
        <button data-f="mej" class="${FILTRO==='mej'?'on':''}">Mejorando</button>
        <button data-f="giro" class="${FILTRO==='giro'?'on':''}">Se tuercen</button>
        <button data-f="det" class="${FILTRO==='det'?'on':''}">Deteriorando</button>
      </div>
      <div class="rows">${filasLista(r.id, q)}</div>
    </div>
    <div>
      <article class="card profile-hero">
        <div class="profile-title">
          <div class="profile-id">
            <div class="profile-logo">${logo(r.id)}</div>
            <div>
              <h1>${r.id}</h1>
              <div class="meta note">${r.g||'sin grupo'}</div>
            </div>
          </div>
          <div class="profile-actions">
            <button type="button" class="btn" id="btn-brief">Plan de acciones</button>
            <button type="button" class="btn btn-lime" id="btn-brief-llm">Agente + LLM</button>
            <button type="button" class="btn ghost" id="btn-fondo">Fondo</button>
            <button type="button" class="btn ghost" id="btn-metodo">Cómo se calcula</button>
          </div>
        </div>
        <div class="health-strip">
          ${scoreRing(r.s)}
          <div class="profile-summary">${pill(r.c)}
            ${r.giro?`<span class="pill ${r.nat==='caida_estructural'?'pill-bad':'pill-warn'}">${r.nat==='caida_estructural'?'caída':'bache'}</span>`:''}
            <h2>${titula(r)}</h2>
            <div class="change ${r.t}">${r.t==='MEJORANDO'?'Mejorando':r.t==='DETERIORANDO'?'Se tuerce':'Estable'}${r.dir==null?'':(' · '+(r.dir>0?'+':'')+Number(r.dir).toFixed(1)+' pts / 6m')}</div>
          </div>
        </div>
      </article>
      ${signalCards(r.id)}
      <article class="card" style="margin-bottom:14px">
        <div class="card-head"><div><h2>Evolución</h2></div>
          ${r.giro?`<span class="pill pill-warn">${r.nat==='caida_estructural'?'caída':'bache'}</span>`:''}</div>
        ${chart(r.id)}
        <div id="brief-slot">${BRIEF_ON[r.id]?htmlBrief(BRIEF_ON[r.id]):''}</div>
      </article>
    </div>
  </div>`;
  const box=document.getElementById('q');
  if(keepQ){ box.focus(); try{ box.setSelectionRange(caret, caret); }catch(e){} }
  document.querySelector('.row.on')?.scrollIntoView({block:'nearest'});
  box.oninput=()=>{
    document.querySelector('.list .rows').innerHTML=filasLista(r.id, box.value);
  };
  document.querySelector('.list').onclick=ev=>{
    const chip=ev.target.closest('[data-f]');
    if(chip){ FILTRO=chip.dataset.f; empresa(r.id, true); return; }
    const row=ev.target.closest('[data-id]'); if(row) empresa(row.dataset.id, true);
  };
  document.getElementById('btn-brief')?.addEventListener('click',()=>lanzarBrief(r.id, 'pyme'));
  document.getElementById('btn-brief-llm')?.addEventListener('click',()=>lanzarBrief(r.id, 'llm'));
  claveUI();
  document.getElementById('btn-fondo')?.addEventListener('click',()=>lanzarBrief(r.id, 'fondo'));
  document.getElementById('btn-metodo')?.addEventListener('click',()=>show('metodo'));
  if(BRIEF_ON[r.id]) document.getElementById('btn-copy-brief')?.addEventListener('click',()=>{
    navigator.clipboard?.writeText(textoBrief(BRIEF_ON[r.id])); toast('Brief copiado');
  });
}

function radar(){
  const k=D.kpis;
  const sanas=D.companies.filter(x=>x.giro && x.s>=55).sort((a,b)=>(b.sig||0)-(a.sig||0));
  const mej=D.companies.filter(x=>x.t==='MEJORANDO').sort((a,b)=>(b.dir||b.d||0)-(a.dir||a.d||0)).slice(0,8);
  const det=D.companies.filter(x=>x.t==='DETERIORANDO' && x.s>=55).sort((a,b)=>(a.dir||0)-(b.dir||0)).slice(0,6);
  const sano=D.companies.filter(x=>x.c==='SALUDABLE').sort((a,b)=>(b.s||0)-(a.s||0)).slice(0,6);
  const ant=D.companies.filter(x=>x.ant!=null).sort((a,b)=>(b.ant||0)-(a.ant||0)).slice(0,8);
  const top=D.companies.filter(x=>x.s!=null).sort((a,b)=>(b.s||0)-(a.s||0));
  const tableRows=(list)=>list.slice(0,12).map(r=>`<tr class="click" data-id="${r.id}">
    <td><div class="company-cell"><div class="logo">${logo(r.id)}</div><div><strong>${r.id}</strong><small>${r.g||'sin grupo'}</small></div></div></td>
    <td>${scoreBar(r.s)}</td>
    <td><span class="${r.t}">${r.t==='MEJORANDO'?'↑':r.t==='DETERIORANDO'?'↓':'→'} ${r.t||'—'}</span><br><small>${r.dir==null?'':((r.dir>0?'+':'')+r.dir+' pts / 6m')}</small></td>
    <td>${pill(r.c)}</td>
    <td>${r.giro&&r.s>=55?`<span class="pill ${r.nat==='caida_estructural'?'pill-bad':'pill-warn'}">${r.nat||'giro'}</span>`:(r.giro?'<span class="pill pill-ghost">giro ya no sano</span>':'<span class="pill pill-ghost">—</span>')}</td>
  </tr>`).join('');
  document.getElementById('radar').innerHTML=`
  <div class="search-hero">
    <h1>Busca empresas por comportamiento</h1>
    <p>Health score, dirección y si se está torciendo.</p>
    <div class="searchbox">
      <input id="naturalSearch" placeholder="COMP_0725 o GROUP_0222" aria-label="Buscar">
      <button class="btn btn-lime" id="searchButton">Buscar ${k.n} empresas</button>
    </div>
    <div class="prompt-chips">
      <button class="chip" data-jump="giro">Se tuercen y aún parecen sanas</button>
      <button class="chip" data-jump="mej">Mejorando</button>
      <button class="chip" data-jump="sanas">SALUDABLE + ESTABLE</button>
      <button class="chip" data-jump="det">Deteriorando</button>
    </div>
  </div>
  <div class="stats">
    <article class="card stat" style="--stat:#3d6bff"><div class="stat-head"><span>Universo</span><span class="pill pill-blue">Cartera</span></div><div class="stat-value">${k.n.toLocaleString('es')}</div><small>empresas</small></article>
    <article class="card stat" style="--stat:#1f8a6e"><div class="stat-head"><span>Sanas</span><span class="pill pill-good">≥ 52</span></div><div class="stat-value">${k.sano}</div><small>SALUDABLE + ESTABLE</small></article>
    <article class="card stat" style="--stat:#c47a1a"><div class="stat-head"><span>Llamadas</span><span class="pill pill-warn">Giro</span></div><div class="stat-value">${k.giro_sanas}</div><small>giro y score ≥ 55</small></article>
    <article class="card stat" style="--stat:#e07a4a"><div class="stat-head"><span>Deteriorando</span><span class="pill pill-bad">Dirección</span></div><div class="stat-value">${k.det}</div><small>la nota aguanta, el rumbo no</small></article>
  </div>
  <div class="card table-card" style="margin-bottom:16px">
    <div class="results-head" style="padding:14px 14px 0"><div><h2 id="resultTitle">${top.length} empresas</h2><p>Ordenadas por health score.</p></div></div>
    <div class="table-wrap"><table>
      <thead><tr><th>Empresa</th><th>Health</th><th>Momentum</th><th>Nivel</th><th>Señal</th></tr></thead>
      <tbody id="screenerBody">${tableRows(top)}</tbody>
    </table></div>
  </div>
  <div class="qnav">
    <a href="#q1"><b>1. Sano</b><span>${k.sano} SALUDABLE+ESTABLE</span></a>
    <a href="#q2"><b>2. Mejora</b><span>${k.mej} ↑ · ${k.det} ↓</span></a>
    <a href="#q3"><b>3. Se tuerce</b><span>${k.giro_sanas} aún parecen sanas</span></a>
    <a href="#q4"><b>4. Bache / caída</b><span>${k.bache_l} bache · ${k.caida_l} estructural</span></a>
    <a href="#q5"><b>5. Por qué</b><span>6 ejes en la ficha</span></a>
    <a href="#q6"><b>6. Cuándo</b><span>mediana ${k.ant_med??'—'} m</span></a>
  </div>
  <div class="card" id="q1">
    <h2>1. Quién está sano</h2>
    <p class="note">SALUDABLE ≥ 68 · ESTABLE ≥ 52</p>
    ${barsClase()}
    <table><thead><tr><th>Empresa</th><th>Score</th><th>Nivel</th><th>Dirección</th></tr></thead>
    <tbody>${sano.map(r=>`<tr class="click" data-id="${r.id}"><td>${r.id}</td><td>${r.s}</td><td>${pill(r.c)}</td><td class="${r.t}">${r.t}</td></tr>`).join('')}</tbody></table>
  </div>
  <div class="grid2" style="margin-top:14px">
    <div class="card" id="q2">
      <h2>2. Quién está mejorando</h2>
      ${scatter()}
    </div>
    <div class="card">
      <h2>Hacia dónde va cada corriente</h2>
      ${flowsChart()}
    </div>
  </div>
  <div class="card" style="margin-top:14px">
    <div class="results-head"><div><h2>Quién mejora más</h2></div></div>
    <table><thead><tr><th>Empresa</th><th>Pts / 6m</th><th>Score</th></tr></thead>
    <tbody>${mej.map(r=>`<tr class="click" data-id="${r.id}"><td>${r.id}</td><td class="MEJORANDO">${r.dir??'—'}</td><td>${r.s}</td></tr>`).join('')}</tbody></table>
  </div>
  <div class="card" id="q3" style="margin-top:14px">
    <h2>3. Quién empieza a torcerse</h2>
    <p class="note">${sanas.length} empresas con score ≥ 55 y giro</p>
    <div class="scroll"><table><thead><tr><th>Empresa</th><th>Score</th><th>Nivel</th><th>Naturaleza</th><th>Sigmas</th><th>Desde</th><th>Por qué</th></tr></thead>
    <tbody>${sanas.map(r=>`<tr class="click" data-id="${r.id}">
      <td>${r.id}</td><td>${r.s}</td><td>${pill(r.c)}</td>
      <td>${r.nat||'—'}</td><td>${r.sig??'—'}</td><td>${r.pg||'—'}</td>
      <td class="note">${(r.mot||'').slice(0,90)}</td>
    </tr>`).join('')}</tbody></table></div>
  </div>
  <div class="grid2" style="margin-top:14px">
    <div class="card" id="q4">
      <h2>4. Bache o caída</h2>
      <p class="note">Un mes malo no es lo mismo que una caída que se sostiene</p>
      <div class="kpis">
        <div><div class="kpi">${k.bache_l}</div><div class="sub">bache en la lista (rebota +4,8 pts)</div></div>
        <div><div class="kpi">${k.caida_l}</div><div class="sub">caída estructural (sigue −1,8 pts)</div></div>
      </div>
      <table><thead><tr><th>Aún sana y deteriorando</th><th>6m</th><th>Nat.</th></tr></thead>
      <tbody>${det.map(r=>`<tr class="click" data-id="${r.id}"><td>${r.id} (${r.s})</td><td class="DETERIORANDO">${r.dir??'—'}</td><td>${r.nat||'—'}</td></tr>`).join('')}</tbody></table>
    </div>
    <div class="card" id="q6">
      <h2>6. Cuándo se vio venir</h2>
      <p class="note">Mediana de antelación: ${k.ant_med??'—'} meses</p>
      <table><thead><tr><th>Empresa</th><th>Meses antes</th><th>Score</th></tr></thead>
      <tbody>${ant.map(r=>`<tr class="click" data-id="${r.id}"><td>${r.id}</td><td>${r.ant}</td><td>${r.s} ${pill(r.c)}</td></tr>`).join('')}</tbody></table>
    </div>
  </div>
  <div class="card" id="q5" style="margin-top:14px">
    <div class="card-head"><div><h2>5. Por qué ha cambiado</h2><p>Seis ejes de tesorería. El peso es lo que aporta cada uno al Health Score.</p></div>
      <button type="button" class="btn" id="goto-metodo">Ver métricas</button></div>
    <div class="signals" style="margin:0">${D.ejes.map(([k,nom,w])=>`<article class="card signal" style="min-height:88px;padding:16px 18px"><div class="signal-top">${nom}</div><div class="signal-score" style="font-size:28px;margin:8px 0 0">${w}%</div></article>`).join('')}</div>
  </div>`;
  function applyJump(kind){
    FILTRO=kind||'todas';
    const box=document.getElementById('naturalSearch');
    const qq=(box&&box.value||'').toLowerCase();
    const list=D.companies.filter(x=>pasa(x) && (!qq || (x.id+' '+x.g).toLowerCase().includes(qq)))
      .sort((a,b)=>(b.s||0)-(a.s||0));
    const body=document.getElementById('screenerBody');
    const title=document.getElementById('resultTitle');
    if(body) body.innerHTML=tableRows(list);
    if(title) title.textContent=list.length+' empresas';
  }
  document.getElementById('goto-metodo')?.addEventListener('click',()=>show('metodo'));
  document.getElementById('searchButton')?.addEventListener('click',()=>applyJump(FILTRO));
  document.getElementById('naturalSearch')?.addEventListener('keydown',e=>{ if(e.key==='Enter') applyJump(FILTRO); });
  document.querySelectorAll('.chip[data-jump]').forEach(c=>c.onclick=()=>{
    document.querySelectorAll('.chip[data-jump]').forEach(x=>x.classList.remove('on'));
    c.classList.add('on'); applyJump(c.dataset.jump);
  });
  document.getElementById('radar').onclick=e=>{
    const tr=e.target.closest('[data-id]'); if(!tr) return;
    show('empresa'); empresa(tr.dataset.id);
  };
}

function grupos(){
  const rows=[...D.groups].filter(g=>g.hide).sort((a,b)=>a.peor-b.peor);
  const all=[...D.groups].sort((a,b)=>(a.s||99)-(b.s||99));
  document.getElementById('grupos').innerHTML=`
  <div class="card">
    <div class="card-head"><div><h2>El agregado no sustituye a la empresa</h2>
    <p>${D.kpis.hide} de ${D.kpis.ng} grupos esconden una filial en riesgo. Toggle de vista, no de cálculo.</p></div></div>
    <div class="scroll"><table><thead><tr><th>Grupo</th><th>N</th><th>Score grupo</th><th>Peor filial</th><th>Grupo</th><th>Peor</th></tr></thead>
    <tbody>${rows.map(g=>`<tr class="click" data-id="${g.emp}">
      <td>${g.id}</td><td>${g.n}</td><td>${g.s}</td>
      <td>${g.emp} (${g.peor})</td><td>${pill(g.cg)}</td><td>${pill(g.cp)}</td>
    </tr>`).join('')}</tbody></table></div>
  </div>`;
  document.getElementById('grupos').onclick=e=>{
    const tr=e.target.closest('[data-id]'); if(!tr) return;
    show('empresa'); empresa(tr.dataset.id);
  };
}

function monitor(){
  const al=D.alerts||[];
  const last=al.filter(x=>x.tipo==='giro_sana').slice(-80).reverse();
  const down=al.filter(x=>x.tipo==='cruce_abajo').slice(-40).reverse();
  const up=al.filter(x=>x.tipo==='cruce_arriba').slice(-40).reverse();
  const row=a=>`<tr class="click" data-id="${a.id}"><td>${a.m}</td><td>${a.id}</td><td>${a.s??'—'}</td><td class="note">${a.mot}</td></tr>`;
  document.getElementById('monitor').innerHTML=`
  <p class="lede">${al.length} avisos con antirrebote. No dispara si la empresa ya estaba en zona la primera vez que se la ve.</p>
  <div class="card"><div class="card-head"><div><h2>Giro estando sana</h2><p>${last.length} recientes</p></div></div>
    <div class="scroll"><table><thead><tr><th>Mes</th><th>Empresa</th><th>Score</th><th>Motivo</th></tr></thead><tbody>${last.map(row).join('')}</tbody></table></div></div>
  <div class="axes" style="margin-top:12px">
    <div class="card"><h2>Entra en fragil / critico</h2><table>${down.map(row).join('')}</table></div>
    <div class="card"><h2>Entra en SALUDABLE</h2><table>${up.map(row).join('')}</table></div>
  </div>`;
  document.getElementById('monitor').onclick=e=>{
    const tr=e.target.closest('[data-id]'); if(!tr) return;
    show('empresa'); empresa(tr.dataset.id);
  };
}

function metodo(){
  const ejes=[
    {nom:'Deuda comercial',w:20,col:'#e07a4a',preg:'¿Pagáis a los proveedores?',mira:'Impagos de los últimos 3 meses. Si no hay, la deuda comercial frente a lo que entra.',por:'Es el 20% porque dejar de pagar es vuestra decisión y suele ser lo primero que se rompe.',alto:'Cola controlada',bajo:'Vencidos o deuda que crece'},
    {nom:'Liquidez',w:18,col:'#3d6bff',preg:'¿El negocio genera caja?',mira:'Flujo operativo frente al tamaño (ingresos de 12 meses), sobre todo el trimestre.',por:'El 18%: un mes bueno no basta, tiene que aguantar el tamaño.',alto:'El flujo aguanta',bajo:'Entra menos de lo que toca'},
    {nom:'Colchón',w:18,col:'#1f8a6e',preg:'¿Cuántos meses de aire hay?',mira:'Meses de gasto que cubre el flujo (6 meses). El saldo de caja solo entra si existe de verdad.',por:'El 18%: separa un bache de quedarse sin oxígeno.',alto:'Hay margen',bajo:'Un tropiezo se nota ya'},
    {nom:'Trayectoria',w:18,col:'#c47a1a',preg:'¿Va a mejor o a peor?',mira:'Pendiente del flujo, si se recupera deuda a proveedores, ingresos del trimestre y si el problema se sostiene.',por:'El 18%: de aquí salen MEJORANDO y DETERIORANDO. No predice quiebra.',alto:'Rumbo al alza',bajo:'Rumbo a la baja'},
    {nom:'Eficiencia',w:14,col:'#121a42',preg:'¿Se come el gasto la caja?',mira:'Burn de 3 meses. 1,0 es el equilibrio entre lo que entra y lo que sale.',por:'El 14%: un mes loco no explica una quema que se sostiene.',alto:'En equilibrio',bajo:'La quema sigue'},
    {nom:'Cobro',w:12,col:'#6b7288',preg:'¿Os pagan a vosotros?',mira:'Facturas de clientes vencidas y devoluciones, últimos 3 meses.',por:'El 12%: que no os paguen anticipa que no podáis pagar. Pesa menos porque la decisión es del cliente.',alto:'Os pagan a tiempo',bajo:'La cola de cobro se alarga'}
  ];
  document.getElementById('metodo').innerHTML=`
  <div class="demo-say">
    <h2>Lo que cuentas en la demo</h2>
    <p>El Health Score es una nota de tesorería, de 0 a 100. Cada mes miramos seis cosas de caja y facturas, las mezclamos con un peso fijo, y juntamos los meses. Si falta un dato, ese trozo se apaga: no inventamos un 50. Luego leemos tres cosas: si está sana hoy, si mejora o empeora, y si se acaba de torcer.</p>
  </div>
  <div class="card">
    <h2>1. Cómo se llega al número</h2>
    <p class="lede">No es un modelo opaco. Es una receta.</p>
    <div class="steps">
      <article class="card step"><b>Paso A · el mes</b><p>Ese mes, cada eje saca una nota 0–100. Se mezclan así: 20 + 18 + 18 + 18 + 14 + 12. Eso es la nota del mes.</p></article>
      <article class="card step"><b>Paso B · la historia</b><p>Se juntan los meses. Los recientes pesan más (cada 6 meses el peso se reduce a la mitad). Un pico de un mes no manda.</p></article>
      <article class="card step"><b>Paso C · si hay poco dato</b><p>Si hay pocos meses, la nota se acerca a 54 (lo típico). Un único mes bueno no te convierte en SALUDABLE.</p></article>
    </div>
    <div class="pipe">
      <span>Deuda 20%</span><span>Liquidez 18%</span><span>Colchón 18%</span><span>Trayectoria 18%</span><span>Eficiencia 14%</span><span>Cobro 12%</span><span>= nota del mes</span><span>→ meses recientes</span><span>→ Health Score</span>
    </div>
  </div>
  <div class="card" style="margin-top:14px">
    <h2>2. Qué hace el score</h2>
    <div class="trio">
      <article class="card step"><b>Ordena la cartera</b><p>Quién está sano hoy. SALUDABLE ≥ 68, ESTABLE ≥ 52, EN RIESGO ≥ 42, FRÁGIL ≥ 33, si no CRÍTICO.</p></article>
      <article class="card step"><b>Mira las dos direcciones</b><p>No solo a las que se hunden. Una que pasa de 45 a 65 puede ser la mejor llamada. Una de 82 a 68 sigue pareciendo sana.</p></article>
      <article class="card step"><b>Avisa antes</b><p>El giro detecta que se torció contra su propia historia. El plan de acciones sale de los ejes flojos, no de un LLM suelto.</p></article>
    </div>
  </div>
  <div class="card" style="margin-top:14px">
    <h2>3. Las seis métricas</h2>
    <p class="note">En la ficha ves el número de cada una. Aquí es lo que dices al señalarlas.</p>
    <div class="metric-grid">${ejes.map(e=>`
      <article class="card metric">
        <div class="metric-top"><h3>${e.nom}</h3><div class="metric-w" style="color:${e.col}">${e.w}%</div></div>
        <div class="track"><i style="width:${e.w*5}%;background:${e.col}"></i></div>
        <p><strong>${e.preg}</strong></p>
        <p>${e.mira}</p>
        <p>${e.por}</p>
        <div class="hl"><span class="pill-good">${e.alto}</span><span class="pill-bad">${e.bajo}</span></div>
      </article>`).join('')}</div>
  </div>
  <div class="grid2" style="margin-top:14px">
    <div class="card">
      <h2>4. Cómo se lee en pantalla</h2>
      <div class="scale">
        <i style="width:33%;background:#e07a4a"></i>
        <i style="width:9%;background:#c47a1a"></i>
        <i style="width:10%;background:#f0c36a"></i>
        <i style="width:16%;background:#3d6bff"></i>
        <i style="width:32%;background:#1f8a6e"></i>
      </div>
      <div class="scale-leg">
        <span>CRÍTICO &lt; 33</span><span>FRÁGIL 33</span><span>EN RIESGO 42</span><span>ESTABLE 52</span><span>SALUDABLE ≥ 68</span>
      </div>
      <p class="note" style="margin-top:12px">Son cortes fijos, no un ranking contra las demás empresas.</p>
    </div>
    <div class="card">
      <h2>Las tres etiquetas de la ficha</h2>
      <p><strong>Nivel</strong> = el Health Score. ¿Está sana hoy?</p>
      <p><strong>Dirección</strong> = media de 3 meses de Trayectoria. &gt;58 MEJORANDO, &lt;42 DETERIORANDO. No es el cambio del 76. Por eso puede poner SALUDABLE + DETERIORANDO.</p>
      <p><strong>Giro</strong> = se torció respecto a sí misma. Bache = suele rebotar. Caída = se sostiene.</p>
    </div>
  </div>
  <div class="card" style="margin-top:14px">
    <h2>Una frase si te preguntan el truco</h2>
    <p class="lede">Si falta la fuente, el eje se apaga. Nunca rellenamos con 50. No prometemos puntos. No decimos que vaya a quebrar.</p>
  </div>`;
}

(function(){
  const el=document.getElementById('llm-key');
  if(!el) return;
  try{ const k=sessionStorage.getItem('xray_llm_key'); if(k) el.value=k; }catch(e){}
  el.addEventListener('input', claveUI);
  el.addEventListener('change', claveUI);
  claveUI();
})();
const navA=document.getElementById('nav-avisos');
if(navA) navA.textContent=String(D.kpis.avisos||0);
function openAI(){
  document.getElementById('aiPanel').classList.add('open');
}
function closeAI(){ document.getElementById('aiPanel').classList.remove('open'); }
function aiMsg(cls, html){
  const box=document.getElementById('messages');
  const d=document.createElement('div'); d.className='message '+cls; d.innerHTML=html;
  box.appendChild(d); box.scrollTop=box.scrollHeight;
}
document.getElementById('btn-tellme')?.addEventListener('click', openAI);
document.getElementById('aiClose').onclick=closeAI;
document.getElementById('brandHome')?.addEventListener('click',ev=>{ ev.preventDefault(); show('radar'); });
window.addEventListener('scroll',()=>{
  document.getElementById('siteHeader')?.classList.toggle('scrolled', window.scrollY>8);
},{passive:true});
show('radar');
document.getElementById('aiSend').onclick=()=>{ show('empresa'); empresa(CURRENT); closeAI(); };
document.querySelectorAll('[data-ai]').forEach(b=>b.onclick=async()=>{
  const r=D.companies.find(x=>x.id===CURRENT);
  if(!r){ toast('Abre una ficha primero'); return; }
  aiMsg('user', b.textContent);
  show('empresa'); empresa(CURRENT);
  await lanzarBrief(CURRENT, b.dataset.ai);
  const br=BRIEF_ON[CURRENT];
  if(br){
    if(br.vista==='fondo'){
      aiMsg('assistant', `<b>${r.id}</b><br>${esc(br.workspace||'')}`);
    } else {
      const acts=(br.acciones||[]).map(a=>`<div style="margin-top:8px"><b>${esc(a.titulo)}</b> · ${esc(a.quien)}<br>${esc(a.hace)}</div>`).join('');
      aiMsg('assistant', `<b>${r.id}</b><br>${esc(br.situacion||'')}<br><br>${esc(br.tesoreria||'')}${acts||'<br>Sin acción del catálogo para esta ficha.'}`);
    }
  }
});
radar();
empresa(D.kpis.featured || D.companies[0].id);
grupos(); monitor(); metodo();
</script>
</body>
</html>
"""


if __name__ == "__main__":
    build()
