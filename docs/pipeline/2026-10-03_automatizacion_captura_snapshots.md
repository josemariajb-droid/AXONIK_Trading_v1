# Automatización de la captura de snapshots (reemplazo de `autoCaptureSnapshots()`)

**Fecha:** 03/10/2026
**Estado: IMPLEMENTADO (código real) — NO DESPLEGADO.** Bloqueante de
"¿hace falta Playwright?" cerrado del todo (§1.4). Implementación en
`services/snapshot-autocapture/` — pendiente de tu revisión antes de tocar
el servidor, igual que con el fix de idempotencia.
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

### 1.2 Estado tras la 1ª pasada (`docs/pipeline/check_autocapture_triggers.sh`)

Tres preguntas originales, resueltas con el script de solo lectura contra el
código real del Hetzner (ejecutado por el usuario, no por esta sesión — sigo
sin acceso directo):

1. **`detectAutoTrigger` — CONFIRMADO: comparación pura.** Solo compara
   scores ya calculados, no calcula nada por su cuenta. Esto desplazó la
   pregunta a `evaluateTicker()` (quien produce esos scores), que en la 2ª
   pasada **también se confirmó como orquestación pura sobre datos**. El
   bloqueante real que queda son las cuatro piezas que `evaluateTicker()`
   llama (`NYSE_STRATEGIES`, `CRYPTO_STRATEGIES`, `applyEventAdjustments`,
   `tickerHardNo`) — ver §1.4, verificación en curso.
2. **Universo de tickers de `runScan()` — CONFIRMADO: `localStorage`, no un
   endpoint.** Cerrado como decisión de producto, no como hallazgo técnico —
   ver §1.4.
3. **Sesión/autenticación de navegador** — sin revisar explícitamente en esta
   pasada (el script la cubre, pero el resultado no se ha reportado todavía).
   Sigue siendo improbable, coherente con que el proxy no exige autenticación
   en ningún endpoint (BACKLOG entrada 2), pero no lo marco como cerrado
   hasta tener ese resultado también.

### 1.3 Conclusión de esta sección (actualizada)

Dos de las tres preguntas originales ya no son especulación, y
`evaluateTicker()` tampoco. Lo que decide "Python simple" vs. "Playwright"
ahora es un grep acotado a cuatro piezas concretas, no una función más por
confirmar — ver §1.4 para el detalle y qué falta.

---

## 1.4 Addendum — 1ª y 2ª pasada de verificación

**Universo de tickers — CERRADO.** Confirmado que `runScan()` toma el
universo de `localStorage` del navegador, no de un endpoint. **Decisión de
producto (tuya, cerrada):** el proceso automático no depende de
`localStorage` de ningún navegador concreto — usa como universo **los
scanners en estado `EN_PRUEBAS` o `PRODUCCION` de `02_SCANNERS`**, leídos
directamente de esa hoja/tabla en cada ejecución. Esto no es una inferencia
ni una alternativa "probablemente correcta": es la decisión que cierra la
pregunta 2 de §1.2, documentada aquí para que el esqueleto de §2.5
(`cargar_universo_de_scanners()`) tenga una especificación concreta en vez de
un comentario de "pendiente de confirmar". Implicación directa para la
implementación: `cargar_universo_de_scanners()` debe leer `02_SCANNERS`
filtrando por `ESTADO IN ('EN_PRUEBAS', 'PRODUCCION')` — no replicar ni leer
`localStorage` de ninguna sesión de navegador.

**`detectAutoTrigger` — sin cambios respecto a lo ya confirmado:**
comparación pura sobre scores recibidos.

**`evaluateTicker()` — 2ª pasada, CONFIRMADO: orquestación pura sobre `ctx`
(datos), sin DOM.** Recibido y revisado: no toca nada propio del navegador,
solo organiza el cálculo del score a partir del contexto de datos que
recibe. Pero `evaluateTicker()` llama a otras piezas
(`NYSE_STRATEGIES`, `CRYPTO_STRATEGIES`, `applyEventAdjustments`,
`tickerHardNo`) que no se habían revisado todavía — confirmar que
`evaluateTicker()` en sí es limpia no basta si delega en algo que no lo es.

