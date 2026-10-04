#!/usr/bin/env bash
# Despliega POST /api/evaluate-ticker en market_data_proxy.py real --
# idempotente: se puede ejecutar varias veces sin duplicar nada.
#
# NO habilita ningún timer systemd ni toca nada más que
# market_data_proxy.py y los módulos que importa. El timer de
# snapshot_autocapture (Paso 2/3 de README.md) sigue siendo un paso
# aparte, deliberadamente no incluido aquí.
#
# Contexto del NameError real de producción (04/10/2026): un despliegue
# anterior pegó el bloque de EvaluateTickerRequest sin añadir
# `from typing import Optional` a la cabecera de market_data_proxy.py
# -- el campo `funda: Optional[dict] = None` reventó en cuanto FastAPI
# intentó construir el modelo. Este script existe para que esa
# comprobación (y las demás) sean mecánicas, no "a mano y con suerte".
#
# Orden de operaciones:
#   a) Preflight: copiar los módulos que importa el parche
#      (indicator_calc.py, evaluate_ticker_logic.py -- confirmado que
#      no importan nada más propio, ver sus cabeceras) a
#      /opt/axonik/scripts/, y comprobar que importan ANTES de tocar
#      market_data_proxy.py.
#   b) Backup con timestamp + sha256 de market_data_proxy.py.
#   c) Quitar el bloque del endpoint (desde `class
#      EvaluateTickerRequest` hasta antes de
#      `# ─── Learning Engine: signal_snapshots endpoints`) y pegar el
#      nuevo, con el decorador @app.post incluido. El marcador de
#      cierre tiene que ser ese texto completo -- "Learning Engine" a
#      secas aparece DOS veces en el archivo real (línea ~523, sección
#      de Postgres, y línea ~1016, la de signal_snapshots endpoints;
#      dos secciones legítimas distintas, confirmado tras un aborto
#      real de una versión anterior de este script con un marcador
#      demasiado corto). Si el marcador de inicio aparece más de una
#      vez, o el de cierre no aparece EXACTAMENTE una vez, o el de
#      inicio va después del de cierre: ABORTA SIN CAMBIOS.
#   d) Comprobar que la cabecera tiene los imports que el parche usa
#      (json, Optional, Response, HTTPException, BaseModel,
#      evaluate_ticker_logic) y añadir los que falten sin duplicar.
#   e) py_compile, restart, esperar ~8s, comprobar systemctl is-active
#      y /api/health. Si algo falla: restaurar el backup, reiniciar y
#      mostrar las últimas líneas del journal.
#   f) Prueba de humo: POST con velas reales de AAPL (200 + price
#      presente) y POST con payload vacío (422).
#
# Uso:
#   ./deploy_evaluate_endpoint.sh
#   PROXY_PY=/otra/ruta/market_data_proxy.py SERVICE_NAME=otro-nombre \
#     ./deploy_evaluate_endpoint.sh

set -euo pipefail

PROXY_PY="${PROXY_PY:-/opt/axonik/scripts/market_data_proxy.py}"
SCRIPTS_DIR="${SCRIPTS_DIR:-/opt/axonik/scripts}"
PROXY_BASE="${PROXY_BASE:-http://127.0.0.1:8002}"
SERVICE_NAME="${SERVICE_NAME:-axonik-market-proxy}"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"       # .../docs/pipeline
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
SNAP_DIR="$REPO_ROOT/services/snapshot-autocapture"
PATCH_SOURCE="$SNAP_DIR/evaluate_ticker_endpoint.py"
FIXTURE_AAPL="$SCRIPT_DIR/fixtures_js/AAPL_scanbatch_raw.json"

log() { echo "[deploy_evaluate_endpoint] $*"; }

log "=== $(date -u +%Y-%m-%dT%H:%M:%SZ) ==="

# --- a) Preflight -----------------------------------------------------------
log "Preflight: copiando módulos y verificando el import ANTES de tocar el proxy."

for mod in indicator_calc.py evaluate_ticker_logic.py; do
    if [[ ! -r "$SNAP_DIR/$mod" ]]; then
        log "ERROR: no se encuentra $SNAP_DIR/$mod"
        exit 1
    fi
    cp "$SNAP_DIR/$mod" "$SCRIPTS_DIR/$mod"
    log "copiado: $SCRIPTS_DIR/$mod"
