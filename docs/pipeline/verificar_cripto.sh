#!/usr/bin/env bash
# UN SOLO COMANDO para verificar la ruta CRIPTO (BTC/ETH/SOL) del puerto
# contra el JS real del navegador, pensado para ejecutarse en el
# servidor (tiene git, Node 24, acceso a Binance y al repo real). No
# toca market_data_proxy.py, no habilita ningún timer, no despliega nada.
#
# Qué hace, en orden:
#   1. git pull (rama actual) -- para tener este mismo script y el resto
#      del código al día antes de extraer/ejecutar nada.
#   2. Extrae de /opt/axonik/scanner/index.html las mismas 32 piezas que
#      ya usa generar_oraculo_evaluate_js.sh (evaluateTicker,
#      detectAutoTrigger, las 3 evalSC/10 evalST, computeIndicators + 9
#      funciones, etc. -- NYSE y CRYPTO comparten código, ya confirmado)
#      con la misma extracción anclada + aborto por ambigüedad. Además
#      intenta extraer computeMarketContext() (el gate BTC, Pregunta 11
#      de check_autocapture_triggers.sh) -- a diferencia de las 32, esta
#      pieza es OPCIONAL: si no se encuentra o es ambigua, NO aborta el
#      script, degrada el gate a OFF (False) con un aviso, porque la
#      propia Pregunta 11 sigue sin confirmarse (docs/pipeline/BLOQUEOS.md).
#   3. Pide velas reales de Binance para BTC/ETH/SOL directamente (mismos
#      símbolos/intervalos/límites que fetchBinanceKlines: {ticker}USDT,
#      1d×120, 1h×100, 15m×96) -- no via /api/scan-batch, que es NYSE-only
#      (confirmado: fetchCryptoTicker() nunca llama a scan-batch).
#   4. Bajo Node real ejecuta evaluateTicker(t, ind, null, 'CRYPTO',
#      DEFAULT_SETTINGS, btcGateOn, null) + detectAutoTrigger() con el
#      gate BTC real (o degradado, paso 2) -- mismo btcGateOn para los
#      tres tickers, igual que runScan() en el navegador.
#   5. Compara contra evaluate_ticker_logic.evaluate_ticker() (el puerto
#      Python) con el MISMO btcGateOn -- campo a campo, tolerancia 1e-9:
#      hardNo/globalVerdict/globalScore y, por estrategia (SC-01/SC-02/
#      SC-PB), applicable/score/verdict.
#   5b. Si FORCE_BTC_GATE_ON=1: repite los pasos 4-5 con btcGateOn FORZADO
#      a true en los dos lados (JS y Python), MISMAS velas reales --
#      ejercita las ramas de scoring de SC-02/SC-PB que con el gate real
#      (normalmente OFF) nunca se prueban. Es un TEST DE EQUIVALENCIA DE
#      LÓGICA (¿el puerto calcula igual que el JS cuando el gate está
#      ON?), NO una señal de mercado real -- el informe lo marca como tal
#      y dice qué ramas (SC-01/SC-02/SC-PB, aplicable o con qué naReason)
#      quedaron ejercitadas con cada ticker.
#   6. Imprime un informe corto (PASA/FALLA por ticker/estrategia + estado
#      del gate, + la pasada de gate forzado si se pidió) y guarda la
#      salida completa (candles, JS extraído, resultados Node y Python,
#      diff) en docs/pipeline/.
#   7. git add + commit + push de esa salida a la rama actual. Si el push
#      falla (red, auth, conflicto), NO se pierde el resultado: se
#      imprime el informe completo por stdout para pegarlo a mano.
#
# Requiere: git, node (v24 recomendado, cualquier v18+ con fetch nativo
# sirve), python3 (con evaluate_ticker_logic.py/indicator_calc.py ya
# copiados o en services/snapshot-autocapture/), acceso de salida a
# Binance (api.binance.com).
#
# Uso:
#   docs/pipeline/verificar_cripto.sh
#   SCANNER_HTML=/otra/ruta/index.html BINANCE_BASE=https://api.binance.com \
#     docs/pipeline/verificar_cripto.sh
#   FORCE_BTC_GATE_ON=1 docs/pipeline/verificar_cripto.sh
#     -- añade la pasada 5b (equivalencia de lógica SC-02/SC-PB con el
#        gate ON), sin tocar el resultado real de la pasada normal.

