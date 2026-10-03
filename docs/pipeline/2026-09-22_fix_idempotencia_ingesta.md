# Fix de idempotencia en la escritura n8n → 05_OPERACIONES

**Fecha:** 22/09/2026
**Origen:** reconstrucción forense del bug de ST-16, `docs/auditoria/2026-09-22_auditoria_tarea0.md` §2
**Estado: DISEÑO — no desplegado.** Nada de lo que sigue se ha aplicado en
producción.
**⚠ Premisa corregida el 03/10/2026:** el escritor de `05_OPERACIONES` **no es
n8n**, y el duplicado de ST-16 no se origina en la escritura a Sheets. Leer
primero los addenda del 03/10/2026 al final. El diseño de nodos n8n de abajo no
es aplicable tal cual: el diseño vigente es el del "Addendum 2".

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

## Addendum 2 — 03/10/2026: diseño corregido (DISEÑO, no implementado)

Hay **dos hallazgos separados**, con causas y fixes distintos:

- **Hallazgo 1, la causa de ST-16:** `signal_hash` se calcula sobre la fecha de
  ejecución del escaneo.
- **Hallazgo 2, un riesgo latente:** la escritura a Sheets en
  `sync_to_sheet()` no es idempotente.

No se ha tocado nada en producción. Todo lo de abajo es diseño pendiente de
revisión.

### Hallazgo 1 — `signal_hash` usa la fecha de escaneo, no `data_ts`

#### 1.1 La restricción `UNIQUE` de Postgres no cubre el caso

```
signal_snapshots_signal_hash_key | UNIQUE (signal_hash)     ← única restricción de unicidad
signal_snapshots_pkey            | PRIMARY KEY (id)
(+ 3 CHECK de precio/riesgo; índices no únicos en status, ticker, snapshot_ts y temporal_group)
```

(`SELECT conname, pg_get_constraintdef(oid) FROM pg_constraint WHERE conrelid='signal_snapshots'::regclass`)

La restricción solo cubre `signal_hash`, y ese hash
(`compute_signal_hash`) se construye con `snapshot_dt.strftime("%Y%m%d")`.
**No hay ninguna restricción que incluya `data_ts`.** El guard existe en
forma, pero hereda el defecto del hash. No hace falta un guard nuevo: hace
falta que el que ya existe use la clave correcta.

Restricción relevante para cualquier migración: el trigger
`trg_snapshot_immutable` (`prevent_snapshot_mutation`, BEFORE UPDATE) prohíbe
modificar `signal_hash`, `snapshot_ts`, `data_ts`, `strategies`, etc. **No se
pueden recalcular los hashes de las filas existentes** sin desactivar el
trigger. `DELETE` sí está permitido, porque el trigger solo actúa sobre
UPDATE.

#### 1.2 Qué dispara el re-escaneo: es recurrente por diseño, aunque hoy está inactivo

**Quién crea snapshots.** Solo hay una vía: el scanner HTML
(`/opt/axonik/scanner/index.html`, que sirve el propio proxy en
`:8002/scanner`), desde el navegador. **No hay ningún cron ni timer de
servidor que cree snapshots.** Los timers de systemd solo ejecutan el
evaluador, que lee y cierra snapshots. Hay dos rutas:

- `autoCaptureSnapshots()` (~l.2690): se ejecuta en **cada** `runScan()`.
  Captura automáticamente (`AUTO_HIGH`) los tickers que pasan
  `detectAutoTrigger`.
- El botón "Seguir" (`MANUAL`, ~l.2046).

`runScan()` se dispara a mano o con el auto-refresh opcional
(`setAutoRefreshTimer`, cada 15 min mientras la pestaña está visible).

**El único guard del cliente se reinicia a medianoche UTC.** Se llama
`state.followedToday` y lo carga `loadFollowedToday()` con
`GET /api/snapshots?status=OPEN&since=<00:00 UTC de hoy>`. La clave del
servidor también usa el día UTC del escaneo. Los dos guards caducan a la vez
a las 00:00 UTC, mientras que `data_ts` (la vela 1D) no cambia hasta que hay
una vela nueva.

