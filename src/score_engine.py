"""Motor de scoring 0-100 con reglas expertas, trayectoria y alerta temprana.

Por qué reglas y no un modelo entrenado
---------------------------------------
No existe ground truth: el dataset no trae ninguna etiqueta de salud financiera.
Entrenar XGBoost contra un objetivo que definimos nosotros mismos produce un
modelo que aprende nuestra heurística con ruido añadido, y pierde la
explicabilidad que el reto evalúa. Prophet resuelve otro problema: forecasting de
una serie larga con estacionalidad, y aquí hay 24 puntos mensuales por empresa,
un único ciclo incompleto, donde sus changepoints no son identificables.

Lo que sí es un problema estadístico bien planteado es *estimar la dirección* de
una serie corta y ruidosa. Para eso el motor usa:
  - pendiente de Theil-Sen (mediana de pendientes por pares), robusta a outliers,
  - z-scores contra la propia base histórica de la empresa,
  - percentiles transversales dentro del mes,
  - amortiguación por volatilidad como control de falsos positivos,
  - contracción empírica hacia la media cuando la evidencia es escasa.

Todo ello es determinista, auditable y explicable factor a factor. En FEATURES.md
sección 11.3 queda descrito el protocolo para medir la antelación y, si esa
medición lo justificase, el encaje de una capa autosupervisada (objetivo = valor
futuro observado de la propia serie, con corte temporal estricto).

Cada eje resuelve una CASCADA de fuentes ordenadas de más precisa a más
disponible. Un eje solo se apaga si ninguna fuente tiene dato: así la cobertura
deja de ser el cuello de botella sin inventar información.

Salidas:
  scores_mensuales.csv     score por empresa y mes, con alerta temprana
  scores_finales.csv       score agregado, clasificación, tendencia y evidencia
  score_explanations.json  desglose por factor del último mes válido
"""

import json
import numpy as np
import pandas as pd

import src.config as cfg


def val(row, col):
    """Valor de una columna, o None si no existe o es NaN."""
    v = row.get(col)
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return None
    try:
        return None if pd.isna(v) else v
    except (TypeError, ValueError):
        return v


def escalonado(v, tabla, por_debajo=False):
    """Primer tramo que cumple el umbral. tabla = [(umbral, score, texto)]."""
    for umbral, score, txt in tabla:
        if (v < umbral) if por_debajo else (v > umbral):
            return score, txt
    return None, None


# =============================================================================
# EJES DE NIVEL
# =============================================================================

def f_liquidez(row):
    """¿El flujo de caja del trimestre es relevante frente a su tamaño?

    Cascada: media trimestral del flujo relativo -> flujo relativo del mes.
    Normalizar por ingresos_12m_avg absorbe la estacionalidad y hace comparable
    a una pyme con un grupo.
    """
    v, fuente = val(row, "flujo_relativo_3m"), "flujo_relativo_3m"
    if v is None:
        v, fuente = val(row, "flujo_relativo"), "flujo_relativo (mes suelto)"
    if v is None:
        return None, "Sin base de ingresos para normalizar el flujo", None

    pct = v * 100
    score, txt = escalonado(pct, [
        (15, 100, "muy positivo"), (5, 85, "positivo"), (0, 68, "ligeramente positivo"),
        (-5, 45, "ligeramente negativo"), (-15, 22, "negativo"),
    ])
    if score is None:
        score, txt = 5, "muy negativo"
    return score, f"Flujo neto {txt} ({pct:+.1f}% de los ingresos)", fuente


def f_colchon(row):
    """¿Cuántos meses de gasto aguanta?

    Cascada: colchón generado por el propio flujo (63% de cobertura) y, cuando
    existe el snapshot de caja, corrección acotada por el percentil de runway.
    El runway absoluto NO manda: su mediana en este dataset es 0,49 meses, así
    que un umbral fijo penalizaría a casi toda la muestra por igual en lugar de
    discriminar. El percentil sí ordena.
    """
    v = val(row, "colchon_flujo_meses")
    if v is None:
        rw = val(row, "runway_meses")
        if rw is None:
            return None, "Sin colchón de flujo ni caja reportada", None
        score, txt = escalonado(rw, [
            (12, 100, "muy holgado"), (6, 85, "cómodo"), (3, 62, "ajustado"),
            (1, 32, "corto"),
        ])
        if score is None:
            score, txt = 10, "crítico"
        return score, f"Runway {txt} ({rw:.1f} meses de gasto cubiertos)", "runway_meses"

    score, txt = escalonado(v, [
        (6, 100, "muy holgado"), (3, 88, "cómodo"), (1, 72, "suficiente"),
        (0, 58, "al límite"), (-1, 40, "consumiendo colchón"),
        (-3, 22, "quemando caja"),
    ])
    if score is None:
        score, txt = 8, "quema severa"
    razon = f"Colchón de flujo {txt} ({v:+.1f} meses de gasto generados en 6 meses)"
    fuente = "colchon_flujo_meses"

    # Un flujo errático exige más colchón que uno estable para el mismo nivel de
    # seguridad, y la volatilidad resultó ser el mejor predictor de asfixia del
    # panel (AUC 0,71). Aquí entra como descuento del colchón, que es donde tiene
    # sentido económico, en lugar de como simple amortiguador de la tendencia.
    pctl_vol = val(row, "pctl_flujo_volatilidad_6m")
    if pctl_vol is not None and pctl_vol < 0.5:
        castigo = (0.5 - pctl_vol) * 2 * cfg.MOD_VOLATILIDAD_PUNTOS
        score = float(np.clip(score - castigo, 0, 100))
        razon += f"; flujo errático, exige más colchón ({-castigo:+.1f} pts)"
        fuente += "+pctl_flujo_volatilidad_6m"

    # Corrección por caja real: solo donde existe el snapshot, y acotada.
    pctl_rw = val(row, "pctl_runway_meses")
    if pctl_rw is not None:
        ajuste = (pctl_rw - 0.5) * 2 * cfg.MOD_RUNWAY_PUNTOS
        score = float(np.clip(score + ajuste, 0, 100))
        rw = val(row, "runway_meses")
        razon += (f"; caja real en el percentil {pctl_rw*100:.0f} de su cohorte"
                  f"{f' ({rw:.1f} meses)' if rw is not None else ''}"
                  f" ({ajuste:+.1f} pts)")
        fuente += "+pctl_runway_meses"
    return score, razon, fuente


