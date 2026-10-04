#!/usr/bin/env bash
# Solo lectura. No escribe ni modifica nada en el servidor — solo
# grep/sed/wc sobre archivos que ya existen. Resuelve las preguntas
# abiertas en docs/pipeline/2026-10-03_automatizacion_captura_snapshots.md
# §1.2 antes de implementar el timer systemd de ese diseño.
#
# Estado tras la 3ª pasada: bloqueante de "¿hace falta Playwright?" CERRADO
# (detectAutoTrigger, evaluateTicker, NYSE_STRATEGIES, CRYPTO_STRATEGIES,
# applyEventAdjustments y tickerHardNo son aritmética/orquestación pura,
# sin DOM). Universo de tickers cerrado como decisión de producto
# (EN_PRUEBAS/PRODUCCION de 02_SCANNERS, no localStorage).
#
# Lo que queda (Pregunta 4, nueva): nombres de campo exactos del payload
# de POST /api/snapshots y shape de POST /api/scan-batch, para que
# services/snapshot-autocapture/snapshot_autocapture.py deje de tener
# "PENDIENTE DE CONFIRMAR" en construir_payload_snapshot()/
# fetch_scan_batch(). El umbral de detectAutoTrigger() no necesita un
# grep nuevo — ya debería verse en la salida de la Pregunta 1 de una
# pasada anterior.
#
# Uso:
#   ./check_autocapture_triggers.sh
#   SCANNER_HTML=/otra/ruta/index.html PROXY_PY=/otra/ruta/proxy.py ./check_autocapture_triggers.sh
#
# Si algún archivo no es legible, probar con: sudo ./check_autocapture_triggers.sh
#
# Pega la salida completa de vuelta — sobre todo la sección "Pregunta 4"
# — para terminar de confirmar services/snapshot-autocapture/snapshot_autocapture.py.

set -u

SCANNER_HTML="${SCANNER_HTML:-/opt/axonik/scanner/index.html}"
PROXY_PY="${PROXY_PY:-/opt/axonik/scripts/market_data_proxy.py}"
CONTEXT_LINES="${CONTEXT_LINES:-100}"

# Busca la primera línea que case con el patrón en $file y vuelca esa
# línea + CONTEXT_LINES siguientes. No modifica $file.
print_function() {
    local file="$1" pattern="$2"
    local line

    if [[ ! -r "$file" ]]; then
        echo "(archivo no legible: $file — probar con sudo)"
        return
    fi

    line=$(grep -n -m1 -E "$pattern" "$file" 2>/dev/null | head -1 | cut -d: -f1)
    if [[ -z "$line" ]]; then
        echo "(no encontrado: patrón '$pattern' en $file)"
        return
    fi

    echo "(encontrado en línea $line de $file, mostrando hasta línea $((line + CONTEXT_LINES)))"
    sed -n "${line},$((line + CONTEXT_LINES))p" "$file"
}

# Localiza la definición de $name (const/let/var/function/asignación),
# extrae su cuerpo completo contando { } y [ ] hasta que cierran (con un
# tope de seguridad por si el conteo se confunde con llaves dentro de un
# string/regex), y comprueba si contiene alguna referencia a
# navegador/DOM/canvas/chart/fetch interno. Solo vuelca el bloque entero
# si encuentra algo — si no, solo confirma que está limpio.
# Extrae un bloque JS por balance de { } y [ ] (no por indentación —
# JS no es significativo en eso). Con tope de seguridad si el conteo se
# confunde con llaves dentro de un string/regex.
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
                print "... (corte de seguridad a " maxlines " líneas sin cerrar el balance de llaves/corchetes — revisar a mano si hace falta más)"
                exit
            }
        }
    ' "$file"
}

