# Automatización de la captura de snapshots (reemplazo de `autoCaptureSnapshots()`)

**Fecha:** 03/10/2026
**Estado: DISEÑO — no implementado.** Pendiente de tu revisión antes de escribir
ningún código o tocar el servidor.
**Relacionado:** `docs/pipeline/2026-09-22_fix_idempotencia_ingesta.md` (en
adelante **DOC-IDEM**) — el Addendum 2 de ese documento es la fuente de la
evidencia sobre `autoCaptureSnapshots()` usada aquí. `docs/pipeline/BACKLOG.md`
(en adelante **BACKLOG**) — entrada 2, cuya prioridad sube en este documento.

---

## 0. Qué puedo y qué no puedo verificar desde esta sesión

Antes de entrar en el diseño: esta sesión **no tiene acceso al servidor
Hetzner** (ni SSH ni HTTPS — verificado en la tarea anterior, bloqueado a
nivel de política de red del propio entorno). Todo lo que sé sobre
`autoCaptureSnapshots()` viene de **DOC-IDEM, Addendum 2 §1.2**, escrito por
una sesión que sí tenía acceso de solo lectura al filesystem del Hetzner. No
he leído yo mismo `/opt/axonik/scanner/index.html`. Lo marco explícitamente
en cada punto de la sección 1 para no presentar una inferencia como una
lectura directa del código — exactamente la disciplina que este proyecto ya
exige en los documentos anteriores.

---

## 1. Qué hace `autoCaptureSnapshots()`

### 1.1 Confirmado por DOC-IDEM (evidencia de primera mano, sesión con acceso al filesystem)

- Vive en `/opt/axonik/scanner/index.html` (~línea 2690), servido por el propio
  proxy en `:8002/scanner`.
- Se ejecuta en **cada** `runScan()`. `runScan()` se dispara a mano o por el
  auto-refresh opcional del cliente (`setAutoRefreshTimer`, cada 15 min
  mientras la pestaña está visible — es decir, **ya es un timer**, solo que
  vive en el navegador y depende de tener la pestaña abierta).
- Captura automáticamente (etiqueta `AUTO_HIGH`) los tickers que pasan
  `detectAutoTrigger`. Existe una ruta alternativa manual, el botón "Seguir"
  (`MANUAL`, ~línea 2046), que queda fuera de esta automatización — sigue
  siendo una acción humana deliberada y no se toca.
- El efecto de red confirmado es `POST /api/snapshots` contra el mismo proxy
  (`market_data_proxy.py::create_snapshot`): es el único endpoint de alta de
  snapshots que existe, y DOC-IDEM confirma explícitamente que
  `autoCaptureSnapshots` "solo cuenta las respuestas con `created:true`" —
  es decir, interpreta el JSON de respuesta de ese POST para su propia
  contabilidad en pantalla (el aviso de "N señales capturadas").
- Guard de cliente: `state.followedToday`, cargado por `loadFollowedToday()`
  con `GET /api/snapshots?status=OPEN&since=<00:00 UTC de hoy>`. Es una
  petición HTTP normal contra el mismo proxy, sin nada propio del navegador
  más allá de guardar el resultado en una variable JS.
- Universo de endpoints de escritura del proxy que ya existen y que una
  réplica headless usaría (DOC-IDEM, Hallazgo 4): `POST /api/snapshots`,
  `GET /api/snapshots`, y en algún punto previo del flujo `POST
  /api/scan-batch` (es el endpoint que trae los datos de mercado que
  `runScan()` evalúa; no está descrito con más detalle en DOC-IDEM, pero es
  el único candidato entre los endpoints inventariados que puede alimentar un
  escaneo de ese tamaño).

### 1.2 No confirmado — pendiente de leer el código real antes de implementar

Tres preguntas concretas que DOC-IDEM no responde porque no era su objetivo,
y que sí son el núcleo de tu pregunta 1:

1. **¿`detectAutoTrigger` es aritmética pura sobre datos que ya vienen del
   servidor, o usa algo calculado solo en el navegador** (un indicador de una
   librería de gráficos cargada en el cliente, un valor que depende del
   DOM/canvas, etc.)? Si `/api/scan-batch` ya devuelve los indicadores
   calculados (lo más probable, porque el proxy es el mismo proceso Python
   que corre `snapshot_evaluator.py` y ya maneja indicadores en el servidor),
   `detectAutoTrigger` es trasladable a Python sin más. Si depende de un
   cálculo que solo existe en JS/DOM, hace falta un navegador real
   (Playwright) o portar ese cálculo también.
2. **¿De dónde saca `runScan()` el universo de tickers/scanners a evaluar?**
   Si es una llamada a un endpoint del proxy (p.ej. una lista de scanners
   activos desde Postgres), es trivial de replicar. Si es estado solo de la
   UI (un `<select>` con checkboxes marcados a mano, guardado en
   `localStorage` del navegador de quien use el scanner), un proceso headless
   necesita su propia fuente de verdad para ese universo — probablemente
   "todos los scanners `EN_PRUEBAS`/`PRODUCCION` de `02_SCANNERS`", pero eso
   es una decisión de producto, no algo que se pueda inferir del código.
3. **¿Hay algo de sesión/autenticación de navegador en las llamadas actuales**
   (cookies, CSRF token) que un cliente headless tendría que replicar? DOC-IDEM
   no menciona ninguno, y el Hallazgo 4 confirma que hoy el proxy no exige
   autenticación en ningún endpoint — así que es improbable, pero no está
   verificado explícitamente porque no era la pregunta de esa investigación.

### 1.3 Conclusión de esta sección

Con la evidencia disponible, **todo apunta a que el mecanismo es réplicable
sin navegador** (llamadas HTTP + lógica determinista), no a que haga falta
Playwright. Pero esa conclusión depende de las tres preguntas de 1.2, que no
puedo cerrar desde aquí. **Antes de escribir una sola línea del script de la
sección 2, alguien con acceso al Hetzner tiene que extraer literalmente**
`autoCaptureSnapshots`, `detectAutoTrigger`, `runScan` y el bloque que
construye el payload de `/api/scan-batch` (o lo que sea que alimenta el
escaneo) **y pegarlos en un documento**, igual que se hizo con
`compute_signal_hash` en DOC-IDEM. Es una tarea de solo lectura, de minutos,
y es la que convierte este diseño de "probablemente viable sin navegador" a
"confirmado". Lo marco como bloqueante de la implementación, no de esta
revisión.

---

## 2. Diseño del timer systemd (condicionado a confirmar 1.2)

Mismo patrón que `axonik-snapshot-eval-daily`/`-intraday` (DOC-IDEM, Addendum 1,
tabla de "Planificación"): una unit `.service` tipo `oneshot` que ejecuta un
script Python, disparada por una unit `.timer`.

### 2.1 Ventana operativa — regla dura, no una sugerencia

Tu instrucción es explícita: nada fuera de 16:00–18:00 Madrid sin que lo
decidas tú. Lo implemento con **dos capas independientes**, no solo una,
porque un `OnCalendar` mal escrito o un `systemctl start` manual accidental
no deben poder saltársela:

1. **`OnCalendar` del timer**, acotado a la ventana (ver 2.3) — es la
   defensa principal.
2. **Guard dentro del propio script**: lo primero que hace, antes de tocar
   la red, es comprobar la hora actual en `Europe/Madrid` y abortar sin
   efecto (log + exit 0) si no está en `[16:00, 18:00)`. Así, si alguien
   ejecuta `systemctl start axonik-snapshot-autocapture.service` a mano
   fuera de la ventana (para probar, para depurar), no captura nada —
   tiene que forzar el guard explícitamente con una variable de entorno
   (p.ej. `AXONIK_FORCE_WINDOW=1`), lo cual es una decisión explícita y
   queda en el log de systemd (`journalctl` registra el `Environment=`
   efectivo de cada arranque manual).

