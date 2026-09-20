# Teoría que el agente puede citar

Corpus de RAG para la pyme (`src/agente_pyme.py`). No es el manual de entrega.
Sale del motor y de lo que Embat publica de su plataforma. No de un modelo.
Cada bloque empieza por `tags:` para la búsqueda. No hay extractos ni nombres
de esta cartera. No se inventan préstamos, tipos ni puntos de score.

## Qué lee el score
tags: score ficha evidencia prior
El número es una media de ~25 meses, contraída hacia el comportamiento típico
si hay poca evidencia. Un mes excepcional no fabrica un 95. Nadie llega a 0
ni a 100: hace falta consistencia. Si la confianza es baja, hay pocos meses o
facturas huecas: es una lectura, no un plan cerrado.

## Seis ejes
tags: ejes deuda_comercial liquidez colchon trayectoria eficiencia cobro_clientes
Deuda comercial (20%): impagos a proveedores. Liquidez (18%): flujo operativo
del trimestre. Colchón (18%): cuánto aguantáis un mes malo; el runway solo
cuenta el mes con foto de caja. Trayectoria (18%): dirección, no un punto.
Eficiencia (14%): qué se quema por cada euro que entra. Cobro (12%): si os
pagan a vosotros. Si falta la fuente, el eje se apaga. Nunca se imputa 50.

## Bache frente a caída estructural
tags: giro bache caida_estructural naturaleza
Un giro es que os torcéis contra vuestra propia historia, no contra un umbral
ajeno. Bache: en la cartera, a 6 meses más de la mitad recupera (unos +4,7
puntos). Caída estructural: suele sostenerse (unos −1,7). El giro no predice
concurso. Dice si la caída se parece a un tropiezo de caja o a un régimen nuevo.

## Colchón y caja
tags: colchon caja runway cuentas
Sin foto de saldo, "sin visibilidad" no es "cero en caja". Concentrar dinero
en una cuenta operativa no maquilla el número: el motor lee el colchón y el
flujo, no el relato. Mover entre cuentas solo ayuda si el mes siguiente el
colchón real (flujo 6m / gasto, o runway con foto) mejora.

## Deuda cara e intereses
tags: deuda intereses debt_service apalancamiento eficiencia
El servicio de deuda (pagos e intereses) entra todos los meses. Una foto de
apalancamiento solo el mes del snapshot. Un producto con interés alto come
caja cada mes: eso es eficiencia y colchón, no "tener deuda". Exponer ese
coste no es vender otro préstamo.

## Nueva deuda y partners
tags: partner credito factoring linea bache
Una línea de un partner (factoring, póliza, confirming) puede tapar un bache
de cobro: os pagan tarde y vosotros no podéis dejar de pagar a proveedores.
No arregla una caída estructural: si entra menos de lo que sale de forma
sostenida, más deuda alarga el problema. No es una oferta. Nadie afirma que
os la vayan a conceder.

## Cobro y proveedores
tags: cobro_clientes deuda_comercial liquidez
Os pagan tarde o poco: cobrar no se arregla pagando vosotros antes. Dejar de
pagar a proveedores es casi siempre falta de caja, no una táctica. Adelantar
cobros o recortar salidas que no son de la actividad mueve liquidez. El score
lo verá cuando el comportamiento cambie varios meses, no el día del mail.

## Sana que se tuerce
tags: trayectoria DETERIORANDO SALUDABLE watchlist pendiente 82 68
Nivel alto y dirección a la baja es el caso 82→68: aún parecéis sanos. El
score es media larga; un mes que sube por colchón o eficiencia no cancela
flujo cayendo ni ingresos que se contraen. No es hidden champion. Es lista
de llamadas: parar la pendiente, no celebrar el 79.

## Lo que no afirmamos
tags: limites inversione valoracion maquillar
Esto no es valoración, no es promesa de inversión y no es un plan para "subir
el score". El fondo ve score + porqué, sin extracto. Maquillar un mes no
endereza la media de 25. El agente no recalcula.