def f_deuda_comercial(row):
    """Impagos a proveedores: asfixia ya materializada.

    Es el eje más incriminatorio del panel. No pagar a un proveedor es una
    decisión de la empresa, casi siempre porque no puede.

    Cascada: % de vencimientos impagados -> stock vivo sobre ingresos ->
    constancia de que ha comprado y no debe nada vencido. Se modula por la
    antigüedad del impago y por la concentración de proveedores.
    """
    v = val(row, "pct_impagos_prov_3m")
    if v is not None:
        score, txt = escalonado(v, [
            (5, 100, "muy bajos"), (15, 82, "bajos"), (30, 55, "moderados"),
            (50, 30, "altos"), (80, 12, "severos"),
        ], por_debajo=True)
        if score is None:
            score, txt = 0, "críticos"
        razon = f"Impagos a proveedores {txt} ({v:.1f}% de los vencimientos)"
        fuente = "pct_impagos_prov_3m"
    else:
        s = val(row, "stock_prov_sobre_ingresos")
        if s is not None:
            score, txt = escalonado(s, [
                (0.05, 96, "sin deuda vencida relevante"), (0.25, 78, "deuda vencida baja"),
                (1.0, 52, "deuda vencida moderada"), (3.0, 28, "deuda vencida alta"),
            ], por_debajo=True)
            if score is None:
                score, txt = 8, "deuda vencida crítica"
            razon = f"Proveedores: {txt} ({s:.2f} meses de ingresos atrapados)"
            fuente = "stock_prov_sobre_ingresos"
        else:
            compras = val(row, "compras_acum")
            stock = val(row, "stock_overdue_prov")
            if compras and compras > 0 and stock is not None and stock <= 0:
                score = 92
                razon = "Tiene historial de compras y no debe nada vencido"
                fuente = "compras_acum+stock_overdue_prov"
            else:
                return None, "Sin compras suficientes para medir impagos", None

    # Severidad: deuda envejecida es impago, no retraso de gestión.
    share = val(row, "share_stock_prov_antiguo")
    if share is not None and share > 0 and score > 0:
        castigo = share * cfg.MOD_ANTIGUEDAD_PUNTOS
        score = float(np.clip(score - castigo, 0, 100))
        edad = val(row, "edad_media_stock_prov_dias")
        razon += (f"; {share*100:.0f}% con más de {cfg.DIAS_STOCK_ANTIGUO} días"
                  f"{f' (media {edad:.0f} d)' if edad is not None else ''}"
                  f" ({-castigo:+.1f} pts)")

    # Concentración: no puntúa sola, amplifica un problema ya detectado.
    score, extra = modular_concentracion(row, score, "prov")
    return score, razon + extra, fuente


def f_cobro_clientes(row):
    """Calidad de cobro. Pesa menos que proveedores: que te deban es en parte
    riesgo de tu cliente; no pagar tú es tu propia falta de caja."""
    v = val(row, "pct_clientes_morosos_3m")
    if v is not None:
        score, txt = escalonado(v, [
            (10, 100, "muy sano"), (25, 80, "sano"), (45, 55, "tensionado"),
            (70, 30, "deteriorado"),
        ], por_debajo=True)
        if score is None:
            score, txt = 10, "crítico"
        razon = f"Cobro {txt} ({v:.1f}% de los vencimientos sin cobrar)"
        fuente = "pct_clientes_morosos_3m"
    else:
        s = val(row, "stock_clientes_sobre_ingresos")
        if s is not None:
            score, txt = escalonado(s, [
                (0.05, 96, "sin morosidad relevante"), (0.25, 80, "morosidad baja"),
                (1.0, 55, "morosidad moderada"), (3.0, 30, "morosidad alta"),
            ], por_debajo=True)
            if score is None:
                score, txt = 12, "morosidad crítica"
            razon = f"Clientes: {txt} ({s:.2f} meses de ingresos sin cobrar)"
            fuente = "stock_clientes_sobre_ingresos"
        else:
            ventas = val(row, "ventas_acum")
            stock = val(row, "stock_overdue_clientes")
            if ventas and ventas > 0 and stock is not None and stock <= 0:
                score = 92
                razon = "Tiene historial de ventas y nada pendiente de cobro vencido"
                fuente = "ventas_acum+stock_overdue_clientes"
            else:
                return None, "Sin ventas suficientes para medir el cobro", None

    share = val(row, "share_stock_clientes_antiguo")
    if share is not None and share > 0 and score > 0:
        castigo = share * cfg.MOD_ANTIGUEDAD_PUNTOS
        score = float(np.clip(score - castigo, 0, 100))
        razon += (f"; {share*100:.0f}% con más de {cfg.DIAS_STOCK_ANTIGUO} días "
                  f"({-castigo:+.1f} pts)")

    rr = val(row, "refund_rate_3m")
    if rr is None:
        rr = val(row, "refund_rate")
    if rr is not None and rr > 0.005 and score > 0:
        intensidad = min(1.0, (rr - 0.005) / 0.045)
        castigo = intensidad * cfg.MOD_REFUND_PUNTOS
        score = float(np.clip(score - castigo, 0, 100))
        razon += f"; recibos devueltos {rr*100:.1f}% ({-castigo:+.1f} pts)"

    score, extra = modular_concentracion(row, score, "clientes")
    return score, razon + extra, fuente


def f_eficiencia(row):
    """Velocidad de quema: cuánto gasta por cada euro que ingresa."""
    if bool(row.get("mes_sin_ingresos", 0)):
        return 5, "Mes sin ingresos y con gastos: quema pura de caja", "mes_sin_ingresos"

    v, fuente = val(row, "burn_rate_3m_avg"), "burn_rate_3m_avg"
    if v is None:
        v, fuente = val(row, "burn_rate"), "burn_rate (mes suelto)"
    if v is None:
        return None, "Sin ingresos de referencia para el ratio de gasto", None

    score, txt = escalonado(v, [
        (0.7, 100, "muy eficiente"), (1.0, 86, "sano"), (1.3, 62, "ajustado"),
        (2.0, 35, "en quema"),
    ], por_debajo=True)
    if score is None:
        score, txt = 12, "quema severa"
    return score, f"Gasta {v:.2f}x lo que ingresa ({txt})", fuente


# =============================================================================
# EJE DE TRAYECTORIA
# =============================================================================

def f_trayectoria(row):
    """Dirección del movimiento, con la misma sensibilidad al alza y a la baja.

    Cada señal se convierte en una intensidad firmada en [-1, +1] dividiendo por
    su saturación: por encima de ese valor la señal ya es máxima y un outlier no
    puede dominar. El resultado se amortigua por la volatilidad de la serie, de
    modo que una empresa errática no sostiene una afirmación fuerte de dirección.
    """
    comp, razones = {}, []

    p = val(row, "flujo_pendiente_robusta_6m")
    if p is not None:
        comp["pendiente_flujo"] = np.clip(p / cfg.SAT_PENDIENTE_FLUJO, -1, 1)
        razones.append(f"flujo {'mejorando' if p > 0 else 'cayendo'} "
                       f"({p*100:+.2f} pp/mes)")

    r = val(row, "recuperacion_stock_prov")
    if r is None:
        rec = val(row, "recuperacion_prov")
        r = rec / 100 * cfg.SAT_RECUPERACION_STOCK if rec is not None else None
    if r is not None:
        comp["deuda_comercial_dir"] = np.clip(r / cfg.SAT_RECUPERACION_STOCK, -1, 1)
        razones.append(f"deuda con proveedores {'bajando' if r > 0 else 'subiendo'}")

    m = val(row, "ingresos_momentum_3m")
    if m is not None:
        comp["ingresos_momentum"] = np.clip(m / cfg.SAT_MOMENTUM, -1, 1)
        tope = " (topado)" if abs(m) >= cfg.CAP_MOMENTUM else ""
        razones.append(f"ingresos {m*100:+.0f}% vs trimestre anterior{tope}")

    # Sin ninguna señal informativa no hay trayectoria: la persistencia sola no
    # puede activar el eje, o un 25% de peso entraría como 50 neutro sin dato.
    if not comp:
        return None, "Historia insuficiente para medir trayectoria", None

    pen = 0.0
    for flag, peso, txt in [
        ("persistente_flag_flujo_negativo", 0.5, "3 meses de flujo negativo"),
        ("persistente_flag_stock_prov_antiguo", 0.5, "impago envejecido persistente"),
        ("persistente_flag_tijera", 0.4, "ingresos cayendo y gastos subiendo"),
    ]:
        if row.get(flag, 0) == 1:
            pen -= peso
            razones.append(txt)
    comp["persistencia"] = float(np.clip(pen, -1, 0))

    peso_total = sum(cfg.PESOS_TRAYECTORIA[k] for k in comp)
    direccion = sum(cfg.PESOS_TRAYECTORIA[k] * v for k, v in comp.items()) / peso_total

    if vol := val(row, "flujo_volatilidad_6m"):
        amort = max(cfg.AMORTIGUACION_MIN, 1 / (1 + vol / cfg.VOLATILIDAD_REFERENCIA))
    else:
        amort = 0.85
    score = float(np.clip(50 + 50 * direccion * amort, 0, 100))

    if amort < 0.6:
        razones.append(f"serie volátil, señal amortiguada x{amort:.2f}")
    return score, "; ".join(razones), f"{len(comp)} señales"


