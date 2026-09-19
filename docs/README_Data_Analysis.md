# Pipeline de datos y artefactos

HackSpain 2026 · Reto Embat (X-Ray). Cómo se construye el panel, qué sale de
cada script y qué invariantes no se tocan.

Principio: ninguna transformación sin constancia numérica. `NaN` es “sin
evidencia”; `0` es “medido y vale cero”. Los CSV crudos no se escriben.

Cifras de la última corrida: 1.111 alerta nivel/cola; 624 giro alguna vez;
**420** lista de llamadas; prior 54,41; validación 0 errores.

---

## 1. Orden

```
src/config.py                 → fechas, pesos, umbrales, mapeos
src/explore_data.py           → data/features/data_quality_report.txt (opcional)
src/build_features.py         → master_panel.csv + feature_audit.json + cleaning_log.json
src/validate_features.py      → exit 1 si rompe una invariante
src/score_engine.py           → scores mensuales / finales / grupo + explanations
src/evaluate_anticipation.py  → anticipation_report.csv (mira al futuro; va después)
src/monitor.py                → alerts.csv
src/build_dashboard.py        → dashboard/index.html
src/screen_signals.py         → AUC y lift (calibración, no va en src.run)
```

```
pip install -r requirements.txt
python -m src.run
python -m src.brief_server
```

`evaluate_anticipation.py` no vive dentro del motor: si midiera antelación
ahí, el archivo del score dejaría de ser causal.

---

## 2. Artefactos

**`master_panel.csv`** — 1.286 empresas × 25 meses = 32.150 filas. Calendario
entero para que un rolling(3) sean 3 meses. Dentro de la ventana observada
(primer mes completo → último movimiento) sin actividad = 0. Fuera = NaN.
69 columnas; diccionario en `FEATURES.md`.

**`scores_mensuales.csv`** — `score_mensual` 0–100. Si el peso cubierto < 55%,
NaN.

**`scores_finales.csv`** — una fila por empresa.

| Columna | Qué dice |
|---|---|
| `score_final` / `score_bruto` | Agregado contraído / sin contraer |
| `clasificacion` | SALUDABLE … CRÍTICO o NO EVALUABLE |
| `tendencia` | MEJORANDO, ESTABLE, DETERIORANDO |
| `giro_detectado`, `giro_sigmas`, `primer_giro` | Se torció, cuánto, desde cuándo |
| `naturaleza_caida` | `bache` o `caida_estructural` |
| `cambio_real` vs `cambio_cobertura` | Comportamiento vs dato nuevo |
| `motivo_cambio_ultimo_mes` | Texto del último Δ |
| `meses_anticipacion`, `meses_ganados_a_nivel` | Inyectados tras el motor |
| `confianza`, `apto_ranking` | Si la nota se sostiene |

**`scores_grupo.csv`** — 249 grupos: `score_grupo`, `score_peor`,
`agregado_esconde_problema` (74 / 249 = 29,7%).

**`score_explanations.json`** — por empresa, el “por qué” del último mes
evaluable, eje a eje.

**`anticipation_report.csv`** — empresa × evento (`impago_severo`,
`asfixia_de_caja`) × señal (`nivel`, `canales_cola`, `giro_propio`,
`combinada`).

**`alerts.csv`** — monitor: avisa cuando se mueve, no en cada mes ESTABLE.

**`model/pctl_reference.json`** y **`model/prior_contraccion.json`** —
calibración congelada. No van en `data/`.

---

## 3. Fórmulas que el score usa

Todo es escala-libre. No hay umbral en euros.

1. **Flujo relativo** = `flujo_neto / ingresos_12m_avg` (tope ±12).
2. **Burn rate** = `gastos / ingresos`. Si ingresos = 0 → NaN +
   `mes_sin_ingresos`. Tope 8×.
3. **Morosidad 3m** = impagado as-of / facturas que **vencen** en esos 3
   meses (misma cohorte). Sin `.clip(0, 100)`: salirse es un error y el
   validador falla.
4. **Colchón** = `suma(flujo_neto, 6m) / gastos_3m_avg`. El runway
   (`caja_real / gasto_3m`) solo existe el mes de la foto de caja.
5. **Score de empresa** = media exponencial (semivida 6) × confianza ×
   cobertura, contraída al prior 54,41.

Cobro = `pending_amount` ≈ 0. `payment_date` está llena en overdue: no es
fecha de cobro. `status == paid` tampoco: hay facturas liquidadas con otro
status.

Flujo operativo: cuentas de tesorería, sin `transfer`, inversión ni
categorías de deuda (esas van a `debt_service`).

---

## 4. Decisiones que no se tocan

| Regla | Motivo |
|---|---|
| Impago as-of, no `status` de hoy | El status de 2026 pintaría 2024 como sano |
| Snapshot de caja/deuda solo su mes | Copiarlos al pasado es look-ahead |
| Ventana observada: fuera = NaN | Ceros antes del alta inventan un histórico sano |
| Mes parcial 2026-09 fuera del score | Extracción el día 18 |
| Maduración 45 días (`morosidad_censurada`) | Aún no han podido entrar en mora |
| Rectificativas fuera de volúmenes y stock | Un abono no es actividad ni deuda |
| Tipo de cambio solo en `[0,001, 2500]` | Fuera de rango inventa magnitud |
| Transacciones: no forzar EUR | El tipo es 1 en el 64% de cuentas no-EUR |
| Eje sin dato se apaga | Un 50 imputado hincha a quien no tiene facturas |
| Caja reconstruida hacia atrás: no | El saldo de 2026 “explica” 2024 |

Limpieza y moneda, con recuentos: `LIMPIEZA.md`. Motor: `SCORE_ENGINE.md`.

---

## 5. Limitaciones abiertas

- No se filtra facturación **intragrupo**.
- Deuda **sin histórico** (un snapshot). `debt_service` cubre el mes a mes;
  no dice cuánto queda.
- **Sin sector.** Los percentiles comparan a toda la muestra.
- Antelación medida contra umbrales del propio panel, no contra concurso
  real. Lifts 1,4–1,5.
- Morosidad no fiable en el 55–61% de las filas (documentos que no son
  factura). Las cascadas cubren el hueco.
