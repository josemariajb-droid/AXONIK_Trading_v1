# Backlog del pipeline — pendientes priorizados

Documento vivo. Recoge hallazgos **abiertos** para que no se pierdan entre los
addenda de los documentos de investigación. Cada entrada apunta a su fuente
original, que es donde está la evidencia. Aquí solo hay un resumen y el
criterio de cierre.

Al cerrar una entrada: moverla a "Cerrados" con la fecha y el commit o
documento que contiene la evidencia.

Abreviatura usada: **DOC-IDEM** =
[`docs/pipeline/2026-09-22_fix_idempotencia_ingesta.md`](2026-09-22_fix_idempotencia_ingesta.md).

## Abiertos

### 1. [MEDIA] Concurrencia entre los timers diario e intradía (L-V, 18:30)

- **Descripción:** `axonik-snapshot-eval-daily` (18:30 todos los días) y
  `axonik-snapshot-eval-intraday` (L-V, cada 30 min entre 16:00 y 22:00)
  coinciden todos los días laborables a las 18:30. Son dos units `oneshot` sin
  exclusión mutua (hay 44 arranques simultáneos en
  `/var/log/axonik/snapshot_eval.log`). El bloque "Reintento de sync
  pendiente" de `snapshot_evaluator.py` no filtra por `temporal_group`, así
  que dos ejecuciones simultáneas pueden añadir la misma fila dos veces a
  `05_OPERACIONES`. Hoy no se ha materializado (0 snapshots pendientes).
- **Hallazgo original:** DOC-IDEM, Addendum 2, "Hallazgo 3 — ejecuciones
  diaria e intradía simultáneas sin exclusión mutua".
- **Estado:** DISEÑO, sin fix. En DOC-IDEM el hallazgo no tiene esbozo de fix
  a propósito. La única dirección candidata mencionada es `flock`
  compartido en el `ExecStart` de ambas units, y está sin diseñar.
- **Para cerrarlo:** una tarea propia que haga el diseño (lock entre las units,
  o que el reintento se ejecute en una sola de ellas), con su revisión, el
  despliegue y una verificación que fuerce dos ejecuciones simultáneas con un
  snapshot pendiente de prueba y compruebe que se escribe 1 sola fila.

### 2. [ALTA] Puerto 8002 (`market_data_proxy.py`) sin autenticación y con CORS abierto

> Prioridad subida de BAJA a ALTA el 03/10/2026: el diseño de
> `docs/pipeline/2026-10-03_automatizacion_captura_snapshots.md` añade un
> proceso automático nuevo que llama a este proxy sin supervisión humana en
> cada ejecución — no tiene sentido construir más automatización sobre un
> endpoint que hoy solo protege el firewall.

- **Descripción:** el proxy (FastAPI con uvicorn, como root, unit
  `axonik-market-proxy`) escucha en `0.0.0.0:8002` sin autenticación en ningún
  endpoint y con `allow_origins=["*"]`. Expone escrituras: crear, cerrar y
  borrar snapshots, `circuit-breaker/breach` y `scan-batch`. Estuvo expuesto
  a internet desde el 07/08/2026 hasta el 03/10/2026 a las 18:21 CEST. Solo se
  observaron sondeos de bots (404) y no hay rastro de escrituras ajenas. Hoy
  lo protege **solo el firewall**, verificado el 03/10 a las 20:10: ufw sin
  regla para 8002, iptables, ip6tables y nftables sin reglas para 8002, y
  política `INPUT DROP`.
- **Hallazgo original:** DOC-IDEM, "Hallazgo 4 — `market_data_proxy`
  expuesto en `0.0.0.0:8002` sin autenticación", más la "Comprobación previa
  al despliegue" del Addendum 3.
- **Estado:** DISEÑO (antes INFORME) — decisión tomada: bind a `127.0.0.1`
  en vez de token (§3.4/§1.6 de
  `docs/pipeline/2026-10-03_automatizacion_captura_snapshots.md`). Patch de
  una línea + pasos de despliegue en
  `services/snapshot-autocapture/README.md`, sin aplicar todavía.
- **Para cerrarlo:** añadir autenticación real en el servicio, no depender solo
  del firewall. Como mínimo, los endpoints de escritura deben exigir un token
  y el frontend `/scanner` debe enviarlo. Además, restringir el CORS al
  origen real del scanner y valorar el bind a `127.0.0.1` si nada externo lo
  necesita. Verificación: peticiones sin token rechazadas (401/403) en todos
  los endpoints de escritura, y el scanner sigue funcionando con token.

### 3. [BAJA] `/opt/axonik/scripts/` no está bajo control de versiones

