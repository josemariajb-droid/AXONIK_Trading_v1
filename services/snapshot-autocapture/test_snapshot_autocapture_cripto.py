"""
Pruebas de la rama CRIPTO de snapshot_autocapture.py -- primera prueba
directa de este script (antes solo se probaban sus dependencias:
evaluate_ticker_logic.py/indicator_calc.py). Todo con mocks de
requests/gspread -- SIN RED, consistente con la instrucción explícita de
la tarea ("pruebas offline del puerto cripto, sin red").
"""
from __future__ import annotations

import sys
from datetime import datetime
from unittest.mock import MagicMock, patch
from zoneinfo import ZoneInfo

import pytest

# gspread (vía google-auth -> cryptography) falla al importar en ESTE
# sandbox con un pyo3_runtime.PanicException nativo, no relacionado con
# este código (confirmado ya antes en esta tarea, al invocar
# cargar_universo_de_tickers() desde generar_oraculo_evaluate_js.sh --
# ver docs/pipeline/BLOQUEOS.md). Ninguna prueba de este archivo necesita
# gspread de verdad (siempre se monkeypatchea cargar_universo_cripto()/
# _leer_filas_universo()), así que se sustituye por un stub ANTES de
# importar snapshot_autocapture -- si el entorno real tiene gspread
# sano, sys.modules.setdefault no hace nada (mantiene el real).
sys.modules.setdefault("gspread", MagicMock())

import snapshot_autocapture as sa


# --- cargar_universo_cripto() -----------------------------------------------

def test_cargar_universo_cripto_filtra_por_mercado_y_estado(monkeypatch):
    filas = [
        {"TICKER": "BTC", "MERCADO": "CRYPTO", "ESTADO": "ACTIVO"},
        {"TICKER": "ETH", "MERCADO": "CRYPTO", "ESTADO": "PAUSADO"},  # excluido: no ACTIVO
        {"TICKER": "SOL", "MERCADO": "CRYPTO", "ESTADO": "activo"},  # minúsculas -- debe normalizar
        {"TICKER": "AAPL", "MERCADO": "NYSE", "ESTADO": "ACTIVO"},  # excluido: no CRYPTO
        {"TICKER": "", "MERCADO": "CRYPTO", "ESTADO": "ACTIVO"},  # excluido: sin ticker
    ]
    monkeypatch.setattr(sa, "_leer_filas_universo", lambda: filas)
    universo = sa.cargar_universo_cripto()
    assert sorted(u.ticker for u in universo) == ["BTC", "SOL"]
    assert all(u.mercado == "CRYPTO" for u in universo)


def test_cargar_universo_cripto_vacio_hoy_btc_eth_sol_pausados(monkeypatch):
    """
    Estado real esperado HOY en 14_UNIVERSO_TICKERS (instrucción
    explícita del usuario): BTC/ETH/SOL con ESTADO!=ACTIVO hasta que
    verificar_cripto.sh pase -- esta función debe devolver una lista
    vacía con ese estado, sin ningún guard extra en código.
    """
    filas = [
        {"TICKER": "BTC", "MERCADO": "CRYPTO", "ESTADO": "PAUSADO"},
        {"TICKER": "ETH", "MERCADO": "CRYPTO", "ESTADO": "PAUSADO"},
        {"TICKER": "SOL", "MERCADO": "CRYPTO", "ESTADO": "PAUSADO"},
    ]
    monkeypatch.setattr(sa, "_leer_filas_universo", lambda: filas)
    assert sa.cargar_universo_cripto() == []


# --- fetch_binance_klines() -------------------------------------------------

def _fake_binance_kline(t_ms, o, h, l, c, v):
    # Shape real de un kline de Binance: array posicional, strings para
    # los precios/volumen (confirmado en fetchBinanceKlines: raw.map(k=>
    # ({t:Math.floor(k[0]/1000), o:+k[1], h:+k[2], l:+k[3], c:+k[4], v:+k[5]})) --
    # el +k[i] solo tiene sentido si Binance manda strings, no numbers).
    return [t_ms, str(o), str(h), str(l), str(c), str(v), 0, "0", 0, "0", "0", "0"]


