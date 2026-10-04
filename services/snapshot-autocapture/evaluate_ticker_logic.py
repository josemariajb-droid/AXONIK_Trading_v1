"""
Puerto literal de evaluateTicker() + 21 piezas de
/opt/axonik/scanner/index.html a Python, para exponerse como
POST /api/evaluate-ticker en market_data_proxy.py (single source of
verdad, decisión 04/10/2026 — ver
docs/pipeline/2026-10-03_automatizacion_captura_snapshots.md §1.7+).

Las 22 piezas, confirmadas contra el texto literal (no resumen en
prosa): docs/pipeline/pregunta5_5b_salida.txt, pregunta5c_salida.txt,
pregunta5d_salida.txt. Cadena de dependencias cerrada: MAX_RAW_SCORE es
un objeto literal de constantes, sin más llamadas.

RESUELTO (04/10/2026): la forma de "data" (ind[tf].ema20/.rsi/...) que
asumía evaluate_ticker() **no** la produce scan_batch() directamente —
scan_batch() solo devuelve candles/periods en bruto (confirmado contra
el código real: KeyError 'price' en la primera verificación
navegador-vs-endpoint). El cálculo real vive en computeIndicators() +
9 funciones (Preguntas 9/10, fondo de la cadena), portado y probado
contra fixtures reales en indicator_calc.py. build_ind() de abajo es el
puente: toma el "data" en bruto de scan_batch() y produce el "ind" que
evaluate_ticker() siempre esperó.
"""
from __future__ import annotations

import math
from datetime import datetime, timezone
from typing import Any, Optional

import indicator_calc

# --- Pieza: STRATEGY_META (línea 614 del navegador) -------------------------
STRATEGY_META: dict[str, dict[str, Any]] = {
    "ST-01": {"name": "Pullback a Tendencia", "group": "swing", "holding": "1-5 días", "maxHoldDays": 5},
    "ST-04": {"name": "MACD Triple Confluencia", "group": "medio", "holding": "1-4 sem", "maxHoldDays": 28},
    "ST-05": {"name": "Gap Continuidad", "group": "intraday", "holding": "30m-4h", "maxHoldDays": 0},
    "ST-06": {"name": "Rebote EMA200", "group": "swing", "holding": "1-4 sem", "maxHoldDays": 28},
    "ST-09": {"name": "Swing 2D Momentum", "group": "swing", "holding": "2-3 días", "maxHoldDays": 3},
    "ST-11": {"name": "Proximidad 52W High", "group": "medio", "holding": "1-4 sem", "maxHoldDays": 28},
    "ST-15": {"name": "ADX Breakout", "group": "medio", "holding": "1-4 sem", "maxHoldDays": 28},
    "ST-16": {"name": "Compresión en Tendencia", "group": "swing", "holding": "1-3 días", "maxHoldDays": 3},
    "SC-01": {"name": "BTC Explosivo", "group": "crypto", "holding": "1-5 días", "maxHoldDays": 5},
    "SC-02": {"name": "Altcoin Rotation", "group": "crypto", "holding": "1-5 días", "maxHoldDays": 5},
    "SC-PB": {"name": "Pullback + Gate BTC", "group": "crypto", "holding": "2-7 días", "maxHoldDays": 7},
}

# --- Pieza: MAX_RAW_SCORE (línea 608) — fondo de la cadena, sin más refs ---
MAX_RAW_SCORE: dict[str, float] = {
    "ST-01": 110, "ST-04": 85, "ST-05": 75, "ST-06": 75, "ST-09": 80,
    "ST-11": 70, "ST-15": 65, "ST-16": 75,
    "SC-01": 65, "SC-02": 80, "SC-PB": 80,
}

_NAN = float("nan")


def f_factor(text: str, tf: str, points: float) -> dict:
    """Pieza: f() (línea 871) — constructor trivial de un factor."""
    return {"text": text, "tf": tf, "points": points}


