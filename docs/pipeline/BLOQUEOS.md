# Bloqueos abiertos

Documento vivo -- se añade una entrada cuando algo bloquea un cierre real
(no una duda menor), con qué falta exactamente y cómo resolverlo. No se
improvisa el valor que falta: se deja el código en el estado más seguro
conocido y se sigue con el resto de la tarea.

## 1. `computeMarketContext()` -- gate BTC de la ruta CRIPTO — RESUELTO (07/10/2026)

**Texto literal confirmado** (`docs/pipeline/pregunta11_salida.txt`,
línea 1384 real):

```js
async function computeMarketContext(mode){
  try{
    if (mode==='NYSE'){
      const ind = await fetchNyseTicker('SPY');
      const d = ind['1d'];
      if (!d) return null;
      return {ticker:'SPY', price:d.price, ema50:d.ema50, gateOn:d.price>d.ema50, atrPct:d.atrPct, rsi:d.rsi};
    } else {
      const ind = await fetchCryptoTicker('BTC');
      const d = ind['1d'];
      if (!d) return null;
      return {ticker:'BTC', price:d.price, ema50:d.ema50, gateOn:d.price>d.ema50, atrPct:d.atrPct, rsi:d.rsi, macdHist:d.macdHist};
    }
  }catch(e){ return null; }
}
```

`gateOn = BTC.price > BTC.ema50` (1D) -- confirma literalmente la regla
del proyecto que el usuario describió ("BTC < EMA50 diaria = cero
longs"). Portado a `snapshot_autocapture.compute_btc_gate()` (rama
`'CRYPTO'` únicamente -- la rama `'NYSE'` real usa SPY, fuera de alcance
de este script). Pruebas: `test_compute_btc_gate_price_mayor_que_ema50_da_true`/
`_menor_que_ema50_da_false`/`_excepcion_da_false_igual_que_catch_del_js`/
`_pide_solo_velas_1d_de_btc`.

**Bug real encontrado y corregido en `verificar_cripto.sh` al validar
este puerto (07/10/2026):** el resultado real `3/3 PASA, Gate BTC OFF
(real)` que reportó el usuario era, en parte, un FALSO POSITIVO.
`computeMarketContext()` llama a `fetchCryptoTicker('BTC')`, que llama a
`fetchBinanceKlines()` -- ninguna de las dos estaba cargada en el
contexto de Node del driver de `verificar_cripto.sh` (solo se extraían
las 32 piezas compartidas con NYSE + `computeMarketContext()` sola).
Al ejecutarse, `computeMarketContext()` lanzaba internamente
`ReferenceError: fetchCryptoTicker is not defined` -- **silenciado por
su propio `catch(e){return null}` real**, indistinguible desde fuera de
un fallo de red genuino: el script veía `ctx=null` y reportaba
`{"gateOn": false, "real": true, "error": null}`, que parecía un
resultado de mercado legítimo sin serlo. Confirmado reproduciendo el
`ReferenceError` exacto en Node (`fetchCryptoTicker is not defined`) y
corregido extrayendo también `fetchBinanceKlines`/`fetchCryptoTicker`/
`sleep`/`BINANCE_BASE` (líneas reales 1338/1356/707/1336) junto con
`computeMarketContext()`, probado end-to-end con un mock de Binance:
ahora `computeMarketContext()` ejecuta de verdad y devuelve un `ctx`
real, no `null` por una dependencia ausente.

**Importante -- el "Gate BTC OFF" del 07/10/2026 NO está confirmado como
real.** El puerto Python (`compute_btc_gate()`), ejecutado contra las
velas de BTC que ese mismo run comiteó
(`docs/pipeline/fixtures_js/oraculo_cripto/BTC_1d_candles.json`), da
`price=85317.85 > ema50=78745.15` -> **gate ON**, lo contrario de lo que
reportó el run con el bug. Esto no prueba que el gate esté ON ahora
(los datos pueden haber cambiado) -- prueba que el "OFF (real)" anterior
no es fiable. **Hace falta re-ejecutar `docs/pipeline/verificar_cripto.sh`
(ya corregido) contra el servidor real para tener un valor de gate
genuino** -- primera acción pendiente de este documento.

## 2. `BINANCE_BASE` -- RESUELTO (07/10/2026)

**Valor real confirmado** (`docs/pipeline/pregunta11_salida.txt`, línea
1336): `const BINANCE_BASE = 'https://data-api.binance.vision';` -- **NO**
es `api.binance.com` (el dominio público "normal"), es el subdominio de
solo datos de mercado de Binance. Corregido en
`snapshot_autocapture.BINANCE_BASE` y en el valor por defecto de
`docs/pipeline/verificar_cripto.sh`. Prueba:
`test_binance_base_default_es_el_dominio_real_confirmado`.

## Nota de entorno (no es un bloqueo real -- no afecta al servidor)

Este sandbox de desarrollo tiene roto el import de `gspread` (cadena
`google-auth` -> `cryptography` -> binding nativo de Rust, termina en
`pyo3_runtime.PanicException: Python API call failed` al hacer
`import gspread`) -- confirmado real, no una suposición, tanto al probar
`generar_oraculo_evaluate_js.sh` como al escribir
`test_snapshot_autocapture_cripto.py`. El servidor real ya ejecuta
`gspread` en producción sin problema (`cargar_universo_de_tickers()`
lleva semanas funcionando ahí) -- es una limitación de ESTE sandbox, no
del código. Por eso las pruebas de `snapshot_autocapture.py` sustituyen
`gspread` por un stub antes de importar el módulo (nunca se necesita de
verdad: siempre se monkeypatchea `cargar_universo_cripto()`/
`_leer_filas_universo()`), y por eso no se pudo probar
`python3 snapshot_autocapture.py --market crypto --dry-run` como
subproceso real en esta sesión -- esa prueba de verdad le toca al
usuario en el servidor real, primer paso de
`docs/pipeline/RUNBOOK_CRIPTO.md`.

## Qué NO está bloqueado

Todo lo demás de la ruta cripto SÍ tiene texto literal confirmado y ya
está portado/probado: `fetchAllCrypto`, `fetchCryptoTicker`,
`fetchBinanceKlines` (salvo `BINANCE_BASE`, bloqueo 2), `evalSC01`,
`evalSC02`, `evalSCPB`, `computeIndicators` + sus 9 funciones de cálculo
(ya portadas en `indicator_calc.py`, reutilizadas sin cambios para cripto
-- `fetchCryptoTicker()` llama a la misma `computeIndicators()` que NYSE,
solo con velas de origen distinto). `NYSE_STRATEGIES`/`CRYPTO_STRATEGIES`,
`STRATEGY_META`, `MAX_RAW_SCORE`, `mkResult`/`mkNA`/`finalizeVerdict`/`f`
son compartidos entre las dos rutas, ya verificados en la rama NYSE
(oráculo de 17 tickers, `docs/pipeline/fixtures_js/oraculo_evaluate/`).
