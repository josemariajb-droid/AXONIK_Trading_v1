"""
Pruebas de POST /api/evaluate-ticker (evaluate_ticker_endpoint.py)
contra una app FastAPI real (fastapi 0.141.1, confirmado instalado) --
no una simulación de lo que "debería" pasar. Registra el endpoint
exactamente como se pegaría en market_data_proxy.py
(`app.post("/api/evaluate-ticker")(evaluate_ticker_endpoint)`, mismo
efecto que el decorador `@app.post(...)` que se añade al pegarlo) y
le manda peticiones HTTP reales con TestClient.

Condición del usuario: el endpoint con candles en bruto debe devolver
EXACTAMENTE lo mismo que build_ind() + evaluate_ticker() directo --
single source of truth, nunca una segunda implementación.
"""
from __future__ import annotations

import json
import math
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import evaluate_ticker_logic as etl
from evaluate_ticker_endpoint import EvaluateTickerRequest, evaluate_ticker_endpoint

FIXTURES_DIR = Path(__file__).parent.parent.parent / "docs" / "pipeline" / "fixtures_js"
TICKERS = ["AAPL", "MSFT", "NVDA"]
SETTINGS = {"priceMin": 8, "atrMax": 4, "rvolMin": 1}  # DEFAULT_SETTINGS real, Pregunta 6d


def _app() -> FastAPI:
    """Misma app mínima para cada test -- registra el endpoint con el
    mismo efecto que el decorador @app.post(...) que se añade al pegar
    esto en market_data_proxy.py."""
    app = FastAPI()
    app.post("/api/evaluate-ticker")(evaluate_ticker_endpoint)
    return app


def load_raw_data(ticker: str) -> dict:
    raw = json.load(open(FIXTURES_DIR / f"{ticker}_scanbatch_raw.json"))
    item = next(r for r in raw["results"] if r["ticker"] == ticker)
    assert not item.get("error")
    return item["data"]


def assert_close(actual, expected, path="$", rel_tol=1e-9):
    if isinstance(expected, dict):
        assert isinstance(actual, dict), path
        for k, v in expected.items():
            assert_close(actual.get(k), v, f"{path}.{k}", rel_tol)
        return
    if isinstance(expected, list):
        assert isinstance(actual, list) and len(actual) == len(expected), path
        for i, (a, e) in enumerate(zip(actual, expected)):
            assert_close(a, e, f"{path}[{i}]", rel_tol)
        return
    if isinstance(expected, float) and math.isnan(expected):
        assert isinstance(actual, float) and math.isnan(actual), f"{path}: esperado NaN, salió {actual!r}"
        return
    if isinstance(expected, (int, float)) and not isinstance(expected, bool):
        assert math.isclose(actual, expected, rel_tol=rel_tol), f"{path}: {actual!r} != {expected!r}"
        return
    assert actual == expected, f"{path}: {actual!r} != {expected!r}"


@pytest.mark.parametrize("ticker", TICKERS)
def test_endpoint_con_candles_en_bruto_coincide_con_build_ind_mas_evaluate_ticker(ticker):
    """La condición central del usuario: mismo resultado exacto que
    build_ind() + evaluate_ticker() llamados directo -- el endpoint no
    reimplementa nada, solo delega."""
    data = load_raw_data(ticker)
    client = TestClient(_app())

    resp = client.post("/api/evaluate-ticker", json={
        "ticker": ticker, "mode": "NYSE", "candles": data,
        "funda": None, "settings": SETTINGS,
        "btc_gate_on": False, "insider_summary": None,
    })
    assert resp.status_code == 200, resp.text

    # El endpoint sirve NaN como el string sentinela "NaN" (NaN no es
    # JSON válido -- ver evaluate_ticker_endpoint.py). sentinel_to_nan()
    # es la misma conversión que usa snapshot_autocapture.py, no una
    # segunda implementación de esto en el test.
    endpoint_result = etl.sentinel_to_nan(resp.json())

    ind = etl.build_ind(data)
    direct_result = etl.evaluate_ticker(ticker, ind, None, "NYSE", SETTINGS, False, None)

    assert_close(endpoint_result, direct_result, path=f"evaluate-ticker[{ticker}]")