# =============================================================================
# MODULADORES
# =============================================================================

def modular_concentracion(row, score, suf):
    """La concentración no es riesgo: es su multiplicador.

    Un impago del 40% duele distinto si viene de un proveedor o de veinte. Solo
    amplifica cuando ya hay un problema (score < 60): penalizar a una empresa
    sana por tener pocos proveedores sería castigar su modelo de negocio.
    """
    top1 = val(row, f"top1_{suf}_share_3m")
    if top1 is None or top1 < cfg.MOD_CONCENTRACION_UMBRAL or score >= 60:
        return score, ""
    intensidad = (top1 - cfg.MOD_CONCENTRACION_UMBRAL) / (1 - cfg.MOD_CONCENTRACION_UMBRAL)
    castigo = intensidad * cfg.MOD_CONCENTRACION_PUNTOS * (1 - score / 60)
    nuevo = float(np.clip(score - castigo, 0, 100))
    return nuevo, (f"; riesgo concentrado en una contraparte "
                   f"({top1*100:.0f}% del total, {-castigo:+.1f} pts)")


def modular_apalancamiento(row, score):
    """Deuda financiera: corrección acotada, no eje con peso fijo.

    El servicio de deuda sale de las categorías `debt_repayment` e
    `interest_charge` y existe todos los meses (718 empresas). El snapshot de
    `deuda_sobre_ingresos` solo cubre el último mes: se usa como refuerzo, no
    como fuente única, y nunca se propaga al pasado.
    """
    ds = val(row, "debt_service_3m")
    if ds is None:
        ds = val(row, "debt_service")
    d = val(row, "deuda_sobre_ingresos")
    if ds is None and d is None:
        return score, None

    m = cfg.MOD_APALANCAMIENTO_PUNTOS
    if ds is not None:
        if ds == 0:
            if d is None or d == 0:
                ajuste, txt = m * 0.3, "Sin servicio de deuda ni deuda viva"
            elif d < 0.75:
                ajuste, txt = m * 0.1, f"Sin pagos de deuda en el trimestre (deuda viva {d:.2f}x)"
            else:
                ajuste, txt = -m * 0.4, f"Deuda viva alta sin servicio visible ({d:.2f}x)"
        elif ds < 0.10:
            ajuste, txt = m * 0.2, f"Servicio de deuda controlado ({ds*100:.1f}% de ingresos)"
        elif ds < 0.25:
            ajuste, txt = 0.0, f"Servicio de deuda moderado ({ds*100:.1f}% de ingresos)"
        elif ds < 0.50:
            ajuste, txt = -m * 0.6, f"Servicio de deuda alto ({ds*100:.1f}% de ingresos)"
        else:
            ajuste, txt = -m, f"Servicio de deuda muy alto ({ds*100:.1f}% de ingresos)"
    else:
        if d == 0:
            ajuste, txt = m * 0.3, "Sin deuda bancaria viva"
        elif d < 0.25:
            ajuste, txt = m * 0.2, f"Deuda controlada ({d:.2f}x ingresos anuales)"
        elif d < 0.75:
            ajuste, txt = 0.0, f"Deuda moderada ({d:.2f}x ingresos anuales)"
        elif d < 1.5:
            ajuste, txt = -m * 0.6, f"Deuda alta ({d:.2f}x ingresos anuales)"
        else:
            ajuste, txt = -m, f"Deuda muy alta ({d:.2f}x ingresos anuales)"

    if bool(row.get("caja_negativa_flag", 0)):
        ajuste -= m * 0.5
        txt += "; saldo bancario en negativo"
    return float(np.clip(score + ajuste, 0, 100)), f"{txt} ({ajuste:+.1f} pts)"


# =============================================================================
# SCORE MENSUAL
# =============================================================================

FACTORES = {
    "liquidez": f_liquidez,
    "colchon": f_colchon,
    "deuda_comercial": f_deuda_comercial,
    "eficiencia": f_eficiencia,
    "cobro_clientes": f_cobro_clientes,
    "trayectoria": f_trayectoria,
}


def atribuir_cambio(panel):
    """Descompone el cambio de score respecto al mes anterior, eje por eje.

    El score es `sum(w_i/W * s_i)`, así que el cambio se descompone de forma
    exacta y sin residuo separando dos efectos por eje:

        efecto_nivel  = w_i,t-1 * (s_i,t - s_i,t-1)    el eje se movió
        efecto_mezcla = (w_i,t - w_i,t-1) * s_i,t      su peso cambió

    La separación no es cosmética, es la trampa que hay que evitar al contestar
    "por qué ha cambiado": cuando aparece un eje porque llegó dato nuevo, el
    score se mueve SIN que la empresa haya cambiado. Sumando los dos efectos sin
    distinguirlos, el sistema diría "ha mejorado" cuando lo que pasó es que
    empezamos a verla. `cambio_real` es la parte atribuible al comportamiento;
    `cambio_cobertura`, la atribuible a la información.
    """
    ejes = list(FACTORES)
    out = {f"aporte_{e}": np.full(len(panel), np.nan) for e in ejes}
    out["cambio_real"] = np.full(len(panel), np.nan)
    out["cambio_cobertura"] = np.full(len(panel), np.nan)
    out["delta_score"] = np.full(len(panel), np.nan)
    out["motivo_cambio"] = np.array([""] * len(panel), dtype=object)

    detalles = panel["detalle"].to_numpy()
    scores = panel["score_mensual"].to_numpy(dtype=float)
    empresas = panel["company_id"].to_numpy()

    for i in range(1, len(panel)):
        if empresas[i] != empresas[i - 1]:
            continue
        if np.isnan(scores[i]) or np.isnan(scores[i - 1]):
            continue
        ahora, antes = detalles[i], detalles[i - 1]
        real = mezcla = 0.0
        aportes = {}
        for e in ejes:
            a, b = ahora.get(e, {}), antes.get(e, {})
            w_a, w_b = a.get("peso_efectivo", 0.0) or 0.0, b.get("peso_efectivo", 0.0) or 0.0
            s_a, s_b = a.get("score"), b.get("score")
            e_nivel = w_b * (s_a - s_b) if (s_a is not None and s_b is not None) else 0.0
            e_mezcla = (w_a - w_b) * (s_a if s_a is not None else 0.0)
            aportes[e] = e_nivel + e_mezcla
            out[f"aporte_{e}"][i] = round(aportes[e], 3)
            real += e_nivel
            mezcla += e_mezcla

        out["delta_score"][i] = round(scores[i] - scores[i - 1], 2)
        out["cambio_real"][i] = round(real, 2)
        out["cambio_cobertura"][i] = round(mezcla, 2)

        # Redacción: los dos ejes que más explican el movimiento.
        top = sorted(aportes.items(), key=lambda kv: -abs(kv[1]))[:2]
        trozos = [f"{e} {v:+.1f}" for e, v in top if abs(v) >= 0.5]
        if trozos:
            txt = "; ".join(trozos)
            if abs(mezcla) > abs(real):
                txt += " (cambio dominado por datos nuevos, no por comportamiento)"
            out["motivo_cambio"][i] = txt

    return pd.DataFrame(out, index=panel.index)


