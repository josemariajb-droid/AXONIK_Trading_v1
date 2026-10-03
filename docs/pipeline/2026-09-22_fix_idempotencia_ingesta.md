# Fix de idempotencia en la escritura n8n → 05_OPERACIONES

**Fecha:** 22/09/2026
**Origen:** reconstrucción forense del bug de ST-16, `docs/auditoria/2026-09-22_auditoria_tarea0.md` §2
**Estado: DISEÑO — no desplegado.** Nada de lo que sigue se ha aplicado en
producción.
**⚠ Premisa corregida el 03/10/2026:** el escritor de `05_OPERACIONES` **no es
n8n**, y el duplicado de ST-16 no se origina en la escritura a Sheets. Leer
primero el "Addendum 03/10/2026" al final: el diseño de nodos n8n de abajo no
es aplicable tal cual.

## Contexto

La reconstrucción forense confirmó que los 4 "duplicados" de ST-16 no son
ruido: son un único lote de 4 señales, escrito íntegro dos veces con
payload byte-idéntico, 11h30 después de la corrida original. Firma de un
fallo de idempotencia en la ruta de escritura — no hay nada en el
mecanismo actual (n8n → Google Sheets, por lo que se puede inferir sin
acceso directo al workflow) que impida reinsertar el mismo lote si la
ejecución se reintenta o se reprocesa manualmente.

## Diseño: idempotencia por clave, con Redis (ya disponible en el stack)

El stack de Hetzner ya corre `axonik_redis` (confirmado en
`AXONIK_Master_Context_v1.md` §5/§7) — no hace falta infraestructura nueva.

**Clave de idempotencia:**
```
idempotency:op:{scn_id_ref}:{ticker}:{fecha}:{precio_entrada}
```
Se usa `precio_entrada` (no la hora de escritura) como parte de la clave
porque es lo que identifica "la misma señal" independientemente de cuándo
se (re)procese — exactamente el campo que en el bug de ST-16 era idéntico
entre las dos escrituras.

**Mecanismo (nodo a nodo, en el workflow que hoy termina en
"Google Sheets Append" sobre `05_OPERACIONES`):**

```
... (nodo que calcula PRECIO_ENTRADA/PRECIO_SALIDA/RESULTADO) ...
        ↓
[Redis — SET NX EX]                    clave = idempotency:op:...
  NX (solo si no existe) + EX 5184000  (60 días — más que cualquier
                                         ventana de reintento realista)
        ↓
[IF: resultado del SET fue OK?]
   ├── SÍ (clave nueva) → [Google Sheets Append] → fila normal
   └── NO (clave ya existía) → [log a 10_ALERTAS o similar con
         ESTADO=REENVIO_SUPRIMIDO] en vez de escribir una fila duplicada
         en 05_OPERACIONES
```

`SET key value NX EX 5184000` es atómico en Redis — dos ejecuciones
concurrentes del mismo lote no pueden ambas ganar el NX, a diferencia de
un lookup-then-write contra Google Sheets (que sí tiene condición de
carrera). Por eso Redis y no un nodo "Sheets Lookup" antes del Append.

**Por qué esto no se puede montar en este repo:** el nodo vive en el
workflow de n8n en `n8n.axonikai.com`, no en este repositorio. Este
documento es el patch listo para aplicar — aplicarlo requiere editar el
workflow directamente en n8n (ver "Bloqueo de acceso").

## Validación en tiempo real de `is_valid_operation()` — alcance real, no todo

El pedido era que `is_valid_operation()` se aplique en tiempo real, no
solo en auditoría retrospectiva. Construido: `services/validation-api/`,
un microservicio FastAPI que envuelve
`scripts/common/validation.py::is_valid_operation` por HTTP — así n8n (que
ejecuta JavaScript, no Python) consulta la única implementación real en
vez de que alguien la reescriba a mano en un Code node (que es exactamente
la reimplementación paralela que Fase 0A eliminó dentro de este repo).

