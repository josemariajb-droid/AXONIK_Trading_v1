# Captura automática de snapshots — despliegue

**Estado: NO DESPLEGADO.** Implementación real, lista para revisión. No tocar
el servidor hasta que se apruebe aquí, igual que con el fix de idempotencia
(`docs/pipeline/2026-09-22_fix_idempotencia_ingesta.md`).

Diseño completo: `docs/pipeline/2026-10-03_automatizacion_captura_snapshots.md`.
Bloqueante de "¿hace falta Playwright?" cerrado: `detectAutoTrigger()`,
`evaluateTicker()`, `NYSE_STRATEGIES`, `CRYPTO_STRATEGIES`,
`applyEventAdjustments` y `tickerHardNo` son aritmética/orquestación pura
sobre datos, sin DOM ni dependencia de navegador (verificado con
`docs/pipeline/check_autocapture_triggers.sh`).

## Estado (05/10/2026) — puerto Python completo y probado, falta aplicar+verificar en el servidor real

- Universo de tickers: `14_UNIVERSO_TICKERS` (hoja real, ya creada y
  poblada con 17 tickers), ya no `02_SCANNERS`/`localStorage`.
- `evaluate_ticker()` en `snapshot_autocapture.py`: ya hace el `POST
  /api/evaluate-ticker` real, enviando `candles` en bruto (ya no
  `NotImplementedError`, ya no el bug de mandar `data` como si fuera
  `ind`).
- `detect_auto_trigger()`: se usa directamente
  `evaluate_ticker_logic.detect_auto_trigger()` (prioridad estricta
  `AUTO_MULTI`→`AUTO_HIGH` correcta, con pruebas).
- `risk_pct` → `risk_per_share` (confirmado contra `SnapshotCreateRequest`
  real).
- **`computeIndicators()` + las 9 funciones de cálculo: portadas a
  `indicator_calc.py`, probadas contra fixtures reales** (AAPL/MSFT/NVDA
  × 1d/1h/15m, `docs/pipeline/fixtures_js/`). `build_ind()` en
  `evaluate_ticker_logic.py` conecta candles en bruto con `evaluate_ticker()`.
- **`POST /api/evaluate-ticker`: código final, probado contra una app
  FastAPI real** (`test_evaluate_ticker_endpoint.py`) — acepta `candles`
  en bruto (camino normal, calcula `ind` con `build_ind()`) o `ind` ya
  calculado (compatibilidad, mutuamente excluyente, 422 si llegan los
  dos o ninguno). **131 pruebas en este directorio, todas pasan. Sigue
  SIN aplicarse a `market_data_proxy.py` real** — ver Paso 1b más abajo.

**Para cerrar esto de verdad falta, en orden:** (1) aplicar el Paso 1b
(pegar el endpoint, con la línea de decorador y los imports exactos
que pide su propio docstring); (2) ejecutar
`VERIFICACION_NAVEGADOR_VS_ENDPOINT.md` (actualizada al nuevo contrato
de `candles`) — **obligatorio antes de dar nada por cerrado**,
instrucción explícita del usuario; (3) solo entonces el protocolo de
`--dry-run` del Paso 3 más abajo deja de ser prematuro.

## Paso 1 — bind del proxy a 127.0.0.1 (BACKLOG entrada 2, ALTA)

Línea actual confirmada en `market_data_proxy.py` (DOC-IDEM, Hallazgo 4):

```python
uvicorn.run(app, host="0.0.0.0", port=8002)
```

Cambio:

```python
uvicorn.run(app, host="127.0.0.1", port=8002)
```

Es la opción preferida del diseño (§3.4): el proceso de captura corre en el
mismo host, no necesita red, y esto resuelve el hallazgo 2 del backlog sin
necesidad del token bearer — no hace falta autenticar tráfico que nunca sale
del host.

**Efecto colateral a tener en cuenta:** si hoy accedes a `/scanner` desde un
navegador fuera del propio Hetzner, dejará de ser alcanzable directamente.
Si todavía lo necesitas, hace falta un túnel SSH o un reverse proxy con su
propia autenticación antes de aplicar este cambio — decisión tuya, no la
asumo.

### Despliegue del bind

```bash
cp /opt/axonik/scripts/market_data_proxy.py /opt/axonik/scripts/market_data_proxy.py.bak.$(date +%Y%m%d_%H%M%S)
sha256sum /opt/axonik/scripts/market_data_proxy.py  # anotar antes de tocar nada

sed -i 's/host="0\.0\.0\.0", port=8002/host="127.0.0.1", port=8002/' /opt/axonik/scripts/market_data_proxy.py
python3 -m py_compile /opt/axonik/scripts/market_data_proxy.py

systemctl restart axonik-market-proxy
# Anotar T0, igual que en el Addendum 4 del fix de idempotencia.
```

### Verificación del bind

```bash
# Debe mostrar 127.0.0.1:8002, no 0.0.0.0:8002
ss -tlnp | grep 8002

# Desde el propio host, debe seguir respondiendo:
curl -s http://127.0.0.1:8002/api/health

# Desde fuera del host (otra máquina, o un curl con -4 a la IP pública),
# debe fallar con connection refused, no con un 200/404:
curl -sS --max-time 5 http://89.167.80.58:8002/api/health || echo "rechazado, como se espera"
```

Si todo lo anterior pasa, registrar el resultado como addendum en
`docs/pipeline/2026-10-03_automatizacion_captura_snapshots.md`, igual que el
Addendum 4 del otro documento.

## Paso 1b — aplicar `POST /api/evaluate-ticker` (contrato de candles en bruto, 05/10/2026)

