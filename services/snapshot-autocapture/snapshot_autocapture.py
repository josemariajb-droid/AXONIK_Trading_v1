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

ANTES DE ACTIVAR EL TIMER EN PRODUCCIÓN — tres puntos siguen siendo la
mejor estimación a partir de la documentación existente, NO una lectura
literal del código, y hay que cerrarlos con la misma disciplina que el
resto de este diseño (ver docs/pipeline/check_autocapture_triggers.sh,
sección "Pregunta 4"):

  1. El shape exacto de la petición/respuesta de POST /api/scan-batch
     (función fetch_scan_batch) — se asume aquí el mismo contrato que
     usa runScan() en el navegador, a falta de leer el handler completo.
  2. Los nombres de campo entry_price/stop_price/risk_pct en el payload
     de POST /api/snapshots (función construir_payload_snapshot).
     ticker/market/strategies/data_ts/snapshot_ts/temporal_group SÍ
     están confirmados (DOC-IDEM Addendum 3, patch literal de
     create_snapshot, y Addendum 4, payload de prueba real).
  3. El umbral numérico real de detectAutoTrigger() (función
     detect_auto_trigger) — confirmado que es una comparación pura,
     pero el valor exacto del umbral no se ha transcrito a ningún
     documento. 80.0 es una estimación a partir de los SCORE_ENTRADA
     observados en 05_OPERACIONES (Fase 0A: 82, 95, 100...).

Protocolo antes de instalar el timer:
  1. Cerrar los tres puntos de arriba.
  2. Ejecutar con --dry-run contra el proxy real y revisar el log —
     no hace ningún POST, solo registra qué habría enviado.
  3. Ejecutar una vez sin --dry-run con --force-window fuera de la
     franja de los timers del evaluador (16:00-22:00 L-V, 18:30 todos
     los días), usando un scanner/ticker de prueba igual que en el
     protocolo de ST-16 (ZZTEST), y confirmar la respuesta antes de
     instalar axonik-snapshot-autocapture.timer.
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
DEFAULT_SCORE_THRESHOLD = 80.0  # ver punto 3 de la cabecera — estimación, no confirmado


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
    PENDIENTE DE CONFIRMAR (punto 1 de la cabecera del archivo): shape
    exacto de /api/scan-batch. Se asume que acepta una lista de IDs de
    scanner y devuelve {"results": [...]} con al menos ticker/score/
    data_ts/scn_id por entrada — es la forma mínima que necesita el
    resto del script, no una transcripción del handler real.
    """
    resp = requests.post(
        f"{PROXY_BASE}/api/scan-batch",
        json={"scanner_ids": [s.scn_id for s in scanners]},
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json()


def detect_auto_trigger(score: float, threshold: float = DEFAULT_SCORE_THRESHOLD) -> bool:
    """
    Confirmado (diseño §1.2-1.4): detectAutoTrigger() es comparación
    pura. El umbral exacto (punto 3 de la cabecera) sigue siendo una
    estimación — confirmarlo antes de depender de este valor en real.
    """
    return score >= threshold


def construir_payload_snapshot(ticker_data: dict, scanner: ScannerDef,
                                data_ts: str, snapshot_ts: str) -> dict:
    """
    ticker/market/strategies/data_ts/snapshot_ts/temporal_group:
    CONFIRMADOS (DOC-IDEM Addendum 3 y Addendum 4). entry_price/
    stop_price/risk_pct: PENDIENTE DE CONFIRMAR (punto 2 de la
    cabecera) — nombres estimados a partir de la prosa de Addendum 4
    ("entry 100 / stop 95 / risk 5"), no de una lectura literal del
    modelo Pydantic.
    """
    return {
        "ticker": ticker_data["ticker"],
        "market": scanner.mercado.lower(),
        "data_ts": data_ts,
        "snapshot_ts": snapshot_ts,
        "temporal_group": ticker_data.get("temporal_group", "swing"),
        "strategies": [{"id": scanner.scn_id}],
        "entry_price": ticker_data["entry_price"],
        "stop_price": ticker_data["stop_price"],
        "risk_pct": ticker_data.get("risk_pct"),
    }


def capture_signal(scanner: ScannerDef, ticker_data: dict, data_ts: str,
                    snapshot_ts: str, dry_run: bool) -> bool:
    payload = construir_payload_snapshot(ticker_data, scanner, data_ts, snapshot_ts)
    if dry_run:
        log.info(f"[DRY RUN] POST /api/snapshots {json.dumps(payload, ensure_ascii=False)}")
        return False

    resp = requests.post(f"{PROXY_BASE}/api/snapshots", json=payload, timeout=10)
    resp.raise_for_status()
    body = resp.json()
    created = bool(body.get("created"))
    if created:
        log.info(f"capturado: {ticker_data['ticker']} / {scanner.scn_id} (id={body.get('id')})")
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

    capturas = 0
    for ticker_data in datos_mercado.get("results", []):
        score = ticker_data.get("score")
        if score is None or not detect_auto_trigger(score):
            continue
        scanner = next((s for s in scanners if s.scn_id == ticker_data.get("scn_id")), None)
        if scanner is None:
            continue
        try:
            if capture_signal(
                scanner, ticker_data,
                data_ts=ticker_data["data_ts"],
                snapshot_ts=now.astimezone(ZoneInfo("UTC")).isoformat(),
                dry_run=args.dry_run,
            ):
                capturas += 1
        except Exception:
            log.exception(f"Fallo al capturar {ticker_data.get('ticker')} / {scanner.scn_id} "
                           f"— se sigue con el resto del lote.")

    log.info(f"Fin de la corrida. Señales capturadas: {capturas}.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
