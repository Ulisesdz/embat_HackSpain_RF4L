# Limpieza de datos y política de moneda

Limpieza de verdad, no borrar columnas vacías. Cada decisión queda numerada
en `data/features/cleaning_log.json`. Los CSV RAW no se tocan. El score está
en [`SCORE_ENGINE.md`](SCORE_ENGINE.md).

## 1. Qué había sucio (medido, no intuido)

### Fechas

| Sitio | Suciedad | Qué hacemos |
|---|---|---|
| `invoices.due_date` | Año 2000 y 2100; plazos < 0 o > 730 días; 13 NaT | `issuance_date + 30 días` |
| `invoices.payment_date` | Llena en el 99,99% de las filas, también en overdue | **No es un cobro.** Cobro = `pending_amount` ≈ 0. Luego se recortan fechas futuras o anteriores a emitir |
| `transactions.date` | Rango limpio 2024-09-01 → 2026-09-01 | Se usa esta |
| `transactions.value_date` | Hay 2099-12-31 y 2022-07-01 | **No se usa** |
| Primer mes de una empresa | Alta a mitad de mes | Si el primer movimiento es después del día 3, ese mes no es observado |

### Importes y etiquetas

| Sitio | Suciedad | Qué hacemos |
|---|---|---|
| Facturas `amount == 0` | Documentos sin derecho de cobro/pago | Se excluyen |
| Facturas gigantes | Una de 6e10 tumba el ratio de la empresa | Winsor p99 por empresa y dirección |
| Transacciones `amount == 0` | Ruido | Se excluyen |
| `status == pending` | Aún no asentadas | Se excluyen |
| `accounting_status == DISCARDED` | 308 k filas, categorías reales (cobros, pagos) | **Se conservan**: es etiqueta de conciliación, no “este movimiento no existió” |
| Duplicados exactos con otro `transaction_id` | ~105 k (TPV, comisiones) | Se cuentan y se dejan |
| `cash_settlements` | Typo de `cash_settlement` | Se normaliza |
| `balances.available` | 100% nulo | No se usa. El runway usa `balance` |
| Saldos `\|x\| ≥ 1e9` y centinelas 999… | Basura del origen | Se anulan |
| `companies.country` | 82% nulo; ESPAÑA/ESPANYA/SPAIN | Se normaliza a ISO. No entra al score |

### Ventana observada

El calendario son 25 meses para que un rolling(3) sea 3 meses de calendario.
**Dentro** de [primer mes completo, último movimiento], sin actividad = 0.
**Fuera**, volumen = NaN. Fingir ceros antes de que la empresa exista en el
dataset inventa un histórico sano.

El validador comprueba esa invariante.

## 2. ¿Pasar todo a la misma moneda?

**No. Forzar EUR empeora el dato.** Los ratios del score ya son invariantes a la
moneda. Convertir mal mezcla peras con manzanas.

Hechos:

- `transactions` **no trae `currency`**. El tipo está en `banking_products`.
- 2,45 M de movimientos tienen `exchange_rate == 1` (96%).
- En cuentas **no-EUR** (247 k filas) el tipo sigue siendo 1 en el **64%**.
  Multiplicar `amount * exchange_rate` no produce euros: deja el peso mexicano
  como si fuera euro, o inventa un tipo basura (0, 0,0003, 6500).
- 513 tipos de transacción están fuera de `[0,001, 2500]`.
- Las facturas sí tienen `currency`, `accounting_currency` y tipo. 44.899 filas
  tienen moneda distinta de la contable. Ahí **sí** se convierte a la moneda de
  los libros, y solo si el tipo está en rango. 415 filas quedan NaN.
- La deuda se lleva a EUR con la misma regla (18 productos no convertibles).

Política final:

1. **Dentro de una empresa**, numerador y denominador van en la misma moneda
   (libros o cuenta). `flujo / ingresos`, burn, morosidad % no necesitan EUR.
2. **Entre empresas**, el score compara ratios y percentiles de ratios, nunca
   euros absolutos. Una pyme en MXN y un grupo en EUR son comparables.
3. **No se inventa un tipo hacia EUR** para transacciones ni saldos.
4. **Facturas sí se convierten** a `accounting_currency` si el tipo está en
   rango. Si no, una empresa mezcla USD y EUR en el mismo ratio de morosidad.

## 3. Qué no se hace (parece limpieza y rompe el score)

| Idea | Por qué no |
|---|---|
| Imputar 50 si falta un bloque | Falsa neutralidad. El eje se apaga |
| Reconstruir caja hacia atrás desde el saldo de 2026 | El presente “explica” 2024 |
| Copiar deuda/caja a todos los meses | Snapshot ≠ historia |
| `status == paid` como cobro | `payment_date` está llena en overdue |
| Incluir `card` en flujos | El cargo se duplica en la corriente |

## 4. Dónde está el recuento

`data/features/cleaning_log.json` y `data/features/data_quality_report.txt`
(`python -m src.explore_data`). El diccionario de variables está en `FEATURES.md`.
