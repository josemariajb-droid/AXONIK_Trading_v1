#!/usr/bin/env bash
# Solo lectura. No escribe ni modifica nada en el servidor — solo
# grep/sed/wc sobre archivos que ya existen. Resuelve las tres preguntas
# abiertas en docs/pipeline/2026-10-03_automatizacion_captura_snapshots.md
# §1.2 (si autoCaptureSnapshots()/detectAutoTrigger()/runScan() dependen
# de algo que solo existe en el navegador), antes de implementar el timer
# systemd de ese diseño.
#
# Uso:
#   ./check_autocapture_triggers.sh
#   SCANNER_HTML=/otra/ruta/index.html PROXY_PY=/otra/ruta/proxy.py ./check_autocapture_triggers.sh
#
# Si algún archivo no es legible, probar con: sudo ./check_autocapture_triggers.sh
#
# Pega la salida completa de vuelta para cerrar las tres preguntas abiertas.

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

echo "=== Archivos objetivo ==="
for f in "$SCANNER_HTML" "$PROXY_PY"; do
    if [[ -r "$f" ]]; then
        echo "OK  $f ($(wc -l < "$f") líneas)"
    else
        echo "!! NO LEGIBLE: $f (¿ruta incorrecta o permisos? probar con sudo)"
    fi
done

echo
echo "=== Pregunta 1: detectAutoTrigger() completa ==="
echo "--- ¿Compara solo campos numéricos recibidos como parámetro (aritmética"
echo "    pura, replicable en Python), o depende de algo calculado solo en"
echo "    el navegador (una librería de gráficos, el DOM/canvas)? ---"
print_function "$SCANNER_HTML" 'function[[:space:]]+detectAutoTrigger|detectAutoTrigger[[:space:]]*='

echo
echo "=== Pregunta 2a: runScan() completa (de dónde sale el universo de tickers) ==="
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
echo "=== Fin. Pega esta salida completa de vuelta para cerrar la sección 1.2 del diseño. ==="