def detectar_giro(panel):
    """Caída del score medida en sigmas de la propia empresa.

    Los canales de cola no pueden ver el caso "de 82 a 68": esa empresa no está
    en el quintil adverso de nada, porque sigue siendo mejor que la mayoría. Lo
    que sí es anómalo es respecto a SÍ MISMA, y eso exige dos cosas:

    1. Suavizar antes de comparar (mediana móvil de 3), porque el score mensual
       es ruidoso y un único mes malo produciría un falso giro.
    2. Normalizar por la volatilidad histórica del propio score. La empresa
       mediana recorre 41,7 puntos, así que "ha caído 14" no significa nada por
       sí solo: significa mucho si su score nunca se mueve, y nada si oscila 40.
    """
    g = panel.groupby("company_id", sort=False)["score_mensual"]
    suave = g.transform(lambda s: s.rolling(cfg.GIRO_SUAVIZADO, min_periods=2).median())
    panel["score_suavizado"] = suave.round(2)

    # Volatilidad propia, con el mes corriente excluido para no diluirse a sí mismo.
    vol = (panel.groupby("company_id", sort=False)["score_mensual"]
           .transform(lambda s: s.shift(1).rolling(cfg.GIRO_VOL_VENTANA,
                                                   min_periods=4).std()))
    vol = vol.clip(lower=cfg.GIRO_VOL_MIN)
    panel["score_volatilidad"] = vol.round(2)

    referencia = suave.groupby(panel["company_id"], sort=False).shift(cfg.GIRO_VENTANA)
    caida = referencia - suave
    panel["caida_score_3m"] = caida.round(2)
    panel["giro_sigmas"] = (caida / vol).round(2)

    panel["senal_giro"] = (
        (panel["giro_sigmas"] >= cfg.GIRO_SIGMAS)
        & (caida >= cfg.GIRO_PUNTOS_MIN)
        & (panel["score_mensual"] >= cfg.GIRO_NIVEL_MIN)
    ).fillna(False).astype(int)
    return panel


def clasificar_bache(panel):
    """Bache de tesorería o caída estructural.

    La diferencia no está en el tamaño de la caída sino en si va a sostenerse, y
    los tres criterios están elegidos por lo que predijeron el desenlace real
    (ver config, sección "Bache o caída"). El criterio dominante es la
    volatilidad propia del score: la misma caída de 10 puntos significa mucho en
    una empresa cuyo score nunca se mueve y casi nada en una que oscila 40.

    Se acumulan criterios en vez de exigirlos todos porque cada uno tiene
    cobertura distinta: `stock_prov_sobre_ingresos` falta en un tercio de las
    filas, y exigirlo convertiría en "bache" todo lo que no podemos ver.
    """
    g = panel.groupby("company_id", sort=False)
    cayendo = panel["senal_giro"] == 1

    c_estable = (panel["score_volatilidad"] <= cfg.BACHE_VOL_ESTABLE).fillna(False)
    c_comportamiento = (panel["cambio_real"] <= cfg.BACHE_CAMBIO_REAL).fillna(False)
    c_deuda = (panel["stock_prov_sobre_ingresos"] > cfg.BACHE_STOCK_PROV).fillna(False)
    panel["criterios_estructurales"] = (c_estable.astype(int)
                                        + c_comportamiento.astype(int)
                                        + c_deuda.astype(int))

    # Solo dos clases. Probé una intermedia ("deterioro_probable", la caída que se
    # sostiene 2 meses pero no cumple los criterios estructurales) y medida contra
    # el desenlace se comportaba igual que un bache: +4,71 puntos a 3 meses y 55,1%
    # de recuperación, frente a +4,50 y 54,5% del bache. Una etiqueta que suena a
    # aviso sobre casos que se recuperan la mitad de las veces es peor que no tenerla.
    estructural = panel["criterios_estructurales"] >= cfg.BACHE_MIN_CRITERIOS
    panel["naturaleza_caida"] = np.select(
        [~cayendo, estructural], ["", "caida_estructural"], default="bache")

    # Texto para la explicación: qué criterio se cumple, no solo la etiqueta.
    motivos = pd.Series("", index=panel.index)
    motivos = motivos.where(~c_estable, motivos + "; su score no suele moverse, "
                            "así que esta caída es un cambio real")
    motivos = motivos.where(~c_comportamiento, motivos + "; la caída viene de su "
                            "comportamiento, no de datos nuevos")
    motivos = motivos.where(~c_deuda, motivos + "; ya hay deuda comercial vencida viva")
    panel["motivo_naturaleza"] = motivos.str.lstrip("; ").where(cayendo, "")
    return panel


def canal_riesgo(panel, disparadores, binarios=()):
    """Riesgo acumulado de un canal: suma ponderada de disparadores de cola.

    Devuelve la intensidad normalizada (0-1 sobre el peso máximo alcanzable con
    los datos disponibles en cada fila) y el texto de los disparadores activos.
    Normalizar por el peso DISPONIBLE y no por el total evita que a una empresa
    con pocos datos le baje el riesgo por el simple hecho de faltarle columnas.
    """
    peso_activo = pd.Series(0.0, index=panel.index)
    peso_disponible = pd.Series(0.0, index=panel.index)
    textos = pd.Series("", index=panel.index)

    for col, umbral, peso, texto in disparadores:
        if col not in panel.columns:
            continue
        hay = panel[col].notna()
        dispara = hay & (panel[col] <= umbral)
        peso_disponible += hay * peso
        peso_activo += dispara * peso
        textos = textos.where(~dispara, textos + "; " + texto)

    for col, peso, texto in binarios:
        if col not in panel.columns:
            continue
        dispara = panel[col].fillna(0) == 1
        peso_disponible += peso
        peso_activo += dispara * peso
        textos = textos.where(~dispara, textos + "; " + texto)

    intensidad = np.where(peso_disponible > 0, peso_activo / peso_disponible, np.nan)
    return pd.Series(intensidad, index=panel.index), textos.str.lstrip("; ")


