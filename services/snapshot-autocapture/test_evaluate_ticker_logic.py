"""
Pruebas del puerto literal contra la aritmética exacta de las 22 piezas
(docs/pipeline/pregunta5_5b_salida.txt, pregunta5c, pregunta5d). No son
pruebas end-to-end contra datos reales -- confirman que la traducción
JS->Python no introdujo errores de signo/umbral/orden, igual que ya
pasó una vez con risk_pct/risk_per_share.
"""
import math

import evaluate_ticker_logic as m

SETTINGS = {"priceMin": 8, "atrMax": 6, "rvolMin": 1.0}


def test_eval_st01_suma_exacta_de_puntos():
    # Todas las condiciones de evalST01 cumplidas a la vez: EMA alineadas
    # (+25) + pullback -1% (+20) + RSI 50 (+15) + MACD hist creciente
    # (+15) + RSI 1H 50 (+5) + MACD 1H girando (+5) + precio>VWAP (+5) +
    # precio>EMA20 15M (+5) + RVOL 2.0 (+10) -- verificado contra la suma
    # real de los puntos de cada factor devuelto, no un número calculado
    # a mano (ya hubo un despiste de suma aquí mismo una vez).
    ctx = {
        "ind": {
            "1d": {"price": 99, "ema20": 100, "ema50": 90, "ema200": 80,
                   "rsi": 50, "macdHist": 1, "macdHistPrev": 0.5, "rvol": 1.2},
            "1h": {"rsi": 50, "macdHist": 1, "macdHistPrev": 0.5},
            "15m": {"price": 10, "vwap": 9, "ema20": 9, "rvol": 2.0},
        },
        "funda": None, "hardNo": False, "settings": SETTINGS,
        "mode": "NYSE", "ticker": "TEST", "btcGateOn": False,
    }
    r = m.eval_st01(ctx)
    assert r["applicable"] is True
    assert len(r["factors"]) == 9, "deberían dispararse las 9 condiciones de bonus"
    assert r["rawScore"] == sum(fa["points"] for fa in r["factors"])
    assert r["rawScore"] == 105
    # js_round(), no round() de Python -- 105/110*100 no cae en un .5
    # exacto así que aquí daría igual, pero usar round() de Python para
    # calcular el esperado de una prueba es precisamente el hábito que
    # causó el bug real de ST-09/MU (ver test_js_round_* más abajo).
    assert r["score"] == m.js_round(105 / 110 * 100)
    assert r["verdict"] == "OPERAR"  # score>=70, rvol1d=1.2>=rvolMin=1.0


def test_eval_st05_no_aplica_sin_gap_real():
    ctx = {"ind": {"1d": {"gapPct": 0.1, "rvol": 1}, "15m": {"price": 10, "vwap": 9, "rvol": 1}},
           "funda": None, "hardNo": False, "settings": SETTINGS,
           "mode": "NYSE", "ticker": "TEST", "btcGateOn": False}
    r = m.eval_st05(ctx)
    assert r["applicable"] is False
    assert r["verdict"] == "N/A"
    assert r["naReason"] == "Sin gap real hoy"


def test_finalize_verdict_tres_bandas_y_downgrade_por_rvol():
    assert m.finalize_verdict(90, hard_no=True, rvol1d=2.0, rvol_min=1.0) == "NO"  # hardNo manda
    assert m.finalize_verdict(50, hard_no=False, rvol1d=2.0, rvol_min=1.0) == "NO"  # <55
    assert m.finalize_verdict(60, hard_no=False, rvol1d=2.0, rvol_min=1.0) == "VIGILAR"  # 55-69
    assert m.finalize_verdict(80, hard_no=False, rvol1d=2.0, rvol_min=1.0) == "OPERAR"  # >=70
    # OPERAR pero rvol1d < rvolMin -> degrada a VIGILAR
    assert m.finalize_verdict(80, hard_no=False, rvol1d=0.5, rvol_min=1.0) == "VIGILAR"
    # NaN de rvol1d no debe tumbar el downgrade (isNaN(rvol1d) en JS corta el check)
    assert m.finalize_verdict(80, hard_no=False, rvol1d=float("nan"), rvol_min=1.0) == "OPERAR"


def test_mk_result_normaliza_y_clampa():
    r = m.mk_result("ST-05", score=150, factors=[], applicable=True,
                     hard_no=False, rvol1d=3.0, rvol_min=1.0)
    # 150/75*100 = 200 -> clamp a 100
    assert r["score"] == 100
    assert r["rawScore"] == 150
    assert r["maxRawScore"] == 75
    assert r["verdict"] == "OPERAR"