# Localiza por nombre (const/let/var/function/asignación) y extrae con
# extract_js_block. Siempre vuelca el bloque completo, sin condición.
# Avisa si hay más de una coincidencia del patrón de localización --
# relevante sobre todo para nombres cortos como "f", donde la primera
# coincidencia podría no ser la definición real (p.ej. un parámetro o
# una variable de bucle con el mismo nombre en otro sitio del archivo).
print_js_def() {
    local file="$1" name="$2" max_lines="${3:-1500}"
    local pattern="(const|let|var)[[:space:]]+${name}\b|function[[:space:]]+${name}\b|\\b${name}[[:space:]]*="
    local line count
    if [[ ! -r "$file" ]]; then
        echo "  (archivo no legible: $file — probar con sudo)"
        return
    fi
    count=$(grep -c -E "$pattern" "$file" 2>/dev/null)
    line=$(grep -n -m1 -E "$pattern" "$file" 2>/dev/null | head -1 | cut -d: -f1)
    if [[ -z "$line" ]]; then
        echo "  (no encontrado: definición de $name)"
        return
    fi
    if [[ "${count:-0}" -gt 1 ]]; then
        echo "  (AVISO: $count líneas coinciden con el patrón de '$name' — se usa la primera,"
        echo "   línea $line. Con nombres cortos puede ser un parámetro o variable de bucle,"
        echo "   no la definición real. Revisar el bloque volcado y, si no parece correcto,"
        echo "   buscar '$name' a mano en el archivo.)"
    fi
    echo "  ($name definido en línea $line de $file)"
    extract_js_block "$file" "$line" "$max_lines"
}

# Igual que print_js_def, pero solo vuelca el bloque si encuentra alguna
# referencia a navegador/DOM/canvas/chart/fetch interno dentro — si está
# limpio, solo lo confirma, sin volcar el texto (usado en la Pregunta 1c).
check_definition_for_browser_markers() {
    local file="$1" name="$2" max_lines="${3:-1500}"
    local line

    if [[ ! -r "$file" ]]; then
        echo "  (archivo no legible: $file — probar con sudo)"
        return
    fi

    line=$(grep -n -m1 -E "(const|let|var)[[:space:]]+${name}\b|function[[:space:]]+${name}\b|\\b${name}[[:space:]]*=" "$file" 2>/dev/null \
        | head -1 | cut -d: -f1)
    if [[ -z "$line" ]]; then
        echo "  (no encontrado: definición de $name)"
        return
    fi
    echo "  ($name definido en línea $line de $file)"

    local block
    block=$(extract_js_block "$file" "$line" "$max_lines")

    local hits
    hits=$(printf '%s\n' "$block" | grep -n -E 'document\.|window\.|canvas|chart\.|getContext|fetch\(')

    if [[ -z "$hits" ]]; then
        echo "  -> limpio: sin document./window./canvas/chart./getContext/fetch( en el cuerpo de $name."
    else
        echo "  -> ENCONTRADO en $name (líneas relativas al bloque extraído):"
        printf '%s\n' "$hits"
        echo "  -> bloque completo de $name:"
        printf '%s\n' "$block"
    fi
}

# Extrae un bloque Python por indentación (no llaves): desde $start_line
# hasta la primera línea no vacía cuya indentación sea <= la de esa
# línea. Sirve para funciones/clases completas sin cortar a mitad ni
# arrastrar código no relacionado detrás.
extract_python_block() {
    local file="$1" start_line="$2" max_lines="${3:-300}"
    if [[ ! -r "$file" ]]; then
        echo "  (archivo no legible: $file — probar con sudo)"
        return
    fi
    awk -v start="$start_line" -v maxlines="$max_lines" '
        function indent_of(s) { match(s, /^[ \t]*/); return RLENGTH }
        NR < start { next }
        NR == start { base = indent_of($0); print; next }
        {
            if ($0 ~ /^[ \t]*$/) { print; next }
            if (indent_of($0) <= base) { exit }
            print
            if (NR - start + 1 >= maxlines) {
                print "... (corte de seguridad a " maxlines " líneas)"
                exit
            }
        }
    ' "$file"
}

# Localiza por nombre (función o clase) y extrae con extract_python_block.
print_python_def() {
    local file="$1" pattern="$2"
    local line
    if [[ ! -r "$file" ]]; then
        echo "  (archivo no legible: $file — probar con sudo)"
        return
    fi
    line=$(grep -n -m1 -E "$pattern" "$file" 2>/dev/null | head -1 | cut -d: -f1)
    if [[ -z "$line" ]]; then
        echo "  (no encontrado: patrón '$pattern' en $file)"
        return
    fi
    echo "  (encontrado en línea $line de $file)"
    extract_python_block "$file" "$line"
}

