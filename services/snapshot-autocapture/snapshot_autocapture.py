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

ESTADO TRAS LA PREGUNTA 4 (confirmado contra el código real, no prosa):

  - fetch_scan_batch(): CORREGIDO. Shape real: {"results": [{"ticker",
    "timestamp", "data", "error"?}]}. "data" son indicadores EN BRUTO,
    no un score precalculado — la asunción anterior de este script
    (`ticker_data.get("score")`) era sencillamente incorrecta, no una
    aproximación válida. Los errores por-ticker vienen dentro del array
    ("error" por entrada), no como fallo global del batch — manejado
    en el bucle principal, no como excepción.

  - construir_payload_snapshot(): CORREGIDO. El campo real es
    risk_per_share, no risk_pct (confirmado contra SnapshotCreateRequest
    literal). entry_price/stop_price sí coincidían.

  - detect_auto_trigger(): CORREGIDO de un único umbral a las dos ramas
    reales — ver evaluate_auto_trigger() más abajo:
      AUTO_HIGH:  una sola estrategia con score >= 90 dispara por sí sola.
      AUTO_MULTI: >=2 estrategias del MISMO GRUPO con score >= 80 cada una
                  disparan juntas.
    "Mismo grupo" se interpreta aquí como mismo temporal_group (swing/
    intraday/medio) — es una LECTURA de la prosa del usuario sobre
    detectAutoTrigger(), no una cita literal de esa función. Dado que ya
    hubo un fallo real por fiarse de una paráfrasis (risk_pct vs.
    risk_per_share), esto debería confirmarse contra el código real antes
    de fiarse de esta agrupación en producción.

GAP REAL DESCUBIERTO AL CORREGIR LO ANTERIOR — no uno de los tres puntos
pedidos, pero lo que los tres puntos, juntos, dejan al descubierto:

  El cálculo del score en sí (evaluateTicker() + NYSE_STRATEGIES +
  CRYPTO_STRATEGIES + applyEventAdjustments + tickerHardNo) NUNCA se portó
  a Python. Solo se confirmó que esas cinco piezas son "limpias" (sin
  document./window./canvas/fetch interno) — nunca se transcribió su
  CONTENIDO. Este script dependía de que /api/scan-batch devolviera un
  "score" ya calculado; el shape real confirmado demuestra que no es así.

  Por eso evaluate_ticker() de abajo es un NotImplementedError explícito,
  no un valor por defecto razonable ni una aproximación. No se inventa
  esa lógica aquí. Para cerrarlo de verdad hacen falta los CUERPOS
  LITERALES de las cinco piezas (no un resumen en prosa — la lección de
  risk_per_share es exactamente esa: una paráfrasis ya introdujo un error
  real). Hasta que eso se porte, este script no puede ejecutarse en
  producción — fallará de forma ruidosa e inmediata en el primer ticker,
  a propósito, en vez de fingir un resultado.

Protocolo antes de instalar el timer (no aplicable todavía, ver el gap de
arriba):
  1. Portar evaluate_ticker() con los cuerpos literales de las 5 piezas.
  2. Confirmar la agrupación real de AUTO_MULTI ("mismo grupo").
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

# --- Configuración ---------------------------------------------------------

PROXY_BASE = os.environ.get("AXONIK_PROXY_BASE", "http://127.0.0.1:8002")
GOOGLE_CREDENTIALS_PATH = os.environ.get(
    "AXONIK_GOOGLE_CREDENTIALS", "/opt/axonik/scripts/credentials.json"
)
DECISION_ENGINE_SHEET_ID = os.environ.get("AXONIK_DECISION_ENGINE_SHEET_ID")
SCANNERS_WORKSHEET = "02_SCANNERS"

# Decisión cerrada (diseño §1.4): scanners EN_PRUEBAS/PRODUCCION, no localStorage.
ACTIVE_STATES = {"EN_PRUEBAS", "PRODUCCION"}
# Ventana operativa: regla dura, no un valor por defecto (instrucción explícita
# del usuario: nada fuera de 16:00-18:00 Madrid sin que lo decida él).
OPERATING_WINDOW = (16, 18)  # [16:00, 18:00) Europe/Madrid
OPERATING_WEEKDAYS = {0, 1, 2, 3, 4}  # datetime.weekday(): lunes=0 ... viernes=4
# Cripto excluido por ahora, a propósito: la ventana 16:00-18:00 Madrid está
# atada a la apertura de NYSE, no a cripto (24/7). Decisión aparte si se quiere
# ampliar, no asumida aquí.
EXCLUDED_MARKETS = {"CRYPTO"}