**Ventana en la que el bug se reproduce (NYSE).** La vela diaria de
yfinance tiene `t = 04:00 UTC`, es decir, 00:00 en Nueva York. Desde las 00:00
UTC hasta la apertura del mercado (13:30 UTC en verano, 14:30 UTC en invierno),
la última vela sigue siendo la del día anterior. **Cualquier escaneo NYSE
en esa franja de unas 13,5 h diarias recaptura, con un hash nuevo, toda
señal capturada el día UTC anterior que siga cumpliendo el trigger.** En fin
de semana o festivo la ventana se amplía: una señal del viernes puede
recapturarse el sábado, el domingo y el lunes por la mañana, es decir, hasta
4 copias. ST-16 encaja exactamente: el primer escaneo fue el 08-07 a las 21:22
UTC (23:22 en Madrid) y el segundo el 08-08 a las 08:52 UTC (10:52 en Madrid),
ambos sobre la vela con `data_ts 2026-08-07 04:00 UTC`.

En crypto el problema prácticamente no existe con velas 1D, porque la vela de
Binance abre a las 00:00 UTC y su fecha coincide casi siempre con el día UTC
del escaneo.

El defecto opuesto también existe: dos escaneos el mismo día UTC sobre
**velas distintas** (por ejemplo, a las 12:00 UTC sobre la vela del día
anterior y a las 15:00 UTC sobre la parcial de hoy) generan el mismo hash, y
el segundo se descarta como duplicado aunque sea una señal nueva.

**¿Está activo ahora?** El bug es recurrente por diseño, pero **hoy no se
está disparando, porque el scanner no se usa:**
- `signal_snapshots` tiene 12 filas (ids 14–26) y la última es del
  **2026-08-08 08:56 UTC**. No se ha capturado nada en casi 2 meses.
- El journal del proxy (disponible desde el 25/09) no tiene ninguna petición
  a `/api/scan-batch` ni a `/api/snapshots`. Solo hay sondeos de bots
  (`/`, `/mcp`, `/robots`…).
- No he podido determinar si el segundo escaneo del 08/08 fue manual o
  vino del auto-refresh: el log de nginx empieza el 15/09 y el proxy no
  registraba accesos en agosto. Sea cual sea el origen, la causa es la misma.

**En cuanto se vuelva a usar el scanner (para acumular PAPER), el bug se
reactiva** en cada escaneo NYSE que caiga en la ventana descrita.

#### 1.3 Diseño del fix: la clave pasa a ser `data_ts`

**Clave de identidad de una señal:** `ticker + market + data_ts + estrategias`.
Una señal es "esta estrategia disparó sobre esta vela". La hora del escaneo
no forma parte de la identidad.

**Fix principal, en Postgres y en el proxy (recomendado, sin Redis):**

```python
# market_data_proxy.py
def compute_signal_hash(ticker, market, data_dt, strategy_ids) -> str:
    data_key = data_dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    ids_sorted = ",".join(sorted(strategy_ids))
    raw = f"v2|{ticker.upper()}|{market.lower()}|{data_key}|{ids_sorted}"
    return hashlib.sha256(raw.encode()).hexdigest()

# create_snapshot():
signal_hash = compute_signal_hash(req.ticker, req.market, data_dt, strategy_ids)  # data_dt, no snapshot_dt
```

- **Por qué basta:** el `UNIQUE (signal_hash)` existente, junto con la captura
  de `UniqueViolation` que ya tiene `create_snapshot`, es atómico. Dos
  peticiones concurrentes no pueden insertar ambas. Esto es equivalente al
  `SET NX` de Redis del diseño original, pero en la fuente de verdad y sin
  infraestructura nueva.
- **`data_ts` completo, no solo la fecha.** Así la clave no depende de
  zonas horarias ni de cómo se trunque la fecha, y sirve igual para
  velas no diarias si en el futuro `data_ts` se toma de otro timeframe.
  Requisito: el cliente debe enviar el `t` de la vela tal cual (hoy ya lo
  hace con `d.candles[last].t`).