done
# Lista confirmada leyendo las cabeceras de ambos módulos: solo se
# importan entre sí (evaluate_ticker_logic -> indicator_calc) y
# librería estándar -- si en el futuro alguno importa algo más propio,
# añadirlo a la lista de arriba.

if ! (cd "$SCRIPTS_DIR" && python3 -c "import evaluate_ticker_logic, indicator_calc"); then
    log "ERROR: el import falla en $SCRIPTS_DIR -- abortando ANTES de tocar market_data_proxy.py."
    exit 1
fi
log "OK: evaluate_ticker_logic + indicator_calc importan limpio."

if [[ ! -r "$PROXY_PY" ]]; then
    log "ERROR: no se puede leer $PROXY_PY"
    exit 1
fi
if [[ ! -r "$PATCH_SOURCE" ]]; then
    log "ERROR: no se puede leer $PATCH_SOURCE"
    exit 1
fi

# --- b) Backup ----------------------------------------------------------------
TS="$(date +%Y%m%d_%H%M%S)"
BACKUP="$PROXY_PY.bak.$TS"
cp "$PROXY_PY" "$BACKUP"
log "backup: $BACKUP"
sha256sum "$PROXY_PY" "$BACKUP"

# --- c) + d) Edición del archivo real (lógica fina en Python) ---------------
log "Editando $PROXY_PY: bloque del endpoint + imports de cabecera."

python3 - "$PROXY_PY" "$PATCH_SOURCE" <<'PYEOF'
import re
import sys

proxy_path, patch_source_path = sys.argv[1], sys.argv[2]

with open(proxy_path) as f:
    proxy = f.read()
with open(patch_source_path) as f:
    patch_src = f.read()

# --- Construir el bloque a pegar a partir de evaluate_ticker_endpoint.py ---
m = re.search(r"^class EvaluateTickerRequest\b.*", patch_src, re.S | re.M)
if not m:
    print("ERROR: no se encontró 'class EvaluateTickerRequest' en el archivo fuente", file=sys.stderr)
    sys.exit(1)
new_block = patch_src[m.start():].rstrip() + "\n"

handler_sig = "async def evaluate_ticker_endpoint(req: EvaluateTickerRequest):"
if handler_sig not in new_block:
    print("ERROR: no se encontró la firma de evaluate_ticker_endpoint en el archivo fuente", file=sys.stderr)
    sys.exit(1)

# El archivo fuente deja el handler SIN decorador a propósito (para ser
# importable/testeable sin NameError de 'app') y en su lugar tiene un
# comentario instructivo explicándolo -- ese comentario menciona
# literalmente la cadena '@app.post("/api/evaluate-ticker")' como texto,
# así que buscar esa subcadena en new_block para decidir si "ya está"
# NO sirve (siempre da positivo, por el comentario, aunque no haya
# decorador real). Se quita el comentario instructivo y se añade el
# decorador real justo encima de la firma, sin condición -- el archivo
# fuente nunca lo trae ya puesto.
split_marker = "# --- A partir de aquí, pegar tal cual"
split_idx = new_block.find(split_marker)
if split_idx == -1:
    print("ERROR: no se encontró el comentario instructivo a quitar antes de pegar "
          "-- revisar si cambió el texto de evaluate_ticker_endpoint.py", file=sys.stderr)
    sys.exit(1)
handler_idx = new_block.find(handler_sig, split_idx)
if handler_idx == -1:
    print("ERROR: no se encontró la firma del handler después del comentario instructivo", file=sys.stderr)
    sys.exit(1)
new_block = (
    new_block[:split_idx].rstrip("\n") + "\n\n\n"
    + '@app.post("/api/evaluate-ticker")\n'
    + new_block[handler_idx:]
)