LOG_PATH = Path(os.environ.get("AXONIK_AUTOCAPTURE_LOG", "/var/log/axonik/snapshot_autocapture.log"))

# Confirmados contra el código real (no estimación): dos ramas, no un umbral único.
AUTO_HIGH_THRESHOLD = 90.0
AUTO_MULTI_THRESHOLD = 80.0
AUTO_MULTI_MIN_COUNT = 2


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
class ScannerDef:
    scn_id: str
    nombre: str
    mercado: str
    estado: str
    tipo_op: str


@dataclass(frozen=True)
class TickerEvaluation:
    """
    Lo que evaluateTicker() produce para un (ticker, scanner) concreto —
    todo lo que autoCaptureSnapshots() necesitaba para decidir y para
    construir el payload de captura.
    """
    scn_id: str
    score: float
    temporal_group: str
    entry_price: float
    stop_price: float
    risk_per_share: float


def within_operating_window(now_madrid: datetime) -> bool:
    """[16:00, 18:00) Europe/Madrid, lunes a viernes. Regla dura."""
    if now_madrid.weekday() not in OPERATING_WEEKDAYS:
        return False
    start_hour, end_hour = OPERATING_WINDOW
    return start_hour <= now_madrid.hour < end_hour


def cargar_universo_de_scanners() -> list[ScannerDef]:
    """
    CERRADO (diseño §1.4): scanners EN_PRUEBAS/PRODUCCION de 02_SCANNERS,
    leídos de Google Sheets vía gspread (misma librería que ya usa
    snapshot_evaluator.py) — no localStorage de ningún navegador.
    Excluye además los de mercado CRYPTO (ver EXCLUDED_MARKETS).
    """
    if not DECISION_ENGINE_SHEET_ID:
        raise RuntimeError("Falta AXONIK_DECISION_ENGINE_SHEET_ID en el entorno.")

    gc = gspread.service_account(filename=GOOGLE_CREDENTIALS_PATH)
    sh = gc.open_by_key(DECISION_ENGINE_SHEET_ID)
    ws = sh.worksheet(SCANNERS_WORKSHEET)
    rows = ws.get_all_records()

    universo = []
    for row in rows:
        estado = str(row.get("ESTADO") or "").strip()
        mercado = str(row.get("MERCADO") or "").strip().upper()
        if estado not in ACTIVE_STATES:
            continue
        if mercado in EXCLUDED_MARKETS:
            log.info(f"scanner {row.get('SCN_ID')} excluido de esta ventana: mercado={mercado}")
            continue
        universo.append(ScannerDef(
            scn_id=str(row.get("SCN_ID", "")),
            nombre=str(row.get("NOMBRE", "")),
            mercado=mercado,
            estado=estado,
            tipo_op=str(row.get("TIPO_OP", "")),
        ))
    return universo


