#!/usr/bin/env bash
# Oráculo Node para verificar POST /api/evaluate-ticker -- sustituye la
# verificación manual por consola de navegador de
# VERIFICACION_NAVEGADOR_VS_ENDPOINT.md (ese documento pasa a describir
# esto como el camino principal; la consola queda como alternativa).
#
# Motivo del cambio (05/10/2026, decisión del usuario): nadie ha abierto
# nunca /scanner contra el servidor real, y desde que el proxy se bindea
# a 127.0.0.1 (Paso 1 del README de este servicio) /scanner deja de ser
# alcanzable desde fuera del propio host -- depender de DevTools para
# verificar era impráctico desde el principio. Node (v24.15.0 confirmado
# en el servidor) es el mismo motor V8 que el navegador: ejecutar el JS
# real bajo Node da el mismo resultado que ejecutarlo en Chrome/Firefox,
# sin necesitar abrir nada. Misma técnica ya usada y probada en
# generar_fixtures_js.sh para computeIndicators()+9 funciones.
#
# Qué hace, en orden:
#   1. Extrae de /opt/axonik/scanner/index.html las 32 piezas que
#      necesitan evaluateTicker()/detectAutoTrigger(): las 22 ya
#      confirmadas (evaluateTicker, detectAutoTrigger, NYSE_STRATEGIES,
#      CRYPTO_STRATEGIES, applyEventAdjustments, tickerHardNo, las 10
#      evalXX, mkResult, mkNA, finalizeVerdict, f, STRATEGY_META,
#      MAX_RAW_SCORE) más computeIndicators() y sus 9 funciones de
#      cálculo (emaArr, calcRSI, calcMACD, calcATR, calcRVOL, calcADX,
#      calcCompression, calcGapPct, calcVWAP) -- éstas últimas YA
#      portadas a Python (indicator_calc.py) pero aquí se necesita el JS
#      real, no el puerto, para que el oráculo no dependa de la misma
#      implementación que se quiere verificar.
#
#      Extracción por ancla: cada pieza tiene una línea real ya
#      confirmada (acumulada en docs/pipeline/pregunta5*/9/10_salida.txt
#      a lo largo de varias pasadas) -- se comprueba esa línea primero;
#      si todavía coincide con el patrón de localización de la pieza, se
#      extrae directamente de ahí, SIN hacer una búsqueda global. Esto
#      evita el riesgo real de ambigüedad de una búsqueda global para un
#      nombre corto como "f" (el patrón `\bf\s*=` puede coincidir con
#      variables de bucle o propiedades `obj.f = ...` en cualquier parte
#      de un archivo de miles de líneas) sin dejar de ser seguro: si la
#      línea conocida ya no coincide (el navegador cambió desde la
#      última auditoría), se cae a una búsqueda global que aborta sin
#      escribir nada si hay 0 o más de 1 coincidencia -- nunca se adivina.
#
#   2. Carga el universo de tickers de 14_UNIVERSO_TICKERS (vía
#      cargar_universo_de_tickers() de snapshot_autocapture.py --
#      ESTADO=ACTIVO, excluye CRYPTO -- misma fuente que usará el timer
#      real, nunca una lista duplicada a mano) y pide sus velas reales
#      con POST /api/scan-batch. Si el proxy responde 400 por exceder
#      MAX_BATCH_TICKERS (valor real nunca confirmado contra el código --
#      solo se sabe que la constante existe), se trocea adaptativamente:
#      se parsea el límite del propio mensaje de error del proxy y se
#      reintenta en lotes de ese tamaño -- no se asume ningún número fijo.
#      Emparejado siempre por ticker, nunca por índice.
#
#   3. Ejecuta bajo Node real (no una reimplementación) computeIndicators()
#      por timeframe + evaluateTicker(t, ind, null, 'NYSE',
#      DEFAULT_SETTINGS, false, null) + detectAutoTrigger() sobre ese
#      resultado, para cada ticker. DEFAULT_SETTINGS aquí es
#      {priceMin:8, atrMax:4, rvolMin:1} -- las 3 claves que de verdad
#      consume la cadena evaluateTicker()/tickerHardNo() (el
#      DEFAULT_SETTINGS real completo trae además capital/riskPct, que
#      esta cadena no toca). NaN se sirve como el string "NaN" (mismo
#      convenio que evaluate_ticker_logic.nan_to_json_sentinel()).
#
#   4. Guarda en docs/pipeline/fixtures_js/oraculo_evaluate/: las velas
#      de entrada, la salida de evaluateTicker() y el resultado de
#      detectAutoTrigger(), por ticker.
#
# Solo lectura sobre index.html y sobre el proxy (GET/POST normales,
# ningún endpoint de escritura). La única escritura es local, dentro de
# este repo. NO DESPLIEGA NADA.
#
# Requiere: node, python3 (con requests instalado -- ya lo necesita
# snapshot_autocapture.py), el proxy corriendo en PROXY_BASE.
#
# Uso:
#   ./generar_oraculo_evaluate_js.sh
#     Universo real desde 14_UNIVERSO_TICKERS (requiere
#     AXONIK_DECISION_ENGINE_SHEET_ID + credenciales de gspread, igual
#     que snapshot_autocapture.py).
#
#   ./generar_oraculo_evaluate_js.sh AAPL MSFT NVDA
#     Override explícito por CLI -- no consulta la hoja. Para pruebas
#     sin credenciales o para repetir solo un ticker concreto.
#
#   SCANNER_HTML=/otra/ruta/index.html PROXY_BASE=http://127.0.0.1:8002 \
#   SNAPSHOT_AUTOCAPTURE_DIR=/otra/ruta ./generar_oraculo_evaluate_js.sh

