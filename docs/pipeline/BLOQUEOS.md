# Bloqueos abiertos

Documento vivo -- se añade una entrada cuando algo bloquea un cierre real
(no una duda menor), con qué falta exactamente y cómo resolverlo. No se
improvisa el valor que falta: se deja el código en el estado más seguro
conocido y se sigue con el resto de la tarea.

## 1. `computeMarketContext()` -- gate BTC de la ruta CRIPTO (06/10/2026)

**Qué falta:** el cuerpo real de `computeMarketContext(mode)`, de dónde
sale `state.marketContext.gateOn` (qué indicador de BTC, qué umbral). Solo
está confirmado el PUNTO DE LLAMADA en `runScan()` (línea 243, ya volcado
en `docs/pipeline/pregunta5_5b_salida.txt` y compañía):

```js
state.marketContext = await computeMarketContext(mode);
renderMarketContext();
const btcGateOn = mode==='CRYPTO' ? (state.marketContext ? state.marketContext.gateOn : false) : null;
```

La propia función nunca se ha extraído/dumpado -- ningún
`pregunta*_salida.txt` contiene `function computeMarketContext`.

**Impacto real:** `evalSC02`/`evalSCPB` (`eval_sc02`/`eval_scpb` en
`evaluate_ticker_logic.py`) ya están portados y verificados (devuelven
`mkNA('...','Gate BTC OFF')` si `btcGateOn` es falso), pero NADA en el
puerto decide todavía si el gate debería estar ON -- esa decisión vive
solo dentro de `computeMarketContext()`.

**Qué se hizo mientras tanto, sin improvisar el cálculo:**
`snapshot_autocapture.compute_btc_gate()` devuelve `False` siempre,
documentado como sustituto temporal -- es exactamente la misma rama que
ya tiene el código real cuando `state.marketContext` sale falsy (gate
OFF), no una aproximación nueva. Con el gate forzado a OFF, SC-02/SC-PB
nunca pueden disparar una señal long mientras esto no se resuelva --
verificado en `test_snapshot_autocapture_cripto.py::test_compute_btc_gate_hoy_siempre_da_false_y_sc02_scpb_salen_na`.

**Cómo resolverlo:** ejecutar la Pregunta 11, ya añadida a
`docs/pipeline/check_autocapture_triggers.sh`, contra el servidor real y
pegar la salida completa (mismo patrón que las Preguntas 1-10). Una vez
con el texto literal, portar `compute_market_context()` a
`evaluate_ticker_logic.py` (o a `snapshot_autocapture.py` si resulta ser
puramente cripto, sin dependencias de `ind`/`evaluate_ticker`) y sustituir
`compute_btc_gate()` por la llamada real.

## 2. `BINANCE_BASE` -- valor real sin confirmar (06/10/2026)

**Qué falta:** el valor de la constante `BINANCE_BASE`, usada en
`fetchBinanceKlines()` (`` `${BINANCE_BASE}/api/v3/klines?...` ``,
confirmado literal en `pregunta9_salida.txt`/`pregunta10_salida.txt`) --
solo se ha visto el NOMBRE dentro de la URL interpolada, nunca la línea
`const BINANCE_BASE = '...'` que le da valor.

**Qué se hizo mientras tanto:** `snapshot_autocapture.BINANCE_BASE` usa
el dominio público estándar (`https://api.binance.com`) como valor por
defecto, **documentado como supuesto no confirmado**, overridable sin
tocar código vía `AXONIK_BINANCE_BASE` si el servidor real usa otro
dominio (p.ej. un proxy propio, o `api.binance.us` si el servidor opera
desde EEUU).

**Cómo resolverlo:** la Pregunta 11 ya añadida a
`check_autocapture_triggers.sh` también busca
`` (const|let|var)\s+BINANCE_BASE\b ``. Si el grep no encuentra nada (la
constante puede estar definida con otra convención, p.ej. inline sin
nombre), buscar a mano `api.binance` en `index.html` y pegar la línea
exacta.

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