def marcar_alertas(panel):
    """Dos capas separadas, porque responden preguntas distintas.

    senal_nivel: el score mensual ya está en zona de riesgo. Es útil para actuar
        hoy, pero no anticipa: cuando salta, el problema ya es presente.
    senal_anticipacion: la empresa AÚN NO ha caído de nivel y sin embargo acumula
        disparadores de cola en los canales que sí predicen. Es la única capa que
        compra tiempo, y por eso exige score_mensual >= ALERTA_NIVEL_CRITICO: en
        cuanto el nivel cae, la observación deja de ser una anticipación.

    La sostenibilidad (ALERTA_MESES_SOSTENIDO) se exige sobre el canal, no sobre
    el nivel: es lo que separa un giro real de un mes atípico.
    """
    panel = panel.sort_values(["company_id", "year_month"]).copy()

    r_imp, t_imp = canal_riesgo(panel, cfg.DISPARADORES_IMPAGO,
                               cfg.DISPARADORES_BINARIOS_IMPAGO)
    r_asf, t_asf = canal_riesgo(panel, cfg.DISPARADORES_ASFIXIA)
    panel["riesgo_impago_comercial"] = r_imp.round(3)
    panel["riesgo_asfixia_caja"] = r_asf.round(3)

    disp_imp = (r_imp >= cfg.UMBRAL_CANAL).fillna(False)
    disp_asf = (r_asf >= cfg.UMBRAL_CANAL).fillna(False)
    cualquiera = disp_imp | disp_asf

    sostenido = (cualquiera.groupby(panel["company_id"], sort=False)
                 .transform(lambda s: s.rolling(cfg.ALERTA_MESES_SOSTENIDO,
                                                min_periods=cfg.ALERTA_MESES_SOSTENIDO).sum())
                 >= cfg.ALERTA_MESES_SOSTENIDO).fillna(False)

    nivel = panel["score_mensual"]
    nivel_ok = (nivel >= cfg.ALERTA_NIVEL_CRITICO).fillna(False)
    panel["senal_nivel"] = (nivel < cfg.ALERTA_NIVEL_CRITICO).fillna(False).astype(int)

    # Los canales de cola y el giro se mantienen SEPARADOS a propósito, aunque los
    # dos sean anticipación. Al fusionarlos en una sola señal, el lift de los
    # canales sobre eventos de severidad se hundía de 1,49 a 1,04 y la activación
    # subía del 40% al 75%: el giro metía empresas que no van a ese evento.
    #
    # No es que el giro falle, es que responde a otra pregunta y se valida contra
    # otro desenlace. Los canales predicen "esta empresa llegará a impago severo o
    # asfixia" (lift 1,49). El giro predice "esta empresa seguirá cayendo"
    # (caída estructural: -2,58 puntos de score a 6 meses, frente a +5,27 del
    # bache). Sumarlos convierte dos señales buenas en una mediocre.
    giro = (panel["senal_giro"] == 1)
    panel["senal_anticipacion"] = (sostenido & nivel_ok).astype(int)
    panel["alerta_temprana"] = ((panel["senal_nivel"] == 1)
                                | (panel["senal_anticipacion"] == 1)
                                | giro).astype(int)
    panel["alerta_tipo"] = np.select(
        [panel["senal_anticipacion"] == 1, giro, panel["senal_nivel"] == 1],
        ["anticipacion", "giro", "nivel"], default="")
    panel["alerta_canal"] = np.select(
        [disp_imp & disp_asf, disp_imp, disp_asf, giro],
        ["impago+asfixia", "impago_comercial", "asfixia_caja", "giro_propio"],
        default="")

    ya_en_problema = sum(panel.get(f, 0) == 1 for f in (
        "persistente_flag_flujo_negativo", "persistente_flag_stock_prov_antiguo",
        "persistente_flag_estres_prov")) > 0
    panel["alerta_severidad"] = np.select(
        [panel["alerta_temprana"] == 0,
         (panel["senal_nivel"] == 1) & ya_en_problema,
         panel["senal_nivel"] == 1,
         disp_imp & disp_asf],
        ["", "critica", "nivel_bajo", "doble_canal"], default="vigilancia")

    t_giro = pd.Series("", index=panel.index)
    t_giro = t_giro.where(~giro, (
        "cae " + panel["caida_score_3m"].round(0).astype("Int64").astype(str)
        + " puntos en 3 meses, " + panel["giro_sigmas"].round(1).astype(str)
        + " sigmas de su propia variabilidad"))
    motivo = (t_imp.where(disp_imp, "") + "|" + t_asf.where(disp_asf, "")
              + "|" + t_giro).str.strip("|").str.replace("||", "|", regex=False)
    panel["motivo_alerta"] = motivo.where(panel["alerta_temprana"] == 1, "")
    vacio = (panel["alerta_temprana"] == 1) & (panel["motivo_alerta"] == "")
    panel.loc[vacio, "motivo_alerta"] = "score mensual en zona de riesgo"
    return panel


def score_mes(row):
    crudos = {k: fn(row) for k, fn in FACTORES.items()}
    activos = {k: v for k, v in crudos.items() if v[0] is not None}

    detalle = {
        k: {
            "score": round(float(crudos[k][0]), 1) if crudos[k][0] is not None else None,
            "peso_nominal": cfg.PESOS[k],
            "peso_efectivo": 0.0,
            "aplicable": k in activos,
            "fuente": crudos[k][2],
            "razon": crudos[k][1],
        }
        for k in FACTORES
    }
    if not activos:
        return pd.Series({
            "score_mensual": np.nan, "score_trayectoria": np.nan,
            "peso_cubierto": 0.0, "n_componentes_validos": 0,
            "detalle": detalle,
        })

    peso_total = sum(cfg.PESOS[k] for k in activos)
    for k in activos:
        detalle[k]["peso_efectivo"] = round(cfg.PESOS[k] / peso_total, 4)

    if peso_total < cfg.MIN_PESO_CUBIERTO_SCORE:
        return pd.Series({
            "score_mensual": np.nan,
            "score_trayectoria": (float(activos["trayectoria"][0])
                                  if "trayectoria" in activos else np.nan),
            "peso_cubierto": round(peso_total, 3),
            "n_componentes_validos": len(activos),
            "detalle": detalle,
        })

    score = sum(cfg.PESOS[k] * activos[k][0] for k in activos) / peso_total
    score, razon_apal = modular_apalancamiento(row, score)
    detalle["_apalancamiento"] = {
        "aplicable": razon_apal is not None,
        "razon": razon_apal or "Sin snapshot de deuda para este mes",
    }

    return pd.Series({
        "score_mensual": round(float(score), 2),
        "score_trayectoria": (float(activos["trayectoria"][0])
                              if "trayectoria" in activos else np.nan),
        "peso_cubierto": round(peso_total, 3),
        "n_componentes_validos": len(activos),
        "detalle": detalle,
    })


# =============================================================================
# AGREGACIÓN TEMPORAL
# =============================================================================