def test_fetch_binance_klines_mapea_shape_binance_a_candle():
    raw = [
        _fake_binance_kline(1700000000000, "100.1", "101.2", "99.3", "100.5", "1000"),
        _fake_binance_kline(1700003600000, "100.5", "102.0", "100.0", "101.5", "2000"),
    ]
    mock_resp = MagicMock()
    mock_resp.json.return_value = raw
    mock_resp.raise_for_status.return_value = None
    with patch.object(sa.requests, "get", return_value=mock_resp) as mock_get:
        candles = sa.fetch_binance_klines("BTCUSDT", "1h", 2)

    mock_get.assert_called_once()
    args, kwargs = mock_get.call_args
    assert args[0] == f"{sa.BINANCE_BASE}/api/v3/klines"
    assert kwargs["params"] == {"symbol": "BTCUSDT", "interval": "1h", "limit": 2}

    assert candles == [
        {"t": 1700000000, "o": 100.1, "h": 101.2, "l": 99.3, "c": 100.5, "v": 1000.0},
        {"t": 1700003600, "o": 100.5, "h": 102.0, "l": 100.0, "c": 101.5, "v": 2000.0},
    ]


def test_fetch_binance_klines_reintenta_y_lanza_tras_agotar(monkeypatch):
    """retries==null?2:retries -- 2 reintentos (3 intentos totales), 800ms
    entre cada uno. Si los 3 fallan, propaga el último error (throw lastErr)."""
    monkeypatch.setattr(sa.time, "sleep", lambda _s: None)  # no esperar de verdad en la prueba
    calls = {"n": 0}

    def boom(*a, **kw):
        calls["n"] += 1
        raise ConnectionError("sin red (simulado)")

    with patch.object(sa.requests, "get", side_effect=boom):
        with pytest.raises(ConnectionError):
            sa.fetch_binance_klines("BTCUSDT", "1d", 120)

    assert calls["n"] == sa.BINANCE_RETRIES + 1 == 3


def test_fetch_binance_klines_reintenta_y_luego_funciona(monkeypatch):
    monkeypatch.setattr(sa.time, "sleep", lambda _s: None)
    mock_resp = MagicMock()
    mock_resp.json.return_value = [_fake_binance_kline(1700000000000, 1, 2, 0.5, 1.5, 10)]
    mock_resp.raise_for_status.return_value = None
    calls = {"n": 0}

    def flaky(*a, **kw):
        calls["n"] += 1
        if calls["n"] < 2:
            raise ConnectionError("sin red (simulado), primer intento")
        return mock_resp

    with patch.object(sa.requests, "get", side_effect=flaky):
        candles = sa.fetch_binance_klines("ETHUSDT", "15m", 96)
    assert calls["n"] == 2
    assert len(candles) == 1


# --- fetch_crypto_candles() -------------------------------------------------

def test_fetch_crypto_candles_usa_symbol_usdt_y_los_limites_confirmados(monkeypatch):
    llamadas = []

    def fake_klines(symbol, interval, limit):
        llamadas.append((symbol, interval, limit))
        return [{"t": 1, "o": 1.0, "h": 1.0, "l": 1.0, "c": 1.0, "v": 1.0}]

    monkeypatch.setattr(sa, "fetch_binance_klines", fake_klines)
    data = sa.fetch_crypto_candles("BTC")

    assert sorted(llamadas) == sorted([
        ("BTCUSDT", "1d", 120), ("BTCUSDT", "1h", 100), ("BTCUSDT", "15m", 96),
    ])
    assert set(data.keys()) == {"1d", "1h", "15m"}
    for tf in ("1d", "1h", "15m"):
        assert data[tf]["periods"] == 1
        assert data[tf]["candles"][0]["c"] == 1.0


# --- compute_btc_gate() -----------------------------------------------------

def test_compute_btc_gate_hoy_siempre_da_false_y_sc02_scpb_salen_na():
    """
    Ata el sustituto temporal (ver docs/pipeline/BLOQUEOS.md) a un
    resultado observable, no solo "devuelve False": con ese valor,
    evalSC02/evalSCPB deben dar N/A por el gate -- si algún día
    compute_btc_gate() deja de devolver False sin que se haya portado
    computeMarketContext(), este test debe fallar y avisar.
    """
    import evaluate_ticker_logic as etl

    gate = sa.compute_btc_gate()
    assert gate is False

    settings = {"priceMin": 8, "atrMax": 4, "rvolMin": 1}
    r_sc02 = etl.eval_sc02({"ind": {"1d": {}, "1h": {}}, "hardNo": False,
                             "settings": settings, "ticker": "SOL", "btcGateOn": gate})
    r_scpb = etl.eval_scpb({"ind": {"1d": {}, "1h": {}, "15m": {}}, "hardNo": False,
                             "settings": settings, "ticker": "SOL", "btcGateOn": gate})
    assert r_sc02["naReason"] == "Gate BTC OFF"
    assert r_scpb["naReason"] == "Gate BTC OFF"