def finalize_verdict(score: float, hard_no: bool, rvol1d: float, rvol_min: float) -> str:
    """Pieza: finalizeVerdict() (línea 873)."""
    if hard_no or score < 55:
        verdict = "NO"
    elif score >= 70:
        verdict = "OPERAR"
    else:
        verdict = "VIGILAR"
    if verdict == "OPERAR" and not math.isnan(rvol1d) and rvol1d < rvol_min:
        verdict = "VIGILAR"
    return verdict


def mk_result(id_: str, score: float, factors: list, applicable: bool,
              hard_no: bool, rvol1d: float, rvol_min: float) -> dict:
    """Pieza: mkResult() (línea 881)."""
    if not applicable:
        return {"id": id_, "score": 0, "baseScore": 0, "factors": factors,
                "applicable": applicable, "verdict": "N/A"}
    max_raw = MAX_RAW_SCORE[id_]
    normalized = round(score / max_raw * 100) if max_raw > 0 else 0
    normalized = max(0, min(100, normalized))
    verdict = finalize_verdict(normalized, hard_no, rvol1d, rvol_min)
    return {"id": id_, "score": normalized, "baseScore": normalized,
            "rawScore": score, "maxRawScore": max_raw,
            "factors": factors, "applicable": applicable, "verdict": verdict}


def mk_na(id_: str, reason: Optional[str] = None) -> dict:
    """Pieza: mkNA() (línea 890)."""
    return {"id": id_, "score": 0, "baseScore": 0, "factors": [],
            "applicable": False, "verdict": "N/A",
            "naReason": reason or "No aplica en este momento"}


def ticker_hard_no(mode: str, price: float, d: dict, settings: dict) -> bool:
    """Pieza: tickerHardNo() (línea 893)."""
    if mode == "NYSE" and price < settings["priceMin"]:
        return True
    atr_pct = d.get("atrPct", _NAN)
    if atr_pct is None:
        atr_pct = _NAN
    if not math.isnan(atr_pct) and atr_pct > settings["atrMax"]:
        return True
    return False


# --- Las 10 piezas evalXX (líneas 899-1060) ---------------------------------
# Cada una replica la aritmética JS 1:1: mismo orden, mismos puntos,
# mismos umbrales (<, <=, strictamente mayor...). ctx = {ind, funda,
# hardNo, settings, mode, ticker, btcGateOn} — igual que en el navegador.

def eval_st01(ctx: dict) -> dict:
    ind, funda, hard_no, settings = ctx["ind"], ctx["funda"], ctx["hardNo"], ctx["settings"]
    d, h, m = ind.get("1d"), ind.get("1h"), ind.get("15m")
    if not d or not h or not m:
        return mk_na("ST-01")
    score, factors = 0, []
    if d["ema20"] > d["ema50"] and d["ema50"] > d["ema200"]:
        score += 25
        factors.append(f_factor("EMA20>50>200 alineación alcista", "1D", 25))
    pullback = (d["price"] - d["ema20"]) / d["ema20"] * 100 if d.get("ema20") else _NAN
    if not math.isnan(pullback) and -2 <= pullback <= 3:
        score += 20
        factors.append(f_factor(f"Pullback EMA20 {pullback:.1f}%", "1D", 20))
    if 40 <= d["rsi"] <= 55:
        score += 15
        factors.append(f_factor(f"RSI {d['rsi']:.0f} zona pullback", "1D", 15))
    if d["macdHist"] > 0 and d["macdHist"] > d["macdHistPrev"]:
        score += 15
        factors.append(f_factor("MACD hist positivo creciente", "1D", 15))
    if 40 <= h["rsi"] <= 60:
        score += 5
        factors.append(f_factor(f"RSI {h['rsi']:.0f} zona", "1H", 5))
    if h["macdHist"] > 0 and h["macdHist"] > h["macdHistPrev"]:
        score += 5
        factors.append(f_factor("MACD girando alcista", "1H", 5))
    if not math.isnan(m.get("vwap", _NAN) or _NAN) and m["price"] > m["vwap"]:
        score += 5
        factors.append(f_factor("Precio > VWAP", "15M", 5))
    if not math.isnan(m.get("ema20", _NAN) or _NAN) and m["price"] > m["ema20"]:
        score += 5
        factors.append(f_factor("Precio > EMA20", "15M", 5))
    if m["rvol"] >= 1.5:
        score += 10
        factors.append(f_factor(f"RVOL {m['rvol']:.1f}x", "15M", 10))
    if funda:
        if funda.get("profit_margin") is not None and funda["profit_margin"] > 0.15:
            score += 3
            factors.append(f_factor("Margen neto >15%", "FUND", 3))
        if funda.get("revenue_growth") is not None and funda["revenue_growth"] > 0.10:
            score += 2
            factors.append(f_factor("Rev growth >10%", "FUND", 2))
    return mk_result("ST-01", score, factors, True, hard_no, d["rvol"], settings["rvolMin"])