def pesos_mes(h):
    """Recencia x confianza x cobertura. Un mes antiguo con datos perfectos pesa
    más que uno reciente con datos dudosos."""
    n = len(h)
    w_recencia = np.exp(-np.log(2) * (n - 1 - np.arange(n)) / cfg.HALF_LIFE_MONTHS)
    w_confianza = h["confianza"].map(cfg.PESO_CONFIANZA).fillna(0.5).to_numpy()
    w_cobertura = h["peso_cubierto"].fillna(0.0).clip(0, 1).to_numpy()
    return w_recencia * w_confianza * w_cobertura


def agregar(hist):
    """Media exponencial ponderada. Devuelve el score y la evidencia efectiva."""
    h = hist.dropna(subset=["score_mensual"])
    if h.empty:
        return np.nan, 0.0
    w = pesos_mes(h)
    if w.sum() == 0:
        return np.nan, 0.0
    return float((h["score_mensual"].to_numpy() * (w / w.sum())).sum()), float(w.sum())


def contraer(score, evidencia, prior):
    """Contracción empírica hacia el comportamiento típico.

    Una empresa con un único mes de baja confianza no puede sostener un 95 ni un
    11: la media ponderada de un solo punto no es una estimación, es ese punto.
    La contracción hace explícito que con poca evidencia lo honesto es acercarse
    a la media, y deja de ser necesario filtrar a mano los casos de 1 mes.
    """
    if pd.isna(score):
        return np.nan
    k = cfg.SHRINKAGE_EVIDENCIA
    return float((evidencia * score + k * prior) / (evidencia + k))


def confianza_final(hist):
    evaluados = hist.dropna(subset=["score_mensual"])
    if evaluados.empty:
        return "baja", 0.0, 0.0
    cobertura_media = float(evaluados["peso_cubierto"].mean())
    cobertura_reciente = float(evaluados["peso_cubierto"].tail(6).mean())
    meses_evaluados = len(evaluados)
    meses_activos = int(hist["mes_activo"].sum()) if "mes_activo" in hist else meses_evaluados

    if (cobertura_media >= 0.80 and cobertura_reciente >= 0.80
            and meses_evaluados >= cfg.MIN_MESES_HISTORIA
            and meses_activos >= cfg.MIN_MESES_HISTORIA):
        nivel = "alta"
    elif (cobertura_media >= 0.65 and cobertura_reciente >= 0.60
          and meses_evaluados >= 6 and meses_activos >= 6):
        nivel = "media"
    else:
        nivel = "baja"
    return nivel, cobertura_media, cobertura_reciente


def etiqueta_tendencia(hist):
    """Se apoya en el eje de trayectoria, no en la diferencia de scores totales.

    Comparar bloques del score agregado confunde un cambio de dirección con una
    mejora de cobertura: si en el mes 10 aparece un factor nuevo, el score salta
    sin que la empresa haya cambiado. El eje de trayectoria mide solo dirección.
    """
    t = hist["score_trayectoria"].dropna()
    if len(t) < 3:
        return "SIN DATOS"
    reciente = float(t.tail(3).mean())
    if reciente > 58:
        return "MEJORANDO"
    if reciente < 42:
        return "DETERIORANDO"
    return "ESTABLE"


def alertas(hist):
    """Señales accionables, derivadas de persistencia y no de un mes suelto."""
    if hist.empty:
        return []
    last = hist.iloc[-1]
    out = []

    # El giro va primero y con su propio encabezado: es el titular del producto,
    # y se pierde si queda mezclado con el motivo genérico de la capa de nivel.
    giros = hist[hist["senal_giro"] == 1]
    if len(giros):
        ult_giro = giros.iloc[-1]
        etiqueta = ("CAÍDA ESTRUCTURAL" if ult_giro["naturaleza_caida"] == "caida_estructural"
                    else "BACHE")
        out.append(f"{etiqueta}: pierde {abs(ult_giro['caida_score_3m']):.0f} puntos en "
                   f"3 meses ({ult_giro['giro_sigmas']:.1f} sigmas de su propia "
                   f"variabilidad), visto en {ult_giro['year_month']}"
                   + (f". {ult_giro['motivo_naturaleza']}"
                      if ult_giro["motivo_naturaleza"] else ""))

    if last.get("motivo_alerta"):
        out.append(f"ALERTA TEMPRANA: {last['motivo_alerta']}")
    if last.get("motivo_cambio"):
        out.append(f"CAMBIO ESTE MES ({last['delta_score']:+.1f} pts): "
                   f"{last['motivo_cambio']}")
    for flag, txt in [
        ("persistente_flag_flujo_negativo", "Tres meses consecutivos de flujo de caja negativo"),
        ("persistente_flag_estres_prov", "Impagos a proveedores sobre el 30% durante tres meses"),
        ("persistente_flag_estres_clientes", "Más del 30% de los vencimientos sin cobrar en tres meses"),
        ("persistente_flag_tijera", "Ingresos cayendo mientras el gasto sube, de forma sostenida"),
        ("persistente_flag_stock_prov_antiguo", "Más de la mitad del impago supera los 90 días"),
    ]:
        if last.get(flag, 0) == 1:
            out.append(txt)
    edad = last.get("edad_media_stock_prov_dias")
    if pd.notna(edad) and edad > 180:
        out.append(f"Deuda con proveedores de {edad:.0f} días de antigüedad media")
    rw = last.get("runway_meses")
    if pd.notna(rw) and rw < 1:
        out.append(f"Caja por debajo de un mes de gasto ({rw:.1f})")
    top1 = last.get("top1_clientes_share_3m")
    if pd.notna(top1) and top1 > 0.7:
        out.append(f"El {top1*100:.0f}% de las ventas depende de un solo cliente")
    return out


# =============================================================================
# MAIN
# =============================================================================

def vista_grupo(scores, panel):
    """Agrega a nivel de grupo SIN promediar a ciegas.

    El cálculo canónico es por empresa y esto es una vista encima, nunca al
    revés: agregar es una proyección que no se puede deshacer, así que si el
    motor puntuara grupos ya no habría forma de bajar a la empresa.

    Los datos dicen que el grupo importa pero no basta: explica el 61,9% de la
    varianza del score, y sin embargo el 33,5% de los grupos tiene a la vez una
    empresa MEJORANDO y otra DETERIORANDO, y 13 grupos mezclan una SALUDABLE con
    una CRÍTICA. Una media aritmética cancelaría exactamente la señal que el reto
    pide detectar. Por eso la vista expone tres cosas a la vez:

      score_grupo       media ponderada por evidencia (la foto agregada)
      score_peor        la peor empresa del grupo (lo que de verdade decide un
                        riesgo de crédito: un grupo responde por sus filiales)
      dispersion        desviación típica interna, y el flag de que el agregado
                        está escondiendo un problema
    """
    s = scores.dropna(subset=["score_final", "group_id"]).copy()
    if s.empty:
        return pd.DataFrame()

    def agg(g):
        w = g["evidencia_efectiva"].clip(lower=0.01)
        n_alerta = int(g["alerta_temprana"].sum())
        return pd.Series({
            "n_empresas": len(g),
            "score_grupo": round(float((g["score_final"] * w).sum() / w.sum()), 2),
            "score_peor": round(float(g["score_final"].min()), 2),
            "score_mejor": round(float(g["score_final"].max()), 2),
            "dispersion_interna": round(float(g["score_final"].std(ddof=0)), 2),
            "empresa_peor": g.loc[g["score_final"].idxmin(), "company_id"],
            "empresas_con_alerta": n_alerta,
            "empresas_con_giro": int(g["giro_detectado"].sum()),
            "tendencias_opuestas": int({"MEJORANDO", "DETERIORANDO"}
                                       .issubset(set(g["tendencia"]))),
            "meses_evaluados_min": int(g["meses_evaluados"].min()),
            "confianza_peor": ("baja" if (g["confianza"] == "baja").any()
                               else "media" if (g["confianza"] == "media").any()
                               else "alta"),
        })

    v = s.groupby("group_id").apply(agg, include_groups=False).reset_index()
    v["clasificacion_grupo"] = v["score_grupo"].map(cfg.clasificar)
    v["clasificacion_peor"] = v["score_peor"].map(cfg.clasificar)
    # El flag que justifica que la vista de grupo no sustituya a la de empresa.
    v["agregado_esconde_problema"] = (
        (v["clasificacion_grupo"] != v["clasificacion_peor"])
        & (v["score_peor"] < cfg.ALERTA_NIVEL_CRITICO)
    ).astype(int)
    return v.sort_values("score_grupo")


