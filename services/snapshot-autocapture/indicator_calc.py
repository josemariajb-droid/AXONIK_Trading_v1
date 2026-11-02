"""
Puerto literal de computeIndicators() + las 9 funciones de cálculo que
calcula de verdad los indicadores técnicos (price/ema/rsi/macd/atr/rvol/
adx/compression/gapPct/vwap), confirmadas contra el texto real del
navegador en docs/pipeline/pregunta9_salida.txt y pregunta10_salida.txt
(Preguntas 9 y 10 — fondo de la cadena, sin más dependencias).

Probado contra fixtures reales (Node ejecutando el JS real sobre velas
reales de /api/scan-batch) en docs/pipeline/fixtures_js/ — ver
test_indicator_calc.py.

DOS COSAS A RESPETAR TAL CUAL, NO "CORREGIR" (ver diseño §1.10):

1. `ema200` nunca es una EMA de 200 períodos de verdad con los datos
   reales de hoy (120/100/96 velas por timeframe, los tres por debajo
   de 200) — siempre cae en el fallback de `ema_arr(..., allow_partial=True)`:
   la media simple de todos los cierres disponibles.
2. Hay DOS familias de suavizado distintas, implementadas aquí a
   propósito en funciones separadas, nunca compartiendo una sola
   implementación: EMA clásica (`ema_arr`/`calc_macd`, α=2/(period+1))
   y Wilder (`calc_rsi`/`calc_atr`/`calc_adx`, α=1/period). Reutilizar
   una sola función de suavizado para las dos da un número sutilmente
   distinto sin lanzar ningún error — exactamente el patrón que ya
   costó risk_pct/risk_per_share y atrMax. test_indicator_calc.py
   incluye una prueba diseñada para fallar si alguien intercambia las
   dos convenciones.

`calc_vwap` agrupa por fecha de calendario **UTC**
(`datetime.fromtimestamp(t, tz=timezone.utc).date()`), no por sesión de
NYSE en hora local — igual que el navegador, no una corrección.
"""
from __future__ import annotations

import math
from datetime import datetime, timezone
from typing import Optional

_NAN = float("nan")


def _is_nan(x: float) -> bool:
    return isinstance(x, float) and math.isnan(x)


def _js_truthy_number(x: float) -> bool:
    """
    JS trata 0 y NaN como falsy para un número -- todo lo demás es
    truthy (incluyendo negativos). Solo hace falta para atrPct, que en
    JS es `(atr && price) ? atr/price*100 : NaN` -- una coerción de
    truthiness sobre números, no una comparación `>`. Las comparaciones
    `>`/`<` normales (compression, gapPct, vwap, rvol) ya se comportan
    igual en Python que en JS para NaN (ambas son IEEE754), así que no
    necesitan este helper.
    """
    return not (x == 0 or _is_nan(x))


def ema_arr(prices: list[float], period: int, allow_partial: bool = False) -> list[float]:
    """Pieza: emaArr() -- EMA clásica, α=2/(period+1), semilla=SMA de los primeros `period`."""
    n = len(prices)
    if n < period:
        if not allow_partial or n < 2:
            return [_NAN] * n
        seed = sum(prices) / n
        out = [_NAN] * (n - 1)
        out.append(seed)
        return out
    k = 2 / (period + 1)
    seed = sum(prices[:period]) / period
    out = [_NAN] * (period - 1)
    out.append(seed)
    for i in range(period, n):
        out.append(prices[i] * k + out[-1] * (1 - k))
    return out


def calc_rsi(closes: list[float], period: int = 14) -> float:
    """Pieza: calcRSI() -- Wilder, α=1/period."""
    if len(closes) < period + 2:
        return _NAN
    deltas = [closes[i] - closes[i - 1] for i in range(1, len(closes))]
    avg_g = sum(d if d > 0 else 0 for d in deltas[:period]) / period
    avg_l = sum(-d if d < 0 else 0 for d in deltas[:period]) / period
    for i in range(period, len(deltas)):
        g = deltas[i] if deltas[i] > 0 else 0
        l = -deltas[i] if deltas[i] < 0 else 0
        avg_g = (avg_g * (period - 1) + g) / period
        avg_l = (avg_l * (period - 1) + l) / period
    if avg_l == 0:
        return 100.0
    return 100 - 100 / (1 + avg_g / avg_l)