def test_js_round_replica_math_round_de_js_no_round_de_python():
    """
    Math.round() de JS es floor(x+0.5) -- redondeo hacia +Infinity en los
    .5 exactos, incluidos los negativos (Math.round(-2.5) es -2, no -3).
    round() de Python usa round-half-to-even: round(62.5)==62,
    round(63.5)==64 -- coincide con Math.round en 63.5 (64==64) pero NO en
    62.5 (62 vs 63), que es exactamente el bug real encontrado en
    producción (MU/ST-09, ver test_eval_st09_regresion_mu_rounding_boundary
    más abajo). Los casos de abajo son los mismos valores que
    Math.round() de Node confirma en la sesión de depuración real.
    """
    assert m.js_round(62.5) == 63  # round() de Python da 62 aquí -- el bug real
    assert m.js_round(63.5) == 64  # aquí round() de Python también da 64 -- coincide por casualidad
    assert m.js_round(-2.5) == -2  # no -3 -- Math.round(-2.5) real de JS
    assert m.js_round(0.5) == 1
    assert m.js_round(-0.5) == 0
    assert m.js_round(5.0) == 5  # entero exacto, sin sorpresas
    assert m.js_round(-5.0) == -5


def test_mk_result_usa_js_round_no_round_de_python():
    """
    Reproduce el bug real con los números exactos del caso MU/ST-09:
    maxRaw=80 (MAX_RAW_SCORE['ST-09']), raw=50 -> 50/80*100 = 62.5 EXACTO
    (sin ruido de punto flotante, confirmado: 50/80 = 0.625 es exacto en
    binario). Antes del fix, mk_result() usaba round() de Python ->
    normalized=62; el oráculo Node real (Math.round) da 63. Este test
    habría fallado contra el código viejo -- es la prueba de regresión
    del bug, no solo del helper aislado.
    """
    r = m.mk_result("ST-09", score=50, factors=[], applicable=True,
                     hard_no=False, rvol1d=2.0, rvol_min=1.0)
    assert r["score"] == 63
    assert round(50 / 80 * 100) == 62, (
        "si esto deja de ser 62, el escenario de la prueba ya no reproduce "
        "el bug real -- revisar los números, no el assert de arriba"
    )


def test_eval_st09_regresion_mu_rounding_boundary():
    """
    Caso de regresión end-to-end (no solo mk_result aislado): indicadores
    sintéticos construidos para que evalST09 llegue exactamente a
    raw=50/maxRaw=80 (20 por RVOL sesión anterior >=1.8, +15 por RSI
    55-70, +15 por MACD 1H positivo; rangeClose sale NaN a propósito --
    prevC.h==prevC.l -- y el bonus de VWAP 15M se omite con vwap=NaN, para
    que el raw total sea exactamente 50 y no otro número).

    NO son las velas reales de MU (esta sesión no tiene las velas reales
    que generó el oráculo en el servidor -- docs/pipeline/fixtures_js/
    oraculo_evaluate/MU_*_candles.json no está en este checkout). Esto
    reproduce el MISMO mecanismo (el límite de redondeo 62.5) con datos
    sintéticos controlados, no las velas originales. Si se comitea el
    fixture real de MU, añadir además una prueba contra esas velas
    exactas con build_ind()+evaluate_ticker(), mismo patrón que
    test_evaluate_ticker_endpoint.py.
    """
    candles = [{"o": 1, "h": 10, "l": 9, "c": 9.5, "v": 1000} for _ in range(20)]
    candles.append({"o": 1, "h": 100, "l": 100, "c": 100, "v": 2000})  # prevC: h==l -> rangeClose NaN
    candles.append({"o": 1, "h": 10, "l": 9, "c": 9.5, "v": 1500})  # última vela, irrelevante aquí
    assert len(candles) == 22

    ctx = {
        "ind": {
            "1d": {"candles": candles, "rsi": 60, "rvol": 2.0},
            "1h": {"macdHist": 1},
            "15m": {"price": 10, "vwap": float("nan")},
        },
        "funda": None, "hardNo": False, "settings": SETTINGS,
        "mode": "NYSE", "ticker": "MU", "btcGateOn": False,
    }
    r = m.eval_st09(ctx)
    assert r["applicable"] is True
    assert r["rawScore"] == 50, (
        f"el escenario sintético no llega al raw=50 esperado -- salió {r['rawScore']!r}, "
        f"factores: {r['factors']!r}"
    )
    assert r["maxRawScore"] == 80
    assert r["score"] == 63, (
        "con round() de Python en vez de js_round() esto daría 62 -- si vuelve a dar "
        "62, el bug de redondeo ha vuelto"
    )