def eval_st05(ctx: dict) -> dict:
    ind, hard_no, settings = ctx["ind"], ctx["hardNo"], ctx["settings"]
    d, m = ind.get("1d"), ind.get("15m")
    gap_pct = (d.get("gapPct") if d else None)
    gap_pct = _NAN if gap_pct is None else gap_pct
    if not d or not m or math.isnan(gap_pct) or abs(gap_pct) < 0.3:
        return mk_na("ST-05", "Sin gap real hoy")
    score, factors = 0, []
    if gap_pct >= 1.5:
        score += 20
        factors.append(f_factor(f"Gap alcista +{gap_pct:.1f}%", "1D", 20))
    if d["rvol"] >= 2:
        score += 15
        factors.append(f_factor(f"RVOL 1D {d['rvol']:.1f}x", "1D", 15))
    if not math.isnan(m.get("vwap", _NAN) or _NAN) and m["price"] > m["vwap"]:
        score += 20
        factors.append(f_factor("Precio > VWAP post-gap", "15M", 20))
    if m["rvol"] >= 2.5:
        score += 20
        factors.append(f_factor(f"RVOL 15M {m['rvol']:.1f}x", "15M", 20))
    return mk_result("ST-05", score, factors, True, hard_no, d["rvol"], settings["rvolMin"])


def eval_st06(ctx: dict) -> dict:
    ind, hard_no, settings = ctx["ind"], ctx["hardNo"], ctx["settings"]
    d, h = ind.get("1d"), ind.get("1h")
    ema200 = (d.get("ema200") if d else None)
    if not d or not h or ema200 is None or math.isnan(ema200):
        return mk_na("ST-06")
    dist = (d["price"] - d["ema200"]) / d["ema200"] * 100
    if abs(dist) > 2:
        return mk_na("ST-06", "Precio lejos de EMA200")
    score = 25
    factors = [f_factor(f"Precio en zona EMA200 ({dist:.1f}%)", "1D", 25)]
    if 35 <= d["rsi"] <= 50:
        score += 20
        factors.append(f_factor(f"RSI {d['rsi']:.0f} zona rebote", "1D", 20))
    if d["price"] > d["ema200"]:
        score += 15
        factors.append(f_factor("Precio > EMA200", "1D", 15))
    if h["rvol"] >= 1.5:
        score += 15
        factors.append(f_factor(f"RVOL 1H {h['rvol']:.1f}x", "1H", 15))
    return mk_result("ST-06", score, factors, True, hard_no, d["rvol"], settings["rvolMin"])


def eval_st09(ctx: dict) -> dict:
    ind, hard_no, settings = ctx["ind"], ctx["hardNo"], ctx["settings"]
    d, h, m = ind.get("1d"), ind.get("1h"), ind.get("15m")
    if not d or not h or not m or len(d.get("candles", [])) < 22:
        return mk_na("ST-09")
    vols = [c["v"] for c in d["candles"]]
    prev_vol = vols[-2]
    prev_avg20 = sum(vols[-22:-2]) / 20
    rvol_prev = prev_vol / prev_avg20 if prev_avg20 > 0 else _NAN
    prev_c = d["candles"][-2]
    range_close = ((prev_c["c"] - prev_c["l"]) / (prev_c["h"] - prev_c["l"])
                   if (prev_c["h"] - prev_c["l"]) > 0 else _NAN)
    if math.isnan(rvol_prev) or rvol_prev < 1.3:
        return mk_na("ST-09", "Sesión anterior sin RVOL alto")
    score, factors = 0, []
    if rvol_prev >= 1.8:
        score += 20
        factors.append(f_factor(f"RVOL sesión anterior {rvol_prev:.1f}x", "1D", 20))
    if not math.isnan(range_close) and range_close >= 0.8:
        score += 15
        factors.append(f_factor(f"Cierre en {range_close*100:.0f}% del rango", "1D", 15))
    if 55 <= d["rsi"] <= 70:
        score += 15
        factors.append(f_factor(f"RSI {d['rsi']:.0f} momentum", "1D", 15))
    if h["macdHist"] > 0:
        score += 15
        factors.append(f_factor("MACD 1H positivo", "1H", 15))
    if not math.isnan(m.get("vwap", _NAN) or _NAN) and m["price"] > m["vwap"]:
        score += 15
        factors.append(f_factor("Precio > VWAP sesión", "15M", 15))
    return mk_result("ST-09", score, factors, True, hard_no, d["rvol"], settings["rvolMin"])


