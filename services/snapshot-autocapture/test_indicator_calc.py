"""
Pruebas del puerto literal de indicator_calc.py contra fixtures reales:
velas reales de /api/scan-batch ejecutadas con Node real sobre el JS
real del navegador (docs/pipeline/fixtures_js/, generadas con
docs/pipeline/generar_fixtures_js.sh, commit 4225c02). No son datos
sintéticos -- son la salida real de computeIndicators() y las 9
funciones, ejecutadas por un intérprete JS de verdad, no una
re-implementación en otro lenguaje de lo que "debería" devolver.

"NaN" llega como string explícito en los fixtures (así lo serializa el
driver de Node, JSON no tiene NaN nativo) -- se convierte a
float('nan') al cargar, y se compara con math.isnan(), nunca con `==`
(NaN != NaN en IEEE754, en Python y en JS por igual).
"""
from __future__ import annotations

import json
import math
from pathlib import Path

import pytest

import indicator_calc as calc

FIXTURES_DIR = Path(__file__).parent.parent.parent / "docs" / "pipeline" / "fixtures_js"
TICKERS = ["AAPL", "MSFT", "NVDA"]
TIMEFRAMES = ["1d", "1h", "15m"]
REL_TOL = 1e-9


def _nan_sentinel_to_float(obj):
    """Recorre recursivamente una estructura JSON y convierte el string
    sentinela "NaN" (así lo escribe el driver de Node, ver
    generar_fixtures_js.sh) a float('nan') real."""
    if obj == "NaN":
        return float("nan")
    if isinstance(obj, dict):
        return {k: _nan_sentinel_to_float(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_nan_sentinel_to_float(v) for v in obj]
    return obj


def load_fixture(ticker: str, tf: str) -> tuple[list[dict], dict]:
    candles_path = FIXTURES_DIR / f"{ticker}_{tf}_candles.json"
    output_path = FIXTURES_DIR / f"{ticker}_{tf}_output.json"
    with open(candles_path) as f:
        candles = json.load(f)
    with open(output_path) as f:
        output = _nan_sentinel_to_float(json.load(f))
    return candles, output


def assert_close(actual, expected, path: str = "$", rel_tol: float = REL_TOL):
    """Compara actual contra expected, recursivamente, con NaN==NaN
    (vía math.isnan, nunca ==) y tolerancia relativa para floats."""
    if isinstance(expected, dict):
        assert isinstance(actual, dict), f"{path}: se esperaba dict, salió {type(actual)}"
        for k, v in expected.items():
            assert k in actual, f"{path}: falta la clave '{k}'"
            assert_close(actual[k], v, f"{path}.{k}", rel_tol)
        return
    if isinstance(expected, list):
        assert isinstance(actual, list), f"{path}: se esperaba list, salió {type(actual)}"
        assert len(actual) == len(expected), (
            f"{path}: longitud {len(actual)} != esperada {len(expected)}"
        )
        for i, (a, e) in enumerate(zip(actual, expected)):
            assert_close(a, e, f"{path}[{i}]", rel_tol)
        return
    if isinstance(expected, float) and math.isnan(expected):
        assert isinstance(actual, float) and math.isnan(actual), (
            f"{path}: se esperaba NaN, salió {actual!r}"
        )
        return
    if isinstance(expected, (int, float)) and not isinstance(expected, bool):
        assert isinstance(actual, (int, float)) and not isinstance(actual, bool), (
            f"{path}: se esperaba número, salió {actual!r}"
        )
        assert math.isclose(actual, expected, rel_tol=rel_tol), (
            f"{path}: {actual!r} != {expected!r} (rel_tol={rel_tol})"
        )
        return
    assert actual == expected, f"{path}: {actual!r} != {expected!r}"


FIXTURE_IDS = [f"{t}_{tf}" for t in TICKERS for tf in TIMEFRAMES]
FIXTURE_PARAMS = [(t, tf) for t in TICKERS for tf in TIMEFRAMES]


@pytest.mark.parametrize("ticker,tf", FIXTURE_PARAMS, ids=FIXTURE_IDS)
def test_compute_indicators_contra_fixture_real(ticker, tf):
    candles, expected = load_fixture(ticker, tf)
    actual = calc.compute_indicators(candles, tf)
    assert_close(actual, expected["computeIndicators"], path=f"computeIndicators[{ticker}/{tf}]")


@pytest.mark.parametrize("ticker,tf", FIXTURE_PARAMS, ids=FIXTURE_IDS)
def test_ema_arr_20_50_200_contra_fixture_real(ticker, tf):
    candles, expected = load_fixture(ticker, tf)
    closes = [c["c"] for c in candles]
    assert_close(calc.ema_arr(closes, 20), expected["emaArr_20"], path=f"emaArr_20[{ticker}/{tf}]")
    assert_close(calc.ema_arr(closes, 50), expected["emaArr_50"], path=f"emaArr_50[{ticker}/{tf}]")
    assert_close(calc.ema_arr(closes, 200, True), expected["emaArr_200_allowPartial"],
                 path=f"emaArr_200[{ticker}/{tf}]")


@pytest.mark.parametrize("ticker,tf", FIXTURE_PARAMS, ids=FIXTURE_IDS)
def test_calc_rsi_contra_fixture_real(ticker, tf):
    candles, expected = load_fixture(ticker, tf)
    closes = [c["c"] for c in candles]
    assert_close(calc.calc_rsi(closes, 14), expected["calcRSI_14"], path=f"calcRSI_14[{ticker}/{tf}]")


@pytest.mark.parametrize("ticker,tf", FIXTURE_PARAMS, ids=FIXTURE_IDS)
def test_calc_macd_contra_fixture_real(ticker, tf):
    candles, expected = load_fixture(ticker, tf)
    closes = [c["c"] for c in candles]
    actual = list(calc.calc_macd(closes))
    assert_close(actual, expected["calcMACD_default"], path=f"calcMACD[{ticker}/{tf}]")


@pytest.mark.parametrize("ticker,tf", FIXTURE_PARAMS, ids=FIXTURE_IDS)
def test_calc_atr_contra_fixture_real(ticker, tf):
    candles, expected = load_fixture(ticker, tf)
    highs = [c["h"] for c in candles]
    lows = [c["l"] for c in candles]
    closes = [c["c"] for c in candles]
    assert_close(calc.calc_atr(highs, lows, closes, 14), expected["calcATR_14"],
                 path=f"calcATR_14[{ticker}/{tf}]")


@pytest.mark.parametrize("ticker,tf", FIXTURE_PARAMS, ids=FIXTURE_IDS)
def test_calc_rvol_contra_fixture_real(ticker, tf):
    candles, expected = load_fixture(ticker, tf)
    volumes = [c["v"] for c in candles]
    assert_close(calc.calc_rvol(volumes), expected["calcRVOL"], path=f"calcRVOL[{ticker}/{tf}]")


@pytest.mark.parametrize("ticker,tf", FIXTURE_PARAMS, ids=FIXTURE_IDS)
def test_calc_adx_contra_fixture_real(ticker, tf):
    candles, expected = load_fixture(ticker, tf)
    highs = [c["h"] for c in candles]
    lows = [c["l"] for c in candles]
    closes = [c["c"] for c in candles]
    assert_close(calc.calc_adx(highs, lows, closes, 14), expected["calcADX_14"],
                 path=f"calcADX_14[{ticker}/{tf}]")


@pytest.mark.parametrize("ticker,tf", FIXTURE_PARAMS, ids=FIXTURE_IDS)
def test_calc_compression_contra_fixture_real(ticker, tf):
    candles, expected = load_fixture(ticker, tf)
    assert_close(calc.calc_compression(candles, 6), expected["calcCompression_6"],
                 path=f"calcCompression_6[{ticker}/{tf}]")


@pytest.mark.parametrize("ticker,tf", FIXTURE_PARAMS, ids=FIXTURE_IDS)
def test_calc_gap_pct_contra_fixture_real(ticker, tf):
    candles, expected = load_fixture(ticker, tf)
    assert_close(calc.calc_gap_pct(candles), expected["calcGapPct"], path=f"calcGapPct[{ticker}/{tf}]")


@pytest.mark.parametrize("ticker,tf", FIXTURE_PARAMS, ids=FIXTURE_IDS)
def test_calc_vwap_contra_fixture_real(ticker, tf):
    candles, expected = load_fixture(ticker, tf)
    assert_close(calc.calc_vwap(candles), expected["calcVWAP"], path=f"calcVWAP[{ticker}/{tf}]")


@pytest.mark.parametrize("ticker,tf", FIXTURE_PARAMS, ids=FIXTURE_IDS)
def test_vwap_solo_en_15m_gap_solo_en_1d(ticker, tf):
    """computeIndicators() solo calcula vwap en 15m y gapPct en 1d -- en
    el resto debe salir NaN, tal cual el navegador (tf=='1d'/'15m' como
    único gate, tal cual confirmado en el texto literal)."""
    candles, _ = load_fixture(ticker, tf)
    result = calc.compute_indicators(candles, tf)
    if tf == "15m":
        assert not math.isnan(result["vwap"]), f"{ticker}/15m: vwap no debería ser NaN"
    else:
        assert math.isnan(result["vwap"]), f"{ticker}/{tf}: vwap debería ser NaN (solo existe en 15m)"
    if tf == "1d":
        assert not math.isnan(result["gapPct"]), f"{ticker}/1d: gapPct no debería ser NaN"
    else:
        assert math.isnan(result["gapPct"]), f"{ticker}/{tf}: gapPct debería ser NaN (solo existe en 1d)"


# --- Pruebas deterministas, independientes de los fixtures: protegen
#     los dos hallazgos del diseño §1.10 que cualquier puerto debe
#     reproducir tal cual, no "corregir". ---

def test_ema200_cae_en_fallback_de_sma_con_menos_de_200_cierres():
    """Con los n reales (120/100/96, confirmado en el diseño §1.10), ema200
    SIEMPRE cae en la rama allow_partial de ema_arr: la media simple de
    TODOS los cierres disponibles, no una EMA de 200 de verdad. Si
    alguien 'arregla' esto para que sea una EMA real, este test falla."""
    closes = [100.0 + i * 0.3 for i in range(120)]  # 120 < 200, determinista
    result = calc.ema_arr(closes, 200, True)
    assert len(result) == 120
    assert all(math.isnan(x) for x in result[:-1])
    assert math.isclose(result[-1], sum(closes) / len(closes), rel_tol=REL_TOL)


def test_ema200_sin_allow_partial_da_nan_no_una_media():
    """Sin el tercer argumento (como usan ema20/ema50), con menos velas
    que el período el resultado es NaN -- NUNCA una media de reemplazo.
    El fallback a SMA es exclusivo de allow_partial=True."""
    closes = [100.0 + i * 0.3 for i in range(120)]
    result = calc.ema_arr(closes, 200, False)
    assert all(math.isnan(x) for x in result)


def test_rsi_atr_adx_usan_wilder_no_ema_clasica():
    """RSI/ATR/ADX usan suavizado de Wilder (α=1/period); emaArr/MACD
    usan EMA clásica (α=2/(period+1)). Si alguien reemplaza el
    recurrente de Wilder de calc_rsi por la fórmula clásica de ema_arr
    (el atajo más tentador al refactorizar), este test debe fallar."""
    # Serie determinista con ganancias/pérdidas simples y conocidas.
    closes = [100, 102, 101, 104, 103, 106, 105, 108, 107, 110, 109, 112, 111, 114, 113, 116]
    period = 14

    # Wilder real (lo que debe hacer calc_rsi).
    deltas = [closes[i] - closes[i - 1] for i in range(1, len(closes))]
    avg_g_wilder = sum(d if d > 0 else 0 for d in deltas[:period]) / period
    avg_l_wilder = sum(-d if d < 0 else 0 for d in deltas[:period]) / period
    for i in range(period, len(deltas)):
        g = deltas[i] if deltas[i] > 0 else 0
        l = -deltas[i] if deltas[i] < 0 else 0
        avg_g_wilder = (avg_g_wilder * (period - 1) + g) / period
        avg_l_wilder = (avg_l_wilder * (period - 1) + l) / period
    rsi_wilder = 100 - 100 / (1 + avg_g_wilder / avg_l_wilder) if avg_l_wilder else 100.0

    # EMA clásica sobre la MISMA serie de ganancias/pérdidas -- la
    # implementación INCORRECTA si alguien reutilizara ema_arr aquí.
    gains = [d if d > 0 else 0 for d in deltas]
    losses = [-d if d < 0 else 0 for d in deltas]
    avg_g_ema = calc.ema_arr(gains, period)[-1]
    avg_l_ema = calc.ema_arr(losses, period)[-1]
    rsi_classic_ema = 100 - 100 / (1 + avg_g_ema / avg_l_ema) if avg_l_ema else 100.0

    actual = calc.calc_rsi(closes, period)
    assert math.isclose(actual, rsi_wilder, rel_tol=REL_TOL), (
        "calc_rsi debe coincidir con el recurrente de Wilder calculado aquí mismo"
    )
    assert not math.isclose(actual, rsi_classic_ema, rel_tol=1e-6), (
        "calc_rsi coincide con EMA clásica sobre ganancias/pérdidas -- "
        "alguien mezcló las dos convenciones de suavizado"
    )


def test_calc_vwap_agrupa_por_fecha_calendario_utc_no_hora_local():
    """calc_vwap agrupa por la fecha UTC de la última vela -- una vela a
    las 23:00 UTC y otra a las 01:00 UTC del día siguiente (mismo
    'día' en casi cualquier zona horaria de EEUU) deben tratarse como
    sesiones DISTINTAS, porque el navegador agrupa por fecha de
    calendario UTC, no por sesión NYSE en hora local. Si alguien
    'corrige' esto a hora de Nueva York, este test falla."""
    day1_2300_utc = 1700000000  # 2023-11-14T23:00:00Z
    day2_0100_utc = day1_2300_utc + 2 * 3600  # 2023-11-15T01:00:00Z, +2h

    candles_misma_sesion_nyse_pero_distinto_dia_utc = [
        {"t": day1_2300_utc, "o": 100, "h": 101, "l": 99, "c": 100.5, "v": 1000},
        {"t": day2_0100_utc, "o": 100.5, "h": 102, "l": 100, "c": 101.5, "v": 1000},
    ]
    vwap_ambas = calc.calc_vwap(candles_misma_sesion_nyse_pero_distinto_dia_utc)
    vwap_solo_ultima = calc.calc_vwap(candles_misma_sesion_nyse_pero_distinto_dia_utc[-1:])
    assert math.isclose(vwap_ambas, vwap_solo_ultima, rel_tol=REL_TOL), (
        "la vela de 23:00 UTC del día anterior no debería entrar en el VWAP "
        "de la última vela si se agrupa por fecha de calendario UTC"
    )