**Días:** lunes a viernes, igual que `axonik-snapshot-eval-intraday` — la
ventana 16:00-18:00 Madrid está atada a la apertura de NYSE
(`AXONIK_Master_Context_v1.md` §8), no a cripto. Esto significa que **esta
automatización no captura señales de los scanners cripto** fuera de esa
franja, aunque cripto opera 24/7 — es una limitación deliberada, coherente
con "no captures fuera de esa ventana sin que yo lo decida explícitamente".
Si quieres una ventana distinta (o sin ventana) para los scanners `SC-01`/
`SC-02`, es una decisión tuya, aparte de este diseño — no la asumo.

### 2.2 Cadencia

El auto-refresh del navegador corre cada 15 min (`setAutoRefreshTimer`).
Propongo la misma cadencia para no cambiar el comportamiento observado hasta
ahora, ni inventar una frecuencia nueva sin motivo. Con el Hallazgo 1 de
DOC-IDEM ya desplegado y verificado (`signal_hash` v2 sobre `data_ts`),
repetir el escaneo varias veces sobre la misma vela ya no duplica nada en
`signal_snapshots` — el proxy responde `created:false` a los repetidos sin
escribir fila. La cadencia es ahora una cuestión de cuota de API
(yfinance/Binance) y carga, no de integridad. **Ajustable, es un parámetro,
no una restricción de diseño.**

### 2.3 Unit de timer

```ini
# /etc/systemd/system/axonik-snapshot-autocapture.timer
[Unit]
Description=AXONIK - captura automática de snapshots (16:00-18:00 Madrid, L-V)

[Timer]
OnCalendar=Mon..Fri *-*-* 16:00:00 Europe/Madrid
OnCalendar=Mon..Fri *-*-* 16:15:00 Europe/Madrid
OnCalendar=Mon..Fri *-*-* 16:30:00 Europe/Madrid
OnCalendar=Mon..Fri *-*-* 16:45:00 Europe/Madrid
OnCalendar=Mon..Fri *-*-* 17:00:00 Europe/Madrid
OnCalendar=Mon..Fri *-*-* 17:15:00 Europe/Madrid
OnCalendar=Mon..Fri *-*-* 17:30:00 Europe/Madrid
OnCalendar=Mon..Fri *-*-* 17:45:00 Europe/Madrid
AccuracySec=30s
Persistent=false
Unit=axonik-snapshot-autocapture.service

[Install]
WantedBy=timers.target
```

Última corrida a las 17:45 (no a las 18:00) a propósito, para que ninguna
ejecución pueda solaparse con el límite de la ventana. `Persistent=false`
deliberado: si el host estuvo caído durante parte de la ventana, no hay que
recuperar capturas retroactivas — el `runScan()` manual sigue existiendo
como red de seguridad humana.

### 2.4 Unit de servicio

```ini
# /etc/systemd/system/axonik-snapshot-autocapture.service
[Unit]
Description=AXONIK - captura automática de snapshots (reemplaza autoCaptureSnapshots del navegador)
After=network.target axonik-market-proxy.service
Requires=axonik-market-proxy.service

[Service]
Type=oneshot
WorkingDirectory=/opt/axonik/scripts
EnvironmentFile=/etc/axonik/proxy_token.env
ExecStart=/usr/bin/python3 /opt/axonik/scripts/snapshot_autocapture.py
TimeoutStartSec=120
```

(`EnvironmentFile` es el token de autenticación de la sección 3 — mismo
mecanismo de secretos que ya usáis para no meter credenciales en el propio
script, coherente con cómo está tratado `credentials.json` en BACKLOG entrada
3.)

### 2.5 Script `snapshot_autocapture.py` — esqueleto, no implementación

Pseudocódigo, para que la revisión se centre en el flujo y no en sintaxis
Python que de todas formas no se despliega hoy:

