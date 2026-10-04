"""
Prueba de integración: build_ind() (evaluate_ticker_logic.py) +
indicator_calc.py + evaluate_ticker()/detect_auto_trigger(), sobre el
"data" en bruto real de /api/scan-batch (docs/pipeline/fixtures_js/,
Preguntas 9/10 + verificación navegador-vs-endpoint).

No es una comparación contra un resultado real de evaluateTicker() del
navegador -- esa verificación (VERIFICACION_NAVEGADOR_VS_ENDPOINT.md)
sigue pendiente, ahora que el gap de computeIndicators() está cerrado.
Esto confirma que la cadena completa corre de punta a punta sobre datos
reales (no sintéticos) sin excepciones y con un shape de salida
coherente -- el puente que faltaba entre "candles en bruto" e
"ind ya calculado".
"""
from __future__ import annotations

import json
import math
from pathlib import Path

import pytest

import evaluate_ticker_logic as etl

FIXTURES_DIR = Path(__file__).parent.parent.parent / "docs" / "pipeline" / "fixtures_js"
TICKERS = ["AAPL", "MSFT", "NVDA"]
SETTINGS = {"priceMin": 8, "atrMax": 4, "rvolMin": 1}  # DEFAULT_SETTINGS real, Pregunta 6d


def load_raw_data(ticker: str) -> dict:
    raw = json.load(open(FIXTURES_DIR / f"{ticker}_scanbatch_raw.json"))
    item = next(r for r in raw["results"] if r["ticker"] == ticker)
    assert not item.get("error"), f"{ticker}: scan-batch devolvió error en el fixture"
    return item["data"]


@pytest.mark.parametrize("ticker", TICKERS)
def test_build_ind_produce_los_tres_timeframes_con_indicadores_reales(ticker):
    data = load_raw_data(ticker)
    ind = etl.build_ind(data)
    assert set(ind.keys()) == {"1d", "1h", "15m"}
    for tf in ("1d", "1h", "15m"):
        assert ind[tf] is not None, f"{ticker}/{tf}: build_ind() no debería dar None con datos reales"
        assert not math.isnan(ind[tf]["price"]), f"{ticker}/{tf}: price no debería ser NaN"
        assert not math.isnan(ind[tf]["rsi"]), f"{ticker}/{tf}: rsi no debería ser NaN con datos reales suficientes"


@pytest.mark.parametrize("ticker", TICKERS)
def test_build_ind_coincide_con_indicator_calc_directo(ticker):
    """build_ind() no debe ser una segunda implementación -- debe dar
    exactamente lo mismo que llamar a indicator_calc.compute_indicators()
    directamente sobre las mismas velas."""
    import indicator_calc

    data = load_raw_data(ticker)
    ind = etl.build_ind(data)
    for tf in ("1d", "1h", "15m"):
        candles = data[tf]["candles"]
        direct = indicator_calc.compute_indicators(candles, tf)
        for key in direct:
            a, b = ind[tf][key], direct[key]
            if isinstance(a, float) and math.isnan(a):
                assert isinstance(b, float) and math.isnan(b), f"{ticker}/{tf}.{key}"
            else:
                assert a == b, f"{ticker}/{tf}.{key}: {a!r} != {b!r}"


@pytest.mark.parametrize("ticker", TICKERS)
def test_cadena_completa_evaluate_ticker_sobre_datos_reales_sin_excepciones(ticker):
    """evaluate_ticker() + detect_auto_trigger() corren de punta a punta
    sobre candles reales (vía build_ind()) sin lanzar nada y con un
    shape de resultado coherente -- las 7 estrategias NYSE evaluadas,
    cada una con su veredicto. No compara contra un resultado real del
    navegador (eso sigue pendiente, VERIFICACION_NAVEGADOR_VS_ENDPOINT.md)."""
    data = load_raw_data(ticker)
    ind = etl.build_ind(data)

    result = etl.evaluate_ticker(ticker, ind, None, "NYSE", SETTINGS, False, None)

    assert result is not None, f"{ticker}: evaluate_ticker() no debería dar None con datos reales"
    assert result["ticker"] == ticker
    assert [s["id"] for s in result["strategies"]] == [
        "ST-01", "ST-05", "ST-06", "ST-09", "ST-11", "ST-15", "ST-16",
    ]
    for s in result["strategies"]:
        assert s["verdict"] in ("OPERAR", "VIGILAR", "NO", "N/A")
        if s["applicable"]:
            assert 0 <= s["score"] <= 100

    # No debe lanzar tampoco -- puede devolver None (sin disparo) o un
    # dict con "type"/"strategies", cualquiera de los dos es válido.
    trigger = etl.detect_auto_trigger(result)
    if trigger is not None:
        assert trigger["type"] in ("AUTO_HIGH", "AUTO_MULTI")
        assert len(trigger["strategies"]) >= 1