- **Descripción:** los scripts de producción (`market_data_proxy.py`,
  `snapshot_evaluator.py`, `schema.sql`, etc.) no están en ningún repositorio
  git. El fix del 03/10/2026 (hash v2) solo existe como fichero desplegado, la
  copia `market_data_proxy.py.bak.20261003_201110` y el diff transcrito en
  DOC-IDEM, sin un diff real de git. El directorio acumula `.bak` con fecha
  como único historial.
- **Hallazgo original:** DOC-IDEM, Addendum 3 ("Comprobaciones previas…
  no está bajo control de versiones") y Addendum 4 (despliegue y rollback).
- **Estado:** pendiente de decidir dónde vivirá: en este repo o en uno aparte.
- **Para cerrarlo:**
  1. Decidir el repositorio.
  2. Antes del primer commit, excluir los secretos:
     `/opt/axonik/scripts/credentials.json` es una service account de
     Google y **no debe** entrar en git.
  3. Excluir también `.bak*`, `__pycache__` y similares.
  4. Hacer un commit inicial con el estado actual, que ya incluye el hash v2.
  5. Acordar que los cambios en producción pasen por commit (y, si se quiere,
     un despliegue desde el repo en lugar de editar en sitio).

### 4. [MEDIA, propuesta: confirmar] `sync_to_sheet()` no es idempotente

> Esta entrada no estaba en la lista original del backlog. La añado para que
> no se pierda, porque es el otro hallazgo abierto de DOC-IDEM. La prioridad es
> una propuesta y está pendiente de confirmar.

- **Descripción:** en `snapshot_evaluator.py::sync_to_sheet()`:
  - un `except Exception` amplio convierte errores ambiguos (la fila llegó
    a escribirse pero la respuesta falló) en `sheet_synced=FALSE`, y el
    reintento la duplica;
  - no se comprueba `OP_ID` en la hoja antes del append;
  - hay una ventana sin atomicidad entre el append y el
    `UPDATE sheet_synced=TRUE`;
  - gspread no tiene timeout (`timeout=None`).

  Es independiente de ST-16 y no se ha materializado (0 fallos de sync en el
  log). Está relacionado con la entrada 1, que es otro camino hacia el mismo
  síntoma.
- **Hallazgo original:** DOC-IDEM, Addendum 2, "Hallazgo 2 —
  `sync_to_sheet()` no es idempotente".
- **Estado:** DISEÑO, con un esbozo de dirección (comprobar `OP_ID` antes
  del append, `set_timeout` y tratamiento de errores ambiguos).
- **Para cerrarlo:** diseño, revisión y despliegue. La verificación consiste
  en simular un fallo tras un append correcto y comprobar que el reintento no
  duplica la fila.

### 5. [MEDIA] Automatizar `autoCaptureSnapshots()` (reemplazar la dependencia del navegador)

- **Descripción:** la captura de snapshots depende hoy de tener el scanner
  HTML abierto con auto-refresh en el navegador. Diseño +
  **implementación real** (sin Playwright, confirmado) en
  `docs/pipeline/2026-10-03_automatizacion_captura_snapshots.md` y
  `services/snapshot-autocapture/`.
- **Hallazgo original:** este documento (03/10/2026), a partir de la
  investigación ya existente en DOC-IDEM Addendum 2 §1.2.
- **Estado:** IMPLEMENTADO (parcial), NO DESPLEGADO, BLOQUEADO por un gap
  real. Bloqueante de Playwright cerrado (`detectAutoTrigger`/
  `evaluateTicker`/`NYSE_STRATEGIES`/`CRYPTO_STRATEGIES`/
  `applyEventAdjustments`/`tickerHardNo`, confirmados como aritmética/
  orquestación pura sin DOM — pero solo confirmado que son "limpias", no
  su contenido). Pregunta 4 ejecutada contra el código real: 2 de 3
  puntos estimados se corrigieron (`risk_pct` → `risk_per_share` — era
  un error real, no solo una estimación sin confirmar; umbral único →
  dos ramas `AUTO_HIGH`/`AUTO_MULTI`), pero reveló que el cálculo del
  score en sí nunca se portó — `/api/scan-batch` devuelve indicadores en
  bruto, no un score precalculado como asumía el script.
  `evaluate_ticker()` es ahora un `NotImplementedError` explícito.
  Depende también de la entrada 2 de este backlog (bind a `127.0.0.1`,
  patch listo, no aplicado).
- **Decisión de arquitectura (04/10/2026):** no se porta `evaluate_ticker()`
  dentro de `snapshot_autocapture.py`. Se expone `POST /api/evaluate-ticker`
  nuevo en `market_data_proxy.py` — single source of truth server-side, en
  vez de dos implementaciones (navegador y script Python) que puedan
  divergir en silencio, como ya pasó con `signal_hash` y con
  `risk_pct`/`risk_per_share`.
- **Cadena de dependencias cerrada (04/10/2026):** 4 rondas de extracción
  dirigida (Preguntas 5/5b/5c/5d) llegaron a 22 piezas con texto literal,
  fondo confirmado en `MAX_RAW_SCORE` (objeto literal, sin más llamadas).
  Puerto a Python entregado en
  `services/snapshot-autocapture/evaluate_ticker_logic.py`, con 10
  pruebas unitarias (todas pasan) — detalle en el documento de diseño §1.7.
- **BLOQUEADO por un hallazgo estructural nuevo, no uno de datos:**
  `evaluateTicker()` real evalúa las 7 estrategias NYSE (o las 3 crypto)
  fijas por `mode` en una sola llamada por *ticker* — no una llamada por
  (ticker, scanner) como asumía el diseño de `cargar_universo_de_scanners()`.
  `NYSE_STRATEGIES`/`CRYPTO_STRATEGIES` son arrays fijos en el código, no
  se filtran por `02_SCANNERS.ESTADO` en tiempo de ejecución. Falta
  decidir de dónde sale el universo de *tickers* a evaluar (no de
  estrategias) antes de cablear el endpoint a `snapshot_autocapture.py` —
  ver documento de diseño §1.8. `ST-04` tiene entrada en `STRATEGY_META`/
  `MAX_RAW_SCORE` pero no está en `NYSE_STRATEGIES` — no se evalúa hoy en
  ningún `autoCaptureSnapshots()`, señalado sin interpretar más.
- **Verificación de `11_LISTAS` como fuente del universo de tickers
  (04/10/2026):** descartada. Contenido real confirmado leyendo
  `11_LISTAS.csv` (snapshot del 21/09/2026, exportado de
  `AXONIK Decision Engine v2.xlsx`): la hoja es un catálogo de 22 columnas
  `rng_*` (`rng_markets`, `rng_categories`, `rng_timeframes`,
  `rng_strategy_type`, `rng_indicators`, `rng_sectors`, `rng_brokers`,
  `rng_exchanges`, etc.) con valores enumerados para listas desplegables
  (`ACCIONES_US`, `MOMENTUM`, `1m`, `LONG`, `EMA20`, `TECNOLOGIA`, `IBKR`,
  `NYSE`, `WIN`...). Ninguna columna contiene símbolos de ticker
  individuales (`AAPL`, `GOOGL`, `BTC`...) — es catálogo de categorías, no
  una lista de tickers. Decisión tomada a continuación: lista nueva en
  hoja propia, no en `11_LISTAS`.
- **Decisión del universo de tickers (04/10/2026):** hoja nueva
  `14_UNIVERSO_TICKERS` en el Decision Engine (no JSON estático, no
  `localStorage`). Columnas, esquema **aprobado** 04/10/2026: `TICKER`,
  `MERCADO` (`NYSE`/`CRYPTO`), `ESTADO` (`ACTIVO`/`PAUSADO`, misma lógica
  de activación que `02_SCANNERS.ESTADO`), `FECHA_ALTA`, `NOTAS` (texto
  libre, mismo patrón que `05_OPERACIONES.NOTAS`). Esquema final y fila
  propuesta para `00_README` documentados en el diseño §1.9. Sustituye a
  `cargar_universo_de_scanners()`/`02_SCANNERS.ESTADO` como fuente del
  universo para esta automatización (`02_SCANNERS` sigue existiendo para
  lo demás).
- **BLOQUEADO (herramienta, no decisión) — crear la hoja real:** esta
  sesión no tiene ninguna herramienta capaz de escribir en el Google
  Sheet real (el `Google_Drive` MCP conectado aquí solo soporta
  operaciones de archivo completo — crear archivo nuevo o cambiar
  título/carpeta de uno existente, no añadir pestañas ni filas dentro de
  un spreadsheet; las escrituras reales usan `gspread` con la service
  account del Hetzner, sin acceso desde esta sesión). El contenido exacto
  para pegar a mano (fila de `00_README` + cabecera de la pestaña nueva)
  está listo en el diseño §1.9, a la espera de que el usuario lo aplique
  él mismo.
- **Para cerrarlo:** (1) aplicar a mano en el Excel real la fila de
  `00_README` y la pestaña `14_UNIVERSO_TICKERS` (contenido listo en
  diseño §1.9 — bloqueado para esta sesión por falta de herramienta, ver
  arriba); (2) actualizar `cargar_universo_de_tickers()` en
  `snapshot_autocapture.py` para leer de ahí filtrando `ESTADO=ACTIVO`;
  (3) cablear `POST /api/evaluate-ticker` en el proxy con
  `evaluate_ticker_logic.py`; (4) verificación navegador-vs-endpoint con
  datos reales, obligatoria antes de marcar "verificado"; (5) confirmar
  si "mismo grupo" en `AUTO_MULTI` es de verdad `temporal_group` (lectura
  actual del campo `group` de `STRATEGY_META`, consistente con el texto
  literal de `detectAutoTrigger`, pero sin una comparación navegador-vs-
  endpoint todavía); (6) aplicar el bind a `127.0.0.1`; (7) desplegar y
  verificar siguiendo el protocolo del README (`--dry-run`, luego una
  corrida real con ZZTEST fuera de la franja de los timers del
  evaluador) antes de habilitar el timer.

### 6. [BAJA] `/scanner` mantiene su copia local de `evaluateTicker()` tras crear `/api/evaluate-ticker`

- **Descripción:** al cerrar la entrada 5, `evaluateTicker()` +
  `NYSE_STRATEGIES`/`CRYPTO_STRATEGIES`/`applyEventAdjustments`/
  `tickerHardNo` pasan a vivir también (portadas) en
  `POST /api/evaluate-ticker` dentro de `market_data_proxy.py`. El
  navegador (`/opt/axonik/scanner/index.html`) sigue calculando con su
  propia copia local — deliberadamente, no se toca en esa tarea. Mientras
  existan dos copias, pueden divergir si alguien edita una sin la otra.
- **Hallazgo original:** decisión de arquitectura del 04/10/2026 en la
  entrada 5 de este backlog.
- **Estado:** DEUDA ACEPTADA, no urgente — las dos copias parten del mismo
  texto fuente recién verificado (entrada 5), así que el riesgo de
  divergencia es bajo mientras no se edite ninguna de las dos.
- **Para cerrarlo:** una vez que `POST /api/evaluate-ticker` lleve tiempo
  estable en uso automático (criterio a definir — p.ej. unas semanas sin
  incidencias), migrar `evaluateTicker()` del navegador a llamar a ese
  mismo endpoint en vez de calcular localmente, y retirar la copia JS.

### 7. [MEDIA] `ST-04` no está en `NYSE_STRATEGIES` — no se evalúa en ningún escaneo

- **Descripción:** la auditoría Fase 0A certificó una operación real con
  `ST-04` (GOOGL, el único WIN de esa estrategia). Sin embargo, el array
  real `NYSE_STRATEGIES` del navegador (confirmado por texto literal en
  la Pregunta 5/5b, ver entrada 5 de este backlog) no incluye `ST-04` —
  solo contiene `ST-01, ST-05, ST-06, ST-09, ST-11, ST-15, ST-16`. Como
  `evaluateTicker()` recorre ese array fijo por `mode`, `ST-04` no se
  evalúa hoy en ningún escaneo, ni manual (navegador) ni automático
  (futuro `POST /api/evaluate-ticker`, que porta el mismo array). Es
  independiente de la tarea de automatización: el hallazgo es que una
  estrategia con un WIN certificado quedó fuera del escaneo activo, no un
  problema de cómo se automatiza.
- **Hallazgo original:** cruce entre la auditoría Fase 0A (operación
  GOOGL/ST-04) y la extracción literal de `NYSE_STRATEGIES` en
  `docs/pipeline/2026-10-03_automatizacion_captura_snapshots.md` §1.7
  (entrada 5 de este backlog).
- **Estado:** INFORME, sin decisión. No se ha confirmado si `ST-04`
  tiene también entrada en `STRATEGY_META`/`MAX_RAW_SCORE` como las
  demás (pendiente de revisar si hace falta para la decisión) ni por qué
  se excluyó de `NYSE_STRATEGIES` en su momento.
- **Para cerrarlo:** decidir si `ST-04` se reincorpora a
  `NYSE_STRATEGIES` (y a partir de ahí se evalúa igual que las otras 7) o
  se retira formalmente como estrategia (documentando que su único WIN
  queda como histórico, sin escaneo futuro). Fuera del alcance de la
  tarea de automatización de la entrada 5 — no bloquea su cierre.

## Cerrados

| Fecha | Entrada | Evidencia |
|---|---|---|
| 03/10/2026 | `signal_hash` calculado sobre la fecha de escaneo (causa de los duplicados de ST-16): hash v2 sobre `data_ts` | DOC-IDEM, Addendum 4 (commit `fc6ed75`) |