**Verificación dirigida (Pregunta 1c) — CERRADA: las cuatro piezas salen
limpias.** `NYSE_STRATEGIES`, `CRYPTO_STRATEGIES`, `applyEventAdjustments`
y `tickerHardNo` no contienen `document.`, `window.`, `canvas`, `chart.`,
`getContext` ni un `fetch(` interno. **Bloqueante de "¿hace falta
Playwright?" cerrado del todo:** `evaluateTicker()` y todo lo que llama es
aritmética/orquestación pura sobre datos — un script Python sin navegador
es viable.

### 1.5 Implementación real entregada — Pregunta 4 ejecutada, 3 puntos corregidos, 1 gap real descubierto

`services/snapshot-autocapture/`: `snapshot_autocapture.py`,
`axonik-snapshot-autocapture.service`/`.timer`, `README.md`.
**No desplegado** — pendiente de tu revisión.

**Los tres puntos de la Pregunta 4, confirmados contra el código real (no
prosa) y corregidos:**

1. **Shape de `POST /api/scan-batch` — corregido.** Real:
   `{"results": [{"ticker", "timestamp", "data", "error"?}]}`. `fetch_scan_batch()`
   ya no asume esta forma, y el bucle principal maneja `"error"` por-ticker
   como una omisión de ese ticker, no como un fallo del batch completo.
2. **`risk_pct` — MAL, corregido a `risk_per_share`.** `entry_price`/
   `stop_price` sí coincidían con la estimación original.
3. **Umbral de `detectAutoTrigger()` — corregido de un único valor a dos
   ramas reales**, implementadas en `evaluate_auto_trigger()`:
   `AUTO_HIGH` (una estrategia, score≥90) y `AUTO_MULTI` (≥2 estrategias
   del mismo grupo, score≥80 cada una). "Mismo grupo" se interpreta aquí
   como mismo `temporal_group` — es una lectura de la descripción, no una
   cita literal de `detectAutoTrigger()`; dado que la paráfrasis de
   `risk_pct` ya introdujo un error real una vez, esta agrupación debería
   confirmarse contra el código antes de fiarse de ella en producción.

**Gap real descubierto al corregir el punto 1, no uno de los tres pedidos:**
el shape real de `scan-batch` confirma que `"data"` son indicadores EN
BRUTO, no un score precalculado. Este script dependía de
`ticker_data.get("score")`, que nunca existió en la respuesta real — era
una asunción incorrecta, no una aproximación válida. El cálculo del score
(`evaluateTicker()` + `NYSE_STRATEGIES`/`CRYPTO_STRATEGIES` +
`applyEventAdjustments` + `tickerHardNo`) nunca se portó: solo se había
confirmado que esas cinco piezas son "limpias" (sin `document.`/`window.`/
`canvas`/`fetch` interno — Pregunta 1c), nunca se transcribió su
**contenido**. `evaluate_ticker()` es ahora un `NotImplementedError`
explícito, verificado que falla ruidoso en el primer ticker (no silencia
el fallo ni finge un resultado — probado con mocks, incluido un ticker con
`"error"` que sí se omite correctamente antes de llegar ahí).

**Por esto no se escribe todavía el protocolo de verificación completo**
que cerraría esta tarea: ejecutarlo contra el proxy real fallaría de
inmediato en `evaluate_ticker()`, y documentar un protocolo de prueba
sobre una pieza que admite no estar implementada sería exactamente el
tipo de falsa certeza que este diseño ha evitado en todo lo anterior.
Para cerrar esto de verdad hacen falta los **cuerpos literales** de las
cinco piezas — no otro resumen en prosa, por la misma razón que
`risk_per_share` ya se perdió en una paráfrasis.

### 1.6 Bind a 127.0.0.1 (hallazgo 2 del backlog) — patch listo, no aplicado

