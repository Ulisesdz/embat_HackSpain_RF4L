"""Catálogo de acciones para la pyme. No es un marketplace.

Quién ejecuta: empresa, embat o partner. El CEO de Embat dejó claro que no
todo tiene que ser producto propio: barridos entre cuentas, exponer deuda
cara, o una línea de un partner. El agente solo propone tipos del catálogo.
No inventa un préstamo ni un delta de score.
"""

# condiciones: siempre | bache | estructural | cobro_flojo | confianza_baja
#              trayectoria_floja | deteriorando
CATALOGO = [
    {
        "id": "parar_pendiente",
        "titulo": "Parar la pendiente, no celebrar el nivel",
        "quien": "empresa",
        "ejes": ["trayectoria"],
        "cuando": "trayectoria_floja",
        "hace": (
            "El score alto no cancela la dirección. Si el flujo cae, los "
            "proveedores suben o los ingresos se contraen, eso es lo que hay "
            "que parar. Un mes bueno no endereza la media."
        ),
        "no_hace": "No es un plan para 'subir el score'. Es no confundir SALUDABLE con 'ya está'.",
    },
    {
        "id": "watchlist_sana",
        "titulo": "Trataros como el caso 82→68",
        "quien": "embat",
        "ejes": ["trayectoria"],
        "cuando": "deteriorando",
        "hace": (
            "Nivel alto y dirección a la baja es la lista de llamadas: aún "
            "parecéis sanos. Embat os deja en seguimiento; no sois un "
            "hidden champion este mes."
        ),
        "no_hace": "No es una rebaja de rating. Es no dormirse en el 79.",
    },
    {
        "id": "no_tapar_pendiente",
        "titulo": "No tapar la pendiente con deuda nueva",
        "quien": "empresa",
        "ejes": ["trayectoria", "eficiencia"],
        "cuando": "deteriorando",
        "hace": (
            "Si el flujo cae y los ingresos se contraen, una póliza nueva "
            "alarga el problema. Recortar salidas que no son de la actividad; "
            "no pedir para maquillar un mes bueno."
        ),
        "no_hace": "No es un no a toda financiación. Es no usarla para tapar una pendiente que aún no es giro.",
    },
    {
        "id": "barrido_cuentas",
        "titulo": "Barrido entre cuentas",
        "quien": "empresa",
        "ejes": ["colchon", "liquidez"],
        "cuando": "siempre",
        "hace": (
            "Concentrar tesorería ociosa en la cuenta operativa hasta tener "
            "un mes de gasto visible. Embat puede orquestar el barrido; el "
            "movimiento es vuestro."
        ),
        "no_hace": "El traspaso no sube el score. El motor lee el colchón del mes, no el relato.",
    },
    {
        "id": "adelantar_cobros",
        "titulo": "Adelantar cobros, no pagar antes",
        "quien": "empresa",
        "ejes": ["cobro_clientes", "liquidez"],
        "cuando": "cobro_flojo",
        "hace": (
            "Acortar vencimientos o cobrar lo vencido. El eje de cobro baja "
            "cuando os pagan tarde; pagando vosotros antes no se arregla."
        ),
        "no_hace": "No es un plan comercial de ventas. Es tesorería de lo ya facturado.",
    },
    {
        "id": "cola_proveedores",
        "titulo": "Revisar la cola a proveedores",
        "quien": "empresa",
        "ejes": ["deuda_comercial"],
        "cuando": "siempre",
        "hace": (
            "Dejar de pagar es casi siempre falta de caja. Priorizad vencidos "
            "vivos antes de nueva deuda."
        ),
        "no_hace": "No sugerimos impago táctico. El eje ya lo lee como problema.",
    },
    {
        "id": "recortar_no_op",
        "titulo": "Recortar salidas que no son de la actividad",
        "quien": "empresa",
        "ejes": ["eficiencia", "liquidez"],
        "cuando": "siempre",
        "hace": (
            "Si el burn 3m está alto, un ingreso puntual no cambia la pendiente. "
            "Cortar lo que no opera."
        ),
        "no_hace": "No es un ERE ni un plan de negocio. Es caja operativa.",
    },
    {
        "id": "exponer_deuda_cara",
        "titulo": "Exponer deuda con interés alto",
        "quien": "embat",
        "ejes": ["eficiencia", "colchon"],
        "cuando": "siempre",
        "hace": (
            "Si hay productos caros, el servicio de deuda come caja todos los "
            "meses. Embat puede poner el coste al lado del flujo, no vender "
            "otro préstamo."
        ),
        "no_hace": "No refinancia. Solo enseña el coste. Sin foto de producto no afirma un tipo.",
    },
    {
        "id": "linea_partner_bache",
        "titulo": "Línea puente de un partner",
        "quien": "partner",
        "ejes": ["colchon", "deuda_comercial", "liquidez"],
        "cuando": "bache",
        "hace": (
            "En un bache (en la cartera suele rebotar), una póliza o confirming "
            "externo puede evitar impago a proveedores mientras cobráis. Embat "
            "presenta; el partner decide."
        ),
        "no_hace": "No es una oferta ni una concesión. Nueva deuda no arregla una quema sostenida.",
    },
    {
        "id": "factoring_partner",
        "titulo": "Factoring o anticipo de facturas",
        "quien": "partner",
        "ejes": ["cobro_clientes", "liquidez"],
        "cuando": "cobro_flojo",
        "hace": (
            "Si el eje flojo es que os pagan tarde, anticipar facturas mueve "
            "caja hoy. Lo ejecuta un partner, no Embat."
        ),
        "no_hace": "No cambia a vuestros clientes. El score lo verá cuando el cobro deje de ser el lastre.",
    },
    {
        "id": "no_deuda_estructural",
        "titulo": "No tapar una caída con más deuda",
        "quien": "embat",
        "ejes": ["trayectoria", "eficiencia"],
        "cuando": "estructural",
        "hace": (
            "Caída que se sostiene: más crédito alarga el problema. Primero "
            "parar la quema; después, si acaso, partner."
        ),
        "no_hace": "No es un no eterno al crédito. Es el orden: comportamiento, luego balance.",
    },
    {
        "id": "mas_visibilidad",
        "titulo": "Conectar la cuenta que falta",
        "quien": "embat",
        "ejes": ["colchon"],
        "cuando": "confianza_baja",
        "hace": (
            "Sin foto de caja el colchón no afirma runway. Más visibilidad "
            "apaga menos ejes; no inventa un 50."
        ),
        "no_hace": "Conectar no mejora la salud. Mejora la evidencia.",
    },
]


