# Runbook — ruta CRIPTO de la captura automática (BTC/ETH/SOL)

**Estado: NO DESPLEGADO. Paso 1 EJECUTADO una vez contra el servidor
real (07/10/2026), pero con un bug que invalida su resultado de gate —
hace falta RE-EJECUTARLO con el fix.** Paso 2 (dry-run real del script)
todavía pendiente. BTC/ETH/SOL siguen con `ESTADO` distinto de `ACTIVO`
en `14_UNIVERSO_TICKERS` a propósito — no tocar la hoja hasta el Paso 3.

**`computeMarketContext()`/`BINANCE_BASE` ya confirmados y PORTADOS DE
VERDAD** (Pregunta 11, `docs/pipeline/pregunta11_salida.txt`) —
`compute_btc_gate()` en Python ya NO es un sustituto, calcula
`BTC.price > BTC.ema50` (1D) real. **Pero el "3/3 PASA, Gate BTC OFF
(real)" del primer run estaba inflado por un bug de `verificar_cripto.sh`**
(extraía `computeMarketContext()` sin sus 4 dependencias, que lanzaba un
`ReferenceError` silenciado por su propio `catch` real -- parecía un
resultado de mercado genuino y no lo era). Ya corregido y probado con un
mock de Binance. Detalle completo en `docs/pipeline/BLOQUEOS.md`,
bloqueo 1 -- **re-ejecutar el Paso 1 de este runbook es la acción
pendiente más urgente**, no asumir que el gate sigue OFF.

**Desviación consciente añadida (07/10/2026):** la CAPTURA (no el
scanner) bloquea TODOS los longs cripto con el gate OFF, incluido SC-01
— ver Paso 2 más abajo y `docs/pipeline/BACKLOG.md`.

Contexto: `docs/pipeline/BACKLOG.md` (entrada 5, bloque "CRIPTO") y
`docs/pipeline/BLOQUEOS.md` (los dos bloqueos reales:
`computeMarketContext()`/gate BTC y `BINANCE_BASE`).

## Antes de empezar

- Ejecutar esto en el servidor real (Hetzner), no en un sandbox de
  desarrollo — necesita acceso de salida a Binance y el repo real con
  `git push` funcionando.
- `AXONIK_DECISION_ENGINE_SHEET_ID` y las credenciales de gspread ya
  deben estar configuradas (las usa `cargar_universo_cripto()`, igual
  que la rama NYSE ya en producción).
- No hace falta tocar `market_data_proxy.py` para este runbook — la
  rama cripto habla con Binance directo, no con `/api/scan-batch` ni con
  `/api/evaluate-ticker` (ver más abajo, Paso 2, por qué eso es
  deliberado y no un gap).

## Paso 1 — verificar la ruta CRIPTO contra el JS real

```bash
docs/pipeline/verificar_cripto.sh
```

**Qué hace:** `git pull`; extrae del `index.html` real las 32 piezas
compartidas con NYSE (ya confirmadas) más, si se puede,
`computeMarketContext()` (el gate BTC — ver "Qué esperar" abajo); pide
velas reales de Binance para BTC/ETH/SOL; ejecuta el JS real bajo Node
(`evaluateTicker`/`detectAutoTrigger`, mode `'CRYPTO'`); compara contra
`evaluate_ticker_logic.py` campo a campo (tolerancia `1e-9`); comitea y
pushea el resultado a la rama actual.

**Qué esperar:**

- Un informe corto en la terminal, algo así:
  ```
  Gate BTC: OFF (degradado) | ON (real) | OFF (real)
  BTC: PASA
  ETH: PASA
  SOL: PASA
  Resultado global: 3/3 PASA
  ```
- **`Gate BTC: ON (real)` u `OFF (real)` es lo esperado ahora** —
  `computeMarketContext()` y sus 4 dependencias
  (`fetchCryptoTicker`/`fetchBinanceKlines`/`sleep`/`BINANCE_BASE`) ya
  están confirmadas y se extraen juntas (bloqueo 1 de `BLOQUEOS.md`
  RESUELTO, 07/10/2026) — el gate ya no debería degradar salvo que el
  navegador haya cambiado desde entonces. `compute_btc_gate()` en Python
  calcula lo mismo (`BTC.price > BTC.ema50` 1D), no un sustituto.