set -euo pipefail

SCANNER_HTML="${SCANNER_HTML:-/opt/axonik/scanner/index.html}"
PROXY_BASE="${PROXY_BASE:-http://127.0.0.1:8002}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
OUT_DIR="${OUT_DIR:-$SCRIPT_DIR/fixtures_js/oraculo_evaluate}"
SNAPSHOT_AUTOCAPTURE_DIR="${SNAPSHOT_AUTOCAPTURE_DIR:-$SCRIPT_DIR/../../services/snapshot-autocapture}"

if [[ $# -gt 0 ]]; then
    TICKERS=("$@")
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

# --- Extracción por balance de llaves/corchetes. ---
#
# OJO -- esta variante corrige un caso de borde real respecto a la
# misma función en generar_fixtures_js.sh/check_autocapture_triggers.sh:
# la original nunca corta en la PRIMERA línea aunque ya esté balanceada
# (a propósito, para no truncar una firma de función cuya "{" va en la
# línea siguiente). Eso es correcto para funciones multilínea, pero con
# una sentencia de una sola línea que ya cierra sus propios corchetes
# (p.ej. "const NYSE_STRATEGIES = [...];") hace que el bloque "sangre" a
# la línea siguiente -- inocuo si esa línea siguiente es irrelevante,
# pero real y roto aquí: en el archivo real, justo después de
# NYSE_STRATEGIES va "const CRYPTO_STRATEGIES = [...];" -- si el bloque
# de NYSE_STRATEGIES se come esa línea Y además se extrae
# CRYPTO_STRATEGIES por separado, el const queda declarado dos veces
# (SyntaxError al concatenar). Se corrige cortando también cuando la
# propia línea de inicio ya contenía algún corchete y el balance ya es
# <=0 tras procesarla -- sin eso no se habría detectado con los 22+9
# piezas anteriores (todas eran funciones multilínea).
extract_js_block() {
    local file="$1" start_line="$2" max_lines="${3:-3000}"
    awk -v start="$start_line" -v maxlines="$max_lines" '
        NR < start { next }
        {
            print
            o = gsub(/[{\[]/, "&")
            c = gsub(/[}\]]/, "&")
            depth += o - c
            saw = (o + c) > 0
            if ((NR > start || saw) && depth <= 0) { exit }
            if (NR - start + 1 >= maxlines) {
                print "/* CORTE DE SEGURIDAD a " maxlines " líneas sin cerrar el balance -- revisar a mano */"
                exit
            }
        }
    ' "$file"
}

# Búsqueda global por nombre, sin ancla. Aborta (exit 1, sin escribir
# nada) si hay 0 o más de 1 coincidencia del patrón de localización --
# nunca concatena algo potencialmente equivocado al oráculo.
extract_js_def_or_fail() {
    local file="$1" name="$2" max_lines="${3:-3000}"
    local pattern="(const|let|var)[[:space:]]+${name}\b|function[[:space:]]+${name}\b|\\b${name}[[:space:]]*="
    local count line
    count=$(grep -c -E "$pattern" "$file" 2>/dev/null || true)
    if [[ "${count:-0}" -eq 0 ]]; then
        echo "ERROR: no se encontró la definición de '$name' en $file (ni por ancla ni por búsqueda global)." >&2
        exit 1
    fi
    if [[ "${count:-0}" -gt 1 ]]; then
        echo "ERROR: '$name' coincide $count veces en $file -- ambiguo, revisar a mano antes de generar el oráculo." >&2
        exit 1
    fi
    line=$(grep -n -m1 -E "$pattern" "$file" | cut -d: -f1)
    extract_js_block "$file" "$line" "$max_lines"
}

# Ancla primero a la línea real ya confirmada (KNOWN_LINES, acumulada en
# pasadas anteriores de check_autocapture_triggers.sh). Si esa línea ya
# no coincide con el patrón de localización de $name (el navegador
# cambió desde la última auditoría), cae a extract_js_def_or_fail -- una
# búsqueda global que aborta ante cualquier ambigüedad, nunca asume la
# línea vieja a ciegas.
extract_js_def_anchored() {
    local file="$1" name="$2" known_line="$3" max_lines="${4:-3000}"
    local pattern="(const|let|var)[[:space:]]+${name}\b|function[[:space:]]+${name}\b|\\b${name}[[:space:]]*="
    if [[ -n "$known_line" ]] && sed -n "${known_line}p" "$file" | grep -qE "$pattern"; then
        extract_js_block "$file" "$known_line" "$max_lines"
        return 0
    fi
    echo "AVISO: la línea conocida ($known_line) para '$name' ya no coincide en $file -- recurriendo a búsqueda global con comprobación de ambigüedad (no se asume la línea vieja a ciegas)." >&2
    extract_js_def_or_fail "$file" "$name" "$max_lines"
}

# Líneas reales confirmadas (acumuladas en docs/pipeline/pregunta5_5b,
# 5c, 5d, 9 y 10_salida.txt) la última vez que se auditó el archivo real
# -- solo un punto de partida para el ancla, nunca la fuente de verdad
# (si difieren, extract_js_def_anchored cae a la búsqueda global).
declare -A KNOWN_LINES=(
    [MAX_RAW_SCORE]=608 [STRATEGY_META]=614 [emaArr]=712 [calcRSI]=731
    [calcMACD]=747 [calcATR]=762 [calcADX]=776 [calcRVOL]=812
    [calcVWAP]=820 [calcCompression]=829 [calcGapPct]=839
    [computeIndicators]=845 [f]=871 [finalizeVerdict]=873 [mkResult]=881
    [mkNA]=890 [tickerHardNo]=893 [evalST01]=899 [evalST05]=934
    [evalST06]=946 [evalST09]=959 [evalST11]=979 [evalST15]=995
    [evalST16]=1007 [evalSC01]=1019 [evalSC02]=1033 [evalSCPB]=1048
    [NYSE_STRATEGIES]=1068 [CRYPTO_STRATEGIES]=1069
    [applyEventAdjustments]=1074 [evaluateTicker]=1114
    [detectAutoTrigger]=2669
)

# Orden de extracción -- irrelevante en la práctica para la validez del
# JS resultante: las 28 funciones usan la forma "function nombre(...)",
# hoisted por el motor JS sin importar el orden textual; los 4 const
# (MAX_RAW_SCORE, STRATEGY_META, NYSE_STRATEGIES, CRYPTO_STRATEGIES)
# solo contienen literales y referencias a esas funciones ya hoisted,
# nunca a otro const -- se mantiene este orden solo por legibilidad.
ORDER=(MAX_RAW_SCORE STRATEGY_META emaArr calcRSI calcMACD calcATR calcADX
       calcRVOL calcVWAP calcCompression calcGapPct computeIndicators f
       finalizeVerdict mkResult mkNA tickerHardNo evalST01 evalST05
       evalST06 evalST09 evalST11 evalST15 evalST16 evalSC01 evalSC02
       evalSCPB NYSE_STRATEGIES CRYPTO_STRATEGIES applyEventAdjustments
       evaluateTicker detectAutoTrigger)

echo "=== 1. Extrayendo las 32 piezas de $SCANNER_HTML ==="
EXTRACTED_JS="$OUT_DIR/oraculo_extracted.js"
{
    echo "// Extraído de $SCANNER_HTML el $(date -u +%Y-%m-%dT%H:%M:%SZ) por generar_oraculo_evaluate_js.sh"
    echo "// NO EDITAR A MANO -- regenerar con el script si el navegador cambia."
    echo
    for name in "${ORDER[@]}"; do
        echo "// --- $name ---"
        extract_js_def_anchored "$SCANNER_HTML" "$name" "${KNOWN_LINES[$name]}" 3000
        echo
    done
} > "$EXTRACTED_JS"
echo "Escrito: $EXTRACTED_JS"

if ! node --check "$EXTRACTED_JS" 2>&1; then
    echo "ERROR: el JS extraído no es sintácticamente válido -- revisar $EXTRACTED_JS a mano." >&2
    exit 1
fi
echo "OK: $EXTRACTED_JS parsea como JS válido."

echo
echo "=== 2. Universo de tickers ==="
if [[ "${TICKERS+x}" ]]; then
    echo "Override por CLI (${#TICKERS[@]} tickers) -- no se consulta 14_UNIVERSO_TICKERS."
else
    echo "Cargando desde 14_UNIVERSO_TICKERS (cargar_universo_de_tickers(), ESTADO=ACTIVO, excluye CRYPTO)..."
    mapfile -t TICKERS < <(
        PYTHONPATH="$SNAPSHOT_AUTOCAPTURE_DIR${PYTHONPATH:+:$PYTHONPATH}" python3 -c "
import snapshot_autocapture as sa
for u in sa.cargar_universo_de_tickers():
    print(u.ticker)
"
    )
    if [[ "${#TICKERS[@]}" -eq 0 ]]; then
        echo "ERROR: cargar_universo_de_tickers() no devolvió ningún ticker -- revisar 14_UNIVERSO_TICKERS, AXONIK_DECISION_ENGINE_SHEET_ID o las credenciales de gspread." >&2
        exit 1
    fi
fi
echo "Tickers: ${TICKERS[*]}"

echo
echo "=== 3. Velas reales por ticker (POST /api/scan-batch, lotes adaptativos si hace falta) ==="
python3 - "$PROXY_BASE" "$OUT_DIR" "${TICKERS[@]}" <<'PYEOF'
import json, re, sys
import requests

proxy_base, out_dir = sys.argv[1], sys.argv[2]
tickers = sys.argv[3:]


def do_batch(subset):
    return requests.post(f"{proxy_base}/api/scan-batch", json={"tickers": subset}, timeout=60)


resp = do_batch(tickers)
if resp.status_code == 200:
    batches = [(tickers, resp.json())]
elif resp.status_code == 400:
    try:
        detail = resp.json().get("detail", "")
    except Exception:
        detail = resp.text
    m = re.search(r"\d+", detail)
    if not m:
        print(f"ERROR: scan-batch devolvió 400 pero no se pudo extraer un límite numérico "
              f"del mensaje de error (detail={detail!r}) -- abortando, no se adivina un "
              f"tamaño de lote.", file=sys.stderr)
        sys.exit(1)
    limit = int(m.group(0))
    if limit <= 0:
        print(f"ERROR: límite parseado inválido ({limit}) -- abortando.", file=sys.stderr)
        sys.exit(1)
    print(f"AVISO: scan-batch limita a {limit} tickers por lote (MAX_BATCH_TICKERS real, "
          f"nunca confirmado como número literal) -- troceando {len(tickers)} tickers.",
          file=sys.stderr)
    chunks = [tickers[i:i + limit] for i in range(0, len(tickers), limit)]
    batches = []
    for chunk in chunks:
        r = do_batch(chunk)
        if r.status_code != 200:
            print(f"ERROR: el lote {chunk} devolvió HTTP {r.status_code} (cuerpo: {r.text}) "
                  f"-- abortando sin escribir fixtures parciales.", file=sys.stderr)
            sys.exit(1)
        batches.append((chunk, r.json()))
else:
    print(f"ERROR: scan-batch devolvió HTTP {resp.status_code} (ni 200 ni 400) -- "
          f"cuerpo: {resp.text}", file=sys.stderr)
    sys.exit(1)

# Emparejado siempre por ticker, nunca por índice -- mismo criterio que
# snapshot_autocapture.py y generar_fixtures_js.sh.
merged = {}
for chunk, body in batches:
    for item in body.get("results", []):
        t = item.get("ticker")
        if t in merged:
            print(f"ERROR: el ticker {t} aparece en más de un lote de la respuesta -- "
                  f"abortando, algo inconsistente en el troceado.", file=sys.stderr)
            sys.exit(1)
        merged[t] = item

missing = [t for t in tickers if t not in merged]
if missing:
    print(f"ERROR: los tickers {missing} no aparecieron en ninguna respuesta de "
          f"scan-batch -- abortando.", file=sys.stderr)
    sys.exit(1)

# Solo se escribe una vez que toda la fusión de lotes está validada --
# ningún fichero parcial si algo de arriba abortó primero.
written = []
for t in tickers:
    item = merged[t]
    if item.get("error"):
        print(f"AVISO: scan-batch devolvió error para {t}: {item['error']} -- se omite.",
              file=sys.stderr)
        continue
    data = item.get("data") or {}
    any_tf = False
    for tf in ("1d", "1h", "15m"):
        tf_data = data.get(tf)
        if not tf_data or not tf_data.get("candles") or tf_data.get("error"):
            continue
        with open(f"{out_dir}/{t}_{tf}_candles.json", "w") as f:
            json.dump(tf_data["candles"], f, indent=2)
        any_tf = True
        written.append(f"{t}_{tf}")
    if not any_tf:
        print(f"AVISO: {t} sin velas en ningún timeframe -- se omite del oráculo.",
              file=sys.stderr)

print(f"Escritas velas para: {', '.join(written) if written else '(ninguna)'}")
PYEOF

echo
echo "=== 4. Ejecutando Node real (evaluateTicker + detectAutoTrigger) por ticker ==="
DRIVER_JS="$OUT_DIR/_driver.js"
cat > "$DRIVER_JS" <<'DRIVER_EOF'
const fs = require('fs');
const [, , extractedPath, outDir, ticker] = process.argv;

eval(fs.readFileSync(extractedPath, 'utf8'));

// Solo las 3 claves que de verdad consume la cadena evaluateTicker()/
// tickerHardNo() -- el DEFAULT_SETTINGS real completo trae además
// capital/riskPct, que esta cadena no toca (confirmado Pregunta 6d).
const DEFAULT_SETTINGS = { priceMin: 8, atrMax: 4, rvolMin: 1 };

function loadCandles(tf) {
    const p = `${outDir}/${ticker}_${tf}_candles.json`;
    if (!fs.existsSync(p)) return null;
    return JSON.parse(fs.readFileSync(p, 'utf8'));
}

const ind = {};
for (const tf of ['1d', '1h', '15m']) {
    const candles = loadCandles(tf);
    // Mismo criterio que el navegador (fetchNyseTicker(), Pregunta 8) y
    // que build_ind() en evaluate_ticker_logic.py: sin velas, ind[tf]=null.
    ind[tf] = candles ? computeIndicators(candles, tf) : null;
}

const evalResult = evaluateTicker(ticker, ind, null, 'NYSE', DEFAULT_SETTINGS, false, null);
const triggerResult = detectAutoTrigger(evalResult);

// NaN no es JSON válido -- mismo sentinela de texto "NaN" que
// evaluate_ticker_logic.nan_to_json_sentinel() en el lado Python, para
// que la prueba de comparación pueda comparar NaN contra NaN sin
// ambigüedad.
const nanSafeReplacer = (_, v) => (typeof v === 'number' && Number.isNaN(v)) ? 'NaN' : v;
fs.writeFileSync(`${outDir}/${ticker}_evaluate_output.json`,
    JSON.stringify(evalResult, nanSafeReplacer, 2));
fs.writeFileSync(`${outDir}/${ticker}_trigger_output.json`,
    JSON.stringify(triggerResult, nanSafeReplacer, 2));
console.log(`escrito: ${ticker}_evaluate_output.json, ${ticker}_trigger_output.json`);
DRIVER_EOF

for ticker in "${TICKERS[@]}"; do
    if [[ ! -r "$OUT_DIR/${ticker}_1d_candles.json" ]] && [[ ! -r "$OUT_DIR/${ticker}_1h_candles.json" ]] \
       && [[ ! -r "$OUT_DIR/${ticker}_15m_candles.json" ]]; then
        echo "  (sin velas para $ticker en ningún timeframe, omitido -- ver aviso de arriba)"
        continue
    fi
    echo "  ejecutando Node sobre $ticker..."
    node "$DRIVER_JS" "$EXTRACTED_JS" "$OUT_DIR" "$ticker"
done

rm -f "$DRIVER_JS"

echo
echo "=== Fin. Fixtures en $OUT_DIR: ==="
echo "  - oraculo_extracted.js (JS real ejecutado, para inspección)"
echo "  - <TICKER>_<TF>_candles.json (velas de entrada, congeladas)"
echo "  - <TICKER>_evaluate_output.json (salida real de evaluateTicker())"
echo "  - <TICKER>_trigger_output.json (salida real de detectAutoTrigger())"
echo
echo "Haz commit y push de docs/pipeline/fixtures_js/oraculo_evaluate/ para poder"
echo "ejecutar la prueba de comparación contra POST /api/evaluate-ticker."