def _debil(f):
    return {x["eje"] for x in (f.get("ejes_debiles") or []) if x.get("eje")}


def _ok_cuando(item, f):
    c = item.get("cuando") or "siempre"
    if c == "siempre":
        return True
    if c == "bache":
        return bool(f.get("giro") and f.get("naturaleza") == "bache")
    if c == "estructural":
        return bool(f.get("giro") and f.get("naturaleza") == "caida_estructural")
    if c == "cobro_flojo":
        return "cobro_clientes" in _debil(f)
    if c == "confianza_baja":
        return f.get("confianza") == "baja"
    if c == "trayectoria_floja":
        return "trayectoria" in _debil(f)
    if c == "deteriorando":
        return (f.get("tendencia") == "DETERIORANDO") or ("trayectoria" in _debil(f))
    return False


def proponer(f, max_n=4):
    """Solo tipos del catálogo que encajan con ejes flojos o la naturaleza."""
    deb = _debil(f)
    out = []
    for item in CATALOGO:
        if not _ok_cuando(item, f):
            continue
        if deb and not (set(item["ejes"]) & deb):
            if item["cuando"] not in (
                "estructural", "confianza_baja", "deteriorando", "trayectoria_floja"
            ):
                continue
        hit = [e for e in item["ejes"] if e in deb] or list(item["ejes"][:1])
        row = dict(item)
        row["ejes_objetivo"] = hit
        out.append(row)
        if len(out) >= max_n:
            break
    return out


def impacto(f, acciones):
    """Qué eje mueve cada acción. Cero puntos prometidos."""
    por_eje = {x["eje"]: x for x in (f.get("ejes_debiles") or []) + (f.get("ejes_fuertes") or [])}
    rows = []
    for a in acciones:
        eje = (a.get("ejes_objetivo") or a.get("ejes") or [None])[0]
        info = por_eje.get(eje) or {}
        hoy = info.get("score")
        rows.append({
            "id": a["id"],
            "eje": eje,
            "eje_hoy": hoy,
            "lectura": (
                f"El eje {eje or '—'} está en {hoy:.0f}." if hoy is not None else
                f"El eje {eje or '—'} no está puntuado este mes."
            ) + (
                f" Hoy: {info['razon']}." if info.get("razon") else ""
            ) + (
                " Si el comportamiento que lee mejora varios meses, ese eje "
                "puede subir. El score de empresa es media larga: un mes no lo endereza."
            ),
            "promesa_puntos": None,
        })
    return rows
