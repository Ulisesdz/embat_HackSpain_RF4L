# Teoría que el agente puede citar

Corpus de RAG para la pyme. Sale del motor, no de un modelo.
Cada bloque empieza por `tags:` para la búsqueda. No hay extractos ni nombres.

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
