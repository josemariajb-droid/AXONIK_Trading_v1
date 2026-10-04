#!/usr/bin/env python3
"""
Reemplaza autoCaptureSnapshots() del navegador (scanner HTML en
/opt/axonik/scanner/index.html). Ejecutado por
axonik-snapshot-autocapture.timer, SOLO dentro de 16:00-18:00
Europe/Madrid, lunes a viernes — guard redundante dentro del propio
script, no solo en el OnCalendar del timer.

Diseño completo y verificación de que detectAutoTrigger()/evaluateTicker()/
NYSE_STRATEGIES/CRYPTO_STRATEGIES/applyEventAdjustments/tickerHardNo son
aritmética pura sobre datos, sin dependencia de navegador:
docs/pipeline/2026-10-03_automatizacion_captura_snapshots.md (§1, cerrado).

UNIVERSO DE TICKERS (04/10/2026) — ya no viene de 02_SCANNERS.ESTADO.

  Decisión cerrada (diseño §1.9, BACKLOG entrada 5): el universo vive en
  la hoja nueva 14_UNIVERSO_TICKERS del Decision Engine (TICKER, MERCADO,
  ESTADO, FECHA_ALTA, NOTAS), ya creada en el Excel real con cabeceras y
  sin poblar. cargar_universo_de_tickers() la lee filtrando
  ESTADO='ACTIVO'. Esto además resuelve de raíz el hallazgo estructural
  de §1.8: la evaluación real es una llamada por *ticker* (no por
  (ticker, scanner)), así que el universo de tickers+mercado encaja
  directamente con evaluate_ticker_logic.evaluate_ticker(ticker, ind,
  funda, mode, ...) sin el cruce artificial con scanners que tenía el
  diseño anterior. 02_SCANNERS sigue existiendo para lo que ya hacía
  (catálogo de scanners), simplemente deja de ser la fuente de este
  universo.

ESTADO TRAS LA PREGUNTA 4 (confirmado contra el código real, no prosa):

  - fetch_scan_batch(): shape de RESPUESTA confirmado: {"results":
    [{"ticker", "timestamp", "data", "error"?}]}. "data" son indicadores
    EN BRUTO, no un score precalculado. Los errores por-ticker vienen
    dentro del array ("error" por entrada), manejado en el bucle
    principal, no como excepción.

    El shape de PETICIÓN (qué campo espera el POST para indicar qué
    tickers escanear) NO está confirmado contra el modelo Pydantic real
    — solo tenemos el shape de la respuesta (Pregunta 4c). Antes de este
    cambio se enviaba "scanner_ids" (ya no tiene sentido: no hay
    scanners en el universo nuevo). Se cambia a "tickers" porque es la
    lectura obvia dado el universo nuevo, pero es una SUPOSICIÓN, no una
    cita literal — confirmar contra el cuerpo real de scan_batch() antes
    del --dry-run (mismo tipo de hueco que ya causó el error de
    risk_pct/risk_per_share).

  - construir_payload_snapshot(): el campo real es risk_per_share, no
    risk_pct (confirmado contra SnapshotCreateRequest literal).
    entry_price/stop_price sí coincidían. Ninguno de los tres aparece en
    el shape de evaluate_ticker_logic.evaluate_ticker() (confirmado
    leyendo su código: solo produce score/verdict/factors por
    estrategia) — de dónde salen exactamente sigue sin resolver, ver
    GAP REAL más abajo.

  - detect_auto_trigger(): ya no hay una reimplementación local en este
    archivo. Se usa evaluate_ticker_logic.detect_auto_trigger(), que ya
    tiene la prioridad estricta correcta (AUTO_MULTI antes que
    AUTO_HIGH, con corte) y pruebas unitarias dedicadas — mantener una
    segunda copia aquí es exactamente lo que ya introdujo el bug de
    unión de ramas una vez.

PASO 3 (04/10/2026): evaluate_ticker() YA LLAMA a POST /api/evaluate-ticker —
pero ese endpoint TODAVÍA NO EXISTE en market_data_proxy.py real.

  Lado cliente (este archivo): cableado. evaluate_ticker() hace el POST
  real con el shape que espera evaluate_ticker_logic.evaluate_ticker()
  (ticker/mode/ind/funda/settings/btc_gate_on/insider_summary) y devuelve
  la respuesta directamente — ya no es un NotImplementedError.

  Lado servidor: el código del endpoint está escrito y listo en
  services/snapshot-autocapture/evaluate_ticker_endpoint.py (import de
  evaluate_ticker_logic, modelo Pydantic, cuerpo del handler), pero NO
  está aplicado a market_data_proxy.py — esta sesión nunca ha visto ese
  archivo completo (no está en git, BACKLOG entrada 3; solo fragmentos
  por "Pregunta N" de check_autocapture_triggers.sh), así que no se
  inventa el decorador/imports reales. Pendiente de la Pregunta 6
  (añadida a ese script: imports+app de la cabecera, decorador real de
  create_snapshot/scan_batch, y los modelos Pydantic — para ajustar el
  endpoint al estilo real antes de pegarlo).

  Hasta que el endpoint exista en el servidor real, correr este script
  contra el proxy real falla con 404 en evaluate_ticker() — ruidoso,
  a propósito, no silenciado.

  Tres puntos quedan explícitamente SIN CONFIRMAR, señalados también en
  evaluate_ticker_endpoint.py y en la Pregunta 6:

  1. SETTINGS de abajo (priceMin/atrMax/rvolMin) — valores de ejemplo,
     NO los reales de producción. tickerHardNo()/los 10 evalXX dependen
     de ellos directamente (p.ej. decide HARD_NO). Pregunta 6d busca de
     dónde salen los reales (state.settings en el navegador, o quizá
     09_PARAMETROS/12_CONFIGURACION en Sheets).
  2. fetch_scan_batch() sigue enviando "tickers" como suposición (no
     confirmado contra el Pydantic real — Pregunta 6c lo repite porque
     la salida original de la Pregunta 4a se perdió al resumir el
     contexto, nunca se comitió a un archivo).
  3. construir_payload_snapshot(): de dónde salen entry_price/
     stop_price/risk_per_share sigue sin resolver — no están en el
     shape de evaluate_ticker_logic.evaluate_ticker() (confirmado
     leyendo su código: solo produce score/verdict/factors). Se leen
     con .get() de `evaluation` a propósito, para fallar visible
     (None) en vez de fingir un valor, hasta que se resuelva esto.

Protocolo antes de instalar el timer (no aplicable todavía, ver arriba):
  1. Ejecutar la Pregunta 6 de check_autocapture_triggers.sh contra el
     servidor real y pegar/comitir la salida.
  2. Aplicar evaluate_ticker_endpoint.py a market_data_proxy.py con el
     decorador/imports reales confirmados en 6a/6b.
  3. Corregir SETTINGS de abajo con los valores reales (6d) y el campo
     de fetch_scan_batch() si "tickers" no es el real (6c).
  4. Resolver el origen de entry_price/stop_price/risk_per_share.
  5. Ejecutar con --dry-run contra el proxy real y revisar el log.
  6. Ejecutar una vez sin --dry-run con --force-window fuera de la franja
     de los timers del evaluador, con un ticker de prueba (ZZTEST), y
     confirmar la respuesta antes de instalar el timer.
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import gspread
import requests

import evaluate_ticker_logic as etl
import indicator_calc

# --- Configuración ---------------------------------------------------------

PROXY_BASE = os.environ.get("AXONIK_PROXY_BASE", "http://127.0.0.1:8002")
GOOGLE_CREDENTIALS_PATH = os.environ.get(
    "AXONIK_GOOGLE_CREDENTIALS", "/opt/axonik/scripts/credentials.json"
)
DECISION_ENGINE_SHEET_ID = os.environ.get("AXONIK_DECISION_ENGINE_SHEET_ID")
UNIVERSE_WORKSHEET = "14_UNIVERSO_TICKERS"

# Decisión cerrada (diseño §1.9): hoja 14_UNIVERSO_TICKERS, ESTADO=ACTIVO.
# Ya no se lee 02_SCANNERS ni localStorage para este propósito.
ACTIVE_STATES = {"ACTIVO"}
# Ventana operativa: regla dura, no un valor por defecto (instrucción explícita
# del usuario: nada fuera de 16:00-18:00 Madrid sin que lo decida él).
OPERATING_WINDOW = (16, 18)  # [16:00, 18:00) Europe/Madrid
OPERATING_WEEKDAYS = {0, 1, 2, 3, 4}  # datetime.weekday(): lunes=0 ... viernes=4
# Cripto excluido por ahora, a propósito: la ventana 16:00-18:00 Madrid está
# atada a la apertura de NYSE, no a cripto (24/7). Decisión aparte si se quiere
# ampliar, no asumida aquí. Usado solo por cargar_universo_de_tickers() (rama
# NYSE) -- la rama CRYPTO usa cargar_universo_cripto(), que hace lo inverso
# (solo MERCADO=CRYPTO), ver más abajo.
EXCLUDED_MARKETS = {"CRYPTO"}

# --- Rama CRIPTO (06/10/2026) ------------------------------------------------
#
# BTC/ETH/SOL siguen con ESTADO!=ACTIVO en 14_UNIVERSO_TICKERS a propósito
# (instrucción explícita del usuario) hasta que
# docs/pipeline/verificar_cripto.sh pase contra el servidor real --
# cargar_universo_cripto() ya los filtraría igual que a cualquier otro
# ticker inactivo, así que no hace falta ningún guard adicional aquí: el
# guard real vive en la hoja, no en este código.
#
# BINANCE_BASE: CONFIRMADO (Pregunta 11, 07/10/2026,
# docs/pipeline/pregunta11_salida.txt línea 1428):
# "const BINANCE_BASE = 'https://data-api.binance.vision';" -- NO es
# api.binance.com (el dominio público "normal"), es el subdominio de solo
# datos de mercado de Binance. Overridable sin tocar código vía
# AXONIK_BINANCE_BASE si hiciera falta (p.ej. un proxy propio).
BINANCE_BASE = os.environ.get("AXONIK_BINANCE_BASE", "https://data-api.binance.vision")
# Límites de velas por timeframe: CONFIRMADOS contra fetchCryptoTicker()
# (Pregunta 9/10) -- 120/100/96, distintos de los de NYSE (que no fija un
# "limit" explícito, scan-batch decide cuántas velas devuelve).
BINANCE_KLINE_LIMITS = {"1d": 120, "1h": 100, "15m": 96}
# fetchBinanceKlines(symbol, interval, limit, retries): retries==null?2:retries
# -- 2 reintentos (3 intentos en total), 800ms entre cada uno. Literal.
BINANCE_RETRIES = 2
BINANCE_RETRY_SLEEP_SECONDS = 0.8

# CONFIRMADO (Pregunta 6d, docs/pipeline/pregunta6_salida.txt línea 1026):
# DEFAULT_SETTINGS real del navegador es {capital:10000, riskPct:0.5,
# priceMin:8, atrMax:4, rvolMin:1} — el placeholder anterior tenía
# atrMax=6, que era INCORRECTO (el real es 4), corregido aquí. Nota: son
# los valores por defecto del navegador, editables en su UI
# (settingMap en index.html línea 2480) y persistidos solo en el
# localStorage de cada navegador — si el usuario los cambió a mano ahí,
# esta automatización seguirá usando los defaults, no lo que vea en su
# sesión. No hay una fuente server-side única de esto hoy.
SETTINGS = {
    "priceMin": float(os.environ.get("AXONIK_SETTINGS_PRICE_MIN", 8)),
    "atrMax": float(os.environ.get("AXONIK_SETTINGS_ATR_MAX", 4)),
    "rvolMin": float(os.environ.get("AXONIK_SETTINGS_RVOL_MIN", 1)),
}

LOG_PATH = Path(os.environ.get("AXONIK_AUTOCAPTURE_LOG", "/var/log/axonik/snapshot_autocapture.log"))


def _setup_logging() -> logging.Logger:
    handlers: list[logging.Handler] = [logging.StreamHandler()]
    try:
        LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        handlers.append(logging.FileHandler(LOG_PATH))
    except OSError as exc:
        print(f"aviso: no se pudo abrir {LOG_PATH} ({exc}) — solo se registra en stdout/journal",
              file=sys.stderr)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s",
                         handlers=handlers)
    return logging.getLogger("snapshot_autocapture")


log = _setup_logging()


@dataclass(frozen=True)
class TickerUniverseEntry:
    """Una fila de 14_UNIVERSO_TICKERS (diseño §1.9)."""
    ticker: str
    mercado: str  # NYSE | CRYPTO — mismo valor que evaluate_ticker_logic mode
    estado: str
    fecha_alta: str
    notas: str


def within_operating_window(now_madrid: datetime) -> bool:
    """[16:00, 18:00) Europe/Madrid, lunes a viernes. Regla dura."""
    if now_madrid.weekday() not in OPERATING_WEEKDAYS:
        return False
    start_hour, end_hour = OPERATING_WINDOW
    return start_hour <= now_madrid.hour < end_hour


def _leer_filas_universo() -> list[dict]:
    """Conexión + lectura en bruto de 14_UNIVERSO_TICKERS, compartida por
    cargar_universo_de_tickers() (NYSE) y cargar_universo_cripto()."""
    if not DECISION_ENGINE_SHEET_ID:
        raise RuntimeError("Falta AXONIK_DECISION_ENGINE_SHEET_ID en el entorno.")

    gc = gspread.service_account(filename=GOOGLE_CREDENTIALS_PATH)
    sh = gc.open_by_key(DECISION_ENGINE_SHEET_ID)
    ws = sh.worksheet(UNIVERSE_WORKSHEET)
    return ws.get_all_records()


def cargar_universo_de_tickers() -> list[TickerUniverseEntry]:
    """
    Diseño §1.9: hoja 14_UNIVERSO_TICKERS, filtrando ESTADO='ACTIVO', vía
    gspread (misma librería y credenciales que ya usa snapshot_evaluator.py)
    — no localStorage de ningún navegador, no 02_SCANNERS.
    Excluye además los de mercado CRYPTO (ver EXCLUDED_MARKETS) -- rama
    NYSE, gated por la ventana operativa 16:00-18:00 Madrid.
    """
    universo = []
    for row in _leer_filas_universo():
        estado = str(row.get("ESTADO") or "").strip().upper()
        mercado = str(row.get("MERCADO") or "").strip().upper()
        ticker = str(row.get("TICKER") or "").strip()
        if not ticker or estado not in ACTIVE_STATES:
            continue
        if mercado in EXCLUDED_MARKETS:
            log.info(f"ticker {ticker} excluido de esta ventana: mercado={mercado}")
            continue
        universo.append(TickerUniverseEntry(
            ticker=ticker,
            mercado=mercado,
            estado=estado,
            fecha_alta=str(row.get("FECHA_ALTA", "")),
            notas=str(row.get("NOTAS", "")),
        ))
    return universo


def cargar_universo_cripto() -> list[TickerUniverseEntry]:
    """
    Igual que cargar_universo_de_tickers() pero al revés: solo
    MERCADO='CRYPTO' con ESTADO='ACTIVO' -- rama 24/7, sin ventana
    operativa (BTC/ETH/SOL cotizan todo el día, no solo en horario NYSE).

    BTC/ETH/SOL siguen con ESTADO!=ACTIVO en la hoja real a propósito
    (instrucción explícita del usuario, 06/10/2026) hasta que
    docs/pipeline/verificar_cripto.sh pase -- esta función ya los
    excluirá igual que a cualquier ticker inactivo, sin ningún guard
    adicional en código. No es responsabilidad de este script decidir
    cuándo activarlos; solo lee lo que diga la hoja.
    """
    universo = []
    for row in _leer_filas_universo():
        estado = str(row.get("ESTADO") or "").strip().upper()
        mercado = str(row.get("MERCADO") or "").strip().upper()
        ticker = str(row.get("TICKER") or "").strip()
        if not ticker or estado not in ACTIVE_STATES or mercado != "CRYPTO":
            continue
        universo.append(TickerUniverseEntry(
            ticker=ticker,
            mercado=mercado,
            estado=estado,
            fecha_alta=str(row.get("FECHA_ALTA", "")),
            notas=str(row.get("NOTAS", "")),
        ))
    return universo


def fetch_scan_batch(universo: list[TickerUniverseEntry]) -> dict:
    """
    Shape de RESPUESTA confirmado (Pregunta 4): {"results": [{"ticker",
    "timestamp", "data", "error"?}]}. El manejo de "error" por-entrada es
    responsabilidad del llamador (main()), no de esta función.

    Shape de PETICIÓN: "tickers" es una suposición (ver cabecera del
    archivo), no una cita literal del Pydantic real de scan_batch() —
    confirmar antes de usar esto contra el proxy real.
    """
    resp = requests.post(
        f"{PROXY_BASE}/api/scan-batch",
        json={"tickers": [u.ticker for u in universo]},
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json()


def fetch_binance_klines(symbol: str, interval: str, limit: int) -> list[dict]:
    """
    Pieza: fetchBinanceKlines() (línea 1338 del navegador, Pregunta 9) --
    puerto literal, no una reimplementación con otra forma de pedir velas.
    GET {BINANCE_BASE}/api/v3/klines?symbol=...&interval=...&limit=...;
    reintentos: retries==null?2:retries -- 2 reintentos (3 intentos en
    total), 800ms entre cada uno (BINANCE_RETRIES/BINANCE_RETRY_SLEEP_SECONDS).
    Mapea cada vela [t_ms,o,h,l,c,v,...] de Binance a {t:floor(t_ms/1000),
    o,h,l,c,v} -- mismo shape que usa indicator_calc.compute_indicators()
    para NYSE, sin bifurcar el cálculo por mercado.

    BINANCE_BASE sigue sin confirmar contra el texto literal (ver
    docs/pipeline/BLOQUEOS.md) -- usa el dominio público estándar de
    Binance como valor por defecto, documentado como supuesto.
    """
    last_err: Exception | None = None
    for attempt in range(BINANCE_RETRIES + 1):
        try:
            resp = requests.get(
                f"{BINANCE_BASE}/api/v3/klines",
                params={"symbol": symbol, "interval": interval, "limit": limit},
                timeout=10,
            )
            resp.raise_for_status()
            raw = resp.json()
            return [
                {"t": int(k[0] // 1000), "o": float(k[1]), "h": float(k[2]),
                 "l": float(k[3]), "c": float(k[4]), "v": float(k[5])}
                for k in raw
            ]
        except Exception as exc:  # noqa: BLE001 -- igual que el catch(e) real, reintenta cualquier fallo
            last_err = exc
            if attempt < BINANCE_RETRIES:
                time.sleep(BINANCE_RETRY_SLEEP_SECONDS)
    raise last_err  # type: ignore[misc]


def fetch_crypto_candles(ticker: str) -> dict:
    """
    Pieza: fetchCryptoTicker() (línea 1356, Pregunta 9) -- símbolo
    `{ticker}USDT`, 1d/1h/15m con los límites confirmados
    (BINANCE_KLINE_LIMITS: 120/100/96). A diferencia del navegador (que
    llama a computeIndicators() aquí mismo), esta función solo devuelve
    las velas en bruto con el mismo shape que "data" de scan_batch()
    ({"1d":{"candles":[...],"periods":N}, ...}) -- el cálculo de "ind"
    sigue pasando siempre por build_ind()/evaluate_ticker_endpoint.py del
    lado servidor (single source of truth, misma decisión de arquitectura
    que la rama NYSE, no una segunda ruta de cálculo para cripto).
    """
    symbol = f"{ticker}USDT"
    data = {}
    for tf, limit in BINANCE_KLINE_LIMITS.items():
        candles = fetch_binance_klines(symbol, tf, limit)
        data[tf] = {"candles": candles, "periods": len(candles)}
    return data


def compute_btc_gate() -> bool:
    """
    Pieza: computeMarketContext() (línea 1384 del navegador, Pregunta 11
    -- texto literal confirmado 07/10/2026,
    docs/pipeline/pregunta11_salida.txt). Puerto de la rama 'CRYPTO' de
    esa función (la única que usa este script -- la rama 'NYSE' real usa
    SPY, fuera de alcance aquí):

        const ind = await fetchCryptoTicker('BTC');
        const d = ind['1d'];
        if (!d) return null;
        return {... gateOn: d.price > d.ema50, ...};

    gateOn = BTC.price > BTC.ema50 (1D) -- "BTC por debajo de su EMA50
    diaria apaga el gate", confirmado contra el texto real, no una
    interpretación. Solo pide las velas 1D de BTC (computeMarketContext
    real solo lee ind['1d'], nunca 1h/15m) -- evita 2 llamadas de
    Binance innecesarias por ejecución, que síno se usarían para nada.

    Si algo falla (BTC sin datos, excepción de red): devuelve False --
    mismo `catch(e){ return null }` -> `state.marketContext` falsy ->
    `btcGateOn = false` del JS real (runScan()), no una rama nueva.
    """
    try:
        candles = fetch_binance_klines("BTCUSDT", "1d", BINANCE_KLINE_LIMITS["1d"])
        d = indicator_calc.compute_indicators(candles, "1d")
        if not d:
            return False
        return bool(d["price"] > d["ema50"])
    except Exception:
        log.exception("compute_btc_gate(): fallo al calcular el gate BTC real -- se trata como "
                       "OFF, igual que el catch(e){return null} del JS real.")
        return False


def evaluate_ticker(ticker: str, data: dict, mercado: str, btc_gate_on: bool = False) -> dict:
    """
    Llama a POST /api/evaluate-ticker (decisión de arquitectura
    04/10/2026, actualizada 05/10/2026: el endpoint recibe `candles` en
    bruto -- el "data" tal cual lo devuelve /api/scan-batch -- y calcula
    "ind" él mismo con build_ind()/indicator_calc.py, single source of
    truth server-side. Este script ya NO envía "ind" (ese era
    precisamente el bug que reveló el primer KeyError 'price' de la
    verificación navegador-vs-endpoint: `data` son candles en bruto,
    nunca indicadores ya calculados).

    GAP REAL que sigue abierto, no resuelto por este cambio: el endpoint
    todavía no existe en market_data_proxy.py (ver evaluate_ticker_endpoint.py)
    — esta llamada falla con 404 contra el proxy real hasta que se
    aplique. `funda`/`insider_summary` van como None a propósito: no se
    porta aquí /api/fundamentals-batch ni una fuente de insider score,
    fuera del alcance de este paso — con funda=None, ST-11 sale N/A y
    ST-01 pierde sus 2 puntos de bonus de fundamentales, nada más
    (evaluate_ticker_logic ya lo maneja sin fallar).

    `btc_gate_on` (06/10/2026): antes hardcodeado a False porque CRYPTO
    estaba excluido de toda ejecución (EXCLUDED_MARKETS) y el flag nunca
    se usaba. Con la rama cripto (main(), --market crypto) sí se usa de
    verdad -- viene de compute_btc_gate() (sustituto temporal de
    computeMarketContext(), ver docs/pipeline/BLOQUEOS.md). La rama NYSE
    sigue llamando a esto con btc_gate_on=False explícito (mode='NYSE'
    nunca lo consulta, pero se pasa a propósito en vez de dejarlo
    implícito en el default).
    """
    resp = requests.post(
        f"{PROXY_BASE}/api/evaluate-ticker",
        json={
            "ticker": ticker,
            "mode": mercado,
            "candles": data,
            "funda": None,
            "settings": SETTINGS,
            "btc_gate_on": btc_gate_on,
            "insider_summary": None,
        },
        timeout=15,
    )
    resp.raise_for_status()
    # NaN no es JSON válido -- el endpoint lo sirve como el string
    # sentinela "NaN" (etl.nan_to_json_sentinel, ver
    # evaluate_ticker_endpoint.py; probado contra una app FastAPI real).
    # sentinel_to_nan() es la conversión inversa, misma función que usan
    # las pruebas -- no una segunda implementación de esto.
    return etl.sentinel_to_nan(resp.json())


def construir_payload_snapshot(ticker: str, evaluation: dict, trigger: dict,
                                market: str, data_ts: str, snapshot_ts: str) -> dict:
    """
    ticker/market/strategies/data_ts/snapshot_ts/temporal_group:
    CONFIRMADOS (DOC-IDEM Addendum 3 y 4). entry_price/stop_price:
    CONFIRMADOS contra SnapshotCreateRequest (Pregunta 4). risk_per_share:
    CORREGIDO — el campo real no es risk_pct.

    entry_price/stop_price/risk_per_share NO están en el shape de
    evaluate_ticker_logic.evaluate_ticker() (confirmado leyendo su
    código — solo produce score/verdict/factors) — de dónde salen sigue
    sin resolver, pendiente junto con el cableado del endpoint. Se leen
    aquí de `evaluation` con .get() a propósito, para que esto falle con
    un KeyError/None visible en vez de fingir un valor, hasta que se
    resuelva ese gap.
    """
    primary = trigger["strategies"][0]
    return {
        "ticker": ticker,
        "market": market.lower(),
        "data_ts": data_ts,
        "snapshot_ts": snapshot_ts,
        "temporal_group": primary["group"],
        "strategies": [{"id": s["id"]} for s in trigger["strategies"]],
        "entry_price": evaluation.get("entry_price"),
        "stop_price": evaluation.get("stop_price"),
        "risk_per_share": evaluation.get("risk_per_share"),
    }


def capture_signal(payload: dict, dry_run: bool) -> bool:
    if dry_run:
        log.info(f"[DRY RUN] POST /api/snapshots {json.dumps(payload, ensure_ascii=False)}")
        return False

    resp = requests.post(f"{PROXY_BASE}/api/snapshots", json=payload, timeout=10)
    resp.raise_for_status()
    body = resp.json()
    created = bool(body.get("created"))
    if created:
        log.info(f"capturado: {payload['ticker']} / {payload['strategies']} (id={body.get('id')})")
    # created:false ya queda registrado por el propio proxy
    # ("snapshot duplicado suprimido", Hallazgo 1 de DOC-IDEM) — no duplicar ese log aquí.
    return created


def _evaluar_y_capturar(ticker: str, data: dict, mercado: str, btc_gate_on: bool,
                         data_ts: str, snapshot_ts: str, dry_run: bool) -> bool:
    """
    Núcleo compartido por la rama NYSE y la rama CRYPTO de main(): evalúa
    un ticker ya con sus velas en mano, detecta el trigger y captura si
    corresponde. Devuelve True si se capturó una señal nueva (no
    duplicada). No atrapa la excepción de evaluate_ticker() -- debe fallar
    ruidoso y parar la corrida, no silenciarse ticker a ticker.

    DESVIACIÓN CONSCIENTE respecto al JS del scanner (07/10/2026, decisión
    explícita del usuario): con el gate BTC OFF, la CAPTURA bloquea TODOS
    los longs cripto, incluidos los de SC-01 -- aunque evalSC01() (el JS
    real, confirmado literal) NO comprueba btcGateOn en absoluto (a
    diferencia de SC-02/SC-PB, que sí la tienen incorporada vía mkNA()).
    Regla del proyecto: BTC por debajo de su EMA50 diaria = cero longs
    cripto, sin excepción -- la captura automática es deliberadamente más
    estricta que lo que muestra el scanner (que sigue enseñando el score
    de SC-01 igual, gate o no gate: esto NUNCA toca evaluate_ticker_logic.py,
    que debe seguir siendo un puerto fiel del JS para que el oráculo de
    verificar_cripto.sh siga comparando lo mismo que el navegador). Ver
    docs/pipeline/BACKLOG.md.
    """
    evaluation = evaluate_ticker(ticker, data, mercado, btc_gate_on=btc_gate_on)

    trigger = etl.detect_auto_trigger(evaluation)
    if not trigger:
        return False

    if mercado == "CRYPTO" and not btc_gate_on:
        log.info(f"{ticker}: trigger {trigger['type']} descartado en la captura -- gate BTC OFF "
                 f"bloquea todos los longs cripto (regla del proyecto, más estricta que el JS del "
                 f"scanner -- evalSC01 no exige el gate, pero la captura sí lo aplica aquí).")
        return False

    payload = construir_payload_snapshot(
        ticker, evaluation, trigger, market=mercado,
        data_ts=data_ts, snapshot_ts=snapshot_ts,
    )
    try:
        return capture_signal(payload, dry_run=dry_run)
    except Exception:
        log.exception(f"Fallo al capturar {ticker} / {trigger['type']} — se sigue con el resto del lote.")
        return False


def _ejecutar_nyse(args: argparse.Namespace, now: datetime) -> int:
    """Rama NYSE: gated por la ventana operativa 16:00-18:00 Madrid L-V,
    velas vía /api/scan-batch, btc_gate_on=False explícito (mode='NYSE'
    nunca lo consulta)."""
    if not within_operating_window(now) and not args.force_window:
        log.info(f"Fuera de la ventana operativa 16:00-18:00 Madrid L-V "
                 f"(ahora: {now.isoformat()}). No se captura nada.")
        return 0
    if args.force_window and not within_operating_window(now):
        log.warning(f"--force-window activo fuera de la ventana operativa ({now.isoformat()}) "
                    f"— uso de prueba, no debe ocurrir desde el timer.")

    try:
        universo = cargar_universo_de_tickers()
    except Exception:
        log.exception("No se pudo cargar el universo de tickers desde 14_UNIVERSO_TICKERS.")
        return 1

    log.info(f"Universo de tickers activos (NYSE): {[u.ticker for u in universo]}")
    if not universo:
        log.warning("Universo de tickers vacío — revisar 14_UNIVERSO_TICKERS antes de seguir.")
        return 0

    try:
        datos_mercado = fetch_scan_batch(universo)
    except Exception:
        log.exception("Fallo al llamar a /api/scan-batch.")
        return 1

    universo_por_ticker = {u.ticker: u for u in universo}
    snapshot_ts = now.astimezone(ZoneInfo("UTC")).isoformat()
    capturas = 0

    for item in datos_mercado.get("results", []):
        ticker = item.get("ticker")
        if item.get("error"):
            log.warning(f"scan-batch devolvió error para {ticker}: {item['error']} — se omite "
                        f"(no es un fallo del batch completo).")
            continue

        entry = universo_por_ticker.get(ticker)
        if entry is None:
            log.warning(f"scan-batch devolvió un ticker fuera del universo pedido: {ticker} — se omite.")
            continue

        data = item.get("data") or {}
        if _evaluar_y_capturar(ticker, data, entry.mercado, btc_gate_on=False,
                                data_ts=item.get("timestamp"), snapshot_ts=snapshot_ts,
                                dry_run=args.dry_run):
            capturas += 1

    log.info(f"Fin de la corrida NYSE. Señales capturadas: {capturas}.")
    return 0


def _ejecutar_cripto(args: argparse.Namespace, now: datetime) -> int:
    """
    Rama CRYPTO: 24/7, SIN ventana operativa (BTC/ETH/SOL cotizan todo el
    día -- la ventana 16:00-18:00 Madrid está atada a NYSE, no a esto,
    --force-window no aplica ni se consulta aquí). Velas vía Binance
    directo (fetch_crypto_candles(), no /api/scan-batch -- esa ruta es
    NYSE-only, confirmado: fetchCryptoTicker() del navegador nunca llama a
    scan-batch, pide Binance directo). Gate BTC real vía compute_btc_gate()
    -- hoy un sustituto que siempre da False (ver su docstring y
    docs/pipeline/BLOQUEOS.md) hasta que computeMarketContext() se porte.
    """
    try:
        universo = cargar_universo_cripto()
    except Exception:
        log.exception("No se pudo cargar el universo cripto desde 14_UNIVERSO_TICKERS.")
        return 1

    log.info(f"Universo de tickers activos (CRYPTO): {[u.ticker for u in universo]}")
    if not universo:
        log.warning("Universo cripto vacío — BTC/ETH/SOL siguen sin ESTADO=ACTIVO en "
                    "14_UNIVERSO_TICKERS (esperado hasta que verificar_cripto.sh pase). "
                    "No se captura nada.")
        return 0

    btc_gate_on = compute_btc_gate()
    log.info(f"Gate BTC: {'ON' if btc_gate_on else 'OFF'}")

    snapshot_ts = now.astimezone(ZoneInfo("UTC")).isoformat()
    data_ts = now.astimezone(ZoneInfo("UTC")).isoformat()
    capturas = 0

    for entry in universo:
        try:
            data = fetch_crypto_candles(entry.ticker)
        except Exception:
            log.exception(f"Fallo al pedir velas de Binance para {entry.ticker} — se omite "
                           f"(no es un fallo del resto del lote).")
            continue

        if _evaluar_y_capturar(entry.ticker, data, entry.mercado, btc_gate_on=btc_gate_on,
                                data_ts=data_ts, snapshot_ts=snapshot_ts,
                                dry_run=args.dry_run):
            capturas += 1

    log.info(f"Fin de la corrida CRYPTO. Señales capturadas: {capturas}.")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                      formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--market", choices=["nyse", "crypto"], default="nyse",
                         help="Rama a ejecutar (default: nyse, mismo comportamiento que antes "
                              "de añadir la rama cripto -- el timer NYSE existente no cambia).")
    parser.add_argument("--dry-run", action="store_true",
                         help="No hace ningún POST real — solo registra qué habría enviado.")
    parser.add_argument("--force-window", action="store_true",
                         help="Ignora el guard de ventana operativa. Solo para pruebas manuales "
                              "deliberadas — nunca activarlo en el timer de systemd. Sin efecto "
                              "en --market crypto (esa rama no tiene ventana).")
    args = parser.parse_args()

    now = datetime.now(ZoneInfo("Europe/Madrid"))
    if args.market == "crypto":
        return _ejecutar_cripto(args, now)
    return _ejecutar_nyse(args, now)


if __name__ == "__main__":
    sys.exit(main())