- **El prefijo `v2|`** separa explícitamente el espacio de hashes nuevo
  del antiguo. Las filas existentes conservan su hash v1, que el trigger de
  inmutabilidad impide recalcular. No hay riesgo de colisión ni de falso
  "no duplicado" entre v1 y v2, porque todas las filas v1 son de agosto y
  nunca se volverá a escanear sobre esas velas.
- **Sin precio en la clave**, y esto es una corrección deliberada respecto
  al diseño original, que incluía `precio_entrada`. Si se escanea durante la
  sesión, la vela de hoy es parcial y `entry_price` cambia en cada escaneo.
  Con el precio en la clave, cada re-escaneo intradía crearía otra señal. En
  el propio ST-16, el `stop_price` de AVGO ya difería entre las dos copias
  (389.0360 frente a 389.0352). La regla resultante es "la primera captura
  sobre una vela gana" y las siguientes devuelven `created:false` con
  `existing_id`, que es la misma semántica que tiene hoy dentro de un día
  UTC. **Este punto requiere su confirmación.**
- **Rastro de la supresión:** hoy `created:false` se devuelve sin dejar
  registro. El diseño añade un `logger.info("snapshot duplicado suprimido
  ticker=… data_ts=… existing_id=…")`. Es el equivalente a la rama
  `REENVIO_SUPRIMIDO`.
- **Cliente (opcional, solo para la interfaz):** `loadFollowedToday()` podría
  dejar de filtrar por medianoche UTC y considerar seguido un ticker si tiene
  un snapshot `OPEN` sobre la vela actual. No es necesario para la
  integridad, porque el servidor ya rechaza el duplicado, pero evita el
  aviso falso de "señal capturada".

**Endurecimiento opcional (alternativa a la anterior, más invasiva):**
añadir una columna `dedup_key` con su propio `UNIQUE`, en lugar de reutilizar
`signal_hash`. La única ventaja es que la regla queda explícita en el
esquema. Costes: una migración y un backfill que chocaría con los 4 pares
duplicados existentes (habría que dejar `dedup_key = NULL` en los ids 19–22).
**No lo recomiendo** para este fix.

**Guard Redis complementario: no lo recomiendo para el hallazgo 1.**
Postgres ya ofrece unicidad atómica en el mismo punto de escritura. Un `SET
NX` en Redis delante añadiría una segunda fuente de verdad que puede
divergir (si el `SET` tiene éxito y el `INSERT` falla, la señal queda
bloqueada 60 días sin existir) y no cubre ningún caso adicional. Redis
podría encajar en el hallazgo 2 (ver abajo), no aquí.

**Filas existentes (fuera de este fix):** los 4 duplicados (ids 19–22) siguen
en la base de datos. Su exclusión de métricas ya está decidida en la capa de
validación (`duplicate_batch_replay`), así que el fix no los borra ni los
modifica.

#### 1.4 Protocolo de verificación reformulado para el hallazgo 1

Se ejecuta contra `POST /api/snapshots`, no contra n8n:

1. **Doble positivo, que reproduce el mecanismo de ST-16.** Hacer dos POST con
   `ticker=ZZTEST`, `strategies=[{id:"ST-16"}]` y el **mismo** `data_ts`, pero
   con `snapshot_ts` en **días UTC distintos** (por ejemplo, 23:22 UTC del día
   D y 08:52 UTC del día D+1). Esperado: el primero devuelve `created:true`,
   el segundo `created:false` con el `existing_id` del primero, y hay 1 sola
   fila en la base de datos.
2. **Rama de supresión:** la línea `snapshot duplicado suprimido` aparece en el
   log del proxy para el segundo POST.
3. **Negativo de control:** un tercer POST con `data_ts` distinto (la vela
   siguiente) debe devolver `created:true`, con 2 filas en total. Un segundo
   negativo: mismo `data_ts` y otra estrategia (`ST-05`) también debe devolver
   `created:true`.
4. **TTL:** no aplica, porque no hay Redis en este fix. La clave de Postgres
   es permanente, lo cual es correcto: una vela pasada no vuelve a ser
   actual.