# --- Localizar los marcadores en el proxy real ---
# El marcador de cierre tiene que ser el texto completo y único de esa
# cabecera -- "# ─── Learning Engine" a secas aparece DOS veces en el
# archivo real (confirmado por el usuario tras un aborto real de este
# script: línea ~523 "Learning Engine: Postgres access
# (signal_snapshots)" y línea ~1016 "Learning Engine: signal_snapshots
# endpoints" -- dos secciones legítimas distintas, no un error del
# archivo). Solo la segunda es el límite real del bloque a reemplazar.
start_pat = re.compile(r"^class EvaluateTickerRequest\b.*$", re.M)
end_marker_text = "Learning Engine: signal_snapshots endpoints"
end_pat = re.compile(r"^#\s*─+\s*" + re.escape(end_marker_text) + r"\b.*$", re.M)

start_matches = list(start_pat.finditer(proxy))
end_matches = list(end_pat.finditer(proxy))

if len(start_matches) > 1:
    print(f"ERROR: 'class EvaluateTickerRequest' aparece {len(start_matches)} veces -- "
          f"ambiguo, abortando sin cambios.", file=sys.stderr)
    sys.exit(1)
if len(end_matches) != 1:
    print(f"ERROR: el marcador '# ─── {end_marker_text}' aparece {len(end_matches)} veces "
          f"(se esperaba exactamente 1) -- abortando sin cambios.", file=sys.stderr)
    sys.exit(1)

end_idx = end_matches[0].start()

# Marcador de inicio: a lo sumo 1 aparición (ya comprobado arriba) Y,
# si existe, tiene que ir ANTES del de cierre -- si no, el archivo no
# tiene la forma esperada y no se toca nada.
if start_matches:
    start_idx = start_matches[0].start()
    if start_idx > end_idx:
        print(f"ERROR: 'class EvaluateTickerRequest' (línea con offset {start_idx}) aparece "
              f"DESPUÉS del marcador '# ─── {end_marker_text}' (offset {end_idx}) -- orden "
              f"inesperado, abortando sin cambios.", file=sys.stderr)
        sys.exit(1)
    before, after = proxy[:start_idx], proxy[end_idx:]
    action = "bloque existente reemplazado (idempotente)"
else:
    before, after = proxy[:end_idx], proxy[end_idx:]
    action = "bloque insertado (primera vez, no existía todavía)"

updated = before.rstrip("\n") + "\n\n\n" + new_block + "\n\n" + after

# --- d) Imports de cabecera: añadir los que falten, sin duplicar ---
# Solo se mira la cabecera (antes de "# ─── Config", confirmado en
# Pregunta 6a) para no confundir con imports locales dentro de funciones.
header_marker = "# ─── Config"
header_end = updated.find(header_marker)
if header_end == -1:
    print(f"ERROR: no se encontró el marcador de cabecera '{header_marker}' -- "
          f"abortando sin cambios.", file=sys.stderr)
    sys.exit(1)
header, rest = updated[:header_end], updated[header_end:]

required_imports = [
    ("import json", r"^\s*import\s+json\s*$"),
    ("from typing import Optional", r"from\s+typing\s+import\s+[^\n]*\bOptional\b"),
    ("from fastapi import Response", r"from\s+fastapi\s+import\s+[^\n]*\bResponse\b"),
    ("from fastapi import HTTPException", r"from\s+fastapi\s+import\s+[^\n]*\bHTTPException\b"),
    ("from pydantic import BaseModel", r"from\s+pydantic\s+import\s+[^\n]*\bBaseModel\b"),
    ("import evaluate_ticker_logic as etl", r"import\s+evaluate_ticker_logic\s+as\s+etl"),
]
to_add = [line for line, pattern in required_imports if not re.search(pattern, header, re.M)]

if to_add:
    insertion = (
        "\n# --- Imports añadidos por deploy_evaluate_endpoint.sh para "
        "POST /api/evaluate-ticker (NameError de 'Optional' sin importar "
        "ya pasó una vez en producción -- de ahí esta comprobación) ---\n"
        + "\n".join(to_add) + "\n"
    )
    header = header.rstrip("\n") + "\n" + insertion + "\n"
    print("Imports añadidos:", ", ".join(to_add))
else:
    print("OK: todos los imports necesarios ya estaban en la cabecera.")

updated = header + rest

