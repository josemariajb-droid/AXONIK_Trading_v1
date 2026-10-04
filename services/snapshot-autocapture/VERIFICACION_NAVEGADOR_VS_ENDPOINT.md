# Verificación oráculo (Node) vs. endpoint — `POST /api/evaluate-ticker`

**Obligatoria antes de marcar el paso 3 como cerrado** (instrucción explícita
del usuario). **Esta sesión no puede ejecutarla**: no tiene acceso SSH/HTTPS
al Hetzner (verificado en una tarea anterior). Hay que ejecutar esto a mano
(o desde la sesión con acceso al Hetzner) y comitir el resultado — mismo
patrón que `check_autocapture_triggers.sh` en todo este diseño.

Objetivo: confirmar que, con las **mismas velas de entrada**, el endpoint
nuevo (`evaluate_ticker_logic.py` vía `POST /api/evaluate-ticker`) produce
el **mismo resultado** que `evaluateTicker()`/`detectAutoTrigger()` del
navegador — no una aproximación, una igualdad campo a campo.

## Cambio de camino principal (05/10/2026)

Hasta esta revisión, el Paso C pedía abrir `/scanner` en un navegador y pegar
las velas en la consola de DevTools. Eso dejó de ser práctico por dos
motivos reales, no hipotéticos:

- **Nadie ha abierto nunca `/scanner` contra el servidor real** — no hay un
  resultado de navegador ya confirmado con el que comparar.
- **El Paso 1 de este mismo README bindea el proxy a 127.0.0.1** — en cuanto
  se aplique, `/scanner` deja de ser alcanzable desde fuera del propio host,
  así que depender de un navegador externo para esto no es solo incómodo,
  deja de funcionar.

Node (v24.15.0 confirmado en el servidor) es el mismo motor V8 que
Chrome/Firefox: ejecutar el JS real de `evaluateTicker()`/`detectAutoTrigger()`
bajo Node da el mismo resultado que ejecutarlo en un navegador, sin
necesidad de abrir nada. Misma técnica ya usada y probada en
`generar_fixtures_js.sh` para `computeIndicators()` + sus 9 funciones de
cálculo. **El oráculo Node es ahora el camino principal.** La consola del
navegador (antiguo Paso C, abajo en "Alternativa") queda como vía de
repuesto si alguna vez hace falta comparar también contra un navegador real
con acceso a `/scanner` — no es necesaria para cerrar el paso 3.

## Requisito previo

El patch de `evaluate_ticker_endpoint.py` ya aplicado a `market_data_proxy.py`
(`docs/pipeline/deploy_evaluate_endpoint.sh`) y el proxy reiniciado y sano
(`systemctl is-active` + `/api/health`).

## Paso 1 — generar el oráculo (Node real, no una reimplementación)

```bash
docs/pipeline/generar_oraculo_evaluate_js.sh
```

Sin argumentos, carga el universo real de `14_UNIVERSO_TICKERS` (vía
`cargar_universo_de_tickers()`, `ESTADO=ACTIVO`, excluye `CRYPTO`) y pide sus
velas reales con `POST /api/scan-batch` (troceando en lotes adaptativos si el
proxy responde 400 por `MAX_BATCH_TICKERS` — nunca se asume un tamaño fijo).
Para un ticker concreto o para repetir sin tocar la hoja:

```bash
docs/pipeline/generar_oraculo_evaluate_js.sh AAPL MSFT NVDA
```

Qué hace, en orden (detalle completo en la cabecera del script):

1. Extrae de `/opt/axonik/scanner/index.html` las 32 piezas que necesita
   `evaluateTicker()`/`detectAutoTrigger()`: las 22 ya confirmadas
   (`evaluateTicker`, `detectAutoTrigger`, `NYSE_STRATEGIES`,
   `CRYPTO_STRATEGIES`, `applyEventAdjustments`, `tickerHardNo`, las 10
   `evalXX`, `mkResult`, `mkNA`, `finalizeVerdict`, `f`, `STRATEGY_META`,
   `MAX_RAW_SCORE`) más `computeIndicators()` y sus 9 funciones de cálculo.
   Extracción **anclada**: cada pieza tiene una línea real ya confirmada
   (acumulada en pasadas anteriores de `check_autocapture_triggers.sh`); si
   esa línea ya no coincide (el navegador cambió desde la última auditoría),
   el script cae a una búsqueda global que **aborta sin escribir nada** si
   hay 0 o más de 1 coincidencia — nunca adivina, ni con nombres cortos como
   `f`.