- **`Gate BTC: OFF (degradado)` sigue siendo posible** si el navegador
  cambió (ancla desplazada + búsqueda global ambigua/sin match) — en ese
  caso compara la aritmética de scoring con el gate forzado a OFF en los
  dos lados (JS y Python), válido para "¿el puerto calcula igual que el
  JS", pero NO confirma el gate en sí. Revisar el aviso para saber cuál
  de las 5 piezas (`computeMarketContext`/`fetchCryptoTicker`/
  `fetchBinanceKlines`/`sleep`/`BINANCE_BASE`) falló exactamente.
- **El primer run (07/10/2026) reportó `OFF (real)`, pero tenía un bug
  real que lo invalida** (`docs/pipeline/BLOQUEOS.md`, bloqueo 1):
  `computeMarketContext()` se extraía sin sus dependencias y lanzaba un
  `ReferenceError` silenciado por su propio `catch` -- parecía un
  resultado de mercado genuino sin serlo. Ya corregido. **No asumir que
  el gate sigue OFF de aquel run** -- el puerto Python, corrido contra
  esas mismas velas, da gate ON. Re-ejecutar este Paso 1 para un valor
  fiable.
- **Opcional — `FORCE_BTC_GATE_ON=1 docs/pipeline/verificar_cripto.sh`:**
  repite la comparación con `btcGateOn` forzado a `true` en JS y Python,
  mismas velas reales. Es un TEST DE EQUIVALENCIA DE LÓGICA de SC-02/
  SC-PB (sus ramas de scoring con el gate ON), **no una señal de mercado
  real** — útil porque con el gate real normalmente OFF, esas dos ramas
  nunca se ejercitan en la pasada normal. El informe añade una sección
  "Gate forzado a ON" con PASA/FALLA y qué estrategias quedaron
  `aplicable` (o con qué `naReason`) por ticker.
- **Si algún ticker da `FALLA`:** el mensaje ya señala el campo exacto
  que difiere (p.ej. `SC-01.score: py=65 js=70`). NO seguir al Paso 2 --
  pegar la salida completa (`docs/pipeline/verificacion_cripto_<TS>.txt`,
  ya comiteada) para localizar el `evalSCxx` o factor concreto que
  diverge, mismo criterio que ya resolvió el bug de `js_round()`.
- **Si el script aborta** (extracción ambigua, Binance no responde,
  `git pull` falla): no escribe nada a medias en git — revisar el
  mensaje de `ABORTADO:` y resolver eso primero (p.ej. si `BINANCE_BASE`
  real resulta ser otro dominio, pasarlo por la variable de entorno
  `BINANCE_BASE=... docs/pipeline/verificar_cripto.sh`, confirmar el
  valor real y actualizar `snapshot_autocapture.BINANCE_BASE`).
- **Si el `git push` final falla:** el script imprime el informe
  completo por la terminal con un aviso en mayúsculas — pegarlo a mano
  en la conversación, igual que ya se hacía con
  `check_autocapture_triggers.sh`.

**Cuándo parar aquí:** si el resultado no es `3/3 PASA`, o si
`computeMarketContext()` se extrajo pero nunca se ha revisado su texto
literal contra lo que ya calcula `compute_btc_gate()` (siempre False) —
no seguir al Paso 2 hasta pegar el resultado y decidir con el usuario.

## Paso 2 — dry-run real del script de captura (rama cripto)

Solo si el Paso 1 dio `3/3 PASA`. **Comando exacto, listo para ejecutar
tal cual:**

```bash
cd services/snapshot-autocapture
python3 snapshot_autocapture.py --market crypto --dry-run
```

**Qué esperar:**

- `Universo de tickers activos (CRYPTO): []` y
  `Universo cripto vacío — BTC/ETH/SOL siguen sin ESTADO=ACTIVO...` — es
  el resultado CORRECTO y ESPERADO hoy (BTC/ETH/SOL siguen pausados a
  propósito). El comando debe terminar con código de salida 0 sin
  capturar nada, confirmando que la rama cripto no actúa sola.
- Si se quiere probar el camino completo (fetch de Binance + scoring +
  log de lo que capturaría) sin esperar a activar los tickers reales,
  cambiar TEMPORALMENTE el `ESTADO` de uno solo (p.ej. `BTC`) a
  `ACTIVO` en `14_UNIVERSO_TICKERS`, repetir el comando, y revisar que
  los logs `[DRY RUN] POST /api/snapshots ...` tengan sentido (precio,
  score, estrategia) — **y volver a poner `ESTADO` como estaba
  inmediatamente después**, no dejarlo en `ACTIVO` desde este paso.
