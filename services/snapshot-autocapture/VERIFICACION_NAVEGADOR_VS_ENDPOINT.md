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
`market_data_proxy.py` (ver docstring de ese archivo — dónde pegarlo) y
`evaluate_ticker_logic.py` copiado a `/opt/axonik/scripts/`, con
`axonik-market-proxy` reiniciado.

## Paso A — congelar los datos de entrada de un ticker real

```bash
curl -s -X POST http://127.0.0.1:8002/api/scan-batch \
  -H 'Content-Type: application/json' \
  -d '{"tickers": ["AAPL"]}' | python3 -m json.tool > /tmp/aapl_scanbatch.json

# Extraer solo el campo "data" del primer resultado (es el "ind" que
# espera evaluate-ticker):
python3 -c "
import json
r = json.load(open('/tmp/aapl_scanbatch.json'))
json.dump(r['results'][0]['data'], open('/tmp/aapl_ind.json','w'), indent=2)
"
cat /tmp/aapl_ind.json
```

Si `AAPL` no está en ese momento en una franja horaria con datos completos
(1d/1h/15m), probar con otro de los 17 tickers ya poblados en
`14_UNIVERSO_TICKERS`.

## Paso B — llamar al endpoint nuevo con esos datos exactos

```bash
python3 -c "
import json
ind = json.load(open('/tmp/aapl_ind.json'))
payload = {
    'ticker': 'AAPL', 'mode': 'NYSE', 'ind': ind, 'funda': None,
    'settings': {'priceMin': 8, 'atrMax': 4, 'rvolMin': 1},
    'btc_gate_on': False, 'insider_summary': None,
}
json.dump(payload, open('/tmp/aapl_request.json','w'))
"
curl -s -X POST http://127.0.0.1:8002/api/evaluate-ticker \
  -H 'Content-Type: application/json' \
  -d @/tmp/aapl_request.json | python3 -m json.tool > /tmp/aapl_endpoint.json
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
3. Pegar el contenido de `/tmp/aapl_ind.json` como `ind` y llamar a la
   función real tal cual:
   ```js
   const ind = /* pegar aquí el JSON de /tmp/aapl_ind.json */;
   const r = evaluateTicker('AAPL', ind, null, 'NYSE', state.settings, false, null);
   console.log(JSON.stringify(r, null, 2));
   copy(JSON.stringify(r, null, 2));  // Chrome/Firefox: copia al portapapeles
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
