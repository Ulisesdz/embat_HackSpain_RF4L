# Motor de scoring

Diseño de `src/score_engine.py`. Pesos y umbrales: `src/config.py`. Diccionario: [`FEATURES.md`](FEATURES.md). Limpieza: [`LIMPIEZA.md`](LIMPIEZA.md).

El dataset no trae etiqueta de salud. El motor es reglas sobre ratios, con pesos medidos (AUC / lift) y estimadores para series cortas: Theil-Sen, percentil del mes, contracción hacia el prior. Cada número se puede explicar.

---

## 1. Receta

```
panel mensual
   │
   ├─ 6 EJES → nota 0–100 (media ponderada; eje sin fuente se apaga)
   ├─ MODULADORES (corrigen, no puntúan)
   ├─ AGREGACIÓN  recencia × confianza × cobertura  (semivida 6 meses)
   ├─ CONTRACCIÓN hacia el prior 54,41 si hay poca evidencia
   └─ TRES SEÑALES   nivel · cola · giro propio
```

Calibración en `model/` (`pctl_reference.json`, `prior_contraccion.json`). Borrarlas recalibra.

```
pip install -r requirements.txt
python -m src.run          # features → validador → score → anticipación → monitor → copia la UI a dashboard/
python -m src.brief_server # http://127.0.0.1:8775/
```

`evaluate_anticipation.py` va después del motor: mira al futuro. Si viviera dentro, el score dejaría de ser causal. `screen_signals.py` es calibración; no entra en `src.run`.

---

## 2. Pesos

Medidos en `screen_signals.py` (filas aún aceptables, horizonte 12 meses).

| Eje | Peso | Por qué |
|---|---|---|
| Deuda comercial | 20% | Predictor más fuerte (AUC 0,83). No pagar es decisión propia |
| Liquidez | 18% | Flujo / tamaño (`ingresos_12m_avg`) |
| Colchón | 18% | Meses que aguanta. Absorbe la volatilidad (AUC 0,71 sobre asfixia) |
| Trayectoria | 18% | Dirección para MEJORANDO / DETERIORANDO. AUC 0,49: no se vende como predictor |
| Eficiencia | 14% | Burn. 1,0 = equilibrio. Lift 3,46 sobre asfixia |
| Cobro | 12% | Contagio (AUC 0,72). Pesa menos: decide el cliente |

Si el peso cubierto del mes < 55%, el mes es `NaN` (NO EVALUABLE). Nunca se imputa 50.

**Apalancamiento no es eje.** El snapshot de deuda cubre el 1,2% de las filas. Modula ±8 pts (`debt_service` todos los meses; foto de deuda solo su mes). `caja_negativa_flag` resta 4 pts solo cuando vale 1. NaN no penaliza.

---

## 3. Cascadas

Cada eje usa la fuente más precisa que exista. Solo se apaga si no hay ninguna.

| Eje | 1ª | 2ª | 3ª |
|---|---|---|---|
| Deuda comercial | `% impagos proveedores 3m` | stock vencido / ingresos | ha comprado y no debe |
| Liquidez | flujo relativo 3m | flujo del mes | — |
| Colchón | colchón de flujo 6m | runway (solo foto de caja) | — |
| Trayectoria | ≥1 de 3 señales + persistencia | — | — |
| Eficiencia | burn 3m | burn del mes | — |
| Cobro | `% vencido sin cobrar 3m` | stock clientes / ingresos | ha vendido y no le deben |

Stock 0 con historial de compras/ventas es un dato, no un hueco.

Resultado de la última corrida: mediana 19 meses evaluados de 25; 67,6% de filas-mes con score; 6 empresas NO EVALUABLE; 1.169 aptas para ranking.

---

## 4. Trayectoria

Cada señal se convierte en intensidad `[-1, +1]` (tope = saturación). Un outlier no manda.

| Componente | Peso | Señal | Saturación |
|---|---|---|---|
| Pendiente del flujo | 35% | Theil-Sen 6m | 10 pp de ingresos / mes |
| Deuda a proveedores | 30% | recuperación del stock | 0,5 meses de ingresos |
| Ingresos | 25% | momentum trimestral | ±30% |
| Persistencia | 10% | flags sostenidos 3 meses | solo penaliza |

```
score_trayectoria = 50 + 50 × dirección × amortiguación
```

Amortiguación 0,50–1,00 según volatilidad. Simétrico: misma sensibilidad al alza y a la baja. La persistencia **no activa el eje sola**.

`tendencia` = media de 3 meses de `score_trayectoria`: >58 MEJORANDO, <42 DETERIORANDO. No es el delta del score compuesto: un dato nuevo movería el compuesto sin que la empresa haya cambiado de rumbo. Por eso una ficha puede ser **SALUDABLE + DETERIORANDO**.