def fetch_scan_batch(scanners: list[ScannerDef]) -> dict:
    """
    CORREGIDO (Pregunta 4): shape real {"results": [{"ticker",
    "timestamp", "data", "error"?}]}. El manejo de "error" por-entrada es
    responsabilidad del llamador (main()), no de esta función — un error
    en un ticker no es un fallo del batch completo.
    """
    resp = requests.post(
        f"{PROXY_BASE}/api/scan-batch",
        json={"scanner_ids": [s.scn_id for s in scanners]},
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json()


def evaluate_ticker(ticker: str, data: dict, scanner: ScannerDef) -> TickerEvaluation:
    """
    NO IMPLEMENTADO — GAP REAL, no un valor por defecto.

    Puerto de evaluateTicker() + NYSE_STRATEGIES/CRYPTO_STRATEGIES (según
    scanner.mercado) + applyEventAdjustments + tickerHardNo, para UN
    (ticker, scanner) concreto. Solo se confirmó que esas cinco piezas son
    aritmética/orquestación pura sobre `data` (sin navegador) — nunca se
    transcribió su contenido real.

    Para implementar esto de verdad: pegar aquí los cuerpos LITERALES de
    las cinco piezas (no un resumen en prosa — la paráfrasis de
    risk_pct/risk_per_share ya introdujo un error real una vez).
    """
    raise NotImplementedError(
        f"evaluate_ticker({ticker!r}, scanner={scanner.scn_id!r}): falta portar "
        f"evaluateTicker()/NYSE_STRATEGIES/CRYPTO_STRATEGIES/applyEventAdjustments/"
        f"tickerHardNo. Ver docstring y cabecera del archivo."
    )


def evaluate_auto_trigger(evaluations: dict[str, TickerEvaluation]) -> list[str]:
    """
    Puerto de detectAutoTrigger() — dos ramas confirmadas contra el
    código real (no un único umbral, como se asumía antes de la
    Pregunta 4):

      AUTO_HIGH:  cualquier estrategia individual con score >= 90
                  dispara por sí sola.
      AUTO_MULTI: >=2 estrategias del MISMO GRUPO (aquí: mismo
                  temporal_group — ver nota de "mismo grupo" en la
                  cabecera del archivo, es una lectura, no una cita
                  literal) con score >= 80 cada una disparan juntas.

    Devuelve la lista de scn_id que disparan (vacía si no dispara nada).
    Una estrategia puede aparecer por ambas ramas a la vez sin problema —
    se deduplica.
    """
    triggered: set[str] = set()

    for scn_id, ev in evaluations.items():
        if ev.score >= AUTO_HIGH_THRESHOLD:
            triggered.add(scn_id)

    by_group: dict[str, list[str]] = {}
    for scn_id, ev in evaluations.items():
        if ev.score >= AUTO_MULTI_THRESHOLD:
            by_group.setdefault(ev.temporal_group, []).append(scn_id)
    for scn_ids in by_group.values():
        if len(scn_ids) >= AUTO_MULTI_MIN_COUNT:
            triggered.update(scn_ids)

    return sorted(triggered)


def construir_payload_snapshot(ticker: str, primary: TickerEvaluation,
                                triggered_scn_ids: list[str], market: str,
                                data_ts: str, snapshot_ts: str) -> dict:
    """
    ticker/market/strategies/data_ts/snapshot_ts/temporal_group:
    CONFIRMADOS (DOC-IDEM Addendum 3 y 4). entry_price/stop_price:
    CONFIRMADOS contra SnapshotCreateRequest (Pregunta 4). risk_per_share:
    CORREGIDO — el campo real no es risk_pct.

    `primary` son los datos de entry/stop/risk de la primera estrategia
    disparada; asume que son iguales entre todas las estrategias
    disparadas sobre el mismo ticker/vela — sin confirmar explícitamente,
    pendiente junto con evaluate_ticker().
    """
    return {
        "ticker": ticker,
        "market": market.lower(),
        "data_ts": data_ts,
        "snapshot_ts": snapshot_ts,
        "temporal_group": primary.temporal_group,
        "strategies": [{"id": scn_id} for scn_id in triggered_scn_ids],
        "entry_price": primary.entry_price,
        "stop_price": primary.stop_price,
        "risk_per_share": primary.risk_per_share,
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
        scanners = cargar_universo_de_scanners()
    except Exception:
        log.exception("No se pudo cargar el universo de scanners desde 02_SCANNERS.")
        return 1

    log.info(f"Universo de scanners activos (EN_PRUEBAS/PRODUCCION, no-crypto): "
             f"{[s.scn_id for s in scanners]}")
    if not scanners:
        log.warning("Universo de scanners vacío — revisar 02_SCANNERS antes de seguir.")
        return 0

    try:
        datos_mercado = fetch_scan_batch(scanners)
    except Exception:
        log.exception("Fallo al llamar a /api/scan-batch.")
        return 1

    snapshot_ts = now.astimezone(ZoneInfo("UTC")).isoformat()
    capturas = 0

    for item in datos_mercado.get("results", []):
        ticker = item.get("ticker")
        if item.get("error"):
            log.warning(f"scan-batch devolvió error para {ticker}: {item['error']} — se omite "
                        f"(no es un fallo del batch completo).")
            continue

        data = item.get("data") or {}
        # evaluate_ticker() lanza NotImplementedError a propósito — ver
        # cabecera del archivo. No se captura aquí: debe fallar ruidoso,
        # no silenciarse ticker a ticker.
        evaluations = {
            scanner.scn_id: evaluate_ticker(ticker, data, scanner)
            for scanner in scanners
        }

        triggered = evaluate_auto_trigger(evaluations)
        if not triggered:
            continue

        primary = evaluations[triggered[0]]
        scanner_mercado = next(s.mercado for s in scanners if s.scn_id == triggered[0])
        payload = construir_payload_snapshot(
            ticker, primary, triggered, market=scanner_mercado,
            data_ts=item.get("timestamp"), snapshot_ts=snapshot_ts,
        )
        try:
            if capture_signal(payload, dry_run=args.dry_run):
                capturas += 1
        except Exception:
            log.exception(f"Fallo al capturar {ticker} / {triggered} — se sigue con el resto del lote.")

    log.info(f"Fin de la corrida. Señales capturadas: {capturas}.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