set -uo pipefail  # sin -e: el script decide explícitamente cuándo abortar

SCANNER_HTML="${SCANNER_HTML:-/opt/axonik/scanner/index.html}"
BINANCE_BASE="${BINANCE_BASE:-https://api.binance.com}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
PY_DIR="${PY_DIR:-$REPO_ROOT/services/snapshot-autocapture}"
TS="$(date -u +%Y%m%dT%H%M%SZ)"
OUT_DIR="${OUT_DIR:-$SCRIPT_DIR/fixtures_js/oraculo_cripto}"
REPORT_FULL="$SCRIPT_DIR/verificacion_cripto_${TS}.txt"
TICKERS=(BTC ETH SOL)
KLINE_LIMITS_1D=120
KLINE_LIMITS_1H=100
KLINE_LIMITS_15M=96

mkdir -p "$OUT_DIR"
: > "$REPORT_FULL"
log_full() { echo "$@" | tee -a "$REPORT_FULL"; }

ABORTED=0
abort() {
    log_full "ABORTADO: $*"
    ABORTED=1
}

# --- Paso 1: git pull -------------------------------------------------------
log_full "=== 1. git pull ($(date -u +%Y-%m-%dT%H:%M:%SZ)) ==="
if ! git -C "$REPO_ROOT" pull --ff-only >>"$REPORT_FULL" 2>&1; then
    abort "git pull --ff-only falló -- revisar el estado del checkout a mano (¿cambios locales sin commitear, rama divergida?). No se extrae ni se verifica nada hasta resolverlo."
fi

if [[ "$ABORTED" -eq 1 ]]; then
    cat "$REPORT_FULL"
    exit 1
fi

if [[ ! -r "$SCANNER_HTML" ]]; then
    abort "no se puede leer $SCANNER_HTML (¿ruta incorrecta o permisos? probar con sudo)"
    cat "$REPORT_FULL"
    exit 1
fi
if ! command -v node >/dev/null 2>&1; then
    abort "no se encuentra 'node' en el PATH"
    cat "$REPORT_FULL"
    exit 1
fi
if ! command -v python3 >/dev/null 2>&1; then
    abort "no se encuentra 'python3' en el PATH"
    cat "$REPORT_FULL"
    exit 1
fi

# --- Extracción por balance de llaves/corchetes (misma corrección que
#     generar_oraculo_evaluate_js.sh: corta también si la propia línea de
#     inicio ya cierra sus corchetes, para no "sangrar" a la línea
#     siguiente en sentencias de una sola línea como los const). ---
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

# Búsqueda global por nombre. echo_err: si "abort_on_fail"=1, aborta todo
# el script con exit 1 ante 0 o >1 coincidencias (las 32 piezas
# obligatorias). Si "abort_on_fail"=0 (solo computeMarketContext), NO
# aborta -- devuelve estado por código de salida (0 encontrado, 1 no) para
# que el llamador decida el fallback.
extract_js_def_or_fail() {
    local file="$1" name="$2" max_lines="$3" abort_on_fail="$4"
    local pattern="(const|let|var)[[:space:]]+${name}\b|function[[:space:]]+${name}\b|\\b${name}[[:space:]]*="
    local count line
    count=$(grep -c -E "$pattern" "$file" 2>/dev/null || true)
    if [[ "${count:-0}" -ne 1 ]]; then
        if [[ "$abort_on_fail" -eq 1 ]]; then
            abort "'$name' tiene ${count:-0} coincidencias en $SCANNER_HTML (se esperaba exactamente 1) -- ambiguo o ausente, revisar a mano antes de verificar nada."
            return 1
        fi
        return 1
    fi
    line=$(grep -n -m1 -E "$pattern" "$file" | cut -d: -f1)
    extract_js_block "$file" "$line" "$max_lines"
    return 0
}

extract_js_def_anchored() {
    local file="$1" name="$2" known_line="$3" max_lines="${4:-3000}" abort_on_fail="${5:-1}"
    local pattern="(const|let|var)[[:space:]]+${name}\b|function[[:space:]]+${name}\b|\\b${name}[[:space:]]*="
    if [[ -n "$known_line" ]] && sed -n "${known_line}p" "$file" | grep -qE "$pattern"; then
        extract_js_block "$file" "$known_line" "$max_lines"
        return 0
    fi
    extract_js_def_or_fail "$file" "$name" "$max_lines" "$abort_on_fail"
}