def eval_st11(ctx: dict) -> dict:
    ind, funda, hard_no, settings = ctx["ind"], ctx["funda"], ctx["hardNo"], ctx["settings"]
    d = ind.get("1d")
    if not d or not funda or funda.get("fifty_two_week_high") is None:
        return mk_na("ST-11", "Sin fundamentales/52W high")
    high = funda["fifty_two_week_high"]
    pct = (d["price"] - high) / high * 100
    if pct < -15:
        return mk_na("ST-11", "Lejos del 52W high")
    score, factors = 0, []
    if pct >= -5:
        score += 25
        factors.append(f_factor(f"{pct:.1f}% del 52W high (<5%)", "1D", 25))
    elif pct >= -10:
        score += 15
        factors.append(f_factor(f"{pct:.1f}% del 52W high (<10%)", "1D", 15))
    if d["rsi"] < 75:
        score += 15
        factors.append(f_factor(f"RSI {d['rsi']:.0f} < 75", "1D", 15))
    if funda.get("revenue_growth") is not None and funda["revenue_growth"] > 0.10:
        score += 15
        factors.append(f_factor("Rev growth >10%", "FUND", 15))
    if d["rvol"] >= 1.5:
        score += 15
        factors.append(f_factor(f"RVOL {d['rvol']:.1f}x", "1D", 15))
    return mk_result("ST-11", score, factors, True, hard_no, d["rvol"], settings["rvolMin"])


def eval_st15(ctx: dict) -> dict:
    ind, hard_no, settings = ctx["ind"], ctx["hardNo"], ctx["settings"]
    d = ind.get("1d")
    adx = (d.get("adx") if d else None)
    adx = _NAN if adx is None else adx
    if not d or math.isnan(adx) or adx < 15 or adx > 40:
        return mk_na("ST-15", "ADX fuera de rango de inicio de tendencia")
    score, factors = 0, []
    if 20 <= adx <= 35 and d["diPlus"] > d["diMinus"]:
        score += 25
        factors.append(f_factor(f"ADX {adx:.0f} DI+>DI-", "1D", 25))
    if d["rvol"] >= 1.8:
        score += 15
        factors.append(f_factor(f"RVOL {d['rvol']:.1f}x", "1D", 15))
    if d["price"] > d["ema20"]:
        score += 15
        factors.append(f_factor("Precio > EMA20", "1D", 15))
    if 55 <= d["rsi"] <= 70:
        score += 10
        factors.append(f_factor(f"RSI {d['rsi']:.0f}", "1D", 10))
    return mk_result("ST-15", score, factors, True, hard_no, d["rvol"], settings["rvolMin"])