# --- evaluate_ticker(): btc_gate_on en el payload ---------------------------

def test_evaluate_ticker_envia_btc_gate_on_real_en_el_payload():
    mock_resp = MagicMock()
    mock_resp.json.return_value = {"hardNo": False}
    mock_resp.raise_for_status.return_value = None
    with patch.object(sa.requests, "post", return_value=mock_resp) as mock_post:
        sa.evaluate_ticker("BTC", {"1d": {"candles": []}}, "CRYPTO", btc_gate_on=True)

    _, kwargs = mock_post.call_args
    assert kwargs["json"]["btc_gate_on"] is True
    assert kwargs["json"]["mode"] == "CRYPTO"


# --- Desviación consciente (07/10/2026): gate BTC bloquea TODOS los
#     longs cripto en la CAPTURA, incluido SC-01 -- aunque evalSC01() (el
#     JS real) no comprueba btcGateOn. Regla del proyecto: BTC < EMA50
#     diaria = cero longs cripto, sin excepción, más estricta que lo que
#     enseña el scanner. -----------------------------------------------

def _evaluacion_sc01_trigger_auto_high():
    """SC-01 con score>=90 y applicable=True -- dispara AUTO_HIGH en
    detect_auto_trigger() real (sin mockear esa parte), group='crypto'
    (STRATEGY_META['SC-01']). evalSC01() real nunca comprueba btcGateOn
    -- este resultado es igual de válido con el gate ON o OFF, a
    propósito, para aislar que el bloqueo viene de _evaluar_y_capturar(),
    no de evaluate_ticker_logic.py (que no se toca)."""
    return {
        "ticker": "BTC", "hardNo": False, "globalVerdict": "OPERAR", "globalScore": 95,
        "strategies": [
            {"id": "SC-01", "applicable": True, "score": 95, "verdict": "OPERAR",
             "group": "crypto", "factors": []},
        ],
    }


def test_evaluar_y_capturar_bloquea_sc01_con_gate_off(monkeypatch):
    monkeypatch.setattr(sa, "evaluate_ticker", lambda *a, **kw: _evaluacion_sc01_trigger_auto_high())
    capturado = {"llamado": False}
    monkeypatch.setattr(sa, "capture_signal", lambda *a, **kw: capturado.__setitem__("llamado", True) or True)

    resultado = sa._evaluar_y_capturar("BTC", {}, "CRYPTO", btc_gate_on=False,
                                        data_ts="2026-01-01T00:00:00Z", snapshot_ts="2026-01-01T00:00:00Z",
                                        dry_run=False)

    assert resultado is False
    assert capturado["llamado"] is False, (
        "con el gate OFF, SC-01 NO debe llegar a capture_signal() aunque evalSC01() real "
        "no comprueba btcGateOn -- es la desviación consciente de la capa de captura."
    )


def test_evaluar_y_capturar_permite_sc01_con_gate_on(monkeypatch):
    """Mismo trigger exacto, solo cambia btc_gate_on -- confirma que el
    bloqueo de arriba es por el gate, no porque la función nunca capture
    nada."""
    monkeypatch.setattr(sa, "evaluate_ticker", lambda *a, **kw: _evaluacion_sc01_trigger_auto_high())
    capturado = {"llamado": False}
    monkeypatch.setattr(sa, "capture_signal", lambda *a, **kw: capturado.__setitem__("llamado", True) or True)

    resultado = sa._evaluar_y_capturar("BTC", {}, "CRYPTO", btc_gate_on=True,
                                        data_ts="2026-01-01T00:00:00Z", snapshot_ts="2026-01-01T00:00:00Z",
                                        dry_run=False)

    assert resultado is True
    assert capturado["llamado"] is True


def test_evaluar_y_capturar_gate_off_no_bloquea_nyse(monkeypatch):
    """El guard está scoped a mercado=='CRYPTO' -- NYSE nunca lo toca
    (siempre llama con btc_gate_on=False, que no debe convertirse en un
    bloqueo nuevo para acciones)."""
    evaluacion_nyse = {
        "ticker": "AAPL", "hardNo": False, "globalVerdict": "OPERAR", "globalScore": 95,
        "strategies": [
            {"id": "ST-16", "applicable": True, "score": 95, "verdict": "OPERAR",
             "group": "swing", "factors": []},
        ],
    }
    monkeypatch.setattr(sa, "evaluate_ticker", lambda *a, **kw: evaluacion_nyse)
    capturado = {"llamado": False}
    monkeypatch.setattr(sa, "capture_signal", lambda *a, **kw: capturado.__setitem__("llamado", True) or True)

    resultado = sa._evaluar_y_capturar("AAPL", {}, "NYSE", btc_gate_on=False,
                                        data_ts="2026-01-01T00:00:00Z", snapshot_ts="2026-01-01T00:00:00Z",
                                        dry_run=False)

    assert resultado is True
    assert capturado["llamado"] is True


