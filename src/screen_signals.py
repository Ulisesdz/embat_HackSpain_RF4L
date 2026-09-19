"""Mide qué señales del panel anticipan de verdad, para no elegir pesos a ojo.

Este script es el que justifica los pesos de config.PESOS y los disparadores de
DISPARADORES_IMPAGO / DISPARADORES_ASFIXIA. Sin él, cualquier ponderación sería
una opinión.

Método:
  - Solo se evalúan filas donde el NIVEL aún es aceptable (score_mensual por
    encima de ALERTA_NIVEL_CRITICO). Es la única población donde una alerta puede
    comprar tiempo: si el nivel ya cayó, predecir el evento es una tautología.
  - Etiqueta: el evento ocurre en algún mes FUTURO dentro del horizonte. La señal
    se lee en t, el desenlace en t+1..t+H, así que no hay look-ahead.
  - Se reportan dos métricas porque miden cosas distintas:
      AUC        capacidad de ordenar en todo el rango. 0,50 = no informa.
      lift_decil concentración en la cola adversa. Es la que importa para una
                 alerta, que solo se activa en la cola.
    Varias señales tienen AUC ~0,50 y lift 2-3: no son monótonas, informan solo
    en el extremo. Si se eligieran por AUC se descartarían por error.

Ejecutar después de score_engine.py (necesita scores_mensuales.csv).
"""

import numpy as np
import pandas as pd

import src.config as cfg

# Signo: +1 si valores ALTOS son adversos, -1 si los adversos son los BAJOS.
CANDIDATAS = {
    "score_mensual": -1, "score_trayectoria": -1,
    "riesgo_impago_comercial": +1, "riesgo_asfixia_caja": +1,
    "stock_prov_sobre_ingresos": +1, "stock_clientes_sobre_ingresos": +1,
    "pct_impagos_prov_3m": +1, "pct_clientes_morosos_3m": +1,
    "recuperacion_stock_prov": -1,
    "share_stock_prov_antiguo": +1, "edad_media_stock_prov_dias": +1,
    "flujo_relativo_3m": -1, "burn_rate_3m_avg": +1,
    "colchon_flujo_meses": -1, "runway_meses": -1,
    "flujo_volatilidad_6m": +1, "flujo_pendiente_robusta_6m": -1,
    "ingresos_momentum_3m": -1,
    "refund_rate_3m": +1, "debt_service_3m": +1,
    "top1_prov_share_3m": +1, "top1_clientes_share_3m": +1,
    "persistente_flag_tijera": +1, "persistente_flag_flujo_negativo": +1,
    "persistente_flag_stock_prov_antiguo": +1,
}


def racha(cond, n):
    return cond.fillna(False).rolling(n, min_periods=n).sum() >= n


def etiquetar(m):
    """Marca el evento y, por empresa, si habrá evento en los próximos H meses."""
    g = m.groupby("company_id", sort=False)
    m["ev_impago"] = g.apply(
        lambda h: racha((h["pct_impagos_prov_3m"].fillna(0) >= cfg.EVENTO_IMPAGO_PCT)
                        | (h["stock_prov_sobre_ingresos"].fillna(0) >= cfg.EVENTO_IMPAGO_STOCK),
                        cfg.EVENTO_MESES),
        include_groups=False).reset_index(level=0, drop=True).astype(float)
    m["ev_asfixia"] = g.apply(
        lambda h: racha((h["flujo_relativo_3m"].fillna(0) <= cfg.EVENTO_ASFIXIA_FLUJO)
                        & (h["burn_rate_3m_avg"].fillna(0) >= cfg.EVENTO_ASFIXIA_BURN),
                        cfg.EVENTO_MESES),
        include_groups=False).reset_index(level=0, drop=True).astype(float)

    H = cfg.HORIZONTE_ANTICIPACION
    for ev in ("ev_impago", "ev_asfixia"):
        # Máximo en la ventana futura: invertir la serie, rodar, desinvertir.
        m[f"y_{ev}"] = m.groupby("company_id", sort=False)[ev].transform(
            lambda s: s[::-1].rolling(H, min_periods=1).max()[::-1].shift(-1))
    return m


def auc(y, x):
    ok = y.notna() & x.notna()
    y, x = y[ok].to_numpy(), x[ok].to_numpy()
    if len(y) < 200 or y.sum() in (0, len(y)):
        return np.nan, 0
    r = pd.Series(x).rank().to_numpy()
    n1, n0 = y.sum(), len(y) - y.sum()
    return (r[y == 1].sum() - n1 * (n1 + 1) / 2) / (n1 * n0), len(y)


def run():
    m = pd.read_csv(cfg.SCORES_MENSUAL_PATH)
    m["year_month"] = pd.PeriodIndex(m["year_month"], freq="M")
    m = etiquetar(m.sort_values(["company_id", "year_month"]).reset_index(drop=True))

    elegible = m["score_mensual"] >= cfg.ALERTA_NIVEL_CRITICO
    print(f"Filas con nivel aún aceptable: {int(elegible.sum()):,} de {len(m):,}   "
          f"horizonte: {cfg.HORIZONTE_ANTICIPACION} meses")

    for ev in ("ev_impago", "ev_asfixia"):
        y = m.loc[elegible, f"y_{ev}"]
        print(f"\n===== {ev}   tasa base {y.mean():.1%} =====")
        print(f"{'señal':36s} {'AUC':>6s} {'lift_decil':>11s} {'n':>9s}")
        res = []
        for c, signo in CANDIDATAS.items():
            if c not in m.columns:
                continue
            x = signo * m.loc[elegible, c]
            a, n = auc(y, x)
            ok = y.notna() & x.notna()
            yy, xx = y[ok], x[ok]
            sel = xx >= xx.quantile(0.90) if len(xx) else pd.Series(dtype=bool)
            lift = yy[sel].mean() / yy.mean() if sel.sum() > 20 and yy.mean() > 0 else np.nan
            if not np.isnan(a):
                res.append((c, a, lift, n))
        # Orden por la métrica que decide una alerta: la concentración en la cola.
        for c, a, lift, n in sorted(res, key=lambda t: -(t[2] if not np.isnan(t[2]) else 0)):
            print(f"{c:36s} {a:6.3f} {lift:11.2f} {n:9,}")

    print("\nAUC ~0,50 con lift alto = señal no monótona: informa solo en la cola.")
    return m


if __name__ == "__main__":
    run()