---

## 5. Moduladores

Corrigen. No puntúan solos.

| Modulador | Tope | Dónde |
|---|---|---|
| Antigüedad del impago (>90 días) | −15 pts | deuda / cobro |
| Volatilidad del flujo | −14 pts | colchón |
| Runway real (percentil) | ±12 pts | colchón, solo si hay foto de caja |
| Recibos devueltos | −12 pts | cobro |
| Concentración de contraparte | −10 pts | solo si el eje ya está < 60 |
| Apalancamiento + caja negativa | ±8 / −4 pts | score del mes |

---

## 6. Agregación

Peso de cada mes = recencia (semivida 6) × confianza × cobertura.

```
score_final = (evidencia × score_bruto + 0,75 × 54,41) / (evidencia + 0,75)
```

El prior 54,41 es la mediana de empresas con ≥12 meses (798). Un mes único no saca 95.

Umbrales **absolutos** (misma empresa, misma nota, aunque cambie el resto de la muestra):

| Clase | Umbral | Empresas |
|---|---|---|
| SALUDABLE | ≥ 68 | 229 |
| ESTABLE | 52–68 | 538 |
| EN RIESGO | 42–52 | 315 |
| FRÁGIL | 33–42 | 132 |
| CRÍTICO | < 33 | 66 |
| NO EVALUABLE | sin evidencia | 6 |

Media 55,4. Nadie llega a 0 ni a 100: hace falta consistencia.

---

## 7. Tres señales

- **Nivel** — `score_mensual < 42`. Actuar hoy.
- **Cola** — aún no ha caído y acumula percentiles adversos. Compra tiempo.
- **Giro** — caída contra la σ propia del score (mediana 3m). Cierra el caso «82 → 68»: sigue pareciendo sana frente a la cartera.

Los canales de cola salen de `screen_signals.py`. Percentil, no umbral absoluto (varias señales no son monótonas). Disparo al 55% del peso **disponible** en esa fila, sostenido 2 meses.

`evaluate_anticipation.py`, horizonte 12 meses, evento = 3 meses consecutivos de severidad:

**Asfixia de caja** (tasa base 12,3%): la cola gana **2 meses** al nivel y ve eventos que el nivel no ve. Lift combinado ~1,44.

**Impago severo** (tasa base 34,1%): el nivel es más tautológico (el evento se define sobre el mismo stock). La cola aporta +1 mes.

El giro **no** se mete en los canales: el lift de cola caía de 1,52 a 1,04. Responde a otra pregunta («¿esta caída se sostiene?»).

### Bache o caída

Desenlace = ¿el score suavizado sigue igual o peor 6 meses después? Criterios: volatilidad propia baja, `cambio_real` muy negativo, deuda comercial viva. No se usan nivel ni colchón: predicen por reversión a la media.

| Clase | A 6 meses | Recupera |
|---|---|---|
| Bache | +4,7 pts | ~52% |
| Caída estructural | −1,7 pts | ~33% (y un tercio sigue cayendo) |

### Por qué ha cambiado

```
efecto_nivel  = w_i,t-1 × (s_i,t − s_i,t-1)     el eje se movió
efecto_mezcla = (w_i,t − w_i,t-1) × s_i,t       llegó (o se fue) un dato
```

`cambio_real` = comportamiento. `cambio_cobertura` = ahora la vemos. Sin eso, “ha mejorado” sería “empezamos a verla”.

### Empresas nuevas

La rejilla de cuantiles y el prior congelados hacen que puntuar empresas aisladas dé la misma clase y tendencia que dentro de las 1.286. `model/` vive fuera de `data/` a propósito: `data/` está en `.gitignore`.

---

## 8. Empresa o grupo

El cálculo es por empresa. El grupo es un `groupby` encima.

| Medida | Valor |
|---|---|
| Grupos | 249 |
| MEJORANDO y DETERIORANDO a la vez | 85 (34%) |
| El agregado esconde una filial en riesgo | 74 (30%) |

Toggle de vista, no de cálculo.

---

## 9. Fórmulas que usa el score

Todo es escala-libre. No hay umbral en euros.

1. Flujo relativo = `flujo_neto / ingresos_12m_avg` (tope ±12).
2. Burn = `gastos / ingresos`. Si ingresos = 0 → NaN. Tope 8×.
3. Morosidad 3m = impagado as-of / facturas que **vencen** en esos 3 meses.
4. Colchón = `suma(flujo_neto, 6m) / gastos_3m_avg`. Runway solo el mes de la foto de caja.
5. Cobro = `pending_amount` ≈ 0. `payment_date` está llena en overdue: no es fecha de cobro.

Flujo operativo: cuentas de tesorería. Fuera: `card`, `transfer`, inversión y categorías de deuda (esas van a `debt_service`).

---