echo "=== Archivos objetivo ==="
for f in "$SCANNER_HTML" "$PROXY_PY"; do
    if [[ -r "$f" ]]; then
        echo "OK  $f ($(wc -l < "$f") líneas)"
    else
        echo "!! NO LEGIBLE: $f (¿ruta incorrecta o permisos? probar con sudo)"
    fi
done

echo
echo "=== Pregunta 1: detectAutoTrigger() completa — CONFIRMADO: comparación pura ==="
echo "--- Ya confirmado en una pasada anterior: solo compara scores, no los"
echo "    calcula. Se deja aquí por trazabilidad, no bloquea nada. ---"
print_function "$SCANNER_HTML" 'function[[:space:]]+detectAutoTrigger|detectAutoTrigger[[:space:]]*='

echo
echo "=== Pregunta 1b: evaluateTicker() completa — BLOQUEANTE REAL ==="
echo "--- Es la función que calcula los scores que detectAutoTrigger compara."
echo "    /api/scan-batch devuelve indicadores en bruto, no scores, así que"
echo "    el cálculo del score pasa por aquí. Misma pregunta que antes:"
echo "    ¿aritmética pura sobre los indicadores recibidos (replicable en"
echo "    Python), o depende de algo que solo existe en el navegador? ---"
print_function "$SCANNER_HTML" 'function[[:space:]]+evaluateTicker|evaluateTicker[[:space:]]*='

echo
echo "=== Pregunta 1c: grep dirigido en NYSE_STRATEGIES / CRYPTO_STRATEGIES / applyEventAdjustments / tickerHardNo ==="
echo "--- Si ninguna de las cuatro contiene document./window./canvas/chart./"
echo "    getContext/ o un fetch( interno, evaluateTicker() y todo lo que"
echo "    llama es aritmética pura sobre datos — bloqueante cerrado del todo,"
echo "    sin necesidad de Playwright. ---"
for name in NYSE_STRATEGIES CRYPTO_STRATEGIES applyEventAdjustments tickerHardNo; do
    echo "- $name:"
    check_definition_for_browser_markers "$SCANNER_HTML" "$name"
done

echo
echo "=== Pregunta 2a: runScan() completa (CERRADA — se deja por trazabilidad) ==="
echo "--- Universo confirmado desde localStorage, no un endpoint. Decisión de"
echo "    producto ya tomada: el proceso automático usa los scanners"
echo "    EN_PRUEBAS/PRODUCCION de 02_SCANNERS en su lugar, no localStorage. ---"
print_function "$SCANNER_HTML" 'function[[:space:]]+runScan\b'

echo
echo "=== Pregunta 2b: rastro de localStorage/watchlist/checkboxes de ticker ==="
echo "--- Si aparece algo aquí, el universo puede depender de estado de UI"
echo "    del navegador en vez de un endpoint consultable. ---"
grep -n -E "localStorage|watchlist|checked.*ticker|TICKERS[[:space:]]*=|SCANNERS_UNIVERSE" "$SCANNER_HTML" 2>/dev/null \
    || echo "(sin coincidencias)"

echo
echo "=== Pregunta 3: rastro de sesión/autenticación en el cliente ==="
echo "--- Sin coincidencias es lo esperado, coherente con que el proxy no"
echo "    exige autenticación en ningún endpoint hoy (BACKLOG entrada 2). ---"
grep -n -E "credentials:|document\.cookie|csrf|Authorization" "$SCANNER_HTML" 2>/dev/null \
    || echo "(sin coincidencias)"