# Mismas 32 piezas y mismas líneas conocidas que
# generar_oraculo_evaluate_js.sh -- NYSE y CRYPTO comparten evaluateTicker/
# detectAutoTrigger/mkResult/mkNA/finalizeVerdict/f/STRATEGY_META/
# MAX_RAW_SCORE/computeIndicators+9 funciones; las únicas estrategias que
# importan aquí son evalSC01/evalSC02/evalSCPB (también incluidas).
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
ORDER=(MAX_RAW_SCORE STRATEGY_META emaArr calcRSI calcMACD calcATR calcADX
       calcRVOL calcVWAP calcCompression calcGapPct computeIndicators f
       finalizeVerdict mkResult mkNA tickerHardNo evalST01 evalST05
       evalST06 evalST09 evalST11 evalST15 evalST16 evalSC01 evalSC02
       evalSCPB NYSE_STRATEGIES CRYPTO_STRATEGIES applyEventAdjustments
       evaluateTicker detectAutoTrigger)

echo
log_full "=== 2. Extrayendo las 32 piezas comunes + computeMarketContext (opcional) ==="
EXTRACTED_JS="$OUT_DIR/oraculo_cripto_extracted.js"
{
    echo "// Extraído de $SCANNER_HTML el $(date -u +%Y-%m-%dT%H:%M:%SZ) por verificar_cripto.sh"
    echo "// NO EDITAR A MANO."
    echo
    for name in "${ORDER[@]}"; do
        echo "// --- $name ---"
        extract_js_def_anchored "$SCANNER_HTML" "$name" "${KNOWN_LINES[$name]}" 3000 1
        echo
    done
} > "$EXTRACTED_JS"

if [[ "$ABORTED" -eq 1 ]]; then
    cat "$REPORT_FULL"
    exit 1
fi

if ! node --check "$EXTRACTED_JS" >>"$REPORT_FULL" 2>&1; then
    abort "el JS extraído no es sintácticamente válido -- revisar $EXTRACTED_JS a mano."
    cat "$REPORT_FULL"
    exit 1
fi
log_full "OK: $EXTRACTED_JS parsea como JS válido (32/32 piezas obligatorias)."

# computeMarketContext: OPCIONAL -- sin línea conocida (nunca se ha
# confirmado, Pregunta 11 pendiente). Si no se encuentra/es ambiguo, NO
# aborta: degrada el gate a OFF más abajo, con aviso.
GATE_JS="$OUT_DIR/compute_market_context_extracted.js"
GATE_REAL_DISPONIBLE=0
if extract_js_def_or_fail "$SCANNER_HTML" "computeMarketContext" 300 0 > "$GATE_JS" 2>/dev/null \
   && node --check "$GATE_JS" >/dev/null 2>&1; then
    GATE_REAL_DISPONIBLE=1
    log_full "OK: computeMarketContext() encontrado y parsea -- se intentará ejecutar de verdad."
else
    log_full "AVISO: computeMarketContext() no encontrado o ambiguo en $SCANNER_HTML (Pregunta 11 de"
    log_full "  check_autocapture_triggers.sh sigue pendiente, ver docs/pipeline/BLOQUEOS.md) --"
    log_full "  el gate BTC se degrada a OFF (False) para esta verificación, EN LOS DOS LADOS"
    log_full "  (Node y Python), para comparar la aritmética de scoring, no el gate en sí."
    rm -f "$GATE_JS"
fi

# --- Paso 3: velas reales de Binance para BTC/ETH/SOL -----------------------
echo
log_full "=== 3. Velas reales de Binance (BTC/ETH/SOL) ==="
for ticker in "${TICKERS[@]}"; do
    symbol="${ticker}USDT"
    for spec in "1d:$KLINE_LIMITS_1D" "1h:$KLINE_LIMITS_1H" "15m:$KLINE_LIMITS_15M"; do
        tf="${spec%%:*}"; limit="${spec##*:}"
        out_json="$OUT_DIR/${ticker}_${tf}_candles.json"
        http_code=$(curl -sS -o "$OUT_DIR/${ticker}_${tf}_raw.json" -w '%{http_code}' \
            "$BINANCE_BASE/api/v3/klines?symbol=${symbol}&interval=${tf}&limit=${limit}")
        if [[ "$http_code" != "200" ]]; then
            abort "Binance devolvió HTTP $http_code para $symbol/$tf (cuerpo: $(cat "$OUT_DIR/${ticker}_${tf}_raw.json"))"
            continue
        fi
        python3 -c "
