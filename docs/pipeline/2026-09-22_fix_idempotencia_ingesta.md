# Fix de idempotencia en la escritura n8n → 05_OPERACIONES

**Fecha:** 22/09/2026
**Origen:** reconstrucción forense del bug de ST-16, `docs/auditoria/2026-09-22_auditoria_tarea0.md` §2
**Estado: DISEÑO — no desplegado.** Ver "Bloqueo de acceso" al final. Nada de
lo que sigue se ha aplicado en el n8n de producción (`n8n.axonikai.com`).

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

1. El usuario añade una regla de permiso en `settings.json`/`settings.local.json`
   que autorice llamadas de red a `n8n.axonikai.com` desde esta sesión (skill
   `update-config` puede montarla), y se repite el intento de conexión.
2. El usuario abre una sesión de Claude Code con el entorno Hetzner ya
   conectado (`list_environments`/`create_session`) y se le pasa este
   documento + `services/validation-api/` como contexto de partida.
3. El usuario exporta manualmente el workflow (`n8n → Workflows → el que
   escribe en 05_OPERACIONES → Download`), lo pega o sube aquí, y se aplica
   el patch sobre ese JSON en este repo antes de reimportarlo.

Hasta que una de estas tres rutas se resuelva, **el pipeline sigue sin el
fix** — acumular en PAPER mientras tanto reproduce el mismo riesgo que
esta auditoría ya demostró (silenciosamente corrompe datos), tal como se
señaló en la petición original.