Decisión tomada: bind en vez de token (BACKLOG entrada 2, diseño §3.4 de
este documento). Línea actual confirmada en `market_data_proxy.py`
(DOC-IDEM, Hallazgo 4): `uvicorn.run(app, host="0.0.0.0", port=8002)` →
`host="127.0.0.1"`. Patch de una línea, pasos de despliegue y verificación
completos en `services/snapshot-autocapture/README.md` (incluye el efecto
colateral sobre el acceso manual a `/scanner` desde fuera del host, que
queda como decisión aparte).

### 1.7 Cadena de dependencias cerrada: 22 piezas, texto literal, fondo confirmado

Tras 4 rondas de extracción dirigida (Preguntas 5, 5b, 5c, 5d — cada una
disparada porque la anterior reveló una capa más), la cadena de
dependencias de `evaluateTicker()` está cerrada con **22 piezas**, todas
con texto literal (no resumen en prosa) en
`docs/pipeline/pregunta5_5b_salida.txt`, `pregunta5c_salida.txt` y
`pregunta5d_salida.txt`:

| Capa | Piezas |
|---|---|
| Orquestación | `evaluateTicker`, `detectAutoTrigger` |
| Selección por modo | `NYSE_STRATEGIES`, `CRYPTO_STRATEGIES` (arrays fijos de 7+3 funciones) |
| Ajustes/veto | `applyEventAdjustments`, `tickerHardNo` |
| Cálculo por estrategia | `evalST01`, `evalST05`, `evalST06`, `evalST09`, `evalST11`, `evalST15`, `evalST16`, `evalSC01`, `evalSC02`, `evalSCPB` |
| Normalización/construcción | `mkResult`, `mkNA`, `finalizeVerdict`, `f` |
| Configuración (fondo) | `STRATEGY_META`, `MAX_RAW_SCORE` |

`MAX_RAW_SCORE` (Pregunta 5d) es un objeto literal de 11 pares
`id: número` — sin llamadas, sin referencias a nada más. Es el fondo
real: no hay quinta capa.

**Puerto a Python entregado:** `services/snapshot-autocapture/evaluate_ticker_logic.py`,
1:1 contra el texto literal de las 22 piezas. 10 pruebas en
`test_evaluate_ticker_logic.py` (todas pasan), incluida una diseñada
para fallar si alguien reintrodujera la unión de ramas en vez de la
prioridad estricta `AUTO_MULTI`→`AUTO_HIGH` que `detectAutoTrigger`
tiene en realidad (corregido respecto al diseño original de
`evaluate_auto_trigger()` en `snapshot_autocapture.py`, que hacía unión).

### 1.8 Hallazgo estructural al portar — decisión pendiente antes de cablear el endpoint

Leyendo el texto literal de `evaluateTicker()` (no inferido):

```js
const fns = mode==='NYSE' ? NYSE_STRATEGIES : CRYPTO_STRATEGIES;
let strategies = fns.map(fn=>{ ... });
```

**`evaluateTicker()` evalúa TODAS las estrategias fijas de un modo (7 NYSE
o 3 crypto) en una sola llamada por *ticker* — no una llamada por
(ticker, scanner).** `NYSE_STRATEGIES`/`CRYPTO_STRATEGIES` son arrays
fijos en el código; no se filtran por `02_SCANNERS.ESTADO` en tiempo de
ejecución. Esto no coincide con el diseño de §2.5/BACKLOG entrada 5 tal
como estaba: `cargar_universo_de_scanners()` (EN_PRUEBAS/PRODUCCION de
`02_SCANNERS`) decidía *qué estrategias* evaluar — pero en el código real,
qué estrategias se evalúan no es una decisión de datos en tiempo de
ejecución, es fijo en `NYSE_STRATEGIES`/`CRYPTO_STRATEGIES`.

Dato adicional: `ST-04` tiene entrada en `STRATEGY_META` y `MAX_RAW_SCORE`,
pero **no está en el array `NYSE_STRATEGIES`** — hoy no se evalúa en
ningún `autoCaptureSnapshots()`, aunque existe en la configuración y
tiene una operación real en `05_OPERACIONES` (Fase 0A, GOOGL/ST-04, el
único WIN plausible de toda la auditoría). No lo interpreto más allá de
señalarlo — es un dato para ti, no una decisión que tome yo.

