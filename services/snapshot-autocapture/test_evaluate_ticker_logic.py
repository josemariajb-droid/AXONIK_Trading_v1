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
    assert r["score"] == round(105 / 110 * 100)
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