Decorador/imports confirmados en `docs/pipeline/pregunta6_salida.txt`
(6a/6b/6c/6d). Código completo, listo para pegar, en
`evaluate_ticker_endpoint.py` de este directorio — léelo primero: trae
la lista exacta de imports y el porqué de cada uno (para no repetir un
`NameError` por dar algo por sabido).

```bash
cp evaluate_ticker_logic.py /opt/axonik/scripts/evaluate_ticker_logic.py
cp indicator_calc.py /opt/axonik/scripts/indicator_calc.py

cp /opt/axonik/scripts/market_data_proxy.py /opt/axonik/scripts/market_data_proxy.py.bak.$(date +%Y%m%d_%H%M%S)
sha256sum /opt/axonik/scripts/market_data_proxy.py  # anotar antes de tocar nada
```

Editar `/opt/axonik/scripts/market_data_proxy.py` a mano:
1. Añadir a la cabecera (si no están ya): `import json`,
   `from fastapi import Response` (`HTTPException` ya está importado),
   `import evaluate_ticker_logic as etl`.
2. Pegar el contenido de `evaluate_ticker_endpoint.py` desde
   `class EvaluateTickerRequest` hasta el final (sin la cabecera de
   comentarios ni los imports, ya añadidos en el paso 1) inmediatamente
   después de la línea `return {"results": results}` que cierra
   `scan_batch()`.
3. **Añadir la línea `@app.post("/api/evaluate-ticker")`** justo encima
   de `async def evaluate_ticker_endpoint(req: EvaluateTickerRequest):`
   — no viene en el archivo del repo a propósito (así es importable y
   testeable sin `NameError`, ver cabecera de `evaluate_ticker_endpoint.py`).

```bash
python3 -m py_compile /opt/axonik/scripts/market_data_proxy.py
systemctl restart axonik-market-proxy
curl -s http://127.0.0.1:8002/api/health  # debe seguir respondiendo
```

**Contrato del endpoint:** recibe `candles` en bruto (el `data` de
`scan_batch()`) y calcula `ind` él mismo con `build_ind()` — un único
cálculo real, nunca reimplementado en el endpoint ni en
`snapshot_autocapture.py`. También acepta `ind` ya calculado como
alternativa explícita (mutuamente excluyente con `candles`, 422 si
llegan los dos o ninguno). **NaN no es JSON válido**: el endpoint lo
sirve como el string `"NaN"` (`etl.nan_to_json_sentinel`); cualquier
cliente debe decodificarlo con `etl.sentinel_to_nan` — ya lo hace
`snapshot_autocapture.py`. Probado contra una app FastAPI real en
`test_evaluate_ticker_endpoint.py` (131 pruebas en total en este
directorio, todas pasan).

**Antes de seguir al paso 2:** ejecutar
`VERIFICACION_NAVEGADOR_VS_ENDPOINT.md` de este directorio — obligatorio,
instrucción explícita del usuario. Sin eso, el endpoint puede estar
sintácticamente bien y devolver resultados igualmente incorrectos (mismo
riesgo que ya se vio real una vez con `risk_pct`/`risk_per_share`).

## Paso 2 — instalar el script y las units (bloqueado: falta aplicar+verificar el Paso 1b)

```bash
cp snapshot_autocapture.py /opt/axonik/scripts/snapshot_autocapture.py
chmod +x /opt/axonik/scripts/snapshot_autocapture.py

mkdir -p /etc/axonik
cat > /etc/axonik/autocapture.env <<'EOF'
AXONIK_DECISION_ENGINE_SHEET_ID=<id real de la hoja — confirmar, no inventar>
AXONIK_PROXY_BASE=http://127.0.0.1:8002
EOF
chmod 600 /etc/axonik/autocapture.env

cp axonik-snapshot-autocapture.service axonik-snapshot-autocapture.timer /etc/systemd/system/
systemctl daemon-reload
```

**No habilitar el timer todavía** (`systemctl enable --now axonik-snapshot-autocapture.timer`)
— primero la verificación del paso 3.

## Paso 3 — verificación obligatoria antes de habilitar el timer

Mismo estándar que el protocolo de ST-16 (DOC-IDEM, Addendum 3 §1.4 y
Addendum 4): nada de "está desplegado" sin "está verificado".

```bash
# 1. Dry-run: no hace ningún POST, solo registra qué habría enviado.
#    Revisar que el universo de tickers (14_UNIVERSO_TICKERS, ESTADO=ACTIVO)
#    y el payload tengan sentido.
python3 /opt/axonik/scripts/snapshot_autocapture.py --dry-run --force-window

# 2. Una sola vez, sin --dry-run, fuera de la franja de los timers del
#    evaluador (16:00-22:00 L-V, 18:30 todos los días) y con un ticker de
#    prueba si es posible (ZZTEST), confirmar la respuesta real:
python3 /opt/axonik/scripts/snapshot_autocapture.py --force-window

# 3. Confirmar en Postgres que la fila de prueba se creó con el hash v2
#    (Hallazgo 1 de DOC-IDEM) y limpiarla:
#    SELECT id, ticker, signal_hash, created_at FROM signal_snapshots
#      WHERE ticker = 'ZZTEST' ORDER BY id DESC LIMIT 5;
#    DELETE FROM signal_snapshots WHERE ticker = 'ZZTEST';

# 4. Solo entonces, habilitar el timer:
systemctl enable --now axonik-snapshot-autocapture.timer
systemctl list-timers axonik-snapshot-autocapture.timer
```

Registrar el resultado de estos 4 pasos como addendum en el documento de
diseño antes de considerar esto cerrado — igual que con el hallazgo 1.