## Qué es Embat para vosotros
tags: embat tesoreria plataforma caja
Embat es un sistema de tesorería: une bancos, ERP y productos financieros
en una vista. Consolida saldos, deuda, pagos, cobros y previsiones. No es
un banco y no os concede crédito. El Health Score lee el rastro; la
plataforma es donde veis la caja de verdad y ejecutáis el día a día.
TellMe (este chat) redacta con la ficha; no mueve dinero solo.

## Posición de caja en tiempo real
tags: colchon liquidez caja cuentas visibilidad confianza saldo
Embat enseña la posición de caja consolidada por banco, entidad y divisa,
actualizada a lo largo del día. No hace falta ensamblar portales por la
mañana. Si el colchón sale flojo o sin foto, lo primero es ver todas las
cuentas: "sin visibilidad" no es "cero euros". Conectar la cuenta que
falta mejora la evidencia, no inventa salud.

## Previsión que aprende de cómo os pagan
tags: liquidez trayectoria colchon prevision flujo descubierto
La previsión de Embat no se queda en el vencimiento del contrato. Ajusta
fechas al comportamiento real de cada tercero: si un cliente paga siempre
a 45 y no a 30, la caja se proyecta a 45. Hay tres capas: lo actual
(bancos y saldo), previsiones confirmadas (p. ej. un confirming ya firmado)
y una estimación para decidir. Sirve para ver un descubierto antes, no
para maquillar el score de este mes.

## Confirming, factoring y revolving
tags: partner credito factoring linea confirming bache cobro_clientes deuda_comercial
Embat ve, por producto, lo dispuesto y lo no dispuesto de confirming,
factoring y líneas revolving, y lo mete en la previsión por cuenta. Eso es
visibilidad de liquidez, no una concesión. Si el problema es un bache de
cobro, un partner puede anticipar facturas o cubrir proveedores unos
meses. Embat presenta; el partner decide. En una caída que se sostiene,
más disposición alarga la quema.

## Cartera de deuda, no otro préstamo
tags: deuda intereses debt_service apalancamiento eficiencia leasing
Embat centraliza préstamos, leasing y líneas: calendarios, tipos
(fijos o variables) y cargos bancarios cruzados con lo pactado. Los
vencimientos alimentan la previsión de caja. Si hay deuda cara, el
servicio come eficiencia y colchón todos los meses. Lo útil es ver ese
coste al lado del flujo. Embat no refinancia: enseña el coste. Sin foto
de producto no se afirma un tipo.

## Contrapartes: cómo pagan de verdad
tags: cobro_clientes deuda_comercial clientes proveedores dso dpo
Embat calcula DSO y DPO con facturas cobradas y pagadas, no con el plazo
del PDF. La diferencia entre "a 30" y "pagan a 45" es donde se rompe la
caja. Las alertas marcan contrapartes que se deterioran antes de que el
vencido se dispare. Adelantar cobros es tesorería de lo ya facturado, no
un plan comercial. Pagando vosotros antes no se arregla que os paguen
tarde.

## Pagos a proveedores desde un sitio
tags: deuda_comercial pagos proveedores cola confirming
Embat permite armar, aprobar y lanzar lotes de pago a todos los bancos
desde una plataforma. IBANs validados y datos del ERP en solo lectura
para no pagar al sitio equivocado. Si la deuda comercial está floja, el
orden es: ver la cola de vencidos, priorizar, y solo después hablar de
confirming o de una línea. Dejar de pagar no es táctica: el score ya lo
lee como problema vuestro.

## Conciliación y evidencia
tags: confianza visibilidad colchon facturas
Si la confianza es baja, suele faltar rastro: cuentas sin conectar o
documentos que no son factura. Embat concilia banco con ERP (reglas +
TellMe) y empareja cobros y pagos con facturas, también parciales. Más
visibilidad apaga menos ejes. Conectar no sube el Health Score: deja de
apagar trozos. Un 50 inventado no es honesto.

## Barrido entre cuentas
tags: colchon liquidez cuentas barrido pooling
Dinero ocioso en una cuenta y tensión en la operativa es un problema de
sitio, no de tamaño. Embat ve el pool y puede orquestar el barrido; el
movimiento es vuestro. Concentrar un mes de gasto visible en la cuenta
que paga. El traspaso no sube el score el día del clic: el motor lee el
colchón del mes (flujo 6m / gasto, o runway si hay foto).