def eval_st16(ctx: dict) -> dict:
    ind, hard_no, settings = ctx["ind"], ctx["hardNo"], ctx["settings"]
    d, h, m = ind.get("1d"), ind.get("1h"), ind.get("15m")
    compression = (h.get("compression") if h else None)
    compression = _NAN if compression is None else compression
    if not d or not h or not m or math.isnan(compression) or compression > 3:
        return mk_na("ST-16", "Sin compresión real")
    score, factors = 0, []
    if d["ema20"] > d["ema50"]:
        score += 20
        factors.append(f_factor("Tendencia EMA20>50", "1D", 20))
    if compression <= 2:
        score += 20
        factors.append(f_factor(f"Compresión {compression:.1f}% (6 velas)", "1H", 20))
    if m["rvol"] >= 2:
        score += 20
        factors.append(f_factor(f"RVOL ruptura {m['rvol']:.1f}x", "15M", 20))
    if not math.isnan(m.get("ema200", _NAN) or _NAN) and m["price"] > m["ema200"]:
        score += 15
        factors.append(f_factor("Precio > EMA200", "15M", 15))
    return mk_result("ST-16", score, factors, True, hard_no, d["rvol"], settings["rvolMin"])


def eval_sc01(ctx: dict) -> dict:
    ind, hard_no, settings, ticker = ctx["ind"], ctx["hardNo"], ctx["settings"], ctx["ticker"]
    if ticker not in ("BTC", "ETH"):
        return mk_na("SC-01", "Solo BTC/ETH")
    d, m = ind.get("1d"), ind.get("15m")
    if not d:
        return mk_na("SC-01")
    score, factors = 0, []
    compression = d.get("compression")
    compression = _NAN if compression is None else compression
    squeeze_resolved = not math.isnan(compression) and compression <= 6 and d["rvol"] >= 2.5
    if squeeze_resolved:
        score += 20
        factors.append(f_factor(f"Squeeze resuelto, RVOL {d['rvol']:.1f}x", "1D", 20))
    if 55 <= d["rsi"] <= 70:
        score += 15
        factors.append(f_factor(f"RSI {d['rsi']:.0f}", "1D", 15))
    if d["macdHist"] > 0:
        score += 15
        factors.append(f_factor("MACD positivo", "1D", 15))
    if m and not math.isnan(m.get("vwap", _NAN) or _NAN) and m["price"] > m["vwap"]:
        score += 15
        factors.append(f_factor("Precio > VWAP", "15M", 15))
    return mk_result("SC-01", score, factors, True, hard_no, d["rvol"], settings["rvolMin"])


def eval_sc02(ctx: dict) -> dict:
    ind, hard_no, settings, ticker, btc_gate_on = (
        ctx["ind"], ctx["hardNo"], ctx["settings"], ctx["ticker"], ctx["btcGateOn"]
    )
    if ticker in ("BTC", "ETH"):
        return mk_na("SC-02", "Solo altcoins")
    if not btc_gate_on:
        return mk_na("SC-02", "Gate BTC OFF")
    d, h = ind.get("1d"), ind.get("1h")
    if not d or not h:
        return mk_na("SC-02")
    score, factors = 0, []
    if d["price"] > d["ema50"]:
        score += 20
        factors.append(f_factor("Precio > EMA50", "1D", 20))
    if d["ema20"] > d["ema50"]:
        score += 15
        factors.append(f_factor("EMA20 > EMA50", "1D", 15))
    if d["rsi"] < 60:
        score += 15
        factors.append(f_factor(f"RSI {d['rsi']:.0f} < 60", "1D", 15))
    if d["rvol"] >= 1.5:
        score += 15
        factors.append(f_factor(f"RVOL {d['rvol']:.1f}x", "1D", 15))
    if h["macdHist"] > 0:
        score += 15
        factors.append(f_factor("MACD 1H positivo", "1H", 15))
    return mk_result("SC-02", score, factors, True, hard_no, d["rvol"], settings["rvolMin"])


