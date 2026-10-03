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
- **Estado:** DISEÑO (antes INFORME) — diseño de autenticación mínima en
  `docs/pipeline/2026-10-03_automatizacion_captura_snapshots.md` §3, sin
  desplegar.
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
  HTML abierto con auto-refresh en el navegador. Diseño de automatización
  headless (timer systemd, ventana 16:00-18:00 Madrid L-V) en
  `docs/pipeline/2026-10-03_automatizacion_captura_snapshots.md`. Bloqueado
  por una pregunta sin confirmar: si `detectAutoTrigger()` y el universo de
  tickers que evalúa `runScan()` dependen de algo calculado solo en el
  navegador, haría falta Playwright en vez de un script Python simple — ver
  §1.2 de ese documento.
- **Hallazgo original:** este documento (03/10/2026), a partir de la
  investigación ya existente en DOC-IDEM Addendum 2 §1.2.
- **Estado:** DISEÑO, no implementado. Depende también de que la entrada 2
  de este backlog (autenticación del proxy) tenga al menos una mitigación
  mínima antes de desplegarse — no construir más automatización sobre un
  endpoint abierto.
- **Para cerrarlo:** (1) extraer el código real de `autoCaptureSnapshots`/
  `detectAutoTrigger`/`runScan` para confirmar que es replicable sin
  navegador; (2) implementar `snapshot_autocapture.py` + unit systemd; (3)
  desplegar y verificar que respeta la ventana operativa y que no captura
  nada fuera de ella ni con un arranque manual del servicio.

## Cerrados

| Fecha | Entrada | Evidencia |
|---|---|---|
| 03/10/2026 | `signal_hash` calculado sobre la fecha de escaneo (causa de los duplicados de ST-16): hash v2 sobre `data_ts` | DOC-IDEM, Addendum 4 (commit `fc6ed75`) |
