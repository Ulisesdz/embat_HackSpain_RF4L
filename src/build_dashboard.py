"""Dashboard de producto: un HTML, sin servidor. Formato ficha + curva + bloques."""
import json

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
    data = payload()
    html = TEMPLATE.replace("__DATA__", json.dumps(data, ensure_ascii=False, separators=(",", ":")))
    cfg.DASHBOARD_PATH.parent.mkdir(parents=True, exist_ok=True)
    cfg.DASHBOARD_PATH.write_text(html, encoding="utf-8")
    print(f"Dashboard: {cfg.DASHBOARD_PATH} ({cfg.DASHBOARD_PATH.stat().st_size/1e6:.1f} MB)")


TEMPLATE = r"""<!DOCTYPE html>
<html lang="es">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Embat X-Ray · Private Markets</title>
<style>
:root{
  --ink:#17211f;--muted:#687571;--paper:#f3f4ef;--surface:#fff;--line:#dde2dc;
  --forest:#143f38;--forest2:#215b4f;--lime:#cff56f;--green:#2e7965;--greenSoft:#e2eee9;
  --blue:#3d6d7d;--blueSoft:#e2edf1;--red:#be4938;--redSoft:#f7e7e3;
  --amber:#a76a16;--amberSoft:#f6e9d4;--radius:14px;
}
*{box-sizing:border-box}
body{margin:0;background:var(--paper);color:var(--ink);
  font:13px/1.45 Inter,ui-sans-serif,-apple-system,"Segoe UI",sans-serif}
button,input,select{font:inherit}button{cursor:pointer}
h1,h2,h3,p{margin-top:0}h1{font-size:24px;letter-spacing:-.04em}
h2{font-size:17px;letter-spacing:-.025em}h3{font-size:13px}
.app{min-height:100vh;display:grid;grid-template-columns:226px minmax(0,1fr)}
.sidebar{height:100vh;position:sticky;top:0;background:var(--forest);color:#fff;padding:21px 14px;display:flex;flex-direction:column}
.brand{display:flex;align-items:center;gap:10px;padding:0 9px 25px;font-weight:780;font-size:16px;letter-spacing:-.03em}
.brandmark{width:31px;height:31px;border:1px solid rgba(255,255,255,.4);border-radius:50%;display:grid;place-items:center;color:var(--lime)}
.brand small{display:block;color:rgba(255,255,255,.48);font-size:8px;letter-spacing:.11em;text-transform:uppercase;margin-top:2px}
.nav-label{margin:14px 10px 7px;color:rgba(255,255,255,.45);font-size:9px;font-weight:760;letter-spacing:.13em;text-transform:uppercase}
.nav{border:0;width:100%;padding:10px;border-radius:9px;background:transparent;color:rgba(255,255,255,.68);display:flex;align-items:center;gap:10px;text-align:left}
.nav svg{width:17px;height:17px;flex-shrink:0}.nav:hover,.nav.active{background:rgba(255,255,255,.1);color:#fff}
.nav .count{margin-left:auto;background:rgba(255,255,255,.12);border-radius:8px;padding:2px 6px;font-size:9px}
.side-user{margin-top:auto;border-top:1px solid rgba(255,255,255,.13);padding:15px 8px 0;display:flex;gap:9px;align-items:center}
.avatar{width:31px;height:31px;border-radius:50%;background:var(--lime);color:var(--forest);font-weight:800;display:grid;place-items:center;font-size:10px}
.side-user small{display:block;color:rgba(255,255,255,.5);margin-top:2px}
.main{min-width:0;padding:20px 26px 80px}
.topbar{display:flex;align-items:center;justify-content:space-between;gap:16px;margin-bottom:22px}
.eyebrow{margin:0 0 5px;color:var(--muted);font-size:9px;font-weight:760;letter-spacing:.11em;text-transform:uppercase}
.top-actions{display:flex;gap:7px;align-items:center}
.view{display:none}.view.active{display:block}
.card{background:#fff;border:1px solid var(--line);border-radius:var(--radius);padding:17px}
.btn,.select,.apikey{border:1px solid var(--line);border-radius:9px;background:#fff;color:var(--ink);padding:8px 11px;font-weight:670}
.apikey{min-width:240px}.key-status{font-size:10px;color:var(--muted);max-width:160px;line-height:1.3}
.btn.needs-key{opacity:.7}
.btn:hover{border-color:#aab5ad}.btn-primary{background:var(--forest);border-color:var(--forest);color:#fff}
.btn-lime{background:var(--lime);border-color:var(--lime);color:var(--forest)}.btn.ghost{background:#fff}
.pill{display:inline-flex;align-items:center;padding:4px 7px;border-radius:999px;font-size:9px;font-weight:760}
.SALUDABLE,.pill-good{background:var(--greenSoft);color:var(--green)}
.ESTABLE,.pill-blue{background:var(--blueSoft);color:var(--blue)}
.EN-RIESGO,.pill-warn{background:var(--amberSoft);color:#7b4a0e}
.FRAGIL,.CRITICO,.pill-bad{background:var(--redSoft);color:#8b3024}
.NO-EVALUABLE,.pill-ghost{border:1px dashed #acb6ae;color:var(--muted);background:#fafbf8}
.MEJORANDO,.up{color:var(--green);font-weight:750}.DETERIORANDO,.down{color:var(--red);font-weight:750}
.search-hero{background:var(--forest);color:#fff;border-radius:18px;padding:30px;margin-bottom:16px;position:relative;overflow:hidden}
.search-hero:after{content:"";position:absolute;width:230px;height:230px;border:1px solid rgba(207,245,111,.27);border-radius:50%;right:-60px;top:-80px}
.search-hero h1{font-size:31px;margin:0 0 8px}.search-hero p{color:rgba(255,255,255,.65);max-width:650px;line-height:1.5;margin-bottom:20px}
.searchbox{position:relative;z-index:2;display:flex;max-width:840px;background:#fff;border-radius:12px;padding:6px}
.searchbox input{flex:1;border:0;outline:0;min-width:0;color:var(--ink);padding:8px 10px}
.prompt-chips{display:flex;gap:7px;flex-wrap:wrap;margin-top:13px;position:relative;z-index:2}
.chip{border:1px solid rgba(255,255,255,.2);background:rgba(255,255,255,.07);color:rgba(255,255,255,.78);border-radius:999px;padding:6px 9px;font-size:10px}
.chip:hover,.chip.on{background:rgba(255,255,255,.13);color:#fff}
.stats{display:grid;grid-template-columns:repeat(4,1fr);gap:11px;margin-bottom:16px}
.stat{min-height:104px}.stat-head{display:flex;justify-content:space-between;color:var(--muted);font-size:10px}
.stat-value{font-size:24px;font-weight:780;letter-spacing:-.04em;margin:17px 0 4px}.stat small{color:var(--muted)}
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
table{width:100%;border-collapse:collapse}th{text-align:left;padding:10px 12px;color:var(--muted);font-size:8px;letter-spacing:.09em;text-transform:uppercase;background:#fafbf8;border-bottom:1px solid var(--line)}
td{padding:12px;border-bottom:1px solid var(--line);font-size:13px}
tbody tr.click,tbody tr[data-id]{cursor:pointer}tbody tr:hover{background:#f6f8f4}
.company-cell{display:flex;gap:10px;align-items:center}
.logo,.profile-logo{width:34px;height:34px;border-radius:9px;background:var(--greenSoft);display:grid;place-items:center;color:var(--forest);font-weight:800}
.company-cell strong{display:block}.company-cell small{color:var(--muted);display:block;margin-top:3px}
.score{font-size:17px;font-weight:780}
.qnav{display:grid;grid-template-columns:repeat(6,1fr);gap:8px;margin:4px 0 14px}
.qnav a{background:#fff;border:1px solid var(--line);border-radius:10px;padding:9px 10px;color:var(--ink);text-decoration:none}
.qnav a b{display:block;font-size:12px}.qnav a span{color:var(--muted);font-size:11px}
.qpack{display:grid;grid-template-columns:repeat(3,1fr);gap:8px;margin:10px 0}
.qcell{background:#fafbf8;border:1px solid var(--line);border-radius:10px;padding:8px 10px;font-size:13px}
.qcell b{display:block;font-size:10px;color:var(--muted);letter-spacing:.06em;text-transform:uppercase;margin-bottom:3px}
.barseg{display:flex;height:16px;border-radius:8px;overflow:hidden;margin:8px 0}.barseg i{display:block;height:100%}
svg.lg,.ch,.timeline{width:100%;height:240px;display:block}
.legend{display:flex;gap:14px;flex-wrap:wrap;font-size:12px;color:var(--muted);margin-top:6px}
.legend i{display:inline-block;width:9px;height:9px;border-radius:50%;margin-right:5px;vertical-align:middle}
.grid2{display:grid;grid-template-columns:1.15fr .85fr;gap:12px}
.layout{display:grid;grid-template-columns:280px 1fr;gap:14px}
.list{background:#fff;border:1px solid var(--line);border-radius:var(--radius);overflow:hidden;max-height:78vh;display:flex;flex-direction:column}
.list .rows{overflow:auto;flex:1}
.list input{width:100%;border:0;border-bottom:1px solid var(--line);padding:10px 12px}
.chips{display:flex;gap:6px;padding:8px 10px;flex-wrap:wrap;border-bottom:1px solid var(--line)}
.chips button{background:#fafbf8;border:1px solid var(--line);color:var(--muted);border-radius:999px;padding:4px 10px;font-size:11px}
.chips button.on{color:var(--forest);border-color:var(--forest);background:var(--greenSoft)}
.row{padding:9px 12px;border-bottom:1px solid var(--line);cursor:pointer;display:flex;justify-content:space-between;gap:8px}
.row:hover,.row.on{background:#f6f8f4}.row small{color:var(--muted);display:block}
.profile-hero{margin-bottom:14px}.profile-title{display:flex;justify-content:space-between;gap:15px;flex-wrap:wrap}
.profile-id{display:flex;gap:13px}.profile-logo{width:52px;height:52px;border-radius:13px;font-size:16px}
.profile-actions{display:flex;gap:7px;align-items:flex-start;flex-wrap:wrap}
.health-strip{display:grid;grid-template-columns:170px 1fr;gap:22px;align-items:center;margin-top:24px}
.big-score{font-size:58px;line-height:.9;font-weight:790;letter-spacing:-.07em}
.score-caption{color:var(--muted);margin-top:9px}.change{font-weight:760;margin-top:6px}
.profile-summary h2{font-size:22px;margin-bottom:8px}.profile-summary p{color:var(--muted);line-height:1.55}
.confidence{font-size:10px;color:var(--muted);margin-top:12px}.confidence strong{color:var(--ink)}
.signals{display:grid;grid-template-columns:repeat(6,1fr);gap:9px;margin-bottom:14px}
.signal{padding:13px}.signal-top{display:flex;justify-content:space-between;color:var(--muted);font-size:9px}
.signal-score{font-size:22px;font-weight:780;margin:12px 0 3px}.signal small{color:var(--muted);display:block}
.card-head{display:flex;justify-content:space-between;align-items:flex-start;gap:10px;margin-bottom:14px}
.card-head h2{margin-bottom:4px}.card-head p{margin:0;color:var(--muted);font-size:10px}
.brief{margin-top:12px;padding:14px;background:#fafbf8;border:1px dashed #b4beb6;border-radius:12px}
.brief h2{font-size:15px}.note,.lede{color:var(--muted);font-size:12px}
.acciones{display:grid;grid-template-columns:1fr 1fr;gap:10px;margin-top:12px}
.accion{background:#fff;border:1px solid var(--line);border-radius:12px;padding:12px}
.accion h3{margin:0 0 6px;font-size:13px}.accion p{margin:0;color:var(--muted);font-size:11px;line-height:1.45}
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
.disclosure{margin-top:15px;padding:10px 12px;border:1px dashed #b4beb6;background:#fafbf8;border-radius:10px;color:var(--muted);font-size:9px;line-height:1.5}
.ai-button{position:fixed;right:22px;bottom:22px;border:0;border-radius:999px;padding:12px 16px;background:var(--forest);color:#fff;font-weight:730;z-index:15}
.ai-button span{color:var(--lime);margin-right:6px}
.ai-panel{position:fixed;right:20px;bottom:76px;width:min(440px,calc(100vw - 30px));height:560px;background:#fff;border:1px solid var(--line);border-radius:16px;z-index:16;display:none;flex-direction:column;overflow:hidden}
.ai-panel.open{display:flex}.ai-head{padding:14px 15px;background:var(--forest);color:#fff;display:flex;justify-content:space-between}
.ai-head small{color:rgba(255,255,255,.55);display:block;margin-top:3px}
.ai-close{border:0;background:rgba(255,255,255,.1);color:#fff;border-radius:50%;width:27px;height:27px}
.messages{padding:15px;overflow:auto;flex:1;background:#f7f8f4}
.message{max-width:92%;padding:10px 11px;border-radius:11px;margin-bottom:10px;line-height:1.5;font-size:11px}
.assistant{background:#fff;border:1px solid var(--line)}.user{background:var(--greenSoft);margin-left:auto}
.suggestions{display:flex;gap:5px;flex-wrap:wrap;margin-top:9px}
.suggestions button{border:1px solid var(--line);background:#fff;border-radius:999px;padding:5px 7px;font-size:9px}
.ai-input{display:flex;padding:10px;border-top:1px solid var(--line);gap:7px}
.ai-input input{flex:1;border:1px solid var(--line);border-radius:8px;padding:8px;min-width:0}
.ai-input button{border:0;border-radius:8px;background:var(--forest);color:#fff;padding:8px 10px}
.toast{position:fixed;right:22px;bottom:78px;background:var(--forest);color:#fff;padding:12px 14px;border-radius:10px;opacity:0;transform:translateY(70px);transition:.25s;z-index:25}
.toast.show{opacity:1;transform:none}
svg circle[data-id]{cursor:pointer}
@media(max-width:820px){.app{grid-template-columns:74px 1fr}.brand>div:last-child,.nav span,.nav-label,.side-user>div:last-child{display:none}.workspace,.layout,.profile-grid,.grid2,.qnav,.qpack,.signals,.stats{grid-template-columns:1fr 1fr}.filters{display:none}}
@media(max-width:700px){.app{display:block}.sidebar{display:none}.main{padding:15px 12px}.stats,.signals,.health-strip,.acciones{grid-template-columns:1fr}}
</style>
</head>
<body>
<div class="app">
<aside class="sidebar">
  <div class="brand"><div class="brandmark">E</div><div>X-Ray<small>by Embat</small></div></div>
  <div class="nav-label">Discover</div>
  <button class="nav active" data-view="radar"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor"><circle cx="10.5" cy="10.5" r="6.5" stroke-width="1.5"/><path d="m16 16 5 5" stroke-width="1.5"/></svg><span>Cartera</span></button>
  <button class="nav" data-view="empresa"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor"><path d="M4 7h16M4 12h16M4 17h10" stroke-width="1.5"/></svg><span>Ficha</span></button>
  <div class="nav-label">Monitor</div>
  <button class="nav" data-view="monitor"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor"><path d="m12 3 2.7 5.5 6.1.9-4.4 4.3 1 6.1-5.4-2.9-5.4 2.9 1-6.1-4.4-4.3 6.1-.9z" stroke-width="1.4"/></svg><span>Avisos</span><span class="count" id="nav-avisos">—</span></button>
  <button class="nav" data-view="grupos"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor"><path d="M5 4v16M19 4v16M5 8h14M5 16h14" stroke-width="1.5"/></svg><span>Grupos</span></button>
  <div class="nav-label">Research</div>
  <button class="nav" data-view="metodo"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor"><path d="M4 5h16v12H8l-4 4z" stroke-width="1.5"/></svg><span>Método</span></button>
    <button class="nav" id="nav-ai"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor"><path d="M8 10h8M8 13h5" stroke-width="1.4"/><path d="M4 5h16v12H8l-4 4z" stroke-width="1.5"/></svg><span>Agente pyme</span></button>
  <div class="side-user"><div class="avatar">DF</div><div><strong>Deal team</strong><small>HackSpain · dataset anónimo</small></div></div>
</aside>
<main class="main">
  <header class="topbar">
    <div><p class="eyebrow">Private company intelligence</p><h1 id="pageTitle">Cartera · seis preguntas</h1></div>
    <div class="top-actions">
      <input id="llm-key" class="apikey" type="password" placeholder="API key Gemini (AI Studio)" autocomplete="off">
      <span class="key-status" id="llm-key-status">Sin key: el LLM no se llama</span>
    </div>
  </header>
  <section id="radar" class="view active"></section>
  <section id="empresa" class="view"></section>
  <section id="grupos" class="view"></section>
  <section id="monitor" class="view"></section>
  <section id="metodo" class="view"></section>
</main>
</div>
<button class="ai-button" id="aiButton"><span>✦</span>Agente de la pyme</button>
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
const COLOR = {SALUDABLE:'#2e7965',ESTABLE:'#3d6d7d','EN RIESGO':'#a76a16','FRAGIL':'#be4938','FRÁGIL':'#be4938','CRITICO':'#be4938','CRÍTICO':'#be4938'};
const slug = c => (c||'').normalize('NFD').replace(/[\u0300-\u036f]/g,'').replace(/\s+/g,'-');
const pill = c => `<span class="pill ${slug(c)}">${c||''}</span>`;
const TITLES = {radar:'Cartera · seis preguntas', empresa:'Ficha de empresa', grupos:'Grupos', monitor:'Avisos', metodo:'Método'};
let CURRENT = D.kpis.featured || (D.companies[0]||{}).id;
function show(tab){
  document.querySelectorAll('.view').forEach(s => s.classList.toggle('active', s.id===tab));
  document.querySelectorAll('.nav[data-view]').forEach(b => b.classList.toggle('active', b.dataset.view===tab));
  const t=document.getElementById('pageTitle'); if(t) t.textContent=TITLES[tab]||'X-Ray';
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
    const col=fc.b>0.15?'#2e7965':fc.b<-0.15?'#be4938':'#687571';
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
  const dots=mark?`<circle cx="${X(mark.x)}" cy="${Y(mark.y)}" r="5" fill="#be4938"/>
    <text x="${X(mark.x)+8}" y="${Y(mark.y)-8}" fill="#be4938" font-size="10">giro</text>`:'';
  const ticks=pts.filter((_,i)=>i===0||i===pts.length-1||i===Math.floor(pts.length/2))
    .map(pt=>`<text x="${X(pt.x)}" y="${h-10}" fill="#687571" font-size="10">${pt.m}</text>`).join('');
  const last=pts[pts.length-1];
  const area=pts.length?`M${X(pts[0].x)},${Y(pts[0].y)} `+pts.slice(1).map(pt=>`L${X(pt.x)},${Y(pt.y)}`).join(' ')+` L${X(last.x)},${Y(ymin)} L${X(pts[0].x)},${Y(ymin)} Z`:'';
  const cap=fc
    ? `Línea = score mensual. El punto rojo es el giro vigente. Discontinuo = pendiente reciente a 3 meses, desde el último score real. MAE ${fc.mae??'—'} pts.`
    : 'Línea = score mensual. Punto rojo = giro. Sin proyección: menos de 6 meses puntuados.';
  return `<svg class="timeline" viewBox="0 0 ${w} ${h}">
    ${grid}
    ${(ymin<55 && ymax>55)?`<text x="${w-pr}" y="${Y(55)-5}" fill="#687571" font-size="10" text-anchor="end">55 · aún parece sana</text>`:''}
    <path d="${area}" fill="rgba(46,121,101,.08)"/>
    <path d="${d}" fill="none" stroke="#2e7965" stroke-width="3" stroke-linecap="round"/>
    ${ray}${dots}${ticks}
  </svg>
  <p class="note">${cap}</p>`;
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
  const cols={'SALUDABLE':'#2e7965','ESTABLE':'#3d6d7d','EN RIESGO':'#a76a16','FRÁGIL':'#be4938','FRAGIL':'#be4938','CRÍTICO':'#be4938','CRITICO':'#be4938','NO EVALUABLE':'#acb6ae'};
  const keys=order.filter(k=>cl[k]!=null).concat(Object.keys(cl).filter(k=>!order.includes(k)));
  return `<div class="barseg">${keys.map(k=>`<i style="width:${100*cl[k]/n}%;background:${cols[k]||'#8b9bb4'}" title="${k} ${cl[k]}"></i>`).join('')}</div>
    <div class="legend">${keys.map(k=>`<span><i style="background:${cols[k]||'#888'}"></i>${k} ${cl[k]}</span>`).join('')}</div>`;
}

function scatter(){
  const w=700,h=300,p=36;
  const pts=D.companies.filter(x=>x.s!=null && x.dir!=null);
  const ys=pts.map(p=>p.dir);
  const ymin=Math.min(-12,...ys), ymax=Math.max(12,...ys);
  const X=x=>p+x/100*(w-2*p);
  const Y=y=>h-p-(y-ymin)/(ymax-ymin||1)*(h-2*p);
  const dots=pts.map(c=>{
    const col=c.giro&&c.s>=55?'#be4938':c.t==='MEJORANDO'?'#2e7965':c.t==='DETERIORANDO'?'#a76a16':'#3d6d7d';
    return `<circle data-id="${c.id}" cx="${X(c.s)}" cy="${Y(c.dir)}" r="${c.giro&&c.s>=55?4.2:2.5}" fill="${col}" fill-opacity=".8"><title>${c.id} · ${c.s} · ${c.t} · ${c.dir} pts / 6m</title></circle>`;
  }).join('');
  return `<svg class="lg" viewBox="0 0 ${w} ${h}">
    <line x1="${X(55)}" x2="${X(55)}" y1="${p}" y2="${h-p}" stroke="#dde2dc" stroke-dasharray="4 4"/>
    <line x1="${p}" x2="${w-p}" y1="${Y(0)}" y2="${Y(0)}" stroke="#dde2dc"/>
    <text x="${X(55)+6}" y="${p+12}" fill="#687571" font-size="10">55 aún parece sana</text>
    <text x="${w-p}" y="${h-8}" fill="#687571" font-size="10" text-anchor="end">score (quién está sano) →</text>
    <text x="6" y="${p+8}" fill="#687571" font-size="10">mejora</text>
    <text x="6" y="${h-p+4}" fill="#687571" font-size="10">empeora</text>
    ${dots}</svg>
    <div class="legend"><span><i style="background:#2e7965"></i>MEJORANDO</span><span><i style="background:#a76a16"></i>DETERIORANDO</span><span><i style="background:#3d6d7d"></i>ESTABLE</span><span><i style="background:#be4938"></i>giro y sigue sana</span></div>
    <p class="note">Arriba-derecha: sólida y mejorando. Abajo-derecha: el caso 82→68. Arriba-izquierda: números mediocres hoy, mejor apuesta. No predice quiebras: lee nivel × dirección.</p>`;
}

function flowsChart(){
  const F=D.flows; if(!F||!F.m) return '';
  const w=700,h=220,p=28, n=F.m.length;
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
  return `<svg class="lg" viewBox="0 0 ${w} ${h}" style="height:220px">
    ${path(F.MEJORANDO,'#2e7965')}${path(F.ESTABLE,'#3d6d7d')}${path(F.DETERIORANDO,'#be4938')}
    ${ticks}</svg>
    <div class="legend"><span><i style="background:#2e7965"></i>hoy MEJORANDO (n=${D.kpis.mej})</span><span><i style="background:#3d6d7d"></i>ESTABLE (${D.kpis.est})</span><span><i style="background:#be4938"></i>DETERIORANDO (${D.kpis.det})</span></div>
    <p class="note">Mediana del score mensual de quienes <em>hoy</em> tienen cada etiqueta. Es trayectoria observada, no un pronóstico.</p>`;
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
        ${eje?`<span class="pill pill-ghost">${esc(eje)}${i.eje_hoy!=null?' · hoy '+i.eje_hoy:''}</span>`:''}
      </div>
      <p>${esc(a.hace)}</p>
      <p style="margin-top:6px">${esc(i.lectura||a.no_hace||'Sin promesa de puntos.')}</p>
    </article>`;
  }).join('')}</div>`;
}
function htmlBrief(b){
  const ws=b.vista==='fondo';
  const teor=(b.teoria||[]).slice(0,2);
  return `<div class="brief" id="brief-out">
    <h2>${ws?'Lo que vería el fondo':'Para la pyme'}</h2>
    ${ws?`<p>${esc(b.workspace||'')}</p>`:`
    <div class="qpack">
      <div class="qcell"><b>Qué está pasando</b>${esc(b.situacion||'')}</div>
      <div class="qcell"><b>Qué mirar en tesorería</b>${esc(b.tesoreria||'')}</div>
      <div class="qcell"><b>Qué no afirmamos</b>${esc(b.limites||'')}</div>
    </div>
    ${htmlAcciones(b)}
    ${teor.length?`<div class="teoria"><b>Teoría citada</b>${teor.map(t=>esc(t.id)+'. '+esc((t.texto||'').slice(0,220))).join('<br>')}</div>`:''}
    <div class="tools-used">${(b.herramientas||[]).map(t=>`<span>${esc(t)}</span>`).join('')}</div>`}
    <p class="note">${b.src==='agente'?'Agente: herramientas + LLM.':b.src==='sin-clave'?'No se ha llamado al LLM.':b.src&&String(b.src).includes('herramientas')?'Herramientas locales (sin LLM). Plan de acciones no llama al modelo.':'Plantilla + catálogo.'}
      ${ws?'Resumen anónimo: score + porqué. Sin acciones.':'Las acciones son tipos del catálogo, no una oferta. Cero puntos prometidos.'}
      ${b.aviso?esc(b.aviso):''}</p>
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
  let b=Object.assign({src:'plantilla', aviso:'', vista:modo==='fondo'?'fondo':'pyme'}, bloquesPyme(r));
  if(modo!=='fondo'){
    try{
      const res=await fetch('/api/brief',{
        method:'POST',
        headers:{'Content-Type':'application/json'},
        body:JSON.stringify({company_id:id, llm:modo==='llm', api_key:claveUI()})
      });
      if(res.ok){
        const j=await res.json();
        b.situacion=j.situacion||b.situacion;
        b.tesoreria=j.tesoreria||b.tesoreria;
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
      if(modo==='llm') b.aviso='Sin servidor. python -m src.brief_server y recarga http://127.0.0.1:8765/';
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
    const col=s==null?'#acb6ae': s>=70?'#2e7965':s>=55?'#3d6d7d':s>=40?'#a76a16':'#be4938';
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
    <div style="text-align:right"><span class="score">${x.s??'—'}</span><br>${pill(x.c)}</div>
  </div>`).join('');
}
function titula(r){
  if(r.s==null || r.c==='NO EVALUABLE') return 'Sin evidencia suficiente para puntuar';
  if(r.giro && r.s>=55 && r.nat==='caida_estructural') return 'Se tuerce y aún parece sana · caída que se sostiene';
  if(r.giro && r.s>=55) return 'Se tuerce y aún parece sana · bache de tesorería';
  if(r.c==='SALUDABLE' && r.t==='MEJORANDO') return 'Sólida y mejorando';
  if(r.c==='SALUDABLE') return 'Sólida, con la dirección que marca la etiqueta';
  if(r.t==='DETERIORANDO') return 'El nivel todavía no grita; la dirección sí';
  return r.c+' · '+r.t;
}
function signalCards(id){
  const e=D.explain[id]||{f:{}};
  return `<div class="signals">${D.ejes.map(([k,nom])=>{
    const f=e.f[k]||{}; const s=f.s;
    const arrow=s==null?'—':s>=70?'↑':s>=55?'→':'↓';
    return `<article class="card signal"><div class="signal-top"><span>${nom}</span><span class="${s!=null&&s<55?'down':'up'}">${arrow}</span></div>
      <div class="signal-score">${s??'—'}</div><small>${f.ok===false?'eje apagado':(f.r||'').slice(0,48)}</small></article>`;
  }).join('')}</div>`;
}
function empresa(id, keepQ){
  const r=D.companies.find(x=>x.id===id)||D.companies[0];
  CURRENT=r.id;
  const q=keepQ? ((document.getElementById('q')||{}).value||'') : '';
  const boxWas=document.getElementById('q');
  const caret=boxWas? boxWas.selectionStart : q.length;
  const d6=r.dir==null?'sin 6m':((r.dir>0?'+':'')+r.dir+' pts · 6 meses');
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
            <div><p class="eyebrow">Private company profile</p>
              <h1>${r.id}</h1>
              <div class="meta note">${r.g||'sin grupo'} · IDs del dataset, no hay sector ni país en el dato</div></div>
          </div>
          <div class="profile-actions">
            <button type="button" class="btn" id="btn-brief">Plan de acciones</button>
            <button type="button" class="btn ghost" id="btn-brief-llm">Agente + LLM</button>
            <button type="button" class="btn btn-primary" id="btn-fondo">Qué vería el fondo</button>
          </div>
        </div>
        <div class="health-strip">
          <div><div class="big-score">${r.s??'—'}</div>
            <div class="score-caption">Financial Health Score</div>
            <div class="change ${r.t}">${d6}${r.d!=null?' · Δ '+((r.d>0?'+':'')+r.d)+' último mes':''}</div></div>
          <div class="profile-summary">${pill(r.c)} <span class="${r.t}">${r.t||''}</span>
            ${r.giro?`<span class="pill ${r.nat==='caida_estructural'?'pill-bad':'pill-warn'}">${r.nat||'giro'}</span>`:''}
            <h2>${titula(r)}</h2>
            <p>${r.mot||(D.explain[r.id]&&D.explain[r.id].mot)||'Sin cambio atribuible el último mes.'}</p>
            <div class="confidence"><strong>${r.conf==='alta'?'Alta confianza':r.conf==='media'?'Confianza media':'Confianza baja'}</strong>
              · último mes ${r.last??'—'} · ${r.giro&&r.sig!=null?r.sig+'σ en el giro':'sin giro marcado'}</div>
          </div>
        </div>
      </article>
      ${signalCards(r.id)}
      <article class="card" style="margin-bottom:14px">
        <div class="card-head"><div><h2>Financial momentum</h2><p>Score mensual · no es un pronóstico de quiebra</p></div>
          ${r.giro?`<span class="pill pill-warn">giro ${r.nat||''}</span>`:'<span class="pill pill-ghost">sin giro</span>'}</div>
        ${chart(r.id)}
        ${D.explain[r.id]&&D.explain[r.id].giro?`<p class="note">${D.explain[r.id].giro}</p>`:''}
        ${qpack(r)}
        <div id="brief-slot">${BRIEF_ON[r.id]?htmlBrief(BRIEF_ON[r.id]):''}</div>
      </article>
      <article class="card"><div class="card-head"><div><h2>Por qué este número</h2><p>Seis ejes. Si falta la fuente, el eje se apaga. Nunca se imputa 50.</p></div></div>${ejes(r.id)}</article>
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
    <td><span class="score">${r.s??'—'}</span></td>
    <td><span class="${r.t}">${r.t==='MEJORANDO'?'↑':r.t==='DETERIORANDO'?'↓':'→'} ${r.t||'—'}</span><br><small>${r.dir==null?'':((r.dir>0?'+':'')+r.dir+' pts / 6m')}</small></td>
    <td>${pill(r.c)}</td>
    <td>${r.giro&&r.s>=55?`<span class="pill ${r.nat==='caida_estructural'?'pill-bad':'pill-warn'}">${r.nat||'giro'}</span>`:(r.giro?'<span class="pill pill-ghost">giro ya no sano</span>':'<span class="pill pill-ghost">—</span>')}</td>
  </tr>`).join('');
  document.getElementById('radar').innerHTML=`
  <div class="search-hero">
    <span class="pill pill-ghost" style="color:rgba(255,255,255,.7);border-color:rgba(255,255,255,.25)">X-Ray · no es PitchBook de nombres</span>
    <h1>Busca empresas por comportamiento</h1>
    <p>Health score, dirección y giro. IDs del dataset del reto: no hay sector, país ni facturación, y no se inventan.</p>
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
    <article class="card stat"><div class="stat-head"><span>Universo</span><span class="pill pill-blue">Dataset</span></div><div class="stat-value">${k.n.toLocaleString('es')}</div><small>perfiles anónimos</small></article>
    <article class="card stat"><div class="stat-head"><span>Sanas</span><span class="pill pill-good">≥ 52</span></div><div class="stat-value">${k.sano}</div><small>SALUDABLE + ESTABLE</small></article>
    <article class="card stat"><div class="stat-head"><span>Llamadas</span><span class="pill pill-warn">Giro</span></div><div class="stat-value">${k.giro_sanas}</div><small>giro y score ≥ 55</small></article>
    <article class="card stat"><div class="stat-head"><span>Deteriorando</span><span class="pill pill-bad">Dirección</span></div><div class="stat-value">${k.det}</div><small>tendencia, no quiebra</small></article>
  </div>
  <div class="card table-card" style="margin-bottom:16px">
    <div class="results-head" style="padding:14px 14px 0"><div><h2 id="resultTitle">${top.length} empresas</h2><p>Ordenadas por score. Click abre la ficha.</p></div></div>
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
    <p class="note">Reconocer a la excepcionalmente sólida es tan útil como detectar a la que se hunde. Umbrales absolutos: SALUDABLE ≥68, ESTABLE ≥52.</p>
    ${barsClase()}
    <table><thead><tr><th>Empresa</th><th>Score</th><th>Nivel</th><th>Dirección</th></tr></thead>
    <tbody>${sano.map(r=>`<tr class="click" data-id="${r.id}"><td>${r.id}</td><td>${r.s}</td><td>${pill(r.c)}</td><td class="${r.t}">${r.t}</td></tr>`).join('')}</tbody></table>
  </div>
  <div class="grid2" style="margin-top:14px">
    <div class="card" id="q2">
      <h2>2. Quién está mejorando · las dos direcciones</h2>
      <p class="note">Una que pasa de 45 a 65 puede ser la mejor apuesta. Eje X = nivel hoy. Eje Y = puntos de score suavizado en 6 meses.</p>
      ${scatter()}
    </div>
    <div class="card">
      <h2>Hacia dónde va cada corriente</h2>
      ${flowsChart()}
      <table><thead><tr><th>Mejora más</th><th>Pts/6m</th><th>Score</th></tr></thead>
      <tbody>${mej.map(r=>`<tr class="click" data-id="${r.id}"><td>${r.id}</td><td class="MEJORANDO">${r.dir??'—'}</td><td>${r.s}</td></tr>`).join('')}</tbody></table>
    </div>
  </div>
  <div class="card" id="q3" style="margin-top:14px">
    <h2>3. Quién empieza a torcerse · score ≥ 55 + giro</h2>
    <p class="note">De 82 a 68 sigue pareciendo sana. El punto rojo es el mes en que el comportamiento ya cambió. ${sanas.length} empresas. Click abre la ficha.</p>
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
      <p class="note">Un mes malo de caja no es un deterioro estructural. Validado contra el score a +6 meses.</p>
      <div class="kpis">
        <div><div class="kpi">${k.bache_l}</div><div class="sub">bache en la lista (rebota +4,8 pts)</div></div>
        <div><div class="kpi">${k.caida_l}</div><div class="sub">caída estructural (sigue −1,8 pts)</div></div>
      </div>
      <table><thead><tr><th>Aún sana y deteriorando</th><th>6m</th><th>Nat.</th></tr></thead>
      <tbody>${det.map(r=>`<tr class="click" data-id="${r.id}"><td>${r.id} (${r.s})</td><td class="DETERIORANDO">${r.dir??'—'}</td><td>${r.nat||'—'}</td></tr>`).join('')}</tbody></table>
    </div>
    <div class="card" id="q6">
      <h2>6. Cuándo se vio venir</h2>
      <p class="note">Detectar el mes que pasa no vale. Mediana de antelación ${k.ant_med??'—'} meses; ${k.gan_med??'—'} meses ganados a la capa de nivel.</p>
      <table><thead><tr><th>Empresa</th><th>Meses antes</th><th>Score</th></tr></thead>
      <tbody>${ant.map(r=>`<tr class="click" data-id="${r.id}"><td>${r.id}</td><td>${r.ant}</td><td>${r.s} ${pill(r.c)}</td></tr>`).join('')}</tbody></table>
    </div>
  </div>
  <p class="note" id="q5" style="margin-top:12px">La pregunta 5 (por qué ha cambiado) se responde en la ficha: 6 ejes + motivo. Click en cualquier fila.</p>
  <div class="disclosure"><strong>Dato del reto.</strong> Los IDs son anónimos. No hay nombres comerciales, sector, país ni rango de facturación: no se fabrican. El score lee caja y facturas.</div>`;
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
  document.getElementById('metodo').innerHTML=`
  <div class="card">
    <h2>Las seis preguntas, dónde se contestan</h2>
    <p class="note">El sistema no predice quiebras. Lee comportamiento en las dos direcciones, antes de que sea evidente.</p>
    <table>
      <tr><th>Pregunta</th><th>Campo</th><th>Dónde se ve</th></tr>
      <tr><td>Quién está sano</td><td>clasificacion / score_final</td><td>Seis preguntas §1 · ficha bloque 1</td></tr>
      <tr><td>Quién está mejorando</td><td>tendencia + pts/6m</td><td>Mapa nivel×dirección y curvas de corriente</td></tr>
      <tr><td>Quién empieza a torcerse</td><td>giro + score ≥ 55</td><td>Lista de llamadas · punto rojo en la curva</td></tr>
      <tr><td>Bache o caída</td><td>naturaleza_caida</td><td>§4 · validado a +6 meses</td></tr>
      <tr><td>Por qué ha cambiado</td><td>6 ejes + motivo</td><td>Ficha de empresa</td></tr>
      <tr><td>Cuándo se vio venir</td><td>meses_anticipacion</td><td>§6 y “visto N meses antes” en la ficha</td></tr>
    </table>
  </div>
  <div class="card" style="margin-top:12px">
    <h2>Qué lee cada eje</h2>
    <p class="note">Si falta la fuente, el eje se apaga. Nunca se imputa 50.</p>
    <table>
      <tr><th>Eje</th><th>Peso</th><th>Fuente</th></tr>
      <tr><td>Deuda comercial</td><td>20%</td><td>impagos proveedores 3m, luego stock / ingresos</td></tr>
      <tr><td>Liquidez</td><td>18%</td><td>flujo relativo 3m</td></tr>
      <tr><td>Colchón</td><td>18%</td><td>flujo 6m / gasto; runway solo si hay foto de caja</td></tr>
      <tr><td>Trayectoria</td><td>18%</td><td>Theil-Sen + momentum + persistencia</td></tr>
      <tr><td>Eficiencia</td><td>14%</td><td>burn 3m (topado a 8x)</td></tr>
      <tr><td>Cobro</td><td>12%</td><td>vencimientos sin cobrar 3m + refunds</td></tr>
    </table>
  </div>
  <div class="card" style="margin-top:12px">
    <h2>Agente para la pyme</h2>
    <p class="note">Agente de Embat, no un LLM suelto. El prompt le da el health score
    de esta ficha (cómo se calcula y qué ha dado), las herramientas ya corridas
    (ficha, RAG sobre <code>docs/TEORIA_PYME.md</code>, catálogo) y le pide las
    mismas secciones que ves: qué está pasando, tesorería, límites y acciones.
    Impacto = eje de hoy. Cero puntos prometidos. Partner solo en <b>bache</b>.
    <b>Qué vería el fondo</b> no lleva acciones.</p>
    <h2>Bonus · proyección walk-forward del score</h2>
    <p class="note">No predice quiebras. Predice el propio score a 1–3 meses: pendiente
    Theil-Sen de los últimos 6–12 meses, aplicada desde el último score real
    (no se vuelve a una recta global: un pico no fabrica un crash). La sombra es el
    p80 del error walk-forward de esa misma regla. El motor no usa esta proyección.</p>
  </div>
    <p class="note">Fechas imposibles se reparan, ceros y p99 no entran, fuera de la ventana = NaN.
    No se convierte todo a EUR: el tipo es 1 en el 64% de las cuentas no-EUR. Los ratios bastan.
    Detalle en docs/LIMPIEZA.md.</p>
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
document.getElementById('aiButton').onclick=openAI;
document.getElementById('aiClose').onclick=closeAI;
document.getElementById('nav-ai').onclick=()=>{ show('empresa'); openAI(); };
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