**Pero hay que ser precisos sobre qué cubre esto hoy, y qué no:**

| Motivo de exclusión | ¿Lo captura una llamada a `/validate` en el momento de escribir? |
|---|---|
| `orphan_scanner_ref` | **Sí** — es un lookup puro contra el catálogo de scanners, disponible en el momento de escribir. |
| `duplicate_batch_replay` | **No.** `is_valid_operation` lo detecta hoy por la nota `"excluido..."` en `NOTAS` — pero esa nota la escribe un proceso posterior que ya detectó el lag, no existe todavía en el momento de la escritura original. Este motivo se previene con el mecanismo de Redis de arriba, no llamando a `is_valid_operation` en tiempo real. |
| `entry_price_inconsistent` | **No.** Hoy es una lista de `OP_ID` confirmados manualmente (`CONFIRMED_INVALID_OPS` en `validation.py`) — funciona para auditoría retrospectiva, pero una operación nueva nunca va a estar en esa lista todavía. Para detectar esto en tiempo real haría falta una regla nueva y genérica (p.ej. comparar `PRECIO_ENTRADA` contra la última cotización conocida del mismo ticker y rechazar si la desviación supera un umbral) — **no está construida**, es trabajo de seguimiento, no incluido aquí para no mezclar scope. |

Con esto, `/validate` en tiempo real hoy solo añade protección real contra
`orphan_scanner_ref`. Es real y vale la pena desplegarlo, pero no hay que
presentarlo como "ya cubre las tres causas" — dos de las tres necesitan
mecanismos distintos (Redis para duplicados; una regla de sanidad de
precio, todavía sin diseñar, para el error de entrada).

**Wiring propuesto:** llamar `POST /validate` justo antes del nodo Redis
SET NX de arriba (mismo punto del workflow), y escribir el resultado en
dos columnas nuevas en `05_OPERACIONES` — `VALIDACION_ESTADO`
(`CERTIFICADA`/`EXCLUIDA`) y `VALIDACION_MOTIVO` — en vez de dejar la
exclusión solo como texto libre en `NOTAS`. Eso permite que el dashboard
filtre por una columna estructurada (`COUNTIF(VALIDACION_ESTADO,"CERTIFICADA")`)
en vez de mantener su propia lógica de exclusión — cerrando el hueco que
la auditoría de Fase 0A encontró en las fórmulas actuales.

## Prueba de verificación obligatoria antes de dar la fuga por cerrada

Desplegar el nodo Redis no es el criterio de cierre — el criterio es que
bloquee de verdad el caso exacto que rompió ST-16: un reenvío del mismo
lote con payload idéntico. Sin esta prueba, "está desplegado" y "está
arreglado" son afirmaciones distintas.

**Protocolo:**

1. **Aislar el test.** Usar un ticker y `SCN_ID_REF` obviamente sintéticos
   (p.ej. `ticker=ZZTEST`, `scn_id_ref=ST-16`, `fecha=hoy`) para que la fila
   de prueba sea trivial de identificar y borrar después — no reutilizar un
   scanner real con datos reales para no contaminar el track record.
2. **Reproducir el mecanismo del bug, no solo el síntoma.** El bug
   original no fue "dos filas con 11h30 de diferencia" por sí solo — fue
   "el mismo payload de entrada procesado dos veces". Ejecutar el
   workflow (o el nodo que llega hasta el punto de escritura) dos veces
   seguidas con el mismo payload de prueba (mismo ticker+scn_id+fecha+
   precio_entrada), vía "Execute Node"/"Execute Workflow" con input
   fijado en n8n. No hace falta esperar 11h30 — la clave de idempotencia
   no depende del tiempo transcurrido.