# --- _ejecutar_cripto(): 24/7, dry-run obligatorio probado ------------------

def _entry(ticker):
    return sa.TickerUniverseEntry(ticker=ticker, mercado="CRYPTO", estado="ACTIVO",
                                   fecha_alta="", notas="")


def test_ejecutar_cripto_dry_run_no_hace_post_de_captura(monkeypatch):
    monkeypatch.setattr(sa, "cargar_universo_cripto", lambda: [_entry("BTC")])
    monkeypatch.setattr(sa, "fetch_crypto_candles", lambda t: {"1d": {"candles": [], "periods": 0}})
    monkeypatch.setattr(sa, "compute_btc_gate", lambda: False)

    # El resultado de evaluate_ticker() viene de /api/evaluate-ticker --
    # se simula aquí para que detect_auto_trigger() dé un trigger real y
    # así probar que, pese a eso, --dry-run no manda el POST de captura.
    fake_evaluation = {
        "ticker": "BTC", "hardNo": False, "globalVerdict": "OPERAR", "globalScore": 95,
        "strategies": [
            {"id": "SC-01", "applicable": True, "score": 95, "verdict": "OPERAR",
             "group": "crypto", "factors": []},
        ],
    }
    monkeypatch.setattr(sa, "evaluate_ticker", lambda *a, **kw: fake_evaluation)

    with patch.object(sa.requests, "post") as mock_post:
        args = type("Args", (), {"dry_run": True, "force_window": False})()
        now = datetime.now(ZoneInfo("Europe/Madrid"))
        code = sa._ejecutar_cripto(args, now)

    assert code == 0
    mock_post.assert_not_called()  # dry-run: ni /api/snapshots ni ningún otro POST real


def test_ejecutar_cripto_no_consulta_la_ventana_operativa(monkeypatch):
    """24/7 de verdad: dentro o fuera de 16:00-18:00 Madrid da igual --
    within_operating_window() no debe ni llamarse desde esta rama."""
    monkeypatch.setattr(sa, "cargar_universo_cripto", lambda: [])
    llamado = {"si": False}

    def fail_if_called(*a, **kw):
        llamado["si"] = True
        return False

    monkeypatch.setattr(sa, "within_operating_window", fail_if_called)
    args = type("Args", (), {"dry_run": True, "force_window": False})()
    now = datetime(2026, 1, 1, 3, 0, tzinfo=ZoneInfo("Europe/Madrid"))  # 03:00 -- fuera de la ventana NYSE
    code = sa._ejecutar_cripto(args, now)
    assert code == 0
    assert llamado["si"] is False


# --- main(): --market despacha a la rama correcta ---------------------------

def test_main_market_crypto_despacha_a_ejecutar_cripto(monkeypatch):
    llamadas = []
    monkeypatch.setattr(sa, "_ejecutar_cripto", lambda args, now: llamadas.append("crypto") or 0)
    monkeypatch.setattr(sa, "_ejecutar_nyse", lambda args, now: llamadas.append("nyse") or 0)
    monkeypatch.setattr(sys, "argv", ["snapshot_autocapture.py", "--market", "crypto", "--dry-run"])
    assert sa.main() == 0
    assert llamadas == ["crypto"]


def test_main_sin_market_sigue_yendo_a_nyse_por_defecto(monkeypatch):
    """Compatibilidad: el timer NYSE ya desplegado invoca el script sin
    --market -- debe seguir yendo a la rama NYSE sin cambios."""
    llamadas = []
    monkeypatch.setattr(sa, "_ejecutar_cripto", lambda args, now: llamadas.append("crypto") or 0)
    monkeypatch.setattr(sa, "_ejecutar_nyse", lambda args, now: llamadas.append("nyse") or 0)
    monkeypatch.setattr(sys, "argv", ["snapshot_autocapture.py", "--dry-run"])
    assert sa.main() == 0
    assert llamadas == ["nyse"]