```python
#!/usr/bin/env python3
"""
Reemplaza autoCaptureSnapshots() del navegador. Ejecutado por
axonik-snapshot-autocapture.timer, SOLO dentro de 16:00-18:00 Europe/Madrid
(ver guard de ventana más abajo — no eliminar ni "simplificar" ese guard).
"""
PROXY_BASE = "http://127.0.0.1:8002"   # local al propio host, no via 0.0.0.0
TOKEN = os.environ["AXONIK_PROXY_TOKEN"]  # ver sección 3

def within_operating_window(now_madrid) -> bool:
    return now_madrid.hour >= 16 and now_madrid.hour < 18  # [16:00, 18:00)

def main():
    now = datetime.now(ZoneInfo("Europe/Madrid"))
    if not within_operating_window(now) and not os.environ.get("AXONIK_FORCE_WINDOW"):
        log.info("Fuera de la ventana operativa 16:00-18:00 Madrid, no se captura nada.")
        return

    # PENDIENTE DE CONFIRMAR (sección 1.2, pregunta 2): de dónde sale este universo.
    universo = cargar_universo_de_scanners()

    # PENDIENTE DE CONFIRMAR (sección 1.2, pregunta 1): payload real de scan-batch.
    datos_mercado = requests.post(f"{PROXY_BASE}/api/scan-batch",
                                   json={"tickers": universo}, headers=auth_headers(TOKEN))

    for ticker_data in datos_mercado.json()[...]:
        # PENDIENTE DE CONFIRMAR: puerto exacto de detect_auto_trigger() desde JS.
        if detect_auto_trigger(ticker_data):
            resp = requests.post(f"{PROXY_BASE}/api/snapshots",
                                  json=construir_payload(ticker_data),
                                  headers=auth_headers(TOKEN))
            if resp.json().get("created"):
                log.info(f"capturado {ticker_data['ticker']}")
            # created:false ya queda registrado por el propio proxy
            # ("snapshot duplicado suprimido", Hallazgo 1) — no duplicar ese log aquí.
```

No incluyo la lógica real de `detect_auto_trigger` ni de `construir_payload`
porque son exactamente los puntos de 1.2 sin confirmar — escribirlos ahora
sería inventar comportamiento, no portarlo.

---

## 3. Hallazgo 2 del backlog: prioridad subida a ALTA + diseño de autenticación

### 3.1 Prioridad

`BACKLOG.md`, entrada 2 ("Puerto 8002 sin autenticación y con CORS abierto"):
**[BAJA] → [ALTA]**, aplicado en este mismo commit. Motivo explícito, tal
como pediste: este diseño añade un proceso automático nuevo que habla con ese
endpoint sin supervisión humana en cada llamada — no tiene sentido construir
más automatización sobre un endpoint que hoy solo está protegido por el
firewall.

### 3.2 Por qué un token resuelve la mitad del problema, no todo

El endpoint lo usan dos clientes con amenazas distintas:

| Cliente | Amenaza real hoy | ¿Un token estático la resuelve? |
|---|---|---|
| El nuevo proceso de captura (máquina a máquina, mismo host) | Ninguna especial — ya corre en `127.0.0.1`, no necesita exponerse a la red en absoluto | Sí, trivialmente, y además puede no exponerse: ver 3.4 |
| El navegador en `/scanner` (humano, posiblemente remoto) | Bots automatizados de internet (lo observado: 53 peticiones, 100% sondeos, 0 intentos de escritura) | **Parcialmente.** Un token embebido en HTML/JS servido al navegador es visible para cualquiera que mire el código fuente de la página — no es secreto frente a un atacante que mire, solo frente a un escáner automatizado ciego que no inspecciona el cuerpo de la respuesta. Es exactamente la amenaza observada hasta ahora, así que **vale la pena igualmente**, pero no hay que presentarlo como autenticación real frente a alguien dirigido. |

### 3.3 Diseño mínimo: bearer token en los endpoints de escritura

```python
# market_data_proxy.py
API_TOKEN = Path("/etc/axonik/proxy_token.env").read_text().strip()  # o os.environ, 600, solo root

async def require_token(authorization: str = Header(None)):
    if authorization != f"Bearer {API_TOKEN}":
        raise HTTPException(status_code=401, detail="token inválido o ausente")

@app.post("/api/snapshots", dependencies=[Depends(require_token)])
...
# Igual en PUT .../close, DELETE .../{id}, POST /api/circuit-breaker/breach,
# POST /api/scan-batch, POST /api/fundamentals-batch.
# GET /api/snapshots (lectura) y GET /api/health quedan sin token —
# no hay nada que proteger en una lectura pública de estado agregado,
# y el health check lo necesitan los propios timers systemd sin credenciales.
```