def calc_macd(closes: list[float], fast: int = 12, slow: int = 26,
              signal: int = 9) -> tuple[float, float, float, float]:
    """Pieza: calcMACD() -- EMA clásica vía ema_arr (sin allow_partial) para fast/slow/signal."""
    ef = ema_arr(closes, fast)
    es = ema_arr(closes, slow)
    macd_line = [_NAN if (_is_nan(f) or _is_nan(es[i])) else f - es[i] for i, f in enumerate(ef)]
    valid = [v for v in macd_line if not _is_nan(v)]
    if len(valid) < signal + 1:
        return (_NAN, _NAN, _NAN, _NAN)
    sig_arr = ema_arr(valid, signal)
    histo = []
    for i in range(signal - 1, len(valid)):
        if not _is_nan(sig_arr[i]):
            histo.append(valid[i] - sig_arr[i])
    if len(histo) < 2:
        return (valid[-1], sig_arr[-1], _NAN, _NAN)
    return (valid[-1], sig_arr[-1], histo[-1], histo[-2])


def calc_atr(highs: list[float], lows: list[float], closes: list[float],
             period: int = 14) -> float:
    """Pieza: calcATR() -- Wilder, α=1/period."""
    if len(closes) < period + 2:
        return _NAN
    tr = []
    for i in range(1, len(closes)):
        tr.append(max(highs[i] - lows[i], abs(highs[i] - closes[i - 1]), abs(lows[i] - closes[i - 1])))
    atr = sum(tr[:period]) / period
    for i in range(period, len(tr)):
        atr = (atr * (period - 1) + tr[i]) / period
    return atr


def calc_rvol(volumes: list[float]) -> float:
    """Pieza: calcRVOL() -- media simple de las 20 velas previas (sin la actual)."""
    if len(volumes) < 21:
        return _NAN
    last = volumes[-1]
    prev20 = volumes[-21:-1]
    avg = sum(prev20) / len(prev20)
    return last / avg if avg > 0 else _NAN


def calc_adx(highs: list[float], lows: list[float], closes: list[float],
             period: int = 14) -> dict:
    """Pieza: calcADX() -- Wilder (en la suma de TR/+DM/-DM y en el promedio final)."""
    n = len(highs)
    if n < period * 2:
        return {"adx": _NAN, "diPlus": _NAN, "diMinus": _NAN}
    tr: list[float] = []
    plus_dm: list[float] = []
    minus_dm: list[float] = []
    for i in range(1, n):
        up_move = highs[i] - highs[i - 1]
        down_move = lows[i - 1] - lows[i]
        plus_dm.append(up_move if (up_move > down_move and up_move > 0) else 0)
        minus_dm.append(down_move if (down_move > up_move and down_move > 0) else 0)
        tr.append(max(highs[i] - lows[i], abs(highs[i] - closes[i - 1]), abs(lows[i] - closes[i - 1])))

    def wilder_sum(arr: list[float]) -> list[Optional[float]]:
        out: list[Optional[float]] = [None] * len(arr)
        s = sum(arr[:period])
        out[period - 1] = s
        for i in range(period, len(arr)):
            s = s - s / period + arr[i]
            out[i] = s
        return out

    tr_s, p_s, m_s = wilder_sum(tr), wilder_sum(plus_dm), wilder_sum(minus_dm)
    di_p: list[float] = []
    di_m: list[float] = []
    dx: list[float] = []
    for i in range(period - 1, len(tr)):
        if tr_s[i] is None or tr_s[i] == 0:
            continue
        p = 100 * p_s[i] / tr_s[i]
        m = 100 * m_s[i] / tr_s[i]
        di_p.append(p)
        di_m.append(m)
        dx.append(100 * abs(p - m) / ((p + m) or 1))

    if len(dx) < period:
        return {
            "adx": _NAN,
            "diPlus": di_p[-1] if di_p else _NAN,
            "diMinus": di_m[-1] if di_m else _NAN,
        }
    adx = sum(dx[:period]) / period
    for i in range(period, len(dx)):
        adx = (adx * (period - 1) + dx[i]) / period
    return {"adx": adx, "diPlus": di_p[-1], "diMinus": di_m[-1]}