## TellMe en tesorería, no solo este chat
tags: tellme agente embat
TellMe categoriza movimientos, cruza previsión con lo que ha entrado,
sugiere fechas según cómo pagan de verdad y completa datos de
beneficiario en un lote. Todo queda registrado y se puede deshacer. Este
brief usa la ficha ya calculada: no recategoriza el banco ni mueve un
pago. Si pedís "subid el score", no hay palanca: hay comportamiento
durante meses.

## FRÁGIL o CRÍTICO
tags: FRÁGIL CRÍTICO colchon liquidez deuda_comercial eficiencia
Nivel bajo: el problema ya está aquí. Primero oxígeno (un mes de gasto
a la vista, parar salidas que no operan, cola de proveedores). No
celebrar un ingreso puntual. Nueva deuda solo si es un puente con
rebote a la vista; si la quema se sostiene, más crédito alarga el
agujero. Embat sirve para ver caja, deuda y vencidos en el mismo sitio,
no para prometer un salto de clasificación el mes que viene.

## EN RIESGO
tags: EN RIESGO ESTABLE colchon liquidez
Aún no es crítico, pero no hay margen. El trimestre de flujo y el
colchón mandan más que un mes bueno. Adelantar cobros vencidos, no
pagar antes; recortar lo que no es de la actividad. Si la dirección
ya es DETERIORANDO, trataros como lista de llamadas aunque el número
aún se vea "pasable". El score es media larga: enderezar pide meses.

## MEJORANDO de verdad
tags: MEJORANDO trayectoria liquidez
MEJORANDO sale del eje de trayectoria (media 3 meses), no de que el 76
haya subido un punto. Si el flujo deja de caer, la deuda a proveedores
baja y los ingresos aguantan, eso es rumbo. No relajar el colchón ni
volver a alargar cobros. Un mes de eficiencia alta no cancela una
cola de clientes que se estira. El score lo confirmará cuando se
sostenga, no el día que "parece que va mejor".

## Confianza baja
tags: confianza baja visibilidad conectar cuentas colchon
Poca evidencia: pocos meses o facturas huecas. Es una lectura, no un
plan cerrado. Lo que Embat puede hacer ya: conectar la cuenta o el ERP
que falta, para que el colchón y el cobro dejen de apagarse. Eso no os
hace SALUDABLE. Evita decidir con un número que se acerca al 54 porque
aún no os vemos.

## Quema y eficiencia
tags: eficiencia burn liquidez recortar
Burn 3m: 1,0 es equilibrio (gastáis lo que entra). Por encima, la
quema se sostiene aunque un mes salga bonito. Recortar salidas que no
son de la actividad; un ingreso puntual no cambia la pendiente. El
servicio de deuda cara y las comisiones comen este eje todos los
meses. Embat puede poner esos cargos al lado del flujo; no es un ERE
ni un plan de negocio.

## Caída estructural: orden
tags: caida_estructural estructural trayectoria eficiencia
Si la caída se sostiene, el orden es comportamiento y luego balance.
Parar la quema (salidas que no operan, cola, cobro de lo ya facturado).
Después, si acaso, un partner. Tapar con una póliza nueva alarga el
problema. Embat no dice "no al crédito para siempre": dice que hoy no
es el primer paso. El score no promete recuperación; en la cartera
este patrón suele aguantar a 6 meses.

## Grupo y filial
tags: grupo filial agregado
El Health Score se calcula empresa a empresa. La media del holding
puede tapar una filial tensa. En Embat la previsión y la caja se ven
por cuenta y por grupo: sirve para no decidir solo con el agregado.
Si el grupo "se ve bien" y una sociedad no, la llamada es a esa
sociedad. No se recalibra el número al cambiar de vista.

## Quién hace qué
tags: embat partner empresa acciones
Vosotros: cola de proveedores, adelantar cobros, recortar lo que no
opera, barrer cuentas, parar la pendiente. Embat: visibilidad de caja
y deuda, exponer el coste, seguimiento si estáis sanos pero os
torcéis, orquestar un barrido, presentar a un partner. El partner:
factoring, confirming o póliza, y solo encaja si es un bache o un
hueco de cobro. Nadie afirma que os lo vayan a dar. Nadie promete
puntos.
