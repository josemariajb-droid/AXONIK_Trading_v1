#!/usr/bin/env bash
# Genera fixtures JS -> JSON reales para probar el puerto Python de
# computeIndicators() + las 9 funciones de cálculo (fondo de la cadena,
# confirmado en docs/pipeline/pregunta10_salida.txt y en el diseño §1.10
# de 2026-10-03_automatizacion_captura_snapshots.md).
#
# Qué hace, en orden:
#   1. Extrae computeIndicators y las 9 funciones (emaArr, calcRSI,
#      calcMACD, calcATR, calcRVOL, calcADX, calcCompression,
#      calcGapPct, calcVWAP) de /opt/axonik/scanner/index.html, con la
#      misma extracción por balance de llaves que ya usa
#      check_autocapture_triggers.sh (extract_js_block/print_js_def) --
#      duplicada aquí a propósito para que este script sea autónomo,
#      no por mantener dos copias de buena gana.
#   2. Pide velas reales a POST /api/scan-batch (proxy local, no se
#      inventan datos) para cada ticker pedido, y las "congela"
#      (guarda en el repo) junto con el resultado de ejecutarlas con
#      Node real sobre las 10 funciones extraídas -- no una
#      re-implementación en bash/Python, el intérprete JS real.
#   3. Escribe fixtures en docs/pipeline/fixtures_js/: las velas de
#      entrada, el JS extraído (para poder inspeccionar exactamente qué
#      se ejecutó si algo no coincide más adelante) y las salidas.
#
# Solo lectura sobre index.html y sobre el proxy (GET/POST normales,
# ningún endpoint de escritura). La única escritura es local, dentro
# de este repo.
#
# Requiere: node (v24.15.0 confirmado en el servidor), python3 (ya lo
# necesita market_data_proxy.py), el proxy corriendo en PROXY_BASE.
#
# Uso:
#   ./generar_fixtures_js.sh [TICKER...]
#   Por defecto: AAPL MSFT NVDA (del universo real de 14_UNIVERSO_TICKERS)
#
#   SCANNER_HTML=/otra/ruta/index.html PROXY_BASE=http://127.0.0.1:8002 \
#     ./generar_fixtures_js.sh AAPL

set -euo pipefail

SCANNER_HTML="${SCANNER_HTML:-/opt/axonik/scanner/index.html}"
PROXY_BASE="${PROXY_BASE:-http://127.0.0.1:8002}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
OUT_DIR="${OUT_DIR:-$SCRIPT_DIR/fixtures_js}"
TIMEFRAMES=(1d 1h 15m)