3. **Verificar los tres efectos esperados:**
   - En `05_OPERACIONES`: **una sola fila** para ese payload de prueba
     (no dos).
   - El segundo intento queda registrado como suprimido (rama
     `REENVIO_SUPRIMIDO` del diseño de arriba), no silenciosamente
     descartado sin rastro.
   - En Redis: `GET idempotency:op:ST-16:ZZTEST:<fecha>:<precio_entrada>`
     devuelve el valor esperado, y `TTL` de esa clave está cerca de
     5184000s (60 días), no vacío ni infinito.
4. **Negativo de control (opcional pero recomendado):** repetir el mismo
   procedimiento con un payload de prueba que cambie un solo campo de la
   clave (p.ej. `precio_entrada` distinto) y confirmar que **sí** se
   escriben dos filas — si el fix también bloqueara esto, la clave está
   mal diseñada (demasiado agresiva) y bloquearía señales legítimas
   distintas que coinciden en fecha/ticker/scanner.
5. **Limpieza.** Borrar la fila de prueba de `05_OPERACIONES` y la clave
   de Redis de prueba al terminar.
6. **Registro.** Documentar el resultado (pass/fail de cada paso, IDs de
   ejecución de n8n) como addendum a este mismo archivo, y solo entonces
   cambiar el encabezado de este documento de `DISEÑO — no desplegado` a
   `DESPLEGADO Y VERIFICADO (fecha)`. Sin ese cambio de estado explícito,
   cualquier lectura posterior de este documento debe asumir que la fuga
   sigue abierta.

## Bloqueo de acceso — qué falta para aplicar esto de verdad

Esta sesión no tiene una conexión autorizada al servidor Hetzner ni al
n8n de producción. Se intentó una lectura de solo consulta a la API de
n8n (`GET /api/v1/workflows`, con la API key registrada en
`AXONIK_Master_Context_v1.md`) tras confirmación explícita del usuario —
el propio harness de Claude Code la bloqueó a nivel de clasificador de
permisos ("Credential Exploration"), independientemente de esa
confirmación en el chat. No se reintentó por otras vías para no eludir
ese control.

En consecuencia, **no se ha verificado** si el mecanismo de escritura
actual tiene o no alguna protección parcial ya existente — el diseño de
arriba asume que no la tiene, basado únicamente en la evidencia indirecta
del bug reproducido (si existiera protección real, el bug no habría
ocurrido). Para aplicar el fix hace falta una de estas tres rutas:

1. ~~El usuario añade una regla de permiso en `settings.json`/`settings.local.json`~~
   — descartada deliberadamente: ensancharía el acceso de esta sesión a
   credenciales de producción de forma permanente por un caso puntual.