CORS: cambiar `allow_origins=["*"]` al origen real desde el que se sirve
`/scanner` (o eliminarlo si nadie llama al proxy desde un origen distinto al
propio host — a confirmar contigo, no lo puedo saber sin ver cómo accedes al
scanner hoy).

### 3.4 Diseño preferido: que el proxy deje de necesitar exponerse en absoluto

Esta automatización cambia el panorama: si el nuevo proceso headless cubre la
captura automática, la única razón que queda para que alguien llegue a
`/scanner` desde fuera del propio host es el uso manual ocasional (botón
"Seguir", supervisión visual). Dos piezas, independientes entre sí:

1. **Bind a `127.0.0.1:8002`** en vez de `0.0.0.0:8002` — el proceso de
   captura headless corre en el mismo host, no necesita red. Esto es lo que
   BACKLOG entrada 2 ya sugiere como opción ("valorar el bind a 127.0.0.1 si
   nada externo lo necesita").
2. **Si todavía necesitas `/scanner` desde fuera** para uso manual: un túnel
   SSH (`ssh -L 8002:localhost:8002 ...`) o un reverse proxy con su propia
   autenticación (nginx + basic auth, o detrás del mismo Cloudflare tunnel
   que ya usáis para n8n) — nunca el puerto crudo en `0.0.0.0` otra vez.

Con (1), el token de 3.3 deja de ser necesario para el tráfico
máquina-a-máquina (ya no atraviesa red pública) y solo protege el acceso
manual vía túnel/reverse-proxy, donde además es mucho más difícil de
inspeccionar que en HTML servido a cualquiera. **Es la opción que recomiendo**,
pero cambia cómo accedes tú al scanner día a día, así que la dejo como
decisión tuya, no como parte automática de este diseño.

### 3.5 Verificación (antes de dar esto por cerrado, mismo estándar que DOC-IDEM)

- Petición sin `Authorization` a cada endpoint de escritura → `401`.
- Petición con token correcto → comportamiento normal, sin cambios de
  respuesta más allá del código 200/201 esperado.
- El script de captura (sección 2) funciona con el token puesto en su
  `EnvironmentFile`.
- Si se aplica 3.4: `curl` desde fuera del host a `:8002` → connection
  refused (no hay bind en esa interfaz, no hace falta ni firewall).
- Si se mantiene `/scanner` accesible por túnel/reverse-proxy: confirmar que
  el flujo manual ("Seguir") sigue funcionando end-to-end.

---

## 4. Dependencias y orden recomendado

No construir el timer de la sección 2 antes de:

1. **Confirmar 1.2** (extraer el código real de `autoCaptureSnapshots`,
   `detectAutoTrigger`, `runScan`) — define si el script Python es viable
   tal cual o si hace falta Playwright.
2. **Al menos el bind a 127.0.0.1 o el token de la sección 3** desplegado —
   tu propia instrucción: no más automatización sobre un endpoint abierto.

Ambos son pasos de otra sesión con acceso al Hetzner (no de implementación
aquí) — este documento es la especificación que esa sesión debe seguir,
igual que DOC-IDEM lo fue para el hallazgo 1.

## 5. Qué NO toca este diseño

- `scripts/validation_engine/` y los Gates (Fase 0B) — sin relación.
- Los hallazgos 1, 3 y 4 de BACKLOG (timers simultáneos, control de
  versiones de `/opt/axonik/scripts/`, `sync_to_sheet()` no idempotente) —
  siguen abiertos, sin cambios aquí.
- El botón manual "Seguir" — sigue siendo una acción humana deliberada, no
  se automatiza.
- Nada en producción: este commit solo toca documentos de este repositorio.