- El log debe mostrar `Gate BTC: ON` o `Gate BTC: OFF` -- viene de
  `compute_btc_gate()`, que ya hace el cálculo real (`BTC.price >
  BTC.ema50` 1D, Pregunta 11, ya NO un sustituto fijo) pidiendo las
  velas 1D de BTC a Binance de verdad. No asumir cuál sale sin mirar el
  log -- depende del mercado real en el momento de ejecutar.
- **Con el gate OFF, NINGÚN ticker cripto debe capturar nada, aunque su
  trigger sea `AUTO_HIGH`/`AUTO_MULTI` vía SC-01** (desviación consciente
  de la capa de captura, 07/10/2026 — ver `docs/pipeline/BACKLOG.md`).
  **Con el gate ON, SC-02/SC-PB también pueden capturar** si sus propias
  condiciones se cumplen -- no solo SC-01. Si se activa `BTC` o un
  altcoin temporalmente para probar el camino completo y, con el gate
  OFF, el log muestra `trigger ... descartado en la captura -- gate BTC OFF
  bloquea todos los longs cripto`, es el comportamiento CORRECTO, no un
  bug — `evalSC01()` en el JS real no exige el gate, pero la captura sí
  lo exige aquí, a propósito, más estricta que el scanner.
- Ningún POST real a `/api/snapshots` ni a `/api/evaluate-ticker` (la
  rama cripto construye `ind` vía `build_ind()` llamando a
  `/api/evaluate-ticker` igual que NYSE, con `candles` de Binance en vez
  de `scan-batch` — si el endpoint real sigue sin aplicar en
  `market_data_proxy.py`, esta llamada falla con 404/conexión: es
  esperado, no bloquea el dry-run de todo lo anterior a esa llamada, pero
  si se quiere ver un dry-run completo de principio a fin, aplicar antes
  `docs/pipeline/deploy_evaluate_endpoint.sh`, igual que ya hace falta
  para la rama NYSE).

**Cuándo parar aquí:** si algo en el log no tiene sentido (precio
claramente mal, excepción no esperada, o una captura SÍ ocurre con el
gate OFF) — no seguir, pegar el log completo.

## Paso 3 — decisión del usuario, no automatizada aquí

Estos tres pasos son decisiones explícitas del usuario — **esta tarea
no los ejecuta ni los propone como hechos:**

1. **Resolver los bloqueos reales** (`docs/pipeline/BLOQUEOS.md`):
   portar `compute_market_context()` de verdad (no el sustituto que
   siempre da `False`) y confirmar `BINANCE_BASE`.
2. **Activar BTC/ETH/SOL** en `14_UNIVERSO_TICKERS` (`ESTADO=ACTIVO`) —
   solo cuando el usuario decida, nunca como parte de una verificación.
3. **Crear el timer systemd cripto** — **propuesta, sin crear:**
   frecuencia **1 hora**, igual que ya usa el evaluador para cripto
   (`snapshot_evaluator.py`, referencia ya existente en el repo) — más
   fino que eso no aporta nada nuevo dado que `fetchBinanceKlines` pide
   velas de 15m/1h/1d, no tick a tick; más lento que 1h deja pasar
   compresiones/rupturas intradía que las estrategias SC-01/SC-16-style
   están pensadas para capturar. A diferencia del timer NYSE
   (`OnCalendar` acotado a 16:00-18:00 L-V), este sería
   `OnCalendar=hourly` o `OnUnitActiveSec=1h`, sin ventana — 24/7, como
   ya refleja `_ejecutar_cripto()` en el código. **No se crea ningún
   archivo `.service`/`.timer` en esta tarea** — solo cuando el usuario
   lo pida explícitamente, con el mismo protocolo de verificación del
   Paso 3 del README principal (`--dry-run`, luego una corrida real de
   prueba, solo entonces `systemctl enable --now`).

## Resumen de archivos de esta ruta

| Archivo | Qué es |
|---|---|
| `docs/pipeline/BLOQUEOS.md` | Los 2 bloqueos reales (gate BTC, BINANCE_BASE) y cómo resolverlos |
| `docs/pipeline/check_autocapture_triggers.sh` (Pregunta 11) | Extrae `computeMarketContext()`/`BINANCE_BASE` del servidor real |
| `docs/pipeline/verificar_cripto.sh` | Paso 1 de este runbook |
| `services/snapshot-autocapture/snapshot_autocapture.py` (`--market crypto`) | Paso 2 de este runbook |
| `services/snapshot-autocapture/test_evaluate_ticker_logic_cripto.py` | Pruebas offline del puerto (evalSC01/02/PB, gate off) |
| `services/snapshot-autocapture/test_snapshot_autocapture_cripto.py` | Pruebas offline de la rama cripto del script (mocks, sin red) |