def test_mk_na_no_aplicable():
    r = m.mk_na("ST-09")
    assert r["applicable"] is False
    assert r["score"] == 0
    assert r["naReason"] == "No aplica en este momento"


def test_ticker_hard_no_precio_minimo_nyse():
    assert m.ticker_hard_no("NYSE", price=5, d={"atrPct": 1}, settings=SETTINGS) is True
    assert m.ticker_hard_no("NYSE", price=10, d={"atrPct": 1}, settings=SETTINGS) is False
    assert m.ticker_hard_no("NYSE", price=10, d={"atrPct": 10}, settings=SETTINGS) is True
    # En CRYPTO no aplica el priceMin (mode!='NYSE')
    assert m.ticker_hard_no("CRYPTO", price=0.001, d={"atrPct": 1}, settings=SETTINGS) is False


def test_detect_auto_trigger_auto_multi_tiene_prioridad_sobre_auto_high():
    """
    Caso diseñado para que, si alguien reintroduce la unión de ramas en
    vez de la prioridad estricta, este test falle: hay un grupo con 2
    estrategias >=80 (dispara AUTO_MULTI) Y una tercera estrategia en
    otro grupo con score 95 (que por sí sola dispararía AUTO_HIGH). El
    resultado real del navegador es SOLO AUTO_MULTI -- AUTO_HIGH no se
    evalúa siquiera.
    """
    r = {
        "error": None, "hardNo": False, "globalVerdict": "OPERAR",
        "strategies": [
            {"id": "ST-01", "applicable": True, "score": 82, "group": "swing"},
            {"id": "ST-09", "applicable": True, "score": 85, "group": "swing"},
            {"id": "ST-05", "applicable": True, "score": 95, "group": "intraday"},
        ],
    }
    trigger = m.detect_auto_trigger(r)
    assert trigger["type"] == "AUTO_MULTI"
    assert {s["id"] for s in trigger["strategies"]} == {"ST-01", "ST-09"}


def test_detect_auto_trigger_auto_high_solo_si_no_hay_multi():
    r = {
        "error": None, "hardNo": False, "globalVerdict": "OPERAR",
        "strategies": [
            {"id": "ST-01", "applicable": True, "score": 60, "group": "swing"},
            {"id": "ST-05", "applicable": True, "score": 95, "group": "intraday"},
            {"id": "ST-06", "applicable": True, "score": 91, "group": "swing"},
        ],
    }
    trigger = m.detect_auto_trigger(r)
    assert trigger["type"] == "AUTO_HIGH"
    # el mas alto entre los >=90 (95 > 91)
    assert [s["id"] for s in trigger["strategies"]] == ["ST-05"]


def test_detect_auto_trigger_nada_si_hard_no_o_sin_aplicables():
    assert m.detect_auto_trigger(None) is None
    assert m.detect_auto_trigger({"hardNo": True, "globalVerdict": "OPERAR", "strategies": []}) is None
    assert m.detect_auto_trigger({"hardNo": False, "globalVerdict": "N/A", "strategies": []}) is None


def test_evaluate_ticker_nyse_ejecuta_los_7_y_crypto_los_3():
    ind = {
        "1d": {"price": 100, "ema20": 95, "ema50": 90, "ema200": 80, "rsi": 50,
               "macdHist": 0, "macdHistPrev": 0, "rvol": 1, "gapPct": 0,
               "adx": 10, "diPlus": 0, "diMinus": 0, "candles": []},
        "1h": {"rsi": 50, "macdHist": 0, "macdHistPrev": 0, "rvol": 1, "compression": 10},
        "15m": {"price": 100, "vwap": 99, "ema20": 99, "ema200": 90, "rvol": 1},
    }
    r = m.evaluate_ticker("TEST", ind, None, "NYSE", SETTINGS, False, None)
    assert [s["id"] for s in r["strategies"]] == ["ST-01", "ST-05", "ST-06", "ST-09", "ST-11", "ST-15", "ST-16"]
    r2 = m.evaluate_ticker("BTC", ind, None, "CRYPTO", SETTINGS, True, None)
    assert [s["id"] for s in r2["strategies"]] == ["SC-01", "SC-02", "SC-PB"]
