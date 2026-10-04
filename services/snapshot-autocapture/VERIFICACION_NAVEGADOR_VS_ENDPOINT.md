# Verificación navegador vs. endpoint — `POST /api/evaluate-ticker`

**Obligatoria antes de marcar el paso 3 como cerrado** (instrucción explícita
del usuario). **Esta sesión no puede ejecutarla**: no tiene acceso SSH/HTTPS
al Hetzner (verificado en una tarea anterior) ni acceso a un navegador con
`/scanner` abierto contra el servidor real. Hay que ejecutar esto a mano (o
desde la sesión con acceso al Hetzner) y pegar/comitir el resultado — mismo
patrón que `check_autocapture_triggers.sh` en todo este diseño.

Objetivo: confirmar que, con los **mismos datos de entrada**, el endpoint
nuevo (`evaluate_ticker_logic.py` vía `POST /api/evaluate-ticker`) produce
el **mismo resultado** que `evaluateTicker()` del navegador — no una
aproximación, una igualdad campo a campo.

## Requisito previo

El patch de `evaluate_ticker_endpoint.py` ya aplicado a
`market_data_proxy.py` (ver docstring de ese archivo — dónde y cómo
pegarlo, incluidos los imports exactos) y `evaluate_ticker_logic.py` +
`indicator_calc.py` copiados a `/opt/axonik/scripts/`, con
`axonik-market-proxy` reiniciado.

**Contrato actualizado (05/10/2026):** el endpoint ya no recibe `ind`
precalculado como camino normal — recibe `candles` en bruto (el `data`
tal cual lo devuelve `scan_batch()`) y calcula `ind` él mismo con
`build_ind()`. `ind` sigue existiendo como alternativa explícita
(mutuamente excluyente con `candles`, 422 si llegan los dos o ninguno),
pero el Paso B de abajo usa el camino normal: `candles`.

## Paso A — congelar los datos de entrada de un ticker real

```bash
curl -s -X POST http://127.0.0.1:8002/api/scan-batch \
  -H 'Content-Type: application/json' \
  -d '{"tickers": ["AAPL"]}' | python3 -m json.tool > /tmp/aapl_scanbatch.json

# Extraer el campo "data" del resultado de AAPL (emparejado por ticker,
# no por índice [0] -- con una sola petición da igual, pero es el mismo
# criterio que ya debe seguir snapshot_autocapture.py con 17 tickers).
# Esto son candles/periods EN BRUTO, no "ind" calculado -- lo que el
# endpoint espera ahora en el campo "candles".
python3 -c "
import json
r = json.load(open('/tmp/aapl_scanbatch.json'))
item = next(i for i in r['results'] if i['ticker'] == 'AAPL')
json.dump(item['data'], open('/tmp/aapl_candles.json','w'), indent=2)
"
cat /tmp/aapl_candles.json
```

Si `AAPL` no está en ese momento en una franja horaria con datos completos
(1d/1h/15m), probar con otro de los 17 tickers ya poblados en
`14_UNIVERSO_TICKERS`.

## Paso B — llamar al endpoint nuevo con esos datos exactos (candles en bruto)

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

# El endpoint sirve NaN como el string sentinela "NaN" explícito (NaN
# no es JSON válido -- ver evaluate_ticker_endpoint.py). El Paso C usa
# un replacer para que el navegador serialice NaN de la misma forma
# (JSON.stringify(NaN) da null por defecto en JS -- sin el replacer,
# los dos lados no serían comparables campo a campo donde haya NaN).
cat /tmp/aapl_endpoint.json
```

## Paso C — obtener el resultado del navegador con LOS MISMOS datos

1. Abrir `/scanner` en un navegador contra el servidor real.
2. DevTools → Console. **Antes de nada, comprobar `state.settings`** —
   puede diferir de `DEFAULT_SETTINGS` si se cambió alguna vez en la UI
   (persiste en `localStorage` del navegador, no en el servidor):
   ```js
   JSON.stringify(state.settings)
   ```
   Si difiere de `{priceMin:8, atrMax:4, rvolMin:1}`, **repetir el Paso B**
   con esos mismos valores — la comparación solo es válida si ambos lados
   usan el mismo `settings`.
3. Pegar el contenido de `/tmp/aapl_candles.json` como `data` y calcular
   `ind` con `computeIndicators()` **del propio navegador**, igual que
   hace `fetchNyseTicker()` (Pregunta 8) — así los dos lados (navegador
   y endpoint) parten de las mismas velas en bruto y cada uno calcula
   `ind` con su propia implementación, la comparación más completa
   posible. **Serializar con un replacer, no con `JSON.stringify(r, null, 2)`
   a secas** — `JSON.stringify(NaN)` da `null` en JS de forma nativa, y
   el endpoint sirve NaN como el string `"NaN"` (Paso B): sin el
   replacer, cualquier campo NaN compararía `null` contra `"NaN"` y
   parecería una discrepancia real sin serlo:
   ```js
   const data = /* pegar aquí el JSON de /tmp/aapl_candles.json */;
   const ind = {};
   for (const tf of ['1d','1h','15m']) {
     const tfData = data[tf];
     ind[tf] = (tfData && tfData.candles && !tfData.error) ? computeIndicators(tfData.candles, tf) : null;
   }
   const r = evaluateTicker('AAPL', ind, null, 'NYSE', state.settings, false, null);
   const nanSafeReplacer = (k, v) => (typeof v === 'number' && Number.isNaN(v)) ? 'NaN' : v;
   console.log(JSON.stringify(r, nanSafeReplacer, 2));
   copy(JSON.stringify(r, nanSafeReplacer, 2));  // Chrome/Firefox: copia al portapapeles
   ```
4. Pegar ese resultado en `/tmp/aapl_browser.json`.

## Paso D — diff campo a campo

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

**Deben coincidir exactamente:** `hardNo`, `globalVerdict`, `globalScore`,
y para cada estrategia `applicable`/`score`/`verdict` (los `factors` en
detalle son útiles para depurar una discrepancia, pero el criterio de
cierre es el resumen de arriba).

## Qué hacer con el resultado

- **Coinciden:** pegar/comitir `/tmp/aapl_endpoint.json`,
  `/tmp/aapl_browser.json` y la salida del Paso D como
  `docs/pipeline/verificacion_evaluate_ticker_<TICKER>.txt` — recién
  entonces se puede marcar el paso 3 como cerrado en BACKLOG.
- **Difieren:** NO cerrar nada. Pegar ambos JSON completos (no el resumen)
  para localizar en qué estrategia/factor concreto diverge — mismo
  criterio que ya resolvió `risk_pct` vs. `risk_per_share` y el bug de
  `AUTO_MULTI`/`AUTO_HIGH`: texto literal, no una descripción de la
  diferencia.
- Repetir con 2-3 tickers más (idealmente uno que dispare `AUTO_MULTI` y
  otro `AUTO_HIGH`) antes de dar el endpoint por fiable en producción —
  un solo ticker que coincida no cubre las 10 funciones `evalXX`.
