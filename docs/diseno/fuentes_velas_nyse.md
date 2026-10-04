# Fuentes de velas NYSE: `/api/scan-data` vs `/api/scan-batch`

**Fecha:** 2026-10-04
**Estado:** verificado de forma parcial (ver *Alcance de la verificación*)

## Decisión

`snapshot_autocapture.py` **sigue usando `POST /api/scan-batch`**. No hace falta
migrarlo a `GET /api/scan-data` para que sus velas coincidan con las del
navegador (`fetchNyseTicker`).

## Contrato observado

| | `GET /api/scan-data` | `POST /api/scan-batch` |
|---|---|---|
| Consumidor | `fetchNyseTicker` (navegador) | `snapshot_autocapture.py` |
| Ruta a las velas | `data` | `results[0].data` (un elemento por ticker) |
| Formato de vela | `{t, o, h, l, c, v}` | `{t, o, h, l, c, v}` |
| `t` | segundos epoch | segundos epoch |
| Clave hermana | `periods` | `periods` |

Número de velas observado (AAPL), idéntico en ambos endpoints:

| TF | n |
|---|---|
| 1d | 120 |
| 1h | 100 |
| 15m | 96 |

**La única diferencia es el envoltorio.** Quien lea `scan-batch` debe sacar
`results[i].data` (y `results[i].periods`). No hay que convertir unidades ni
renombrar campos.

## Alcance de la verificación

- Un solo ticker (AAPL), en los TF 1d / 1h / 15m.
- Se compararon solo **la primera vela, la última vela y `n`**. **No** se comparó
  vela a vela.
- Se hizo **con el mercado cerrado**: no se comprobó el comportamiento de la vela
  en curso (sin cerrar) durante la sesión regular.

## Pendiente (para pasar a «verificado»)

1. Comparar vela a vela (diff completo de `data`) en al menos 2 tickers más.
2. Repetir la comparación con el mercado abierto (16:00–18:00 CET) para confirmar
   que ambos endpoints tratan igual la última vela parcial.
3. Con `scan-batch` multiticker, comprobar que el orden de `results[]`
   corresponde al orden de los tickers pedidos o que cada elemento lleva su
   ticker. No asumir el índice.
