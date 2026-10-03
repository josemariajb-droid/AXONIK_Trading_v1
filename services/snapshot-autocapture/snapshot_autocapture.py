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

GAP REAL (sin cambios por este paso, sigue bloqueando la producción real):

  El cálculo del score en sí (evaluateTicker() + NYSE_STRATEGIES +
  CRYPTO_STRATEGIES + applyEventAdjustments + tickerHardNo) está portado
  en evaluate_ticker_logic.py (22 piezas, con pruebas), pero TODAVÍA NO
  está expuesto como POST /api/evaluate-ticker en market_data_proxy.py
  (decisión de arquitectura 04/10/2026: single source of truth
  server-side, no duplicar aquí). evaluate_ticker() de abajo sigue
  siendo un NotImplementedError explícito hasta que ese endpoint exista
  y se cablee la llamada real — no se inventa esa lógica aquí.

  Tampoco está resuelto de dónde salen entry_price/stop_price/
  risk_per_share para construir_payload_snapshot() — no están en el
  shape de evaluate_ticker_logic.evaluate_ticker() (confirmado arriba).
  Pendiente junto con el cableado del endpoint.

Protocolo antes de instalar el timer (no aplicable todavía, ver el gap de
arriba):
  1. Cablear POST /api/evaluate-ticker en market_data_proxy.py con
     evaluate_ticker_logic.py, y resolver el origen de
     entry_price/stop_price/risk_per_share.
  2. Confirmar el shape de petición real de scan_batch() (campo
     "tickers" es una suposición, no una cita literal — ver arriba).
  3. Ejecutar con --dry-run contra el proxy real y revisar el log.
  4. Ejecutar una vez sin --dry-run con --force-window fuera de la franja
     de los timers del evaluador, con un ticker de prueba (ZZTEST), y
     confirmar la respuesta antes de instalar el timer.
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import gspread
import requests

import evaluate_ticker_logic as etl

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
# ampliar, no asumida aquí.
EXCLUDED_MARKETS = {"CRYPTO"}

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


def cargar_universo_de_tickers() -> list[TickerUniverseEntry]:
    """
    Diseño §1.9: hoja 14_UNIVERSO_TICKERS, filtrando ESTADO='ACTIVO', vía
    gspread (misma librería y credenciales que ya usa snapshot_evaluator.py)
    — no localStorage de ningún navegador, no 02_SCANNERS.
    Excluye además los de mercado CRYPTO (ver EXCLUDED_MARKETS).
    """
    if not DECISION_ENGINE_SHEET_ID:
        raise RuntimeError("Falta AXONIK_DECISION_ENGINE_SHEET_ID en el entorno.")

    gc = gspread.service_account(filename=GOOGLE_CREDENTIALS_PATH)
    sh = gc.open_by_key(DECISION_ENGINE_SHEET_ID)
    ws = sh.worksheet(UNIVERSE_WORKSHEET)
    rows = ws.get_all_records()

    universo = []
    for row in rows:
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


def evaluate_ticker(ticker: str, data: dict, mercado: str) -> dict:
    """
    NO IMPLEMENTADO — GAP REAL, no un valor por defecto.

    Pendiente de cablear como llamada a POST /api/evaluate-ticker en
    market_data_proxy.py (decisión de arquitectura 04/10/2026: single
    source of truth server-side con evaluate_ticker_logic.py, no una
    segunda copia en este script). El shape de retorno esperado, una vez
    cableado, es el de evaluate_ticker_logic.evaluate_ticker(): un dict
    con "strategies" (lista completa de las 7 NYSE o 3 crypto fijas por
    `mercado`), "hardNo", "globalVerdict" — listo para pasar directo a
    evaluate_ticker_logic.detect_auto_trigger().
    """
    raise NotImplementedError(
        f"evaluate_ticker({ticker!r}, mercado={mercado!r}): falta cablear "
        f"POST /api/evaluate-ticker. Ver docstring y cabecera del archivo."
    )


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


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                      formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--dry-run", action="store_true",
                         help="No hace ningún POST real — solo registra qué habría enviado.")
    parser.add_argument("--force-window", action="store_true",
                         help="Ignora el guard de ventana operativa. Solo para pruebas manuales "
                              "deliberadas — nunca activarlo en el timer de systemd.")
    args = parser.parse_args()

    now = datetime.now(ZoneInfo("Europe/Madrid"))
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

    log.info(f"Universo de tickers activos (no-crypto): {[u.ticker for u in universo]}")
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
        # evaluate_ticker() lanza NotImplementedError a propósito — ver
        # cabecera del archivo. No se captura aquí: debe fallar ruidoso,
        # no silenciarse ticker a ticker.
        evaluation = evaluate_ticker(ticker, data, entry.mercado)

        trigger = etl.detect_auto_trigger(evaluation)
        if not trigger:
            continue

        payload = construir_payload_snapshot(
            ticker, evaluation, trigger, market=entry.mercado,
            data_ts=item.get("timestamp"), snapshot_ts=snapshot_ts,
        )
        try:
            if capture_signal(payload, dry_run=args.dry_run):
                capturas += 1
        except Exception:
            log.exception(f"Fallo al capturar {ticker} / {trigger['type']} — se sigue con el resto del lote.")

    log.info(f"Fin de la corrida. Señales capturadas: {capturas}.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