**Lo que esto cambia:** "universo" para esta automatización probablemente
tiene que ser *qué TICKERS evaluar* (una lista de acciones/criptos), no
*qué estrategias* — las estrategias ya vienen fijas por `mode`. La
decisión de `02_SCANNERS.ESTADO` (EN_PRUEBAS/PRODUCCION) no tiene un
lugar obvio en este mecanismo tal como está escrito hoy en el navegador.

**No he tocado `snapshot_autocapture.py` para resolver esto por mi
cuenta.** Antes de cablear `POST /api/evaluate-ticker`, necesito que
decidas: (a) de dónde sale la lista de tickers a evaluar (¿un universo
fijo tipo S&P 500 + las criptos ya seguidas? ¿algo que ya exista en
Postgres/Sheets?), y (b) qué hacemos con la lectura de `02_SCANNERS` que
ya estaba diseñada — ¿se descarta, o sigue teniendo un papel distinto
(p.ej. qué *tickers* trackea cada scanner, no qué función ejecutar)?

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

### 2.5 Script `snapshot_autocapture.py` — esqueleto original (superado)

**Superado por la implementación real en
`services/snapshot-autocapture/snapshot_autocapture.py` (§1.5).** Se deja
este pseudocódigo original por trazabilidad de cómo evolucionó el diseño,
no como referencia activa:

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

    # CERRADO (§1.4): 02_SCANNERS, ESTADO IN ('EN_PRUEBAS', 'PRODUCCION').
    # No localStorage, no estado de ningún navegador concreto.
    universo = cargar_universo_de_scanners()

    # PENDIENTE DE CONFIRMAR (§1.4): payload real de scan-batch.
    datos_mercado = requests.post(f"{PROXY_BASE}/api/scan-batch",
                                   json={"tickers": universo}, headers=auth_headers(TOKEN))

    for ticker_data in datos_mercado.json()[...]:
        # BLOQUEANTE REAL (§1.4): evaluate_ticker() calcula el score que
        # detect_auto_trigger() compara — no inventar esa lógica aquí hasta
        # confirmarla contra el código real.
        score = evaluate_ticker(ticker_data)
        if detect_auto_trigger(score):
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

## 4. Dependencias y orden recomendado (actualizado tras §1.5-1.6)

El bloqueante de Playwright (antes punto 1 de esta lista) **está cerrado**.
No instalar el timer (`services/snapshot-autocapture/axonik-snapshot-autocapture.timer`)
antes de:

1. **Cerrar los 3 puntos de §1.5** (shape de `scan-batch`, nombres de
   campo de `/api/snapshots`, umbral de `detectAutoTrigger`) con la
   Pregunta 4 de `check_autocapture_triggers.sh`.
2. **Aplicar el bind a 127.0.0.1 (§1.6)** — tu propia instrucción: no más
   automatización sobre un endpoint abierto. Patch y verificación en
   `services/snapshot-autocapture/README.md`.
3. **El protocolo de verificación del README** (`--dry-run`, luego una
   corrida real con `--force-window` fuera de la franja de los timers del
   evaluador) — mismo estándar que el hallazgo 1 de DOC-IDEM.

Los tres son pasos de otra sesión con acceso al Hetzner (no de esta) — el
código y el README son la especificación que esa sesión debe seguir, igual
que DOC-IDEM lo fue para el hallazgo 1.

## 5. Qué NO toca este diseño ni la implementación

- `scripts/validation_engine/` y los Gates (Fase 0B) — sin relación.
- Los hallazgos 1, 3 y 4 de BACKLOG (timers simultáneos, control de
  versiones de `/opt/axonik/scripts/`, `sync_to_sheet()` no idempotente) —
  siguen abiertos, sin cambios aquí.
- El botón manual "Seguir" — sigue siendo una acción humana deliberada, no
  se automatiza.
- Nada en producción: este repositorio solo contiene el código listo para
  desplegar y el README con los pasos — nadie lo ha aplicado todavía en el
  Hetzner.