import json, sys
raw = json.load(open('$OUT_DIR/${ticker}_${tf}_raw.json'))
candles = [{'t': int(k[0]//1000), 'o': float(k[1]), 'h': float(k[2]), 'l': float(k[3]), 'c': float(k[4]), 'v': float(k[5])} for k in raw]
json.dump(candles, open('$out_json', 'w'), indent=2)
" || abort "no se pudo convertir las velas de $symbol/$tf a formato candle"
        rm -f "$OUT_DIR/${ticker}_${tf}_raw.json"
    done
    log_full "  $ticker: velas 1d/1h/15m guardadas en $OUT_DIR"
done

if [[ "$ABORTED" -eq 1 ]]; then
    cat "$REPORT_FULL"
    exit 1
fi

# --- Paso 4: Node real -- evaluateTicker + detectAutoTrigger + gate -------
echo
log_full "=== 4. Ejecutando Node real (evaluateTicker CRYPTO + detectAutoTrigger + gate BTC) ==="
# forceGate: "" (usa el gate real/degradado, vía computeGate()) | "true" |
#            "false" -- override explícito, sin tocar computeMarketContext().
#            Usado por la pasada de FORCE_BTC_GATE_ON (equivalencia de
#            lógica SC-02/SC-PB con gate ON, ver más abajo).
# suffix: "" para la pasada normal, "_gateon" para la forzada -- nunca
#         pisa los ficheros de la pasada normal.
DRIVER_JS="$OUT_DIR/_driver.js"
cat > "$DRIVER_JS" <<'DRIVER_EOF'
const fs = require('fs');
const [, , extractedPath, gatePath, outDir, tickersCsv, forceGateArg, suffixArg] = process.argv;
const tickers = tickersCsv.split(',');
const forceGate = forceGateArg === 'true' ? true : (forceGateArg === 'false' ? false : null);
const suffix = suffixArg || '';

eval(fs.readFileSync(extractedPath, 'utf8'));

const DEFAULT_SETTINGS = { priceMin: 8, atrMax: 4, rvolMin: 1 };

function loadCandles(ticker, tf) {
    const p = `${outDir}/${ticker}_${tf}_candles.json`;
    if (!fs.existsSync(p)) return null;
    return JSON.parse(fs.readFileSync(p, 'utf8'));
}

async function computeGate() {
    if (!gatePath || !fs.existsSync(gatePath)) return { gateOn: false, real: false, error: null };
    try {
        eval(fs.readFileSync(gatePath, 'utf8'));
        // runScan() real: state.marketContext = await computeMarketContext(mode);
        // btcGateOn = state.marketContext ? state.marketContext.gateOn : false.
        const ctx = await computeMarketContext('CRYPTO');
        return { gateOn: !!(ctx && ctx.gateOn), real: true, error: null };
    } catch (e) {
        return { gateOn: false, real: false, error: (e && e.message) || String(e) };
    }
}

(async () => {
    const gate = forceGate !== null ? { gateOn: forceGate, real: false, error: null, forced: true }
                                     : await computeGate();
    fs.writeFileSync(`${outDir}/_gate${suffix}.json`, JSON.stringify(gate, null, 2));

    const nanSafeReplacer = (_, v) => (typeof v === 'number' && Number.isNaN(v)) ? 'NaN' : v;
    for (const ticker of tickers) {
        const ind = {};
        for (const tf of ['1d', '1h', '15m']) {
            const candles = loadCandles(ticker, tf);
            ind[tf] = candles ? computeIndicators(candles, tf) : null;
        }
        const evalResult = evaluateTicker(ticker, ind, null, 'CRYPTO', DEFAULT_SETTINGS, gate.gateOn, null);
        const triggerResult = detectAutoTrigger(evalResult);
        fs.writeFileSync(`${outDir}/${ticker}_evaluate_output${suffix}.json`,
            JSON.stringify(evalResult, nanSafeReplacer, 2));
        fs.writeFileSync(`${outDir}/${ticker}_trigger_output${suffix}.json`,
            JSON.stringify(triggerResult, nanSafeReplacer, 2));
    }
    console.log(`Node: escritos _gate${suffix}.json + <TICKER>_evaluate_output${suffix}.json/_trigger_output${suffix}.json`);
})();
DRIVER_EOF

TICKERS_CSV=$(IFS=,; echo "${TICKERS[*]}")
if ! node "$DRIVER_JS" "$EXTRACTED_JS" "${GATE_JS:-}" "$OUT_DIR" "$TICKERS_CSV" "" "" >>"$REPORT_FULL" 2>&1; then
    abort "el driver de Node falló -- ver $REPORT_FULL para el error completo."
    cat "$REPORT_FULL"
    exit 1
fi

GATE_ON="false"
GATE_DESC="OFF (degradado)"
if [[ -f "$OUT_DIR/_gate.json" ]]; then
    GATE_ON=$(python3 -c "import json; print(str(json.load(open('$OUT_DIR/_gate.json'))['gateOn']).lower())")
    GATE_IS_REAL=$(python3 -c "import json; print(str(json.load(open('$OUT_DIR/_gate.json'))['real']).lower())")
    GATE_ERR=$(python3 -c "import json; print(json.load(open('$OUT_DIR/_gate.json')).get('error') or '')")
    if [[ "$GATE_IS_REAL" == "true" ]]; then
        GATE_DESC="$([[ "$GATE_ON" == "true" ]] && echo "ON (real)" || echo "OFF (real)")"
    else
        GATE_DESC="OFF (degradado$( [[ -n "$GATE_ERR" ]] && echo ", computeMarketContext lanzó: $GATE_ERR" ))"
    fi
fi
log_full "Gate BTC: $GATE_DESC"

# Pasada adicional opcional: gate FORZADO a ON en los dos lados (JS y
# Python), mismas velas reales -- test de EQUIVALENCIA DE LÓGICA de
# SC-02/SC-PB (sus ramas de scoring con el gate ON), no una señal de
# mercado real. Solo si FORCE_BTC_GATE_ON está activo -- nunca se activa
# sola ni cambia el resultado/gate de la pasada normal de arriba.
FORCE_GATE_RAN=0
if [[ "${FORCE_BTC_GATE_ON:-0}" =~ ^(1|true|TRUE|yes)$ ]]; then
    echo
    log_full "=== 4b. Pasada adicional: gate BTC FORZADO a ON (equivalencia de lógica, NO señal de mercado) ==="
    if ! node "$DRIVER_JS" "$EXTRACTED_JS" "${GATE_JS:-}" "$OUT_DIR" "$TICKERS_CSV" "true" "_gateon" >>"$REPORT_FULL" 2>&1; then
        abort "el driver de Node (gate forzado) falló -- ver $REPORT_FULL."
        cat "$REPORT_FULL"
        exit 1
    fi
    FORCE_GATE_RAN=1
fi
rm -f "$DRIVER_JS"

# --- Paso 5: comparar contra el puerto Python --------------------------------
# Script reutilizable (se llama una vez con el gate real/degradado, y una
# segunda vez con el gate forzado a ON si FORCE_BTC_GATE_ON está activo) --
# acepta un sufijo para no mezclar los ficheros de las dos pasadas.
COMPARE_PY="$OUT_DIR/_compare.py"
cat > "$COMPARE_PY" <<'PYEOF'
import json, math, sys

import evaluate_ticker_logic as etl

out_dir, gate_on_str, tickers_csv, compare_json_path, suffix = sys.argv[1:6]
gate_on = gate_on_str == "true"
tickers = tickers_csv.split(",")
settings = {"priceMin": 8, "atrMax": 4, "rvolMin": 1}


def close(a, b, tol=1e-9):
    if isinstance(b, float) and math.isnan(b):
        return isinstance(a, float) and math.isnan(a)
    if isinstance(b, (int, float)) and not isinstance(b, bool):
        return isinstance(a, (int, float)) and math.isclose(a, b, rel_tol=tol, abs_tol=tol)
    return a == b


results = {}
for ticker in tickers:
    data = {}
    for tf in ("1d", "1h", "15m"):
        p = f"{out_dir}/{ticker}_{tf}_candles.json"
        try:
            candles = json.load(open(p))
        except FileNotFoundError:
            continue
        data[tf] = {"candles": candles, "periods": len(candles)}
    ind = etl.build_ind(data)
    py_result = etl.evaluate_ticker(ticker, ind, None, "CRYPTO", settings, gate_on, None)
    py_trigger = etl.detect_auto_trigger(py_result)

    js_result = json.load(open(f"{out_dir}/{ticker}_evaluate_output{suffix}.json"))
    js_result = etl.sentinel_to_nan(js_result)
    js_trigger = json.load(open(f"{out_dir}/{ticker}_trigger_output{suffix}.json"))
    js_trigger = etl.sentinel_to_nan(js_trigger)

    diffs = []
    if not close(py_result["hardNo"], js_result["hardNo"]):
        diffs.append(f"hardNo: py={py_result['hardNo']!r} js={js_result['hardNo']!r}")
    if not close(py_result["globalVerdict"], js_result["globalVerdict"]):
        diffs.append(f"globalVerdict: py={py_result['globalVerdict']!r} js={js_result['globalVerdict']!r}")
    if not close(py_result["globalScore"], js_result["globalScore"]):
        diffs.append(f"globalScore: py={py_result['globalScore']!r} js={js_result['globalScore']!r}")

    py_by_id = {s["id"]: s for s in py_result["strategies"]}
    js_by_id = {s["id"]: s for s in js_result["strategies"]}
    estrategias = {}
    for sid in sorted(set(py_by_id) | set(js_by_id)):
        ps, js = py_by_id.get(sid), js_by_id.get(sid)
        if ps is None or js is None:
            diffs.append(f"{sid}: falta en {'Python' if ps is None else 'JS'}")
            continue
        for field in ("applicable", "score", "verdict"):
            if not close(ps.get(field), js.get(field)):
                diffs.append(f"{sid}.{field}: py={ps.get(field)!r} js={js.get(field)!r}")
        # applicable/naReason -- para el resumen de "qué ramas se
        # ejercitaron" en la pasada de gate forzado (ver más abajo).
        estrategias[sid] = {"applicable": bool(js.get("applicable")),
                             "naReason": js.get("naReason")}

    trigger_diffs = []
    if (py_trigger is None) != (js_trigger is None):
        trigger_diffs.append(f"trigger: py={py_trigger!r} js={js_trigger!r}")
    elif py_trigger is not None:
        if py_trigger["type"] != js_trigger["type"]:
            trigger_diffs.append(f"trigger.type: py={py_trigger['type']!r} js={js_trigger['type']!r}")
        if sorted(s["id"] for s in py_trigger["strategies"]) != sorted(s["id"] for s in js_trigger["strategies"]):
            trigger_diffs.append(f"trigger.strategies: py={sorted(s['id'] for s in py_trigger['strategies'])!r} "
                                  f"js={sorted(s['id'] for s in js_trigger['strategies'])!r}")

    results[ticker] = {"diffs": diffs, "trigger_diffs": trigger_diffs,
                        "pasa": not diffs and not trigger_diffs,
                        "estrategias": estrategias}
    print(f"--- {ticker} ---")
    print(f"  PASA" if results[ticker]["pasa"] else f"  FALLA:")
    for d in diffs + trigger_diffs:
        print(f"    {d}")

json.dump(results, open(compare_json_path, "w"), indent=2, ensure_ascii=False)
PYEOF

run_compare_pass() {
    local gate_value="$1" suffix="$2" label="$3" compare_json="$4"
    echo
    log_full "=== $label ==="
    PYTHONPATH="$PY_DIR${PYTHONPATH:+:$PYTHONPATH}" python3 "$COMPARE_PY" \
        "$OUT_DIR" "$gate_value" "$TICKERS_CSV" "$compare_json" "$suffix" >>"$REPORT_FULL" 2>&1
    if [[ ! -f "$compare_json" ]]; then
        log_full "ERROR: no se generó $compare_json -- ver detalle arriba ($REPORT_FULL)."
        ABORTED=1
    fi
}

COMPARE_JSON="$OUT_DIR/_comparacion.json"
run_compare_pass "$GATE_ON" "" "5. Comparando contra evaluate_ticker_logic.py (tolerancia 1e-9)" "$COMPARE_JSON"

COMPARE_JSON_GATEON="$OUT_DIR/_comparacion_gateon.json"
if [[ "$FORCE_GATE_RAN" -eq 1 ]]; then
    run_compare_pass "true" "_gateon" \
        "5b. Comparando con gate FORZADO a ON (equivalencia de lógica SC-02/SC-PB)" \
        "$COMPARE_JSON_GATEON"
fi
rm -f "$COMPARE_PY"

echo
log_full "=== INFORME CORTO ==="
log_full "Gate BTC: $GATE_DESC"
if [[ -f "$COMPARE_JSON" ]]; then
    while IFS= read -r line; do log_full "$line"; done < <(python3 -c "
import json
r = json.load(open('$COMPARE_JSON'))
pasa = sum(1 for v in r.values() if v['pasa'])
for ticker, v in r.items():
    estado = 'PASA' if v['pasa'] else 'FALLA'
    detalle = '' if v['pasa'] else ' -- ' + '; '.join(v['diffs'] + v['trigger_diffs'])[:200]
    print(f'{ticker}: {estado}{detalle}')
print(f'Resultado global: {pasa}/{len(r)} PASA')
")
else
    log_full "ERROR: no se generó $COMPARE_JSON -- ver detalle arriba ($REPORT_FULL)."
    ABORTED=1
fi

if [[ "$FORCE_GATE_RAN" -eq 1 && -f "$COMPARE_JSON_GATEON" ]]; then
    log_full ""
    log_full "Gate forzado a ON (equivalencia de lógica, NO es una señal de mercado real):"
    while IFS= read -r line; do log_full "$line"; done < <(python3 -c "
import json
r = json.load(open('$COMPARE_JSON_GATEON'))
pasa = sum(1 for v in r.values() if v['pasa'])
for ticker, v in r.items():
    estado = 'PASA' if v['pasa'] else 'FALLA'
    detalle = '' if v['pasa'] else ' -- ' + '; '.join(v['diffs'] + v['trigger_diffs'])[:200]
    print(f'{ticker} (gate ON): {estado}{detalle}')
print(f'Resultado global (gate ON): {pasa}/{len(r)} PASA')

# Qué ramas se ejercitaron de verdad: SC-02/SC-PB applicable=True con el
# gate forzado a ON significa que, con estas velas, también se satisfizo
# el resto de condiciones de la estrategia (no solo el check del gate).
# applicable=False con el gate ON puede ser por otro motivo (p.ej.
# ticker no altcoin para SC-02) -- se cita la razón real, no se asume.
print()
print('Ramas ejercitadas con el gate ON (naReason cuando sigue N/A):')
for sid in ('SC-01', 'SC-02', 'SC-PB'):
    por_ticker = []
    for ticker, v in r.items():
        est = v['estrategias'].get(sid, {})
        if est.get('applicable'):
            por_ticker.append(f'{ticker}=aplicable')
        else:
            razon = est.get('naReason') or 'N/A'
            por_ticker.append(f'{ticker}={razon}')
    print(f'  {sid}: ' + ', '.join(por_ticker))
")
fi

log_full "Salida completa: $REPORT_FULL"
log_full "Fixtures: $OUT_DIR"

# --- Paso 7: commit + push, con la salvaguarda explícita del enunciado ----
# OJO: el add/commit de $REPORT_FULL congela su contenido en ese momento --
# a propósito no se le sigue añadiendo nada DESPUÉS de comitearlo (si no,
# el blob comiteado y el fichero en disco divergirían por las propias
# líneas de este paso). La salida de git add/commit/push va a stdout
# normal, no al informe.
echo
echo "=== 6. git add/commit/push ==="
cd "$REPO_ROOT" || exit 1
git add "$OUT_DIR" "$REPORT_FULL"
if git diff --cached --quiet; then
    echo "Nada nuevo que comitear (¿ya se había ejecutado con el mismo resultado?)."
else
    git commit -m "Verificación CRIPTO (BTC/ETH/SOL) contra JS real -- $TS"
    if ! git push; then
        echo
        echo "=================================================================="
        echo " EL PUSH FALLÓ -- pega el informe completo de abajo a mano:"
        echo "=================================================================="
        cat "$REPORT_FULL"
        exit 1
    fi
fi

echo
echo "Hecho. No se ha desplegado nada ni habilitado ningún timer."
exit 0
