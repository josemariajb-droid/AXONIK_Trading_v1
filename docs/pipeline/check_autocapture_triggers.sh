#!/usr/bin/env bash
# Solo lectura. No escribe ni modifica nada en el servidor — solo
# grep/sed/wc sobre archivos que ya existen. Resuelve las preguntas
# abiertas en docs/pipeline/2026-10-03_automatizacion_captura_snapshots.md
# §1.2 antes de implementar el timer systemd de ese diseño.
#
# Estado tras la 2ª pasada: detectAutoTrigger() y evaluateTicker()
# confirmados como orquestación/aritmética pura sobre datos; universo de
# tickers confirmado desde localStorage (decisión de producto ya tomada:
# usar EN_PRUEBAS/PRODUCCION de 02_SCANNERS en su lugar). Verificación
# final pendiente: grep dirigido (Pregunta 1c) en las cuatro piezas que
# evaluateTicker() llama (NYSE_STRATEGIES, CRYPTO_STRATEGIES,
# applyEventAdjustments, tickerHardNo) buscando document./window./canvas/
# chart./getContext/fetch( interno. Limpio en las cuatro = bloqueante
# cerrado del todo, sin Playwright.
#
# Uso:
#   ./check_autocapture_triggers.sh
#   SCANNER_HTML=/otra/ruta/index.html PROXY_PY=/otra/ruta/proxy.py ./check_autocapture_triggers.sh
#
# Si algún archivo no es legible, probar con: sudo ./check_autocapture_triggers.sh
#
# Pega la salida completa de vuelta — sobre todo la sección "Pregunta 1c"
# — para cerrar la última verificación pendiente.

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
    block=$(awk -v start="$line" -v maxlines="$max_lines" '
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
    ' "$file")

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
echo "=== Complemento: handler de /api/scan-batch en el proxy ==="
echo "--- Si ya devuelve indicadores calculados (rsi, score, rvol...), refuerza"
echo "    que detectAutoTrigger solo compara y no calcula nada él mismo. ---"
print_function "$PROXY_PY" 'scan.batch|def[[:space:]]+scan_batch|async[[:space:]]+def[^(]*scan_batch'

echo
echo "=== Fin. Lo que falta cerrar: la sección 'evaluateTicker()' de arriba. ==="