def eval_scpb(ctx: dict) -> dict:
    ind, hard_no, settings, btc_gate_on = ctx["ind"], ctx["hardNo"], ctx["settings"], ctx["btcGateOn"]
    if not btc_gate_on:
        return mk_na("SC-PB", "Gate BTC OFF")
    d, h, m = ind.get("1d"), ind.get("1h"), ind.get("15m")
    if not d or not h or not m:
        return mk_na("SC-PB")
    score, factors = 0, []
    if d["ema20"] > d["ema50"] and d["ema50"] > d["ema200"]:
        score += 25
        factors.append(f_factor("EMA 20>50>200", "1D", 25))
    pullback = (d["price"] - d["ema20"]) / d["ema20"] * 100 if d.get("ema20") else _NAN
    if not math.isnan(pullback) and -3 <= pullback <= 2:
        score += 20
        factors.append(f_factor(f"Pullback EMA20 {pullback:.1f}%", "1D", 20))
    if 40 <= d["rsi"] <= 55:
        score += 15
        factors.append(f_factor(f"RSI {d['rsi']:.0f}", "1D", 15))
    if h["macdHist"] > 0 and h["macdHist"] > h["macdHistPrev"]:
        score += 10
        factors.append(f_factor("MACD 1H girando alcista", "1H", 10))
    if m["rvol"] >= 1.5:
        score += 10
        factors.append(f_factor(f"RVOL 15M {m['rvol']:.1f}x", "15M", 10))
    return mk_result("SC-PB", score, factors, True, hard_no, d["rvol"], settings["rvolMin"])


# --- Pieza: NYSE_STRATEGIES / CRYPTO_STRATEGIES (líneas 1068-1069) ----------
# Arrays FIJOS en el código -- no se filtran por 02_SCANNERS.ESTADO en
# tiempo de ejecución. ST-04 existe en STRATEGY_META/MAX_RAW_SCORE pero
# NO está en este array -- hoy no se evalúa en ningún autoCaptureSnapshots,
# tal cual está en el navegador (ver nota en el documento de diseño).
NYSE_STRATEGIES = [eval_st01, eval_st05, eval_st06, eval_st09, eval_st11, eval_st15, eval_st16]
CRYPTO_STRATEGIES = [eval_sc01, eval_sc02, eval_scpb]


def apply_event_adjustments(strategies: list[dict], mode: str, funda: Optional[dict],
                             insider_summary: Optional[dict], hard_no: bool,
                             rvol1d: float, rvol_min: float) -> list[dict]:
    """Pieza: applyEventAdjustments() (línea 1074)."""
    earnings_days = None
    if mode == "NYSE" and funda and funda.get("next_earnings"):
        ed = datetime.fromisoformat(funda["next_earnings"] + "T00:00:00+00:00")
        earnings_days = (ed - datetime.now(timezone.utc)).total_seconds() / 86400

    insider_score = 0
    if mode == "NYSE" and insider_summary:
        insider_score = max(-8, min(8, insider_summary.get("insider_score") or 0))

    result = []
    for s in strategies:
        if not s["applicable"]:
            result.append(s)
            continue
        score = s["score"]
        factors = list(s["factors"])
        earnings_adj, insider_adj = 0, 0

        if earnings_days is not None and earnings_days >= 0 and s["group"] in ("swing", "medio"):
            max_hold = STRATEGY_META[s["id"]]["maxHoldDays"]
            if earnings_days <= max_hold:
                earnings_adj = -10
                score += earnings_adj
                factors.append(f_factor(
                    f"Earnings en {math.ceil(earnings_days)}d dentro del holding — cierra antes",
                    "EVENTO", -10))
        if insider_score != 0:
            insider_adj = insider_score
            score += insider_adj
            sign = "+" if insider_score >= 0 else ""
            factors.append(f_factor(f"Insider score {sign}{insider_score}", "INSIDER", insider_score))

        if score == s["score"]:
            result.append(s)
            continue

        score = max(0, min(100, score))
        verdict = finalize_verdict(score, hard_no, rvol1d, rvol_min)
        result.append({**s, "score": score, "earningsAdj": earnings_adj,
                        "insiderAdj": insider_adj, "factors": factors, "verdict": verdict})
    return result


def build_ind(data: dict) -> dict:
    """
    Puente entre el "data" en bruto de scan_batch() (shape confirmado:
    {"1d": {"candles": [...], "periods": N}, "1h": {...}, "15m": {...}})
    y el "ind" que evaluate_ticker() siempre esperó -- equivalente
    Python de lo que hace fetchNyseTicker()/fetchCryptoTicker() en el
    navegador antes de llamar a evaluateTicker() (Pregunta 8):
    computeIndicators(candles, tf) por cada timeframe.

    Un tf sin velas (o con "error") da ind[tf]=None -- mismo criterio
    que el navegador (`tfData.candles && !tfData.error`), y
    evaluate_ticker() ya maneja ind['1d'] is None devolviendo None.
    """
    ind: dict[str, Optional[dict]] = {}
    for tf in ("1d", "1h", "15m"):
        tf_data = data.get(tf)
        candles = tf_data.get("candles") if tf_data else None
        if not tf_data or not candles or tf_data.get("error"):
            ind[tf] = None
            continue
        ind[tf] = indicator_calc.compute_indicators(candles, tf)
    return ind


