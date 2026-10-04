"""
Código listo para pegar en `market_data_proxy.py` — POST /api/evaluate-ticker
(decisión de arquitectura 04/10/2026: single source of truth server-side con
evaluate_ticker_logic.py, 22 piezas ya portadas y probadas — no una segunda
copia en snapshot_autocapture.py).

CONFIRMADO contra el código real (Pregunta 6, docs/pipeline/pregunta6_salida.txt):

  - Imports reales (6a, líneas 894-920 de market_data_proxy.py): `app` es
    el nombre real de la variable FastAPI; Pydantic es v2
    (`BaseModel, Field`, sintaxis `tipo | None`); `HTTPException` ya
    viene importado de `fastapi` — no hace falta reimportarlo al pegar
    esto.
  - Decorador real (6b): ningún endpoint de escritura usa `Depends` ni
    `response_model` hoy (coherente con BACKLOG entrada 2: sin
    autenticación en ningún endpoint) — mismo estilo simple que
    `create_snapshot`/`scan_batch`:
        @app.post("/api/algo")
        async def handler(req: AlgoRequest):
  - `ScanBatchRequest.tickers` (6c) confirma que `fetch_scan_batch()` en
    snapshot_autocapture.py ya usaba el campo correcto ("tickers") — no
    era solo una suposición con suerte, queda confirmado contra el
    Pydantic real.
  - `DEFAULT_SETTINGS` real (6d, línea 671 de index.html):
    {capital:10000, riskPct:0.5, priceMin:8, atrMax:4, rvolMin:1} — el
    SETTINGS placeholder de snapshot_autocapture.py tenía atrMax=6,
    corregido a 4.

DÓNDE PEGAR: inmediatamente después de la línea `return {"results": results}`
que cierra `scan_batch()` (línea ~942+ de market_data_proxy.py, confirmada
en la Pregunta 4c/6b), antes de lo que venga a continuación. Añadir
también `import evaluate_ticker_logic as etl` junto a los demás imports
de la cabecera, y copiar
`services/snapshot-autocapture/evaluate_ticker_logic.py` a
`/opt/axonik/scripts/evaluate_ticker_logic.py` (mismo directorio que
`market_data_proxy.py`, para que el import resuelva).

SIGUE SIN CONFIRMAR, no bloquea esto: la forma exacta de `ind` que
produce `get_ticker_data()` dentro de `scan_batch()` (no extraída todavía
— ver docstring de evaluate_ticker_logic.py). No es un problema del
endpoint en sí: si el shape real difiere, los evalXX ya devuelven mkNA()
en vez de fallar cuando falta una clave, así que el síntoma sería
"todo N/A", no una excepción — a confirmar en la verificación
navegador-vs-endpoint.
"""
from typing import Optional

from pydantic import BaseModel

import evaluate_ticker_logic as etl


class EvaluateTickerRequest(BaseModel):
    ticker: str
    mode: str  # "NYSE" | "CRYPTO"
    # Shape consumido por evaluate_ticker_logic: {"1d": {...}, "1h": {...},
    # "15m": {...}}. Deliberadamente `dict` sin sub-modelo tipado campo a
    # campo: evaluate_ticker_logic ya hace .get() con fallback a NaN sobre
    # estas claves (mismo diseño que el JS original), y el shape real de
    # get_ticker_data() sigue sin confirmar (ver docstring de arriba) —
    # un esquema Pydantic estricto aquí solo añadiría una SEGUNDA
    # definición de la forma de "ind" que podría divergir de la real.
    ind: dict
    funda: Optional[dict] = None
    settings: dict  # CONFIRMADO (Pregunta 6d): DEFAULT_SETTINGS real, ver docstring arriba.
    btc_gate_on: bool = False
    insider_summary: Optional[dict] = None


# --- Pegar desde aquí en market_data_proxy.py (HTTPException ya está
#     importado en ese archivo, ver docstring arriba) ---

@app.post("/api/evaluate-ticker")
async def evaluate_ticker_endpoint(req: EvaluateTickerRequest):
    result = etl.evaluate_ticker(
        req.ticker, req.ind, req.funda, req.mode, req.settings,
        req.btc_gate_on, req.insider_summary,
    )
    if result is None:
        # evaluate_ticker_logic.evaluate_ticker() devuelve None si falta
        # el indicador "1d" en `ind` -- no es un payload mal formado en
        # sentido estricto, pero tampoco hay nada que evaluar.
        raise HTTPException(status_code=422,
                             detail="Indicador '1d' ausente en 'ind' -- no se puede evaluar.")
    return result

# Nota aparte, no bloqueante: el resultado puede contener float('nan')
# (p.ej. si algún indicador falta). json.dumps estándar de Python lo
# serializa como el literal `NaN` (no JSON estricto, pero válido para
# dos extremos Python con json.dumps/json.loads, y market_data_proxy.py
# usa fastapi.responses.JSONResponse -- no ORJSONResponse, confirmado en
# los imports de 6a -- que por defecto permite NaN). A confirmar de
# todos modos en la verificación navegador-vs-endpoint.