2. Pide las velas reales de cada ticker con `POST /api/scan-batch`,
   emparejado siempre por ticker, nunca por índice.
3. Ejecuta bajo Node real `computeIndicators()` por timeframe +
   `evaluateTicker(t, ind, null, 'NYSE', {priceMin:8, atrMax:4, rvolMin:1},
   false, null)` + `detectAutoTrigger()` sobre ese resultado, para cada
   ticker. NaN se sirve como el string `"NaN"` (mismo convenio que
   `evaluate_ticker_logic.nan_to_json_sentinel()`).
4. Guarda en `docs/pipeline/fixtures_js/oraculo_evaluate/`: las velas de
   entrada, la salida de `evaluateTicker()` y el resultado de
   `detectAutoTrigger()`, por ticker.

Solo lectura sobre `index.html` y sobre el proxy (GET/POST normales, ningún
endpoint de escritura). La única escritura es local, dentro de este repo.
**No despliega nada.**

## Paso 2 — comparar contra el endpoint real

```bash
cd services/snapshot-autocapture
pytest test_oraculo_vs_endpoint.py -v -s
```

Por cada ticker con fixtures en `docs/pipeline/fixtures_js/oraculo_evaluate/`:
reconstruye el payload `candles` a partir de las velas congeladas, llama de
verdad a `POST http://127.0.0.1:8002/api/evaluate-ticker` (no una
`TestClient` en memoria — a propósito, el objetivo es el servidor real) y
compara campo a campo contra el oráculo: `hardNo`, `globalVerdict`,
`globalScore` y, por estrategia, `id`/`applicable`/`score`/`verdict` —
tolerancia `1e-9` en los numéricos. Compara además `detect_auto_trigger()`
(tipo de disparo y conjunto de estrategias), algo que la verificación manual
anterior nunca llegó a cubrir.

Si el proxy real no está arriba o no hay fixtures, la prueba se auto-omite
(`SKIPPED`) con un mensaje explicando por qué — no falla en falso en un
entorno sin servidor.

Al final, un test informativo (`test_informe_cobertura_detect_auto_trigger`)
imprime y comita en
`docs/pipeline/fixtures_js/oraculo_evaluate/_comparacion_resultado.txt` qué
ramas de `detectAutoTrigger()` quedaron ejercitadas con datos reales del día
de la ejecución: `AUTO_MULTI`, `AUTO_HIGH` o ninguna. **Si alguna de las dos
ramas no aparece ahí, no es una laguna de pruebas** — ambas ya tienen
cobertura dedicada con datos sintéticos en `test_evaluate_ticker_logic.py`
(que construye los dos casos a mano, sin depender de que el mercado real los
produzca ese día concreto); este informe es solo un dato adicional de
mercado, no un sustituto de esos tests unitarios.

## Qué hacer con el resultado

- **Todo verde (`pytest` en 0 fallos):** comitear
  `docs/pipeline/fixtures_js/oraculo_evaluate/` completo (velas, salidas del
  oráculo y `_comparacion_resultado.txt`) — recién entonces se puede marcar
  el paso 3 como cerrado en `BACKLOG.md`.
- **Algún test falla:** NO cerrar nada. El mensaje de `assert` ya señala el
  ticker y el campo exacto que difiere (p.ej.
  `evaluate[AAPL].strategies[ST-16].score: 82 != 100`) — localizar en qué
  `evalXX`/factor concreto diverge con eso, mismo criterio que ya resolvió
  `risk_pct` vs. `risk_per_share` y el bug de `AUTO_MULTI`/`AUTO_HIGH`: el
  dato exacto que no coincide, no una descripción de la diferencia.
- El universo real de `14_UNIVERSO_TICKERS` (17 tickers) ya cubre varios
  tickers por ejecución — no hace falta repetir con tickers sueltos salvo
  para aislar un fallo concreto.

## Alternativa — consola del navegador (si alguna vez hace falta)

Solo necesaria si en algún momento hay que comparar también contra un
navegador real con `/scanner` abierto (p.ej. para descartar una diferencia
de motor JS, algo que nunca ha ocurrido hasta ahora) — no es parte del
camino para cerrar el paso 3.

### A — congelar los datos de entrada de un ticker real

