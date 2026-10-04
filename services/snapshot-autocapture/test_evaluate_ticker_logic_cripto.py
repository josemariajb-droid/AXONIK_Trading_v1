"""
Pruebas de la ruta CRIPTO del puerto (evalSC01/evalSC02/evalSCPB +
evaluate_ticker con mode='CRYPTO') contra la aritmética exacta del texto
literal (docs/pipeline/pregunta5_5b_salida.txt, pregunta5c, pregunta5d,
pregunta9, pregunta10 -- evalSC01/02/PB confirmados en las 5 dumps,
idénticos en texto). No necesitan red: todo con ctx sintéticos (mismo
patrón que test_evaluate_ticker_logic.py para evalSTxx) o con velas reales
ya comiteadas de la ruta NYSE para probar que computeIndicators()/
build_ind() funcionan igual sea cual sea el mercado (el mercado solo
decide qué estrategias se ejecutan, nunca cómo se calculan los
indicadores -- confirmado leyendo fetchCryptoTicker(): llama a la MISMA
computeIndicators() que fetchNyseTicker()).
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

import evaluate_ticker_logic as m

SETTINGS = {"priceMin": 8, "atrMax": 6, "rvolMin": 1.0}
NYSE_FIXTURES_DIR = Path(__file__).parent.parent.parent / "docs" / "pipeline" / "fixtures_js"


def test_eval_sc01_suma_exacta_de_puntos():
    # squeezeResolved (compression<=6, rvol>=2.5, +20) + RSI 60 en [55,70]
    # (+15) + MACD positivo (+15) + precio>VWAP 15M (+15) = 65 = MAX_RAW_SCORE['SC-01'].
    ctx = {
        "ind": {
            "1d": {"compression": 5, "rvol": 3.0, "rsi": 60, "macdHist": 1},
            "15m": {"price": 10, "vwap": 9},
        },
        "hardNo": False, "settings": SETTINGS, "ticker": "BTC", "btcGateOn": True,
    }
    r = m.eval_sc01(ctx)
    assert r["applicable"] is True
    assert r["rawScore"] == sum(f["points"] for f in r["factors"])
    assert r["rawScore"] == 65
    assert r["maxRawScore"] == 65
    assert r["score"] == 100


def test_eval_sc01_solo_btc_eth_no_depende_del_gate():
    """
    evalSC01 NO comprueba btcGateOn (confirmado leyendo su texto literal:
    solo filtra por ticker) -- a diferencia de SC-02/SC-PB, que si
    dependen del gate (pruebas de abajo). No mezclar los tres como "la
    ruta cripto depende del gate" sin distinguir cuál.
    """
    ctx = {
        "ind": {"1d": {"compression": 5, "rvol": 3.0, "rsi": 60, "macdHist": 1},
                "15m": {"price": 10, "vwap": 9}},
        "hardNo": False, "settings": SETTINGS, "ticker": "SOL", "btcGateOn": True,
    }
    r = m.eval_sc01(ctx)
    assert r["applicable"] is False
    assert r["naReason"] == "Solo BTC/ETH"

    # Con BTC y gate OFF, SC-01 sigue aplicando -- no es su guard.
    ctx["ticker"] = "BTC"
    ctx["btcGateOn"] = False
    r2 = m.eval_sc01(ctx)
    assert r2["applicable"] is True


def test_eval_sc02_requiere_altcoin_y_gate_on():
    base_ind = {
        "1d": {"price": 100, "ema20": 95, "ema50": 90, "rsi": 50, "rvol": 2.0},
        "1h": {"macdHist": 1},
    }
    # BTC/ETH -> siempre N/A, aunque el gate esté ON (SC-02 es "solo altcoins").
    ctx_btc = {"ind": base_ind, "hardNo": False, "settings": SETTINGS,
               "ticker": "BTC", "btcGateOn": True}
    assert m.eval_sc02(ctx_btc)["naReason"] == "Solo altcoins"

    # Altcoin con gate OFF -> N/A por el gate, no llega a puntuar nada.
    ctx_off = {"ind": base_ind, "hardNo": False, "settings": SETTINGS,
               "ticker": "SOL", "btcGateOn": False}
    r_off = m.eval_sc02(ctx_off)
    assert r_off["applicable"] is False
    assert r_off["naReason"] == "Gate BTC OFF"
    assert r_off["score"] == 0

    # Mismo ticker e indicadores, gate ON -> SÍ puntúa. price>ema50 (+20) +
    # ema20>ema50 (+15) + rsi<60 (+15) + rvol>=1.5 (+15) + macdHist 1h>0
    # (+15) = 80 = MAX_RAW_SCORE['SC-02'].
    ctx_on = {**ctx_off, "btcGateOn": True}
    r_on = m.eval_sc02(ctx_on)
    assert r_on["applicable"] is True
    assert r_on["rawScore"] == 80
    assert r_on["score"] == 100


def test_eval_scpb_requiere_gate_on():
    ind = {
        "1d": {"price": 99, "ema20": 100, "ema50": 90, "ema200": 80, "rsi": 45, "rvol": 1.2},
        "1h": {"macdHist": 1, "macdHistPrev": 0.5},
        "15m": {"rvol": 2.0},
    }
    ctx_off = {"ind": ind, "hardNo": False, "settings": SETTINGS,
               "ticker": "SOL", "btcGateOn": False}
    r_off = m.eval_scpb(ctx_off)
    assert r_off["applicable"] is False
    assert r_off["naReason"] == "Gate BTC OFF"

    # EMA 20>50>200 (+25) + pullback -1% (+20) + RSI 45 en [40,55] (+15) +
    # MACD 1H girando (+10) + RVOL 15M (+10) = 80 = MAX_RAW_SCORE['SC-PB'].
    ctx_on = {**ctx_off, "btcGateOn": True}
    r_on = m.eval_scpb(ctx_on)
    assert r_on["applicable"] is True
    assert r_on["rawScore"] == 80
    assert r_on["score"] == 100


def test_btc_gate_off_altcoin_sin_ninguna_senal():
    """
    Caso central pedido por la tarea: con btcGateOn=False, un altcoin
    (SOL -- ni BTC/ETH) no puede sacar NINGUNA señal, de ninguna de las 3
    estrategias cripto: SC-01 se descarta por ticker ("Solo BTC/ETH"),
    SC-02/SC-PB por el gate ("Gate BTC OFF") -- aunque los indicadores de
    entrada sean los más favorables posibles para las tres a la vez.
    globalVerdict debe salir 'N/A' y detect_auto_trigger() debe dar None.

    NO generaliza a "BTC/ETH tampoco pueden señalar con el gate off" --
    SC-01 no depende del gate (test de arriba) y SÍ podría disparar para
    BTC/ETH incluso con btcGateOn=False. Esa es la semántica real del JS,
    no una simplificación de esta prueba.
    """
    ind = {
        "1d": {"price": 100, "ema20": 95, "ema50": 90, "ema200": 80, "rsi": 50,
               "rvol": 3.0, "compression": 5, "macdHist": 1},
        "1h": {"macdHist": 1, "macdHistPrev": 0.1},
        "15m": {"price": 100, "vwap": 99, "rvol": 2.0},
    }
    r = m.evaluate_ticker("SOL", ind, None, "CRYPTO", SETTINGS, False, None)
    assert all(not s["applicable"] for s in r["strategies"]), (
        f"se esperaba que las 3 estrategias cripto dieran N/A con el gate OFF -- "
        f"salieron: {[(s['id'], s['applicable']) for s in r['strategies']]}"
    )
    assert r["globalVerdict"] == "N/A"
    assert r["globalScore"] == 0
    assert m.detect_auto_trigger(r) is None


def test_evaluate_ticker_crypto_ejecuta_sc01_sc02_scpb_en_orden():
    ind = {"1d": {"price": 100, "ema20": 95, "ema50": 90, "ema200": 80, "rsi": 50,
                  "macdHist": 0, "macdHistPrev": 0, "rvol": 1, "compression": 10},
           "1h": {"rsi": 50, "macdHist": 0, "macdHistPrev": 0, "rvol": 1},
           "15m": {"price": 100, "vwap": 99, "rvol": 1}}
    r = m.evaluate_ticker("BTC", ind, None, "CRYPTO", SETTINGS, True, None)
    assert [s["id"] for s in r["strategies"]] == ["SC-01", "SC-02", "SC-PB"]


def test_build_ind_y_evaluate_ticker_crypto_con_velas_reales_nyse_como_fixture():
    """
    No hay velas reales de Binance comiteadas todavía (bloqueo real,
    ver docs/pipeline/BLOQUEOS.md) -- usa las velas reales de AAPL ya
    comiteadas (docs/pipeline/fixtures_js/AAPL_1d_candles.json, etc.) solo
    como ENTRADA sintética para probar que build_ind()/computeIndicators()
    funcionan igual en la ruta CRYPTO: el cálculo de indicadores es el
    mismo computeIndicators() para los dos mercados, confirmado leyendo
    fetchCryptoTicker() -- lo único que cambia con el mercado es qué
    estrategias se ejecutan, nunca cómo se calculan ema/rsi/macd/etc.
    Se omite si esas fixtures no están en este checkout.
    """
    paths = {tf: NYSE_FIXTURES_DIR / f"AAPL_{tf}_candles.json" for tf in ("1d", "1h", "15m")}
    if not all(p.is_file() for p in paths.values()):
        pytest.skip(f"Faltan fixtures en {NYSE_FIXTURES_DIR}")

    data = {tf: {"candles": json.loads(p.read_text())} for tf, p in paths.items()}
    ind = m.build_ind(data)
    assert ind["1d"] is not None and ind["1d"]["price"] > 0

    r = m.evaluate_ticker("BTC", ind, None, "CRYPTO", SETTINGS, True, None)
    assert [s["id"] for s in r["strategies"]] == ["SC-01", "SC-02", "SC-PB"]
    assert r["hardNo"] is False, "mode='CRYPTO' no debe aplicar el priceMin de NYSE"