def run():
    cfg.asegurar_dirs()
    panel = pd.read_csv(cfg.PANEL_PATH)
    panel["year_month"] = pd.PeriodIndex(panel["year_month"], freq="M")

    if cfg.EXCLUIR_MES_PARCIAL_DEL_SCORE and "mes_parcial" in panel.columns:
        n = int((panel["mes_parcial"] == 1).sum())
        panel = panel[panel["mes_parcial"] == 0].copy()
        print(f"Excluidas {n:,} filas de meses parciales (flujos truncados).")

    print("Calculando score mensual...")
    panel = panel.join(panel.apply(score_mes, axis=1))
    panel = panel.sort_values(["company_id", "year_month"])

    print("Atribuyendo el cambio mes a mes...")
    panel = panel.join(atribuir_cambio(panel))

    print("Detectando giros y separando bache de caída...")
    panel = detectar_giro(panel)
    panel = clasificar_bache(panel)

    print("Marcando alertas tempranas...")
    panel = marcar_alertas(panel)

    print("Agregando por empresa...")
    crudos = {}
    for cid, hist in panel.groupby("company_id"):
        crudos[cid] = (hist, *agregar(hist))

    # El prior se estima solo con empresas de historia suficiente: la referencia
    # no puede contaminarse con los casos que precisamente hay que contraer.
    #
    # Y se congela en disco, por el mismo motivo que la rejilla de percentiles:
    # si se recalcula con la población que toque puntuar, la misma empresa saca
    # notas distintas según con quién la evalúen. Medido sobre 70 empresas
    # sueltas, sin congelar era la ÚNICA fuente de desviación que quedaba.
    solidas = [s for h, s, e in crudos.values()
               if pd.notna(s) and h["score_mensual"].notna().sum() >= cfg.MIN_MESES_HISTORIA]
    prior_local = float(np.median(solidas)) if solidas else 50.0

    if cfg.USAR_REFERENCIA_PRIOR and cfg.PRIOR_REF_PATH.exists():
        guardado = json.loads(cfg.PRIOR_REF_PATH.read_text(encoding="utf-8"))
        prior = float(guardado["prior"])
        print(f"Prior de contracción: {prior:.2f} (congelado en "
              f"{cfg.PRIOR_REF_PATH.name}, calibrado con "
              f"{guardado['n_empresas']:,} empresas; local sería {prior_local:.2f})")
    else:
        prior = prior_local
        print(f"Prior de contracción: {prior:.2f} "
              f"(mediana de {len(solidas):,} empresas con >= {cfg.MIN_MESES_HISTORIA} meses)")
        if cfg.USAR_REFERENCIA_PRIOR:
            cfg.PRIOR_REF_PATH.write_text(
                json.dumps({"prior": prior, "n_empresas": len(solidas),
                            "min_meses": cfg.MIN_MESES_HISTORIA}),
                encoding="utf-8")
            print(f"    prior congelado en {cfg.PRIOR_REF_PATH.name}")

    filas, explicaciones = [], {}
    for cid, (hist, score, evidencia) in crudos.items():
        validos = hist["score_mensual"].notna()
        ajustado = contraer(score, evidencia, prior)
        conf, cobertura_media, cobertura_reciente = confianza_final(hist)
        activas = hist["alerta_temprana"] == 1
        alerta_activa = int(activas.any())
        primera_alerta = str(hist.loc[activas, "year_month"].iloc[0]) if alerta_activa else None
        severidad = hist.loc[activas, "alerta_severidad"].iloc[-1] if alerta_activa else ""
        ult = hist.iloc[-1]
        giros = hist[hist["senal_giro"] == 1]

        fila = {
            "company_id": cid,
            "score_final": round(ajustado, 2) if pd.notna(ajustado) else np.nan,
            "score_bruto": round(score, 2) if pd.notna(score) else np.nan,
            "clasificacion": cfg.clasificar(ajustado) if pd.notna(ajustado) else "NO EVALUABLE",
            "tendencia": etiqueta_tendencia(hist),
            "score_trayectoria": (round(float(hist["score_trayectoria"].dropna().tail(3).mean()), 2)
                                  if hist["score_trayectoria"].notna().any() else np.nan),
            "alerta_temprana": alerta_activa,
            "alerta_severidad": severidad,
            "alerta_activa_ultimo_mes": int(bool(hist["alerta_temprana"].iloc[-1] == 1)),
            "primera_alerta": primera_alerta,
            # Preguntas 3 y 4 del reto: quién empieza a torcerse, y si es bache.
            "giro_detectado": int(len(giros) > 0),
            "primer_giro": str(giros["year_month"].iloc[0]) if len(giros) else None,
            "naturaleza_caida": (giros["naturaleza_caida"].iloc[-1] if len(giros) else ""),
            "caida_score_3m": (float(giros["caida_score_3m"].iloc[-1]) if len(giros) else np.nan),
            "giro_sigmas": (float(giros["giro_sigmas"].iloc[-1]) if len(giros) else np.nan),
            # Pregunta 5: por qué ha cambiado desde el mes pasado.
            "delta_score_ultimo_mes": (float(ult["delta_score"])
                                       if pd.notna(ult["delta_score"]) else np.nan),
            "motivo_cambio_ultimo_mes": ult["motivo_cambio"] or "",
            "cambio_real_ultimo_mes": (float(ult["cambio_real"])
                                       if pd.notna(ult["cambio_real"]) else np.nan),
            "cambio_cobertura_ultimo_mes": (float(ult["cambio_cobertura"])
                                            if pd.notna(ult["cambio_cobertura"]) else np.nan),
            "group_id": ult.get("group_id"),
            "meses_evaluados": int(validos.sum()),
            "meses_activos": int(hist["mes_activo"].sum()) if "mes_activo" in hist else int(validos.sum()),
            "evidencia_efectiva": round(evidencia, 3),
            "cobertura_media": round(cobertura_media, 3),
            "cobertura_reciente": round(cobertura_reciente, 3),
            "confianza": conf,
            "apto_ranking": int(int(validos.sum()) >= 6 and conf != "baja"),
            "score_ultimo_mes": (float(hist.loc[validos, "score_mensual"].iloc[-1])
                                 if validos.any() else np.nan),
        }
        filas.append(fila)

        if validos.any():
            ultimo = hist[validos].iloc[-1]
            explicaciones[str(cid)] = {
                "year_month": str(ultimo["year_month"]),
                "score_final": fila["score_final"],
                "score_bruto": fila["score_bruto"],
                "clasificacion": fila["clasificacion"],
                "tendencia": fila["tendencia"],
                "score_trayectoria": fila["score_trayectoria"],
                "confianza": fila["confianza"],
                "evidencia_efectiva": fila["evidencia_efectiva"],
                "cobertura_media": fila["cobertura_media"],
                "cobertura_reciente": fila["cobertura_reciente"],
                "peso_cubierto": ultimo["peso_cubierto"],
                "n_componentes_validos": int(ultimo["n_componentes_validos"]),
                "apto_ranking": fila["apto_ranking"],
                "factores": ultimo["detalle"],
                "cambio_vs_mes_anterior": {
                    "delta_score": fila["delta_score_ultimo_mes"],
                    "por_comportamiento": fila["cambio_real_ultimo_mes"],
                    "por_datos_nuevos": fila["cambio_cobertura_ultimo_mes"],
                    "explicacion": fila["motivo_cambio_ultimo_mes"],
                    "aportes": {e: (float(ultimo[f"aporte_{e}"])
                                    if pd.notna(ultimo.get(f"aporte_{e}")) else None)
                                for e in FACTORES},
                },
                "giro": {
                    "detectado": bool(fila["giro_detectado"]),
                    "primer_giro": fila["primer_giro"],
                    "naturaleza": fila["naturaleza_caida"],
                    "por_que": (giros["motivo_naturaleza"].iloc[-1]
                                if len(giros) else ""),
                    "caida_puntos_3m": fila["caida_score_3m"],
                    "sigmas_propias": fila["giro_sigmas"],
                },
                "alertas": alertas(hist[validos]),
            }

    scores = pd.DataFrame(filas).sort_values(
        ["apto_ranking", "score_final"], ascending=[False, False])

    grupos = vista_grupo(scores, panel)

    panel.drop(columns=["detalle"]).to_csv(cfg.SCORES_MENSUAL_PATH, index=False)
    scores.to_csv(cfg.SCORES_PATH, index=False)
    if not grupos.empty:
        grupos.to_csv(cfg.SCORES_GRUPO_PATH, index=False)
    cfg.EXPLAIN_PATH.write_text(
        json.dumps(explicaciones, indent=2, ensure_ascii=False, default=str),
        encoding="utf-8")

    resumen(panel, scores, grupos)
    print(f"\nGuardado en {cfg.SCORES_PATH}, {cfg.SCORES_MENSUAL_PATH}, "
          f"{cfg.EXPLAIN_PATH}, {cfg.SCORES_GRUPO_PATH}")
    return scores