def calc_compression(candles: list[dict], n: int = 6) -> float:
    """Pieza: calcCompression() -- rango simple de las últimas n velas, sin suavizado."""
    if len(candles) < n:
        return _NAN
    s = candles[-n:]
    high = max(c["h"] for c in s)
    low = min(c["l"] for c in s)
    mid = (high + low) / 2
    return (high - low) / mid * 100 if mid > 0 else _NAN


def calc_gap_pct(candles: list[dict]) -> float:
    """Pieza: calcGapPct() -- % entre open de hoy y close de ayer, sin suavizado."""
    if len(candles) < 2:
        return _NAN
    today, prev = candles[-1], candles[-2]
    return (today["o"] - prev["c"]) / prev["c"] * 100 if prev["c"] > 0 else _NAN


def calc_vwap(candles: list[dict]) -> float:
    """
    Pieza: calcVWAP() -- VWAP de las velas del mismo día de calendario
    UTC que la última vela (no sesión NYSE en hora local -- igual que
    el navegador, no una corrección).
    """
    if not candles:
        return _NAN
    last_date = datetime.fromtimestamp(candles[-1]["t"], tz=timezone.utc).date()
    session = [c for c in candles
               if datetime.fromtimestamp(c["t"], tz=timezone.utc).date() == last_date]
    pv = 0.0
    vol = 0.0
    for c in session:
        typ = (c["h"] + c["l"] + c["c"]) / 3
        pv += typ * c["v"]
        vol += c["v"]
    return pv / vol if vol > 0 else _NAN


def compute_indicators(candles: list[dict], tf: str) -> Optional[dict]:
    """Pieza: computeIndicators() -- orquesta las 9 funciones de arriba."""
    if not candles or len(candles) < 5:
        return None
    closes = [c["c"] for c in candles]
    highs = [c["h"] for c in candles]
    lows = [c["l"] for c in candles]
    volumes = [c["v"] for c in candles]

    price = closes[-1]
    ema20 = ema_arr(closes, 20)[-1]
    ema50 = ema_arr(closes, 50)[-1]
    ema200 = ema_arr(closes, 200, True)[-1]
    rsi = calc_rsi(closes, 14)
    macd, macd_signal, macd_hist, macd_hist_prev = calc_macd(closes)
    atr = calc_atr(highs, lows, closes, 14)
    atr_pct = atr / price * 100 if (_js_truthy_number(atr) and _js_truthy_number(price)) else _NAN
    rvol = calc_rvol(volumes)
    adx_r = calc_adx(highs, lows, closes, 14)
    compression = calc_compression(candles, 6)
    gap_pct = calc_gap_pct(candles) if tf == "1d" else _NAN
    vwap = calc_vwap(candles) if tf == "15m" else _NAN

    return {
        "price": price, "ema20": ema20, "ema50": ema50, "ema200": ema200,
        "rsi": rsi, "macd": macd, "macdSignal": macd_signal,
        "macdHist": macd_hist, "macdHistPrev": macd_hist_prev,
        "atr": atr, "atrPct": atr_pct, "rvol": rvol,
        "adx": adx_r["adx"], "diPlus": adx_r["diPlus"], "diMinus": adx_r["diMinus"],
        "compression": compression, "gapPct": gap_pct, "vwap": vwap,
        "candles": candles,
    }