if [[ $# -gt 0 ]]; then
    TICKERS=("$@")
else
    TICKERS=(AAPL MSFT NVDA)
fi

if [[ ! -r "$SCANNER_HTML" ]]; then
    echo "ERROR: no se puede leer $SCANNER_HTML (¿ruta incorrecta o permisos? probar con sudo)" >&2
    exit 1
fi
if ! command -v node >/dev/null 2>&1; then
    echo "ERROR: no se encuentra 'node' en el PATH." >&2
    exit 1
fi
if ! command -v python3 >/dev/null 2>&1; then
    echo "ERROR: no se encuentra 'python3' en el PATH." >&2
    exit 1
fi

mkdir -p "$OUT_DIR"

# --- Extracción por balance de llaves -- misma mecánica que
#     check_autocapture_triggers.sh (extract_js_block), duplicada aquí
#     para que este script no dependa de sourcear el otro. ---
extract_js_block() {
    local file="$1" start_line="$2" max_lines="${3:-1500}"
    awk -v start="$start_line" -v maxlines="$max_lines" '
        NR < start { next }
        {
            print
            o = gsub(/[{\[]/, "&")
            c = gsub(/[}\]]/, "&")
            depth += o - c
            if (NR > start && depth <= 0) { exit }
            if (NR - start + 1 >= maxlines) {
                print "/* CORTE DE SEGURIDAD a " maxlines " líneas sin cerrar el balance -- revisar a mano */"
                exit
            }
        }
    ' "$file"
}

# Localiza y extrae la definición de $name. A diferencia de
# print_js_def() en check_autocapture_triggers.sh, esta variante falla
# con exit 1 si no encuentra la definición o si hay más de una
# coincidencia (aquí no hay un humano leyendo la salida para juzgar si
# la ambigüedad importa -- si hay ambigüedad, parar y que lo revise
# alguien, no concatenar algo potencialmente equivocado a un fixture).
extract_js_def_or_fail() {
    local file="$1" name="$2" max_lines="${3:-1500}"
    local pattern="(const|let|var)[[:space:]]+${name}\b|function[[:space:]]+${name}\b|\\b${name}[[:space:]]*="
    local count line
    count=$(grep -c -E "$pattern" "$file" 2>/dev/null || true)
    if [[ "${count:-0}" -eq 0 ]]; then
        echo "ERROR: no se encontró la definición de '$name' en $file" >&2
        exit 1
    fi
    if [[ "${count:-0}" -gt 1 ]]; then
        echo "ERROR: '$name' coincide $count veces en $file -- ambiguo, revisar a mano antes de generar fixtures." >&2
        exit 1
    fi
    line=$(grep -n -m1 -E "$pattern" "$file" | cut -d: -f1)
    extract_js_block "$file" "$line" "$max_lines"
}

echo "=== 1. Extrayendo computeIndicators + las 9 funciones de $SCANNER_HTML ==="
EXTRACTED_JS="$OUT_DIR/computeIndicators_extracted.js"
{
    echo "// Extraído de $SCANNER_HTML el $(date -u +%Y-%m-%dT%H:%M:%SZ) por generar_fixtures_js.sh"
    echo "// NO EDITAR A MANO -- regenerar con el script si el navegador cambia."
    echo
    for name in computeIndicators emaArr calcRSI calcMACD calcATR calcRVOL calcADX calcCompression calcGapPct calcVWAP; do
        echo "// --- $name ---"
        extract_js_def_or_fail "$SCANNER_HTML" "$name" 1500
        echo
    done
} > "$EXTRACTED_JS"
echo "Escrito: $EXTRACTED_JS"

# Sanity check: que el JS extraído al menos parsee como válido antes de
# fiarse de nada más. node --check no ejecuta el archivo.
if ! node --check "$EXTRACTED_JS" 2>&1; then
    echo "ERROR: el JS extraído no es sintácticamente válido -- revisar $EXTRACTED_JS a mano." >&2
    exit 1
fi
echo "OK: $EXTRACTED_JS parsea como JS válido."

# --- Driver de Node: recibe candles (JSON) + tf por argv, calcula
#     computeIndicators() y cada una de las 9 funciones por separado
#     (no solo el resultado combinado -- si algo no coincide más
#     adelante, poder señalar cuál de las 9 es, no solo "algo falló"). ---
DRIVER_JS="$OUT_DIR/_driver.js"
cat > "$DRIVER_JS" <<'DRIVER_EOF'
const fs = require('fs');
const [, , extractedPath, candlesPath, tf, outPath] = process.argv;

eval(fs.readFileSync(extractedPath, 'utf8'));

const candles = JSON.parse(fs.readFileSync(candlesPath, 'utf8'));
const closes = candles.map(c => c.c), highs = candles.map(c => c.h),
      lows = candles.map(c => c.l), volumes = candles.map(c => c.v);

const result = {
    computeIndicators: computeIndicators(candles, tf),
    // Cada función también por separado, con los mismos argumentos que
    // usa computeIndicators() internamente -- para poder aislar cuál
    // de las 9 diverge, no solo que "el resultado combinado no coincide".
    emaArr_20: emaArr(closes, 20),
    emaArr_50: emaArr(closes, 50),
    emaArr_200_allowPartial: emaArr(closes, 200, true),
    calcRSI_14: calcRSI(closes, 14),
    calcMACD_default: calcMACD(closes),
    calcATR_14: calcATR(highs, lows, closes, 14),
    calcRVOL: calcRVOL(volumes),
    calcADX_14: calcADX(highs, lows, closes, 14),
    calcCompression_6: calcCompression(candles, 6),
    calcGapPct: calcGapPct(candles),
    calcVWAP: calcVWAP(candles),
};

// JSON no tiene NaN -- se serializa como el string "NaN" (sentinela
// explícito) en vez de perderlo como null, para que el puerto Python
// pueda comparar NaN contra NaN sin ambigüedad.
const json = JSON.stringify(result, (_, v) => (typeof v === 'number' && Number.isNaN(v)) ? 'NaN' : v, 2);
fs.writeFileSync(outPath, json);
console.log(`escrito: ${outPath}`);
DRIVER_EOF

echo
echo "=== 2. Velas reales por ticker (POST /api/scan-batch, sin inventar datos) ==="
for ticker in "${TICKERS[@]}"; do
    echo "--- $ticker ---"
    BATCH_JSON="$OUT_DIR/${ticker}_scanbatch_raw.json"
    curl -sS -X POST "$PROXY_BASE/api/scan-batch" \
        -H 'Content-Type: application/json' \
        -d "{\"tickers\": [\"$ticker\"]}" \
        -o "$BATCH_JSON"

    # Emparejado por ticker, nunca por índice [0] -- mismo criterio ya
    # aplicado en snapshot_autocapture.py y en
    # VERIFICACION_NAVEGADOR_VS_ENDPOINT.md.
    python3 - "$BATCH_JSON" "$ticker" "$OUT_DIR" <<'PYEOF'
import json, sys
batch_path, ticker, out_dir = sys.argv[1], sys.argv[2], sys.argv[3]
with open(batch_path) as f:
    batch = json.load(f)
item = next((r for r in batch.get("results", []) if r.get("ticker") == ticker), None)
if item is None:
    print(f"ERROR: {ticker} no aparece en la respuesta de scan-batch", file=sys.stderr)
    sys.exit(1)
if item.get("error"):
    print(f"ERROR: scan-batch devolvió error para {ticker}: {item['error']}", file=sys.stderr)
    sys.exit(1)
data = item.get("data") or {}
for tf in ("1d", "1h", "15m"):
    tf_data = data.get(tf)
    if not tf_data or not tf_data.get("candles"):
        print(f"AVISO: {ticker}/{tf} sin velas -- se omite ese timeframe.", file=sys.stderr)
        continue
    with open(f"{out_dir}/{ticker}_{tf}_candles.json", "w") as out:
        json.dump(tf_data["candles"], out, indent=2)
PYEOF

    for tf in "${TIMEFRAMES[@]}"; do
        CANDLES_JSON="$OUT_DIR/${ticker}_${tf}_candles.json"
        if [[ ! -r "$CANDLES_JSON" ]]; then
            echo "  (sin velas para $ticker/$tf, omitido -- ver aviso de arriba)"
            continue
        fi
        OUT_JSON="$OUT_DIR/${ticker}_${tf}_output.json"
        echo "  ejecutando Node sobre $ticker/$tf..."
        node "$DRIVER_JS" "$EXTRACTED_JS" "$CANDLES_JSON" "$tf" "$OUT_JSON"
    done
done

rm -f "$DRIVER_JS"

echo
echo "=== Fin. Fixtures en $OUT_DIR: ==="
echo "  - computeIndicators_extracted.js (JS real ejecutado, para inspección)"
echo "  - <TICKER>_<TF>_candles.json (velas de entrada, congeladas)"
echo "  - <TICKER>_<TF>_output.json (computeIndicators + las 9 funciones, por separado)"
echo
echo "Haz commit y push de docs/pipeline/fixtures_js/ para que se puedan construir"
echo "las pruebas del puerto Python contra estos fixtures."