5. **Limpieza:** `DELETE FROM signal_snapshots WHERE ticker='ZZTEST'` (el
   trigger lo permite) **antes de que corra el siguiente evaluador**. Si no,
   el evaluador intentará evaluar ZZTEST y llegará a `sync_to_sheet()`.
   Hacer la prueba fuera de la franja de los timers (16:00–22:00 en días
   laborables y 18:30 todos los días) y verificar la limpieza con un
   `SELECT` antes de cerrar.

### Hallazgo 2 — `sync_to_sheet()` no es idempotente (riesgo latente, independiente de ST-16)

Este hallazgo **no** causó ST-16: hay 0 fallos de sync en el log desde el
07/08 y ningún snapshot se cerró dos veces. Pero puede producir la misma
firma (filas duplicadas en `05_OPERACIONES`) por una vía totalmente distinta,
y el fix del hallazgo 1 no lo cubre.

**Riesgos** (`/opt/axonik/scripts/snapshot_evaluator.py`):

1. **El `except Exception` se traga los errores** (`sync_to_sheet`, ~l.539).
   Cualquier error devuelve `False` y solo deja un `WARNING`. El problema son
   los errores ambiguos: si `append_row` llegó a escribir en Google pero
   falla la respuesta (un reset de conexión al leer, un 5xx/429 tras aplicar
   la escritura), la fila existe, `sheet_synced` se queda en `FALSE` y el
   bloque "Reintento de sync pendiente" la vuelve a añadir en la siguiente
   ejecución.
2. **No se comprueba `OP_ID` antes del append.** La fila lleva
   `OP_ID = signal_hash[:12]`, una clave natural perfecta, pero nadie
   comprueba si ya está en la hoja antes de añadirla. El único guard es
   `sheet_synced` en Postgres, que no es atómico con la escritura en Google.
3. **Ventana sin atomicidad entre el append y el `UPDATE sheet_synced=TRUE` +
   `commit`.** Si el proceso muere ahí (OOM, reinicio, kill del timer), en la
   siguiente ejecución se duplica.
4. **gspread puede colgarse:** la versión 6.2.1 tiene `timeout=None` por
   defecto, y `_get_worksheet()` no fija ninguno. Una conexión colgada
   bloquea el proceso indefinidamente. Si se mata por timeout externo, se cae
   en el punto 3.
5. **Ejecuciones concurrentes sin lock (riesgo nuevo, confirmado en el log).**
   `axonik-snapshot-eval-daily` (18:30 todos los días) y
   `axonik-snapshot-eval-intraday` (cada 30 min entre 16:00 y 21:30, L-V,
   **incluido 18:30**) son units distintas sin exclusión mutua. Hay **44
   ocasiones** en el log con dos `run start` en el mismo minuto (las más
   recientes: 28/09 a 02/10, siempre a las 18:30). El bucle principal filtra
   por grupo, pero **el bloque de reintento no**: si hubiera snapshots
   pendientes, las dos ejecuciones simultáneas los añadirían a la vez a la
   hoja.

**Dirección del fix (solo esbozo; requiere su propio diseño y revisión):**

- Exclusión mutua entre las dos ejecuciones: `flock` en el `ExecStart` de
  ambas units sobre el mismo fichero de lock, o un lock de Redis `SET NX EX`
  con TTL corto.
- Comprobar `OP_ID` en la hoja antes del append (lee la columna `OP_ID` y
  omite si ya está). Con el lock anterior, esta lectura previa deja de tener
  condición de carrera, y es lo único que resuelve el caso ambiguo del punto 1.
- `set_timeout` explícito en el cliente de gspread.
- Distinguir los errores ambiguos de los definitivos en el `except`, o
  confiar en la comprobación de `OP_ID` para que el reintento sea inocuo
  en ambos casos.

### Estado

**DISEÑO, no implementado ni desplegado.** Pendiente de revisión del usuario
de: (i) la clave `ticker+market+data_ts+estrategias` sin precio (§1.3),
(ii) descartar Redis para el hallazgo 1, y (iii) abrir un diseño propio
para el hallazgo 2. Fuera de alcance y sin tocar: `scripts/validation_engine/`
y los Gates.