```bash
curl -s -X POST http://127.0.0.1:8002/api/scan-batch \
  -H 'Content-Type: application/json' \
  -d '{"tickers": ["AAPL"]}' | python3 -m json.tool > /tmp/aapl_scanbatch.json

# Extraer el campo "data" del resultado de AAPL (emparejado por ticker,
# no por índice [0]).
python3 -c "
import json
r = json.load(open('/tmp/aapl_scanbatch.json'))
item = next(i for i in r['results'] if i['ticker'] == 'AAPL')
json.dump(item['data'], open('/tmp/aapl_candles.json','w'), indent=2)
"
```

### B — llamar al endpoint con esos datos exactos (candles en bruto)

```bash
python3 -c "
import json
candles = json.load(open('/tmp/aapl_candles.json'))
payload = {
    'ticker': 'AAPL', 'mode': 'NYSE', 'candles': candles, 'funda': None,
    'settings': {'priceMin': 8, 'atrMax': 4, 'rvolMin': 1},
    'btc_gate_on': False, 'insider_summary': None,
}
json.dump(payload, open('/tmp/aapl_request.json','w'))
"
curl -s -X POST http://127.0.0.1:8002/api/evaluate-ticker \
  -H 'Content-Type: application/json' \
  -d @/tmp/aapl_request.json -o /tmp/aapl_endpoint.json
cat /tmp/aapl_endpoint.json
```

### C — obtener el resultado del navegador con LOS MISMOS datos

1. Abrir `/scanner` en un navegador contra el servidor real (solo posible si
   el proxy sigue bindeado a `0.0.0.0`, o vía túnel SSH/reverse proxy propio
   si ya se aplicó el Paso 1 de bind a 127.0.0.1).
2. DevTools → Console. Comprobar primero `state.settings` — puede diferir de
   `DEFAULT_SETTINGS` si se cambió alguna vez en la UI (persiste en
   `localStorage` del navegador, no en el servidor):
   ```js
   JSON.stringify(state.settings)
   ```
   Si difiere de `{priceMin:8, atrMax:4, rvolMin:1}`, repetir el Paso B con
   esos mismos valores.
3. Pegar el contenido de `/tmp/aapl_candles.json` como `data` y calcular
   `ind` con `computeIndicators()` del propio navegador:
   ```js
   const data = /* pegar aquí el JSON de /tmp/aapl_candles.json */;
   const ind = {};
   for (const tf of ['1d','1h','15m']) {
     const tfData = data[tf];
     ind[tf] = (tfData && tfData.candles && !tfData.error) ? computeIndicators(tfData.candles, tf) : null;
   }
   const r = evaluateTicker('AAPL', ind, null, 'NYSE', state.settings, false, null);
   // JSON.stringify(NaN) da null en JS de forma nativa -- el endpoint sirve
   // NaN como el string "NaN" (Paso B); sin este replacer, un campo NaN
   // compararía null contra "NaN" y parecería una discrepancia real sin serlo.
   const nanSafeReplacer = (k, v) => (typeof v === 'number' && Number.isNaN(v)) ? 'NaN' : v;
   console.log(JSON.stringify(r, nanSafeReplacer, 2));
   copy(JSON.stringify(r, nanSafeReplacer, 2));  // Chrome/Firefox: copia al portapapeles
   ```
4. Pegar ese resultado en `/tmp/aapl_browser.json`.

### D — diff campo a campo

```bash
python3 -c "
import json
a = json.load(open('/tmp/aapl_endpoint.json'))
b = json.load(open('/tmp/aapl_browser.json'))

def resumen(r):
    return {
        'hardNo': r['hardNo'], 'globalVerdict': r['globalVerdict'],
        'globalScore': r['globalScore'],
        'strategies': sorted([(s['id'], s['applicable'], s.get('score'), s['verdict']) for s in r['strategies']]),
    }

ra, rb = resumen(a), resumen(b)
print('endpoint:', ra)
print('navegador:', rb)
print('COINCIDEN' if ra == rb else 'DIFIEREN -- no cerrar el paso 3 hasta resolver esto')
"
```

**Deben coincidir exactamente:** `hardNo`, `globalVerdict`, `globalScore`, y
para cada estrategia `applicable`/`score`/`verdict`. Repetir con 2-3 tickers
más si se usa esta vía como único criterio de cierre (el oráculo Node del
Paso 1/2 ya cubre el universo completo en una sola ejecución, así que
normalmente no hace falta llegar hasta aquí).