@pytest.mark.parametrize("ticker", TICKERS)
def test_endpoint_con_ind_ya_calculado_da_el_mismo_resultado_que_con_candles(ticker):
    """La ruta de compatibilidad ('ind' ya calculado) debe dar
    exactamente lo mismo que la ruta normal ('candles' en bruto) --
    ambas pasan por el mismo evaluate_ticker(), solo cambia quién
    calculó 'ind'."""
    data = load_raw_data(ticker)
    client = TestClient(_app())

    resp_candles = client.post("/api/evaluate-ticker", json={
        "ticker": ticker, "mode": "NYSE", "candles": data,
        "funda": None, "settings": SETTINGS,
        "btc_gate_on": False, "insider_summary": None,
    })
    # El contrato es simétrico: NaN crudo tampoco es válido al ENVIAR
    # (httpx lo rechaza igual que Starlette al responder, confirmado
    # al escribir este test) -- cualquier cliente que use la vía "ind"
    # debe mandarlo con el mismo sentinela que sirve el endpoint.
    ind_precalculado = etl.nan_to_json_sentinel(etl.build_ind(data))
    resp_ind = client.post("/api/evaluate-ticker", json={
        "ticker": ticker, "mode": "NYSE", "ind": ind_precalculado,
        "funda": None, "settings": SETTINGS,
        "btc_gate_on": False, "insider_summary": None,
    })
    assert resp_candles.status_code == 200
    assert resp_ind.status_code == 200
    assert_close(etl.sentinel_to_nan(resp_candles.json()), etl.sentinel_to_nan(resp_ind.json()),
                 path=f"candles-vs-ind[{ticker}]")


def test_422_si_llegan_candles_e_ind_a_la_vez():
    client = TestClient(_app())
    resp = client.post("/api/evaluate-ticker", json={
        "ticker": "AAPL", "mode": "NYSE",
        "candles": {"1d": {"candles": [], "periods": 0}},
        "ind": {"1d": None},
        "settings": SETTINGS,
    })
    assert resp.status_code == 422, resp.text


def test_422_si_no_llega_ni_candles_ni_ind():
    client = TestClient(_app())
    resp = client.post("/api/evaluate-ticker", json={
        "ticker": "AAPL", "mode": "NYSE", "settings": SETTINGS,
    })
    assert resp.status_code == 422, resp.text


def test_nan_real_sobrevive_el_roundtrip_http_sin_fallar():
    """Confirma con una app FastAPI real (no una suposición) que el
    NaN que sale en 'ind' (p.ej. gapPct en 1h, solo existe en 1d)
    sobrevive el ciclo completo serialización -> HTTP ->
    deserialización -> sentinel_to_nan() sin que FastAPI/Starlette
    lance un error.

    PRIMERA VERSIÓN DE ESTE TEST (antes de escribirlo) asumía que la
    JSONResponse por defecto de FastAPI servía NaN tal cual sin
    problema -- al escribir este test de verdad, con una app FastAPI
    real, eso resultó ser FALSO: Starlette usa `allow_nan=False` y
    lanza ValueError. De ahí nace el sentinela "NaN" de
    nan_to_json_sentinel()/sentinel_to_nan() -- este test confirma que
    la solución real funciona, no solo que no falla."""
    data_aapl = load_raw_data("AAPL")
    client = TestClient(_app())
    resp = client.post("/api/evaluate-ticker", json={
        "ticker": "AAPL", "mode": "NYSE", "candles": data_aapl,
        "funda": None, "settings": SETTINGS,
        "btc_gate_on": False, "insider_summary": None,
    })
    assert resp.status_code == 200, resp.text
    raw_body = resp.json()
    # Antes de decodificar el sentinela: confirmar que de verdad es el
    # string "NaN" en la respuesta cruda, no que sentinel_to_nan() esté
    # tapando un null o un error.
    assert raw_body["ind"]["1h"]["gapPct"] == "NaN", (
        f"se esperaba el sentinela \"NaN\" en la respuesta cruda, salió {raw_body['ind']['1h']['gapPct']!r}"
    )
    decoded = etl.sentinel_to_nan(raw_body)
    gap_pct_1h = decoded["ind"]["1h"]["gapPct"]
    assert isinstance(gap_pct_1h, float) and math.isnan(gap_pct_1h), (
        f"ind['1h'].gapPct debería ser NaN tras sentinel_to_nan(), salió {gap_pct_1h!r}"
    )