def resumen(panel, scores, grupos=None):
    cols = ["company_id", "score_final", "score_bruto", "clasificacion", "tendencia",
            "confianza", "meses_evaluados", "evidencia_efectiva"]
    aptas = scores[scores["apto_ranking"] == 1]

    print(f"\n=== COBERTURA DE FACTORES (sobre {len(panel):,} filas-mes) ===")
    for k in FACTORES:
        disp = panel["detalle"].map(lambda d: d.get(k, {}).get("aplicable", False))
        print(f"  {k:18s} peso {cfg.PESOS[k]:.2f}   aplicable en {disp.mean():6.1%}")
    print(f"  {'peso cubierto medio':18s}          "
          f"{panel['peso_cubierto'].mean():.3f}")
    print(f"  meses con score: {int(panel['score_mensual'].notna().sum()):,} "
          f"de {len(panel):,} ({panel['score_mensual'].notna().mean():.1%})")

    print(f"\n=== TOP 5 SALUDABLES (con evidencia suficiente) ===")
    print(aptas.head(5)[cols].to_string(index=False))
    print(f"\n=== TOP 5 CRÍTICOS (con evidencia suficiente) ===")
    print(aptas.dropna(subset=["score_final"]).tail(5)[cols].to_string(index=False))

    print("\n=== DISTRIBUCIÓN ===")
    print(scores["clasificacion"].value_counts().to_string())
    print(scores["tendencia"].value_counts().to_string())
    print(f"\nEmpresas aptas para ranking: {int(scores['apto_ranking'].sum()):,} "
          f"de {len(scores):,}")
    print(f"Con alerta temprana activa: {int(scores['alerta_temprana'].sum()):,}")
    print(f"Cobertura media del score: {scores['cobertura_media'].mean():.3f}")
    print(f"Meses evaluados (mediana): {scores['meses_evaluados'].median():.0f}")

    print("\n=== QUIÉN EMPIEZA A TORCERSE (giro autorreferenciado) ===")
    print(f"Empresas con giro detectado: {int(scores['giro_detectado'].sum()):,}")
    nat = panel.loc[panel["senal_giro"] == 1, "naturaleza_caida"].value_counts()
    print("Naturaleza de la caída (filas-mes):")
    print(nat.to_string() if len(nat) else "  ninguna")
    sanas = panel[(panel["senal_giro"] == 1) & (panel["score_mensual"] >= 55)]
    llamadas = int(((scores["giro_detectado"] == 1)
                    & (scores["score_final"] >= 55)).sum())
    print(f"Giros con score_mensual >= 55 (alguna vez): "
          f"{len(sanas):,} filas-mes, {sanas['company_id'].nunique():,} empresas")
    print(f"Lista de llamadas (giro + score_final >= 55 AHORA): {llamadas} empresas")

    print("\n=== POR QUÉ HA CAMBIADO ===")
    con = panel["delta_score"].notna()
    print(f"Filas-mes con atribución: {int(con.sum()):,}")
    print(f"  cambio medio |dScore|: {panel.loc[con, 'delta_score'].abs().mean():.2f} pts")
    dom = (panel.loc[con, "cambio_cobertura"].abs()
           > panel.loc[con, "cambio_real"].abs()).mean()
    print(f"  movimientos dominados por datos nuevos y no por comportamiento: {dom:.1%}")

    if grupos is not None and not grupos.empty:
        print(f"\n=== VISTA POR GRUPO ({len(grupos):,} grupos) ===")
        print(f"Grupos donde el agregado esconde una empresa en riesgo: "
              f"{int(grupos['agregado_esconde_problema'].sum()):,} "
              f"({grupos['agregado_esconde_problema'].mean():.1%})")
        print(f"Grupos con tendencias opuestas dentro: "
              f"{int(grupos['tendencias_opuestas'].sum()):,} "
              f"({grupos['tendencias_opuestas'].mean():.1%})")
        print(f"Dispersión interna del score (mediana): "
              f"{grupos['dispersion_interna'].median():.1f} pts")


if __name__ == "__main__":
    run()
