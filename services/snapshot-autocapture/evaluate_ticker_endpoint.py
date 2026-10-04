"""
Código para pegar en `market_data_proxy.py` — POST /api/evaluate-ticker
(decisión de arquitectura 04/10/2026: single source of truth server-side
con evaluate_ticker_logic.py + indicator_calc.py — ninguna lógica de
cálculo se reimplementa aquí ni en snapshot_autocapture.py).

CONTRATO (05/10/2026, decisión del usuario tras el hallazgo de
computeIndicators()): el endpoint acepta **candles en bruto** (el
"data" tal cual lo devuelve scan_batch(): {"1d": {"candles":[...],
"periods":N}, "1h": {...}, "15m": {...}}) y calcula "ind" él mismo con
build_ind() (evaluate_ticker_logic.py) — un único camino de cálculo. Se
mantiene "ind" ya calculado como alternativa explícita, mutuamente
excluyente con "candles" (422 si llegan los dos o ninguno) -- útil para
pruebas o un futuro cliente que ya tenga los indicadores.

ESTE ARCHIVO ES IMPORTABLE Y TESTEABLE TAL CUAL (ver
test_evaluate_ticker_endpoint.py) -- a propósito, para no repetir el
NameError de la versión anterior (que tenía `@app.post(...)` como
decorador de módulo, y `app`/`HTTPException` sin definir ni importar en
este archivo; importarlo para probarlo reventaba antes de llegar a
ejecutar nada). Aquí:
  - `HTTPException` se importa directamente de `fastapi` (duplicar el
    import en market_data_proxy.py, que ya lo tiene, es inocuo).
  - La única pieza que de verdad pertenece solo al archivo real es la
    variable `app` (la instancia FastAPI, un singleton de ese módulo) --
    por eso la función de abajo se queda SIN decorador aquí, y el
    decorador se añade a mano al pegarla (ver "DÓNDE Y CÓMO PEGAR").

IMPORTS que este bloque necesita y de dónde salen (pedido explícito:
no repetir el NameError por no listarlos):
  - `json` de la librería estándar -- import de este archivo (para
    servir el NaN sentinel, ver más abajo).
  - `Optional` de `typing` -- import de este archivo.
  - `HTTPException` y `Response` de `fastapi` -- import de este
    archivo (`HTTPException` es duplicado inocuo si se pega en
    market_data_proxy.py, que ya lo importa; `Response` probablemente
    no estaba importado ahí todavía -- confirmar).
  - `BaseModel` de `pydantic` -- import de este archivo.
  - `evaluate_ticker_logic` -- módulo propio, debe copiarse a
    `/opt/axonik/scripts/evaluate_ticker_logic.py` junto con
    `indicator_calc.py` (del que depende vía `build_ind()`).
  - `app` -- la instancia FastAPI real de `market_data_proxy.py`, NO
    se importa aquí: solo se usa en el decorador que se añade a mano
    al pegar (ver abajo). No está definida en este archivo a propósito.

DÓNDE Y CÓMO PEGAR en market_data_proxy.py:
  1. Añadir los imports de arriba (json/Optional/HTTPException/Response/
     BaseModel) a la cabecera si no están ya, y
     `import evaluate_ticker_logic as etl`.
  2. Copiar `evaluate_ticker_logic.py` + `indicator_calc.py` a
     `/opt/axonik/scripts/` (mismo directorio que market_data_proxy.py).
  3. Pegar `EvaluateTickerRequest`, `resolve_ind` y
     `evaluate_ticker_endpoint` tal cual, inmediatamente después de la
     línea `return {"results": results}` que cierra `scan_batch()`
     (confirmado en Pregunta 4c/6b).
  4. Añadir la línea `@app.post("/api/evaluate-ticker")` justo encima
     de `async def evaluate_ticker_endpoint(req: EvaluateTickerRequest):`
     -- es la única línea que de verdad pertenece solo al archivo real,
     por eso no está aquí (mismo estilo simple que `create_snapshot`/
     `scan_batch`, confirmado en Pregunta 6b: sin `Depends`, sin
     `response_model`).

SIGUE SIN CONFIRMAR, no bloquea esto: la forma exacta de `candles`/
`periods` que produce `get_ticker_data()` dentro de `scan_batch()` (no
extraída todavía) -- pero ya no importa tanto como antes: `build_ind()`
delega en `indicator_calc.compute_indicators()`, que ya está probado
contra 9 fixtures reales (AAPL/MSFT/NVDA × 1d/1h/15m) con la forma real
de "candles" que de verdad llega, así que esto está cubierto salvo que
el shape cambie entre llamadas.
"""
import json
from typing import Optional

