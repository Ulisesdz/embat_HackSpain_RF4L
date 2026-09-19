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
    return {"kpis": kpis, "companies": companies, "groups": groups,
            "series": series, "explain": explain, "ejes": EJES, "alerts": alerts,
            "flows": flows}


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
<title>X-Ray · salud financiera</title>
<style>
:root{
  --bg:#0b1220; --panel:#121a2b; --card:#182338; --line:#27344d;
  --txt:#eef3fb; --muted:#8b9bb4; --acc:#5cb3ff;
  --ok:#3dd68c; --mid:#7eb0d6; --warn:#f0c14b; --bad:#ef8a4c; --crit:#ef5a5a;
}
*{box-sizing:border-box}
html,body{margin:0;height:100%;background:var(--bg);color:var(--txt);
  font:14px/1.45 "Segoe UI",system-ui,sans-serif}
header{display:flex;align-items:center;gap:16px;padding:12px 18px;
  border-bottom:1px solid var(--line);background:#0d1526;position:sticky;top:0;z-index:8}
header h1{margin:0;font-size:16px;font-weight:650;letter-spacing:.02em}
header h1 span{color:var(--acc)}
nav{display:flex;gap:4px;flex-wrap:wrap}
nav button{background:transparent;border:0;color:var(--muted);padding:7px 12px;
  border-radius:8px;cursor:pointer;font-weight:600}
nav button.on{background:var(--card);color:var(--txt)}
main{display:block;padding:16px 18px 40px;max-width:1400px;margin:0 auto}
.lede{color:var(--muted);max-width:860px;margin:0 0 12px;font-size:13px}
.qnav{display:grid;grid-template-columns:repeat(6,1fr);gap:8px;margin:4px 0 14px}
.qnav a{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:9px 10px;color:var(--txt);text-decoration:none}
.qnav a b{display:block;font-size:12px}
.qnav a span{color:var(--muted);font-size:11px}
.qpack{display:grid;grid-template-columns:repeat(3,1fr);gap:8px;margin:10px 0}
.qcell{background:var(--panel);border:1px solid var(--line);border-radius:10px;padding:8px 10px;font-size:13px}
.qcell b{display:block;font-size:10px;color:var(--muted);letter-spacing:.06em;text-transform:uppercase;margin-bottom:3px}
.barseg{display:flex;height:16px;border-radius:8px;overflow:hidden;margin:8px 0}
.barseg i{display:block;height:100%}
svg.lg{width:100%;height:280px;display:block}
.legend{display:flex;gap:14px;flex-wrap:wrap;font-size:12px;color:var(--muted);margin-top:6px}
.legend i{display:inline-block;width:9px;height:9px;border-radius:50%;margin-right:5px;vertical-align:middle}
.grid2{display:grid;grid-template-columns:1.15fr .85fr;gap:12px}
.chips{display:flex;gap:6px;padding:8px 10px;flex-wrap:wrap;border-bottom:1px solid var(--line)}
.chips button{background:#0b1220;border:1px solid var(--line);color:var(--muted);border-radius:999px;padding:4px 10px;cursor:pointer;font-size:11px}
.chips button.on{color:var(--txt);border-color:var(--acc)}
@media(max-width:1000px){.qnav,.grid2,.qpack{grid-template-columns:1fr 1fr}}
.kpis{display:grid;grid-template-columns:repeat(auto-fit,minmax(140px,1fr));gap:10px}
.card{background:var(--card);border:1px solid var(--line);border-radius:14px;padding:14px 16px}
.card h2{margin:0 0 8px;font-size:11px;color:var(--muted);letter-spacing:.08em;text-transform:uppercase}
.kpi{font-size:26px;font-weight:750}
.sub{color:var(--muted);font-size:12px;margin-top:2px}
.layout{display:grid;grid-template-columns:280px 1fr;gap:14px;min-height:70vh}
.list{background:var(--panel);border:1px solid var(--line);border-radius:14px;overflow:hidden;max-height:78vh;display:flex;flex-direction:column}
.list .rows{overflow:auto;flex:1}
.list input{width:100%;background:#0b1220;border:0;border-bottom:1px solid var(--line);
  color:var(--txt);padding:10px 12px;flex-shrink:0}
.row{padding:9px 12px;border-bottom:1px solid var(--line);cursor:pointer;display:flex;justify-content:space-between;gap:8px}
.scroll{max-height:62vh;overflow:auto}
.row:hover,.row.on{background:#1c2a42}
.row b{font-size:13px}
.row small{color:var(--muted);display:block}
.pill{display:inline-block;padding:2px 7px;border-radius:999px;font-size:10px;font-weight:700}
.SALUDABLE{background:#163528;color:var(--ok)} .ESTABLE{background:#163044;color:var(--mid)}
.EN-RIESGO{background:#3a3214;color:var(--warn)} .FRAGIL{background:#3a2414;color:var(--bad)}
.CRITICO{background:#3a1618;color:var(--crit)} .NO-EVALUABLE{color:var(--muted)}
.MEJORANDO{color:var(--ok)} .DETERIORANDO{color:var(--crit)}
.hero{display:flex;justify-content:space-between;align-items:flex-start;gap:12px;flex-wrap:wrap}
.hero .kpi{font-size:42px}
.axes{display:grid;grid-template-columns:repeat(2,1fr);gap:10px}
.axis{background:var(--panel);border:1px solid var(--line);border-radius:10px;padding:10px}
.axis .nm{font-size:12px;color:var(--muted)}
.axis .sc{font-size:22px;font-weight:750}
.track{height:6px;background:#0b1220;border-radius:6px;margin-top:6px;overflow:hidden}
.track i{display:block;height:100%}
table{width:100%;border-collapse:collapse;font-size:13px}
th,td{padding:7px 8px;border-bottom:1px solid var(--line);text-align:left}
th{color:var(--muted);font-size:11px;text-transform:uppercase}
tr.click{cursor:pointer} tr.click:hover td{background:#1c2a42}
.note{color:var(--muted);font-size:13px}
.ch{width:100%;height:260px;display:block}
svg circle[data-id]{cursor:pointer}
.hidden{display:none}
.toolbar{display:flex;gap:8px;margin-bottom:10px;flex-wrap:wrap}
select,input.q{background:#0b1220;border:1px solid var(--line);color:var(--txt);padding:7px 10px;border-radius:8px}
@media(max-width:900px){.layout{grid-template-columns:1fr}}
</style>
</head>
<body>
<header>
  <h1><span>X-Ray</span> · cartera</h1>
  <nav id="nav">
    <button class="on" data-tab="radar">Seis preguntas</button>
    <button data-tab="empresa">Empresa</button>
    <button data-tab="grupos">Grupos</button>
    <button data-tab="monitor">Monitor</button>
    <button data-tab="metodo">Método</button>
  </nav>
</header>
<main>
<section id="radar"></section>
<section id="empresa" class="hidden"></section>
<section id="grupos" class="hidden"></section>
<section id="monitor" class="hidden"></section>
<section id="metodo" class="hidden"></section>
</main>
<script>
const D = __DATA__;
const COLOR = {SALUDABLE:'#3dd68c',ESTABLE:'#7eb0d6','EN RIESGO':'#f0c14b','FRAGIL':'#ef8a4c','FRÁGIL':'#ef8a4c','CRITICO':'#ef5a5a','CRÍTICO':'#ef5a5a'};
const slug = c => (c||'').normalize('NFD').replace(/[\u0300-\u036f]/g,'').replace(/\s+/g,'-');
const pill = c => `<span class="pill ${slug(c)}">${c||''}</span>`;
function show(tab){
  document.querySelectorAll('main > section').forEach(s => s.classList.toggle('hidden', s.id!==tab));
  document.querySelectorAll('nav button').forEach(b => b.classList.toggle('on', b.dataset.tab===tab));
}
document.getElementById('nav').onclick = e => { if(e.target.dataset.tab) show(e.target.dataset.tab); };

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
  const grid=yTicks.map(v=>`<line x1="${pl}" x2="${w-pr}" y1="${Y(v)}" y2="${Y(v)}" stroke="${v===55?'#3d4f6a':'#243044'}" stroke-dasharray="${v===55?'4 4':'none'}"/>
    <text x="${pl-6}" y="${Y(v)+4}" fill="#8b9bb4" font-size="10" text-anchor="end">${v}</text>`).join('');
  let ray='';
  if(fc && pts.length){
    const last=pts[pts.length-1];
    const xs2=[last.x, last.x+1, last.x+2, last.x+3];
    const ys2=[last.y, ...fc.y];
    const los=[last.y, ...fc.lo];
    const his=[last.y, ...fc.hi];
    const band=xs2.map((x,i)=>X(x)+','+Y(his[i])).join(' ')+' '+[...xs2].reverse().map((x,i)=>X(x)+','+Y(los[los.length-1-i])).join(' ');
    const col=fc.b>0.15?'#3dd68c':fc.b<-0.15?'#ef5a5a':'#8b9bb4';
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
  const dots=mark?`<circle cx="${X(mark.x)}" cy="${Y(mark.y)}" r="5" fill="#ef5a5a"/>
    <text x="${X(mark.x)+8}" y="${Y(mark.y)-8}" fill="#ef5a5a" font-size="10">giro</text>`:'';
  const ticks=pts.filter((_,i)=>i===0||i===pts.length-1||i===Math.floor(pts.length/2))
    .map(pt=>`<text x="${X(pt.x)}" y="${h-10}" fill="#8b9bb4" font-size="10">${pt.m}</text>`).join('');
  const cap=fc
    ? `Línea azul = score mensual. El punto rojo es el giro vigente (último episodio). Discontinuo = si la pendiente reciente se mantiene, a 3 meses; parte del último score, no vuelve a una recta. MAE ${fc.mae??'—'} pts.`
    : 'Línea azul = score mensual. Punto rojo = primer giro. Sin proyección: menos de 6 meses puntuados.';
  return `<svg class="ch" viewBox="0 0 ${w} ${h}">
    ${grid}
    <text x="12" y="${pt+8}" fill="#8b9bb4" font-size="10">Score</text>
    ${(ymin<55 && ymax>55)?`<text x="${w-pr}" y="${Y(55)-5}" fill="#8b9bb4" font-size="10" text-anchor="end">55 · aún parece sana</text>`:''}
    <path d="${d}" fill="none" stroke="#5cb3ff" stroke-width="2.2"/>
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
  const cols={'SALUDABLE':'#3dd68c','ESTABLE':'#7eb0d6','EN RIESGO':'#f0c14b','FRÁGIL':'#ef8a4c','FRAGIL':'#ef8a4c','CRÍTICO':'#ef5a5a','CRITICO':'#ef5a5a','NO EVALUABLE':'#8b9bb4'};
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
    const col=c.giro&&c.s>=55?'#ef5a5a':c.t==='MEJORANDO'?'#3dd68c':c.t==='DETERIORANDO'?'#ef8a4c':'#7eb0d6';
    return `<circle data-id="${c.id}" cx="${X(c.s)}" cy="${Y(c.dir)}" r="${c.giro&&c.s>=55?4.2:2.5}" fill="${col}" fill-opacity=".8"><title>${c.id} · ${c.s} · ${c.t} · ${c.dir} pts / 6m</title></circle>`;
  }).join('');
  return `<svg class="lg" viewBox="0 0 ${w} ${h}">
    <line x1="${X(55)}" x2="${X(55)}" y1="${p}" y2="${h-p}" stroke="#33415c" stroke-dasharray="4 4"/>
    <line x1="${p}" x2="${w-p}" y1="${Y(0)}" y2="${Y(0)}" stroke="#33415c"/>
    <text x="${X(55)+6}" y="${p+12}" fill="#8b9bb4" font-size="10">55 aún parece sana</text>
    <text x="${w-p}" y="${h-8}" fill="#8b9bb4" font-size="10" text-anchor="end">score (quién está sano) →</text>
    <text x="6" y="${p+8}" fill="#8b9bb4" font-size="10">mejora</text>
    <text x="6" y="${h-p+4}" fill="#8b9bb4" font-size="10">empeora</text>
    ${dots}</svg>
    <div class="legend"><span><i style="background:#3dd68c"></i>MEJORANDO</span><span><i style="background:#ef8a4c"></i>DETERIORANDO</span><span><i style="background:#7eb0d6"></i>ESTABLE</span><span><i style="background:#ef5a5a"></i>giro y sigue sana</span></div>
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
  const ticks=[0,Math.floor((n-1)/2),n-1].map(i=>`<text x="${X(i)}" y="${h-6}" fill="#8b9bb4" font-size="10">${(F.m[i]||'').slice(0,7)}</text>`).join('');
  return `<svg class="lg" viewBox="0 0 ${w} ${h}" style="height:220px">
    ${path(F.MEJORANDO,'#3dd68c')}${path(F.ESTABLE,'#7eb0d6')}${path(F.DETERIORANDO,'#ef5a5a')}
    ${ticks}</svg>
    <div class="legend"><span><i style="background:#3dd68c"></i>hoy MEJORANDO (n=${D.kpis.mej})</span><span><i style="background:#7eb0d6"></i>ESTABLE (${D.kpis.est})</span><span><i style="background:#ef5a5a"></i>DETERIORANDO (${D.kpis.det})</span></div>
    <p class="note">Mediana del score mensual de quienes <em>hoy</em> tienen cada etiqueta. Es trayectoria observada, no un pronóstico.</p>`;
}

function ejes(id){
  const e=D.explain[id]; if(!e) return '<p class="note">Sin explicacion.</p>';
  return `<div class="axes">${D.ejes.map(([k,nom,w])=>{
    const f=e.f[k]||{}; const s=f.s;
    const col=s==null?'#8b9bb4': s>=70?'#3dd68c':s>=55?'#7eb0d6':s>=40?'#f0c14b':'#ef5a5a';
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
    <div><b>${x.id}</b><small>${x.g||'sin grupo'}</small></div>
    <div style="text-align:right"><b>${x.s??'—'}</b><br>${pill(x.c)}</div>
  </div>`).join('');
}
function empresa(id, keepQ){
  const r=D.companies.find(x=>x.id===id)||D.companies[0];
  const q=keepQ? ((document.getElementById('q')||{}).value||'') : '';
  const boxWas=document.getElementById('q');
  const caret=boxWas? boxWas.selectionStart : q.length;
  document.getElementById('empresa').innerHTML=`
  <div class="layout">
    <div class="list">
      <input id="q" class="q" placeholder="Buscar empresa o grupo..." value="${q.replace(/"/g,'&quot;')}">
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
      <div class="card">
        <div class="hero">
          <div>
            <h2>${r.id} · ${r.g||'sin grupo'}</h2>
            <div class="kpi">${r.s??'—'}</div>
            <div class="sub">${pill(r.c)} · <span class="${r.t}">${r.t}</span> · confianza ${r.conf}
              ${r.giro? ' · giro '+(r.nat||'')+(r.sig!=null?' '+r.sig+'σ':''):''}</div>
          </div>
          <div class="note">último mes ${r.last??'—'} · Δ ${r.d??'—'} · 6m ${r.dir??'—'}</div>
        </div>
        ${qpack(r)}
        ${chart(r.id)}
        <p class="note">${r.mot?('Por qué cambió: '+r.mot):(D.explain[r.id]&&D.explain[r.id].mot)||'Sin cambio atribuible el último mes.'}</p>
        ${D.explain[r.id]&&D.explain[r.id].giro?`<p class="note">${D.explain[r.id].giro}</p>`:''}
      </div>
      <div class="card" style="margin-top:12px"><h2>5. Por qué este número · 6 ejes</h2>${ejes(r.id)}</div>
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
}

function radar(){
  const k=D.kpis;
  const sanas=D.companies.filter(x=>x.giro && x.s>=55).sort((a,b)=>(b.sig||0)-(a.sig||0));
  const mej=D.companies.filter(x=>x.t==='MEJORANDO').sort((a,b)=>(b.dir||b.d||0)-(a.dir||a.d||0)).slice(0,8);
  const det=D.companies.filter(x=>x.t==='DETERIORANDO' && x.s>=55).sort((a,b)=>(a.dir||0)-(b.dir||0)).slice(0,6);
  const sano=D.companies.filter(x=>x.c==='SALUDABLE').sort((a,b)=>(b.s||0)-(a.s||0)).slice(0,6);
  const ant=D.companies.filter(x=>x.ant!=null).sort((a,b)=>(b.ant||0)-(a.ant||0)).slice(0,8);
  document.getElementById('radar').innerHTML=`
  <p class="lede">No predice quiebras. Lee el comportamiento en las dos direcciones, empresa a empresa y mes a mes, <b style="color:var(--txt)">antes de que sea evidente</b>.</p>
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
  <p class="note" id="q5" style="margin-top:12px">La pregunta 5 (por qué ha cambiado) se responde en la ficha: 6 ejes + motivo. Click en cualquier fila.</p>`;
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
    <h2>El agregado no sustituye a la empresa</h2>
    <p class="note">${D.kpis.hide} de ${D.kpis.ng} grupos esconden una filial en riesgo. Toggle de vista, no de cálculo.</p>
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
  <p class="note">${al.length} avisos con antirrebote. No dispara si la empresa ya estaba en zona la primera vez que se la ve.</p>
  <div class="card"><h2>Giro estando sana (${last.length} recientes)</h2>
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

radar();
empresa(D.kpis.featured || D.companies[0].id);
grupos(); monitor(); metodo();
</script>
</body>
</html>
"""


if __name__ == "__main__":
    build()