def evaluate_ticker(ticker: str, ind: dict, funda: Optional[dict], mode: str,
                     settings: dict, btc_gate_on: bool,
                     insider_summary: Optional[dict]) -> Optional[dict]:
    """
    Pieza: evaluateTicker() (línea 1114).

    OJO al integrar: esto evalúa TODAS las estrategias fijas del modo
    (7 NYSE o 3 crypto) en una sola llamada por ticker -- no una
    llamada por (ticker, scanner). Ver nota de arquitectura en el
    documento de diseño antes de cablear esto a snapshot_autocapture.py.
    """
    d = ind.get("1d")
    if not d:
        return None
    hard_no = ticker_hard_no(mode, d["price"], d, settings)
    ctx = {"ind": ind, "funda": funda, "hardNo": hard_no, "settings": settings,
           "mode": mode, "ticker": ticker, "btcGateOn": btc_gate_on}
    fns = NYSE_STRATEGIES if mode == "NYSE" else CRYPTO_STRATEGIES
    strategies = []
    for fn in fns:
        r = fn(ctx)
        strategies.append({**r, **STRATEGY_META[r["id"]]})
    strategies = apply_event_adjustments(strategies, mode, funda, insider_summary,
                                          hard_no, d["rvol"], settings["rvolMin"])

    applicable_strats = [s for s in strategies if s["applicable"]]
    best = None
    if applicable_strats:
        best = applicable_strats[0]
        for s in applicable_strats[1:]:
            if s["score"] > best["score"]:
                best = s

    earnings_days = None
    if mode == "NYSE" and funda and funda.get("next_earnings"):
        ed = datetime.fromisoformat(funda["next_earnings"] + "T00:00:00+00:00")
        earnings_days = (ed - datetime.now(timezone.utc)).total_seconds() / 86400

    return {
        "ticker": ticker, "price": d["price"], "ind": ind, "funda": funda,
        "strategies": strategies, "best": best,
        "globalVerdict": best["verdict"] if best else "N/A",
        "globalScore": best["score"] if best else 0,
        "hardNo": hard_no,
        "insiderSummary": insider_summary,
        "earningsDays": (math.ceil(earnings_days)
                          if earnings_days is not None and 0 <= earnings_days <= 35
                          else None),
    }


def detect_auto_trigger(r: Optional[dict]) -> Optional[dict]:
    """
    Pieza: detectAutoTrigger() (línea 2669). Prioridad ESTRICTA, no
    unión de ramas:

      1. AUTO_MULTI: >=2 estrategias del MISMO grupo con score>=80 --
         se comprueba primero; si algún grupo califica, se devuelve ESE
         grupo y se corta ahí (no se mira AUTO_HIGH).
      2. AUTO_HIGH: solo si ningún grupo califica para AUTO_MULTI --
         la ÚNICA estrategia con score>=90 más alta (no todas las que
         pasen 90).
    """
    if not r or r.get("error") or r.get("hardNo"):
        return None
    if r.get("globalVerdict") in ("NO", "N/A"):
        return None
    applicable = [s for s in r["strategies"] if s["applicable"]]

    by_group: dict[str, list[dict]] = {}
    for s in applicable:
        if s["score"] >= 80:
            by_group.setdefault(s["group"], []).append(s)
    for group_strategies in by_group.values():
        if len(group_strategies) >= 2:
            return {"type": "AUTO_MULTI", "strategies": group_strategies}

    high_single = [s for s in applicable if s["score"] >= 90]
    if high_single:
        top = high_single[0]
        for s in high_single[1:]:
            if s["score"] > top["score"]:
                top = s
        return {"type": "AUTO_HIGH", "strategies": [top]}
    return None