from fastapi import HTTPException, Response
from pydantic import BaseModel

import evaluate_ticker_logic as etl


class EvaluateTickerRequest(BaseModel):
    ticker: str
    mode: str  # "NYSE" | "CRYPTO"
    # Mutuamente excluyentes -- exactamente uno de los dos (ver
    # resolve_ind más abajo, que es quien de verdad lo exige).
    candles: Optional[dict] = None  # "data" en bruto de scan_batch(): {"1d":{"candles":[...],"periods":N},...}
    ind: Optional[dict] = None  # ind ya calculado -- compatibilidad explícita, no el camino normal
    funda: Optional[dict] = None
    settings: dict  # CONFIRMADO (Pregunta 6d): DEFAULT_SETTINGS real {priceMin:8, atrMax:4, rvolMin:1, ...}
    btc_gate_on: bool = False
    insider_summary: Optional[dict] = None


def resolve_ind(candles: Optional[dict], ind: Optional[dict]) -> dict:
    """
    Única función que decide qué "ind" usar -- NUNCA reimplementa el
    cálculo de indicadores, solo elige entre build_ind(candles) (el
    camino normal, un único cálculo real en indicator_calc.py vía
    evaluate_ticker_logic.build_ind) o el "ind" ya dado (compatibilidad).

    Lanza ValueError si llegan los dos o ninguno -- el handler de abajo
    lo traduce a HTTPException 422, no se valida dos veces.

    Si llega "ind" ya calculado, se decodifica con sentinel_to_nan():
    NaN no es JSON válido en ninguna dirección (confirmado con
    httpx/TestClient real en test_evaluate_ticker_endpoint.py -- rechaza
    NaN igual que Starlette al responder), así que cualquier cliente
    que use la vía "ind" debe mandar el mismo sentinela "NaN" que sirve
    este endpoint en sus respuestas -- contrato simétrico en las dos
    direcciones, no solo al responder.
    """
    if (candles is None) == (ind is None):
        raise ValueError("Enviar exactamente uno de 'candles' o 'ind', no los dos ni ninguno.")
    return etl.build_ind(candles) if candles is not None else etl.sentinel_to_nan(ind)


# --- A partir de aquí, pegar tal cual en market_data_proxy.py. Añadir
#     la línea "@app.post("/api/evaluate-ticker")" justo encima de la
#     siguiente (ver "DÓNDE Y CÓMO PEGAR" arriba) -- no está aquí
#     porque `app` no se importa en este archivo a propósito. ---
async def evaluate_ticker_endpoint(req: EvaluateTickerRequest):
    try:
        ind = resolve_ind(req.candles, req.ind)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))

    result = etl.evaluate_ticker(
        req.ticker, ind, req.funda, req.mode, req.settings,
        req.btc_gate_on, req.insider_summary,
    )
    if result is None:
        # evaluate_ticker_logic.evaluate_ticker() devuelve None si falta
        # el indicador "1d" -- no es un payload mal formado en sentido
        # estricto, pero tampoco hay nada que evaluar.
        raise HTTPException(status_code=422,
                             detail="Indicador '1d' ausente -- no se puede evaluar.")

    # El resultado puede contener float('nan') (p.ej. gapPct en 1h/15m,
    # vwap en 1d/1h). PROBADO con una app FastAPI real
    # (test_evaluate_ticker_endpoint.py): la JSONResponse por defecto
    # de Starlette/FastAPI usa `allow_nan=False` y lanza ValueError al
    # intentar servir un NaN -- no lo permite en absoluto, al revés de
    # lo que se había asumido sin probarlo la primera vez. Se sirve a
    # mano con el sentinela de texto "NaN" (mismo convenio que los
    # fixtures de Node) en vez de depender del JSON no estándar.
    body = json.dumps(etl.nan_to_json_sentinel(result))
    return Response(content=body, media_type="application/json")