2. **Ruta elegida.** El usuario (o quien tenga acceso) se conecta por SSH
   al Hetzner (`89.167.80.58`) y ejecuta ahí el `claude` ya instalado
   localmente en esa máquina (`AXONIK_Master_Context_v1.md` §5: "Claude
   Code: instalado y verificado"). **Precisión importante:** `list_environments`
   desde esta sesión solo devuelve dos entornos cloud genéricos
   ("Default — trusted network access"), ninguno vinculado al Hetzner —
   esa instalación es una CLI local en la propia máquina, no un entorno
   de este fleet remoto, así que no se puede lanzar ni mensajear desde
   aquí (`ListAgents` no la ve). Handoff: pasar a esa sesión este
   documento completo (diseño + protocolo de verificación de arriba) como
   contexto inicial — el patch de nodos y el checklist de verificación ya
   están completos, esa sesión solo necesita aplicarlos.
3. El usuario exporta manualmente el workflow (`n8n → Workflows → el que
   escribe en 05_OPERACIONES → Download`), lo pega o sube aquí, y se aplica
   el patch sobre ese JSON en este repo antes de reimportarlo.

Hasta que una de estas tres rutas se resuelva, **el pipeline sigue sin el
fix** — acumular en PAPER mientras tanto reproduce el mismo riesgo que
esta auditoría ya demostró (silenciosamente corrompe datos), tal como se
señaló en la petición original.

---

## Addendum 03/10/2026 — investigación en el Hetzner (solo lectura)

Sesión: Claude Code local en el Hetzner, con acceso directo a los contenedores
`axonik_n8n`, `axonik_redis` y `axonik_postgres`. **No se ha modificado nada en
producción** (n8n, Redis, Postgres, scripts y timers intactos). El estado sigue
en `DISEÑO — no desplegado`, pendiente de revisión del usuario.

### (a) La premisa n8n era incorrecta

Exporté todos los workflows con el CLI del propio contenedor
(`docker exec axonik_n8n n8n export:workflow --all`, sin API key): son 12
workflows y **ninguno escribe en `05_OPERACIONES`**. El único nodo de Google
Sheets está en `TradingView → 10_ALERTAS + Telegram` (`jl2souccwAWpVOBc`:
Gmail Trigger → Parse Alert Code → Sheets Append en `10_ALERTAS` → Mark Read →
Telegram). Ningún workflow tiene nodos de Redis. Por tanto, el patch "nodo
Redis SET NX antes del Google Sheets Append" no tiene dónde aplicarse en n8n.

### (b) Mecanismo real de escritura

| Pieza | Detalle |
|---|---|
| Alta de la señal | `POST /api/snapshots` en `/opt/axonik/scripts/market_data_proxy.py` (`create_snapshot`, ~l.991) → `INSERT` en Postgres `signal_snapshots` |
| Deduplicación existente | `signal_hash` con `UNIQUE CONSTRAINT` (`signal_snapshots_signal_hash_key`), más un SELECT previo y la captura de `UniqueViolation` |
| Escritor de `05_OPERACIONES` | `/opt/axonik/scripts/snapshot_evaluator.py::sync_to_sheet()` (~l.502) → `gspread` `ws.append_row(...)` cuando un snapshot pasa a cerrado |
| Planificación | systemd: `axonik-snapshot-eval-daily.timer` (18:30 todos los días, grupos swing, medio y crypto) y `axonik-snapshot-eval-intraday.timer` (L-V cada 30 min de 16:00 a 22:00, grupo intraday) |
| Reintento | Columna `sheet_synced`. Si `sync_to_sheet()` devuelve `False`, queda en `FALSE` y el bloque "Reintento de sync pendiente" de `main()` lo vuelve a añadir en una ejecución posterior. Ese bloque no filtra por grupo, así que lo ejecutan ambos timers |

### (c) Causa del duplicado de ST-16: no es `sheet_synced`, es el `signal_hash`

**Evidencia de que el sync a Sheets no reenvió nada:**
- `/var/log/axonik/snapshot_eval.log` cubre desde 2026-08-07 16:08 (antes del
  incidente) hasta hoy, con 598 ejecuciones. Contiene **0** líneas
  `sync a Google Sheets falló` y **0** líneas `reintento de sync`.
- Ningún `id` de snapshot aparece cerrado (`CIERRA`) más de una vez.
- Hoy no hay ningún snapshot cerrado con `sheet_synced=FALSE`.

**Evidencia de que el duplicado nace al insertar el snapshot:** busqué en
`signal_snapshots` las filas con el mismo `(ticker, data_ts, entry_price,
estrategias)` y salen exactamente 4 pares, todos de ST-16:

| ticker | data_ts | entry_price | ids | snapshot_ts (UTC) |
|---|---|---|---|---|
| AAPL | 2026-08-07 04:00 | 313.33 | 14 / 19 | 08-07 21:22:40 / 08-08 08:52:53 |
| MSFT | 2026-08-07 04:00 | 499.99 | 15 / 20 | ídem |
| NVDA | 2026-08-07 04:00 | 223.96 | 16 / 21 | ídem |
| AVGO | 2026-08-07 04:00 | 427.76 | 17 / 22 | ídem |

La diferencia es de 11h30m13s, que es exactamente el lag del informe forense.
Cada uno de los 8 snapshots tiene un `signal_hash` distinto, se cerró una sola
vez y se sincronizó una sola vez (`sheet_synced=t`). El evaluador escribió
fielmente 8 filas porque había 8 snapshots.

**Causa raíz** (`market_data_proxy.py::compute_signal_hash`, ~l.552):

```python
date_str = snapshot_dt.strftime("%Y%m%d")      # fecha de la EJECUCIÓN del escaneo
raw = f"{ticker}|{market}|{date_str}|{ids_sorted}"
```

La clave de deduplicación usa la fecha UTC del momento en que corre el
escaneo (`snapshot_ts`), no la de la vela de datos (`data_ts`). La primera
corrida (08-07 21:22 UTC) generó `…|20260807|ST-16` y el re-escaneo de la
mañana siguiente (08-08 08:52 UTC), sobre la **misma** vela de `data_ts`
08-07 y con el mismo precio de entrada, generó `…|20260808|ST-16`. Al ser un
hash distinto, el `UNIQUE` no saltó y entraron 4 snapshots nuevos. Cualquier
re-escaneo que cruce la medianoche UTC antes de que exista una vela nueva
reproduce el bug.

### Latencias secundarias en `sync_to_sheet()` (no causaron ST-16, pero existen)

1. `except Exception` amplio: devuelve `False` ante **cualquier** error. Si
   `append_row` llegó a escribir en Google pero la respuesta falla (error de
   red al leer, 5xx tras commit), la fila existe y `sheet_synced` queda en
   `FALSE`, así que el siguiente reintento la duplica.
2. Ventana sin atomicidad: si el proceso muere entre `append_row` y
   `UPDATE … sheet_synced=TRUE` + `commit`, la siguiente ejecución la vuelve
   a añadir.
3. `gspread` 6.2.1 con `timeout=None` (por defecto): no hay timeout HTTP
   explícito. Un cuelgue bloquearía la ejecución en lugar de fallar.
4. `OP_ID = signal_hash[:12]` se escribe en la hoja, pero no se usa para
   comprobar si ya existe antes del append.

### Implicaciones para el diseño (pendiente de decisión, no aplicado)

- **El guard Redis tal como está diseñado no habría bloqueado ST-16.** La
  clave `…:{fecha}:{precio_entrada}` tomaría `fecha` de la columna `FECHA`,
  que es `snapshot_ts.date()`, y ese valor es justo lo que difería entre
  ambas escrituras (07 frente a 08). Para cubrir el caso, la clave tendría que
  usar la fecha de `data_ts`.
- **El punto de corrección natural es `compute_signal_hash`.** Usar
  `data_dt` (o `data_ts` completo) en lugar de `snapshot_dt` hace que el
  `UNIQUE` ya existente en Postgres sea el guard atómico de idempotencia, sin
  añadir Redis. Contrapartida: dos señales legítimas sobre la misma vela
  y con la misma estrategia pasarían a considerarse la misma. Es el
  comportamiento deseado, pero conviene confirmarlo.
- Las latencias 1 y 2 de `sync_to_sheet()` son un segundo vector
  independiente, con la misma firma. Si se quiere cerrarlo, el guard natural
  es por `OP_ID`/`signal_hash` en el punto del append, ya sea con Redis
  `SET NX` sobre `signal_hash` o con una búsqueda de `OP_ID` en la hoja.
- El protocolo de verificación de arriba (doble positivo, rama suprimida,
  TTL, negativo) sigue siendo válido como criterio de cierre, pero hay que
  reformularlo contra `POST /api/snapshots` y el evaluador en lugar de
  contra "Execute Workflow" en n8n.

**No ejecutado:** ningún paso del protocolo de verificación, porque no hay
nada desplegado que verificar. Fuera de alcance y sin tocar:
`scripts/validation_engine/` y los Gates.
