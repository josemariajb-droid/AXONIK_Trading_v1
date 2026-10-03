"""
Código listo para pegar en `market_data_proxy.py` — POST /api/evaluate-ticker
(decisión de arquitectura 04/10/2026: single source of truth server-side con
evaluate_ticker_logic.py, 22 piezas ya portadas y probadas — no una segunda
copia en snapshot_autocapture.py).

NO APLICADO TODAVÍA EN EL ARCHIVO REAL. Esta sesión nunca ha visto
market_data_proxy.py completo — solo fragmentos extraídos con
docs/pipeline/check_autocapture_triggers.sh (cuerpos de create_snapshot()/
scan_batch() por indentación desde la línea `def`, sin la línea del
decorador de encima). Pegar este código tal cual, sin más, sería inventar
el estilo real del archivo (nombre de la variable `app`, convención de
imports, si otros endpoints de escritura ya usan algún `Depends` de
autenticación) — exactamente el tipo de suposición que este diseño ya ha
evitado en todo lo anterior.

Antes de aplicar esto de verdad:
  1. Ejecutar la Pregunta 6 de check_autocapture_triggers.sh (6a/6b/6c/6d)
     contra el servidor real.
  2. Ajustar el decorador (`@app.post(...)`) y los imports de abajo para
     que coincidan exactamente con el estilo confirmado en 6a/6b.
  3. Confirmar con 6d los valores reales de settings (priceMin/atrMax/
     rvolMin) — los de SETTINGS en snapshot_autocapture.py son un
     placeholder, no los reales de producción.
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
    # estas claves (mismo diseño que el JS original), así que un esquema
    # Pydantic estricto aquí solo añadiría una SEGUNDA definición de la
    # forma de "ind" que podría divergir de la real (NO CONFIRMADO,
    # ver docstring de evaluate_ticker_logic.py) sin aportar nada.
    ind: dict
    funda: Optional[dict] = None
    # NO CONFIRMADO (Pregunta 6d): valores reales de producción pendientes.
    settings: dict
    btc_gate_on: bool = False
    insider_summary: Optional[dict] = None


# --- A partir de aquí, pendiente de ajustar al estilo real (Pregunta 6a/6b) ---
#
# @app.post("/api/evaluate-ticker")
# async def evaluate_ticker_endpoint(req: EvaluateTickerRequest):
#     result = etl.evaluate_ticker(
#         req.ticker, req.ind, req.funda, req.mode, req.settings,
#         req.btc_gate_on, req.insider_summary,
#     )
#     if result is None:
#         # evaluate_ticker_logic.evaluate_ticker() devuelve None si falta
#         # el indicador "1d" en `ind` -- no es un error del cliente en el
#         # sentido de payload mal formado, pero tampoco hay nada que evaluar.
#         raise HTTPException(status_code=422,
#                              detail="Indicador '1d' ausente en 'ind' -- no se puede evaluar.")
#     return result
#
# Nota aparte, no bloqueante: el resultado puede contener float('nan') (p.ej.
# si algún indicador falta). json.dumps estándar de Python lo serializa como
# el literal `NaN` (no JSON estricto, pero válido para dos extremos Python
# con json.dumps/json.loads). Si FastAPI usa ORJSONResponse en este proxy
# (no confirmado), eso fallaría -- a verificar en el --dry-run.