echo
echo "=== Pregunta 4a: modelos Pydantic (class ...BaseModel) en el proxy ==="
echo "--- Para confirmar los nombres de campo exactos del payload de"
echo "    POST /api/snapshots (hoy entry_price/stop_price/risk_pct son una"
echo "    estimación en services/snapshot-autocapture/snapshot_autocapture.py,"
echo "    no una lectura literal). ---"
if [[ -r "$PROXY_PY" ]]; then
    mapfile -t model_lines < <(grep -n -E '^class[[:space:]]+[A-Za-z_]+\(.*BaseModel' "$PROXY_PY" 2>/dev/null)
    if [[ ${#model_lines[@]} -eq 0 ]]; then
        echo "  (no se encontró ninguna clase BaseModel en $PROXY_PY)"
    else
        for entry in "${model_lines[@]}"; do
            ln="${entry%%:*}"
            echo "- definida en línea $ln:"
            extract_python_block "$PROXY_PY" "$ln" 60
        done
    fi
else
    echo "  (archivo no legible: $PROXY_PY — probar con sudo)"
fi

echo
echo "=== Pregunta 4b: create_snapshot() completa (handler de POST /api/snapshots) ==="
print_python_def "$PROXY_PY" 'def[[:space:]]+create_snapshot\b'

echo
echo "=== Pregunta 4c: scan_batch() completa (handler de POST /api/scan-batch) ==="
echo "--- Shape exacto de petición/respuesta que asume fetch_scan_batch() en"
echo "    snapshot_autocapture.py. ---"
print_python_def "$PROXY_PY" 'def[[:space:]]+scan_batch\b'

echo
echo "=== Pregunta 5: texto literal de las 5 piezas a portar a POST /api/evaluate-ticker ==="
echo "--- Decisión 04/10/2026: no se duplican en snapshot_autocapture.py --"
echo "    se portan UNA vez a un endpoint nuevo en market_data_proxy.py."
echo "    Las Preguntas 1/1b ya volcaron detectAutoTrigger/evaluateTicker"
echo "    enteras; la 1c solo volcaba las otras 4 si encontraba un problema"
echo "    de navegador -- como salieron limpias, nunca se volcó su texto."
echo "    Esta sección las vuelca siempre, sin condición. ---"
for name in detectAutoTrigger evaluateTicker NYSE_STRATEGIES CRYPTO_STRATEGIES applyEventAdjustments tickerHardNo; do
    echo "- $name:"
    print_js_def "$SCANNER_HTML" "$name"
done

echo
echo "=== Pregunta 5b: las piezas que de verdad calculan cada score ==="
echo "--- NYSE_STRATEGIES/CRYPTO_STRATEGIES (Pregunta 5) son solo arrays de"
echo "    referencias a estas 10 funciones evalXX -- sin ellas,"
echo "    evaluateTicker() es un orquestador vacío. STRATEGY_META,"
echo "    finalizeVerdict y f() las usan evaluateTicker()/"
echo "    applyEventAdjustments() -- si tienen lógica no trivial, son"
echo "    igual de necesarias para portar el cálculo real. ---"
for name in evalST01 evalST05 evalST06 evalST09 evalST11 evalST15 evalST16 evalSC01 evalSC02 evalSCPB STRATEGY_META finalizeVerdict f; do
    echo "- $name:"
    print_js_def "$SCANNER_HTML" "$name"
done

echo
echo "=== Pregunta 5c: mkResult y mkNA -- las 10 evalXX terminan devolviendo una de las dos ==="
echo "--- Cada evalXX acaba en mkResult(...) o mkNA(...). Ninguna de las dos"
echo "    estaba en la lista de 5b. No son triviales: evaluateTicker() hace"
echo "    Object.assign({}, r, STRATEGY_META[r.id]) sobre lo que devuelven,"
echo "    así que r.score/r.factors/r.applicable/r.verdict salen de aquí --"
echo "    probablemente mkResult llama a finalizeVerdict internamente. ---"
for name in mkResult mkNA; do
    echo "- $name:"
    print_js_def "$SCANNER_HTML" "$name"
done

echo
echo "=== Pregunta 5d: MAX_RAW_SCORE -- mkResult normaliza score/MAX_RAW_SCORE[id]*100 ==="
echo "--- Cuarta capa encontrada al revisar mkResult (Pregunta 5c). Sin esta"
echo "    tabla no se sabe el denominador de normalización por estrategia --"
echo "    tan necesaria como STRATEGY_META. ---"
print_js_def "$SCANNER_HTML" "MAX_RAW_SCORE"

echo
echo "=== Pregunta 6a: cabecera del proxy -- imports + instanciación de la app FastAPI ==="
echo "--- Para escribir POST /api/evaluate-ticker (paso 3, decisión 04/10/2026)"
echo "    hace falta saber el nombre real de la variable 'app', el estilo de"
echo "    import (Pydantic v1 vs v2, 'from fastapi import ...') y si ya existe"
echo "    algún Depends/auth compartido que el endpoint nuevo debería seguir --"
echo "    nunca visto el archivo completo, no se inventa el patrón. ---"
if [[ -r "$PROXY_PY" ]]; then
    sed -n '1,60p' "$PROXY_PY"
else
    echo "  (archivo no legible: $PROXY_PY — probar con sudo)"
fi

echo
echo "=== Pregunta 6b: decorador real de create_snapshot() y scan_batch() ==="
echo "--- print_python_def ya volcó los cuerpos (Pregunta 4b/4c) pero localiza"
echo "    por 'def', no por el '@app.post(...)' de la línea anterior -- nunca"
echo "    se vio ese decorador. Necesario para que el endpoint nuevo use el"
echo "    mismo estilo (ruta, Depends si lo hay, response_model si lo hay). ---"
if [[ -r "$PROXY_PY" ]]; then
    for pattern in 'def[[:space:]]+create_snapshot\b' 'def[[:space:]]+scan_batch\b'; do
        line=$(grep -n -m1 -E "$pattern" "$PROXY_PY" 2>/dev/null | head -1 | cut -d: -f1)
        if [[ -n "$line" ]]; then
            start=$(( line - 5 > 0 ? line - 5 : 1 ))
            echo "- líneas $start-$line (decorador + firma):"
            sed -n "${start},${line}p" "$PROXY_PY"
        else
            echo "  (no encontrado: patrón '$pattern')"
        fi
    done
else
    echo "  (archivo no legible: $PROXY_PY — probar con sudo)"
fi

echo
echo "=== Pregunta 6c: modelos Pydantic -- repetición de la Pregunta 4a ==="
echo "--- La salida de la Pregunta 4a se pegó directamente en el chat (nunca"
echo "    se comitió a un archivo), así que ya no está disponible en esta"
echo "    sesión tras el resumen de contexto. Se repite aquí para no asumir"
echo "    nombres de campo de memoria -- en concreto, confirmar si"
echo "    ScanBatchRequest usa 'tickers' o algo distinto (en"
echo "    snapshot_autocapture.py se cambió 'scanner_ids' a 'tickers' como"
echo "    SUPOSICIÓN, no una cita literal). ---"
if [[ -r "$PROXY_PY" ]]; then
    mapfile -t model_lines < <(grep -n -E '^class[[:space:]]+[A-Za-z_]+\(.*BaseModel' "$PROXY_PY" 2>/dev/null)
    if [[ ${#model_lines[@]} -eq 0 ]]; then
        echo "  (no se encontró ninguna clase BaseModel en $PROXY_PY)"
    else
        for entry in "${model_lines[@]}"; do
            ln="${entry%%:*}"
            echo "- definida en línea $ln:"
            extract_python_block "$PROXY_PY" "$ln" 60
        done
    fi
else
    echo "  (archivo no legible: $PROXY_PY — probar con sudo)"
fi

echo
echo "=== Pregunta 6d: de dónde salen los valores reales de settings (priceMin/atrMax/rvolMin) ==="
echo "--- evaluateTicker()/tickerHardNo() usan settings.priceMin/.atrMax/"
echo "    .rvolMin (ya visto en 5/5b/5c), pero vienen de state.settings en el"
echo "    navegador -- nunca se vio dónde se inicializa ese objeto ni sus"
echo "    valores por defecto. Sin esto, snapshot_autocapture.py no tiene qué"
echo "    settings reales pasarle al endpoint nuevo. ---"
grep -n -E "priceMin|atrMax|rvolMin" "$SCANNER_HTML" 2>/dev/null | grep -v -E "settings\.(priceMin|atrMax|rvolMin)\b" \
    || echo "(sin coincidencias fuera de los usos ya vistos -- puede que los valores por defecto vivan en 09_PARAMETROS/12_CONFIGURACION de Sheets, no en el HTML; revisar ahí si esto sale vacío)"

echo
echo "=== Pregunta 7: fetchAllNyse / fetchAllCrypto -- de dónde sale 'price' en ind['1d'] ==="
echo "--- La verificación navegador-vs-endpoint con AAPL real dio KeyError:"
echo "    'price'. d=ind['1d'] del /api/scan-batch real solo tiene 'candles' y"
echo "    'periods' -- NO 'price'. evaluateTicker() recibe rEntry.ind desde"
echo "    runScan() (ya extraída, Pregunta 2a), que viene de"
echo "    fetchAllNyse()/fetchAllCrypto() -- nunca extraídas ni leídas. Sospecha:"
echo "    esas funciones derivan 'price' (y quizá otros campos) ANTES de pasarle"
echo "    los datos a evaluateTicker() -- si es así, el endpoint nuevo tiene que"
echo "    replicar esa misma transformación, no reenviar el 'data' crudo de"
echo "    scan-batch tal cual. No se reintenta la verificación hasta confirmar"
echo "    esto con el texto literal, no una suposición más. ---"
for name in fetchAllNyse fetchAllCrypto; do
    echo "- $name:"
    print_js_def "$SCANNER_HTML" "$name"
done

echo
echo "=== Pregunta 8: fetchNyseTicker / fetchCryptoTicker / fetchFundamentals / fetchInsiders / sleep ==="
echo "--- Pregunta 7 confirmó: fetchAllNyse/fetchAllCrypto NO derivan 'price'"
echo "    ellas mismas -- son solo orquestación de batching (rate limiting,"
echo "    progreso, sleep) que delega en fetchNyseTicker()/fetchCryptoTicker()"
echo "    para 'ind', y en fetchFundamentals()/fetchInsiders() para 'funda'/"
echo "    'insiders'. Ninguna de las cuatro estaba entre las piezas ya"
echo "    confirmadas -- mismo patrón que ya pasó con mkResult/mkNA y"
echo "    MAX_RAW_SCORE: cada capa revela una más. 'price' probablemente se"
echo "    deriva dentro de fetchNyseTicker()/fetchCryptoTicker() a partir de"
echo "    candles/periods. sleep() es casi con toda seguridad un delay trivial"
echo "    de una línea, pero se vuelca igual -- no se asume de memoria. ---"
for name in fetchNyseTicker fetchCryptoTicker fetchFundamentals fetchInsiders sleep; do
    echo "- $name:"
    print_js_def "$SCANNER_HTML" "$name"
done

echo
echo "=== Pregunta 9: computeIndicators / fetchBinanceKlines -- HALLAZGO MAYOR ==="
echo "--- Pregunta 8 reveló algo más grande que una capa más de orquestación:"
echo "    fetchNyseTicker() NO llama a /api/scan-batch (el endpoint que usa"
echo "    snapshot_autocapture.py) -- llama a GET /api/scan-data?ticker=...,"
echo "    un endpoint distinto, por ticker individual. Trae 'candles' en"
echo "    bruto y los pasa a computeIndicators(candles, tf), que es quien"
echo "    produce price/ema20/50/200/rsi/macdHist/rvol/gapPct/adx/etc -- TODO"
echo "    lo que los 10 evalXX esperan en 'ind[tf]'. computeIndicators() es"
echo "    muy probablemente la pieza MÁS GRANDE de todo este diseño (cálculo"
echo "    real de indicadores técnicos, no orquestación ni scoring) y nunca"
echo "    se había identificado como dependencia hasta ahora. fetchCryptoTicker()"
echo "    usa la misma función sobre velas de fetchBinanceKlines(). Puede"
echo "    llamar a su vez a sub-funciones (cálculo de EMA/RSI/MACD/ADX por"
echo "    separado) -- si print_js_def encuentra algo no trivial dentro, NO"
echo "    asumir que es el fondo sin revisarlo. ---"
for name in computeIndicators fetchBinanceKlines; do
    echo "- $name:"
    print_js_def "$SCANNER_HTML" "$name" 3000
done

echo
echo "=== Fin. Pega la salida completa de las Preguntas 5, 5b, 5c, 5d, 6, 7, 8 y 9 -- hasta"
echo "    tener el cuerpo literal de computeIndicators() (y confirmar si llama a algo"
echo "    más sin confirmar) no se reintenta la verificación navegador-vs-endpoint. ==="