# --- Verificación final: la ruta no puede quedar registrada dos veces ---
route_count = updated.count('@app.post("/api/evaluate-ticker")')
if route_count != 1:
    print(f"ERROR: la ruta /api/evaluate-ticker aparece {route_count} veces tras la "
          f"edición (se esperaba exactamente 1) -- abortando SIN escribir.", file=sys.stderr)
    sys.exit(1)

with open(proxy_path, "w") as f:
    f.write(updated)

print(f"OK: {action}; imports verificados; ruta registrada exactamente 1 vez.")
PYEOF

# --- e) py_compile, restart, healthcheck, rollback si falla -----------------
log "py_compile..."
if ! python3 -m py_compile "$PROXY_PY"; then
    log "ERROR: py_compile falló -- restaurando backup, sin reiniciar el servicio."
    cp "$BACKUP" "$PROXY_PY"
    exit 1
fi

log "Reiniciando $SERVICE_NAME..."
systemctl restart "$SERVICE_NAME"
sleep 8

if systemctl is-active --quiet "$SERVICE_NAME" && curl -sf "$PROXY_BASE/api/health" >/dev/null; then
    log "OK: $SERVICE_NAME activo y /api/health responde."
else
    log "ERROR: el servicio no quedó sano tras el reinicio -- restaurando backup y reiniciando."
    cp "$BACKUP" "$PROXY_PY"
    systemctl restart "$SERVICE_NAME"
    sleep 3
    log "--- últimas 50 líneas del journal de $SERVICE_NAME ---"
    journalctl -u "$SERVICE_NAME" -n 50 --no-pager || true
    exit 1
fi

# --- f) Prueba de humo -------------------------------------------------------
log "Prueba de humo: AAPL real (docs/pipeline/fixtures_js/AAPL_scanbatch_raw.json) -> 200 + price presente."
if [[ ! -r "$FIXTURE_AAPL" ]]; then
    log "ERROR: no se encuentra $FIXTURE_AAPL -- no se puede hacer la prueba de humo."
    exit 1
fi

python3 -c "
import json
raw = json.load(open('$FIXTURE_AAPL'))
item = next(r for r in raw['results'] if r['ticker'] == 'AAPL')
payload = {
    'ticker': 'AAPL', 'mode': 'NYSE', 'candles': item['data'], 'funda': None,
    'settings': {'priceMin': 8, 'atrMax': 4, 'rvolMin': 1},
    'btc_gate_on': False, 'insider_summary': None,
}
json.dump(payload, open('/tmp/deploy_smoke_aapl_request.json', 'w'))
"

HTTP_CODE="$(curl -s -o /tmp/deploy_smoke_aapl_response.json -w '%{http_code}' \
    -X POST "$PROXY_BASE/api/evaluate-ticker" \
    -H 'Content-Type: application/json' \
    -d @/tmp/deploy_smoke_aapl_request.json)"

if [[ "$HTTP_CODE" != "200" ]]; then
    log "ERROR: la prueba de humo con AAPL devolvió HTTP $HTTP_CODE (se esperaba 200)."
    cat /tmp/deploy_smoke_aapl_response.json
    exit 1
fi
python3 -c "
import json
body = json.load(open('/tmp/deploy_smoke_aapl_response.json'))
assert 'price' in body and body['price'] is not None, f\"falta 'price' en la respuesta: {body}\"
print('OK: price presente:', body['price'])
"

log "Prueba de humo: payload vacío -> 422."
HTTP_CODE="$(curl -s -o /tmp/deploy_smoke_empty_response.json -w '%{http_code}' \
    -X POST "$PROXY_BASE/api/evaluate-ticker" \
    -H 'Content-Type: application/json' -d '{}')"
if [[ "$HTTP_CODE" != "422" ]]; then
    log "ERROR: el payload vacío devolvió HTTP $HTTP_CODE (se esperaba 422)."
    cat /tmp/deploy_smoke_empty_response.json
    exit 1
fi
log "OK: payload vacío -> 422."

log "=== Despliegue completo y verificado. NINGÚN timer habilitado -- eso sigue siendo el Paso 2/3 de README.md, aparte. ==="
