# Tarea 0 / Fase 0A — Auditoría de 02_SCANNERS / 05_OPERACIONES

**Fecha:** 22/09/2026
**Fuente:** `AXONIK Decision Engine v2.xlsx` (snapshot del 21/09/2026, Google Drive)
**Script:** `scripts/audit/audit_tarea0.py` (reproducible sobre cualquier export futuro)
**Filtro canónico:** `scripts/audit/validation.py::is_valid_operation` — única función
que decide qué operaciones cuentan para métricas agregadas. Ver §3.
**Datos crudos:** `docs/auditoria/data/02_SCANNERS_20260921.csv`,
`docs/auditoria/data/05_OPERACIONES_20260921.csv`
**Dataset certificado (salida de `is_valid_operation`):**
`docs/auditoria/data/05_OPERACIONES_certified_20260921.csv`

Pregunta que responde esta auditoría (spec QFEL-Cripto §0): los KPIs del dashboard
(WR 14.3%, PF 0.00, P&L €0.00, RR 0.98) — ¿son (a) ruido de muestra insuficiente
o (b) un problema estructural de las estrategias base?

---

## Contexto

- 20 scanners registrados, 14 `EN_PRUEBAS`, 0 `PRODUCCION` (confirma dashboard).
- 05_OPERACIONES contiene 14 filas, pero **no son 14 operaciones independientes**.
  De esas 14, solo **7 son válidas** para métricas agregadas una vez aplicado
  `is_valid_operation` (§3): 4 son reenvíos duplicados de un mismo lote (bug de
  infraestructura reproducible, §2), 2 referencian un scanner que no existe en
  el catálogo, y 1 tiene un precio de entrada incompatible con datos de mercado
  contemporáneos del mismo ticker (§1).
- 03_ESTRATEGIAS, 04_BACKTESTING, 06_HIPOTESIS y 07_VERSIONES están **vacías**
  (0 filas de datos, solo cabecera). La capa formal de "estrategia congelada"
  (`RULESET_vX`) que exige Camino C no existe todavía en ningún sitio.

## Análisis

### 1. AAPL/ST-05 (+41%, RR 17.91): clasificación confirmada — `ENTRY_PRICE_INCONSISTENT`

**Clasificación:** error de datos confirmado por causa raíz, no outlier estadístico
ni operación real. Código: `InvalidReason.ENTRY_PRICE_INCONSISTENT`
(`validation.py`, operación `62f5e3386d05`).

**Justificación causal completa.** La operación registra `PRECIO_ENTRADA=220.00`
(2026-08-06) y `PRECIO_SALIDA=310.10` dos horas después, resultado +40.96% /
RR 17.91. Ese movimiento no es plausible para AAPL (large cap, volatilidad
diaria típica 1-2%) sin evento extraordinario — y `NOTAS` no registra ninguno.
Pero el dataset contiene la prueba directa, no solo la sospecha: **el mismo
ticker, en la misma semana**, aparece en dos operaciones de `ST-16`
(`a1d3348a8630`, `2e2285b99181`, 2026-08-07/08) con `PRECIO_ENTRADA=313.33`.

| Operación | Fecha | Ticker | Precio entrada | Precio salida |
|---|---|---|---|---|
| `62f5e3386d05` (ST-05) | 2026-08-06 | AAPL | **220.00** | 310.10 |
| `a1d3348a8630` (ST-16) | 2026-08-07 | AAPL | **313.33** | 305.55 |
| `2e2285b99181` (ST-16) | 2026-08-08 | AAPL | **313.33** | 305.55 |

El `PRECIO_SALIDA` de ST-05 (310.10) **sí es consistente** con el precio real
de AAPL esa semana (~313, confirmado por las dos operaciones de ST-16 uno y
dos días después). El `PRECIO_ENTRADA` (220.00) **no lo es** — una desviación
del ~30% sin contrapartida en ningún otro registro del sistema. El error está
localizado específicamente en la captura del precio de entrada: lectura de un
precio obsoleto/cacheado, o un mapeo de símbolo incorrecto en el motor de
ejecución PAPER en el momento de abrir la operación. `RESULTADO_PCT` (+40.96%)
y `RR_REAL` (17.91) no son un movimiento de mercado real — son la diferencia
aritmética entre un precio de entrada corrupto y un precio de salida correcto.

**Consecuencia:** esta operación queda excluida de toda métrica agregada
(§3). No se "ajusta" ni se recalcula con un precio de entrada supuesto —
se excluye, porque no hay forma de saber qué habría hecho el sistema con el
precio de entrada real.

### 2. Hallazgo independiente: bug de reenvío por lotes en la ingesta de ST-16

Este hallazgo es distinto de "¿tiene ST-16 ventaja?" (eso se trata en §4) —
es un defecto de infraestructura, confirmado y reproducible, en la ruta de
escritura a `05_OPERACIONES`.

**Reconstrucción forense** (`audit_tarea0.py::reconstruct_batch_replay_bug`,
reproducible sobre el xlsx original):

| Lote | Fecha | Hora entrada | Tickers | Nota |
|---|---|---|---|---|
| 1 (original) | 2026-08-07 | 21:22:00 | AAPL, AVGO, MSFT, NVDA | sin nota |
| 2 (reenvío) | 2026-08-08 | 08:52:00 | AAPL, AVGO, MSFT, NVDA | `data_lag_hours=28.88h — excluido (R4)` |

Verificación campo a campo entre lote 1 y lote 2 para cada ticker
(`PRECIO_ENTRADA`, `PRECIO_SALIDA`, `RESULTADO`, `RESULTADO_PCT`, `RR_REAL`):
**idénticos byte a byte en los 4 tickers.** Solo cambian `OP_ID` y
`HORA_ENTRADA`. Esto descarta que sean 4 duplicados independientes o ruido
disperso: **es un único evento** — el mismo lote de 4 señales detectadas por
ST-16 en la corrida del 07/08 a las 21:22 se reescribió íntegro 11h30min
después, en la corrida del 08/08 a las 08:52, con los mismos precios y
resultados ya cerrados.

**Causa más probable:** fallo de idempotencia en la ruta de escritura —
un reintento o reentrega de la ejecución de n8n, o un reprocesamiento manual
del mismo lote, sin comprobar contra `05_OPERACIONES` si esas 4 señales ya
estaban escritas. La etiqueta `data_lag_hours=28.88h` no mide la distancia
entre los dos lotes (11.5h) sino la antigüedad de los datos de precio
reutilizados en el segundo lote frente al momento de reprocesado — consistente
con que el segundo lote reusó una instantánea de precios ya cerrada del primer
lote en vez de volver a consultar el mercado.

**Por qué importa como hallazgo separado:** la nota `NOTAS` (R4) trata esto
como ruido a filtrar caso por caso. No lo es — es un defecto reproducible de
la capa de ingesta que puede volver a duplicar cualquier lote futuro de
cualquier scanner, no solo ST-16. Corregirlo requiere una clave de
idempotencia en la escritura (hash de `ticker+scn_id+fecha+precio_entrada`,
comprobado contra `05_OPERACIONES` antes de insertar) en el workflow de
n8n — fuera del alcance de este repo, pero debe priorizarse antes de confiar
en el volumen de operaciones que se acumule en PAPER.

### 3. `is_valid_operation()` — única fuente de verdad, sin cálculos paralelos

Para evitar que la limpieza de datos vuelva a ser ad-hoc (como el R4 que
existía solo como nota sin aplicarse), `scripts/audit/validation.py` define
una única función, `is_valid_operation(op, known_scanners)`, con tres motivos
de exclusión — todos con causa raíz documentada, ninguno es un umbral
estadístico genérico:

| Motivo | Operaciones | Base |
|---|---|---|
| `entry_price_inconsistent` | 1 (`62f5e3386d05`, AAPL/ST-05) | §1 |
| `duplicate_batch_replay` | 4 (AAPL/AVGO/MSFT/NVDA, ST-16) | §2 — cualquier fila con nota "excluido" |
| `orphan_scanner_ref` | 2 (SUI/ATOM, `SC-PB`) | `SCN_ID_REF` no existe en `02_SCANNERS` |
| **Total excluidas** | **7 / 14** | |
| **Válidas (certificadas)** | **7 / 14** | |

`audit_tarea0.py` importa esta función y la usa **una sola vez**, en
`certify_operations()`, para partir el dataset en válidas/excluidas. No existe
una segunda ruta de filtrado en el script: la tabla "TODAS" que se muestra a
continuación no es un cálculo alternativo, es deliberadamente **sin filtrar**
— reproduce lo que el dashboard hace hoy, para que la comparación sea
explícita. Todo lo demás (resumen por scanner, exportación a CSV certificado
para Fase 0B) consume la misma lista `validas` que devuelve
`certify_operations()`.

**Alcance de esta garantía:** dentro de este repositorio, cualquier script
Python que necesite "operaciones válidas" debe importar `is_valid_operation`
de `validation.py` — no reimplementar el filtro. El dashboard real
(`01_DASHBOARD` en Google Sheets) vive fuera de este repo y sus fórmulas
todavía no aplican esta lógica (siguen siendo `COUNTIF`/`SUMIF` sin filtrar,
ver §4 del informe original de KPIs rotos); portarla a Apps Script o a una
tabla intermedia en PostgreSQL es trabajo pendiente de pipeline, no de este
repo.

### 4. Métricas: "como hoy" vs. certificadas

Las fórmulas del dashboard (`01_DASHBOARD`) son:

```
PROFIT FACTOR = SUMIF(RESULTADO_EUR>0) / ABS(SUMIF(RESULTADO_EUR<0))   → IFERROR → 0
P&L TOTAL     = SUM(RESULTADO_EUR)                                     → IFERROR → 0
WIN RATE      = COUNTIF(RESULTADO,"WIN") / COUNTA(RESULTADO)           (14 filas, sin filtrar)
RR MEDIO      = AVERAGE(RR_REAL)                                       (14 filas, sin filtrar)
```

`RESULTADO_EUR` está vacía en el 100% de las 14 filas — el 0.00/€0.00 del
dashboard es un artefacto de esa columna sin rellenar, no una medición real.
Calculado sobre `RESULTADO_PCT` en su lugar:

| Cálculo | N | WIN | LOSS | BE | TIMEOUT | WR (wins/N) | WR (wins/(wins+loss)) | RR medio | PF (%pct) |
|---|---|---|---|---|---|---|---|---|---|
| Como hoy (dashboard, sin filtrar) | 14 | 2 | 8 | 2 | 2 | 14.3% | 20.0% | 0.98 | 1.81 |
| **Certificadas (`is_valid_operation`)** | **7** | **1** | **5** | **0** | **1** | **14.3%** | **16.7%** | **−0.27** | **0.86** |

Una vez certificados los datos, el sistema no muestra un rendimiento "bajo
pero positivo" — muestra **RR medio negativo y Profit Factor por debajo de
1** sobre una muestra de 7. Ninguna de las dos lecturas ("dashboard roto
optimista" ni "certificado pesimista") es suficiente para juzgar la
estrategia base: N=7 sigue muy por debajo del gate operativo (≥20).

### 5. Rendimiento por scanner (datos certificados)

| Scanner | N | WIN | Score medio entrada | Resultados |
|---|---|---|---|---|
| ST-16 (Compresión en Tendencia) | 4 | 0 | 99 | LOSS, LOSS, TIMEOUT, LOSS |
| SC-02 (Altcoin Season Rotation) | 2 | 0 | 72 | LOSS, LOSS |
| ST-04 (MACD Triple Confluencia) | 1 | 1 | 82 | WIN |

(ST-05 y las referencias `SC-PB` no aparecen: quedaron excluidas en §1-§3.)

`ST-16` concentra más de la mitad de la muestra certificada (4/7) y exige el
`SCORE_ENTRADA` más alto del sistema (95-100, el filtro de máxima convicción)
— y aun así **0 aciertos**. A diferencia de los duplicados de §2, estas 4
operaciones **no** están marcadas como inválidas: son 4 señales distintas,
reales, del lote original (21:22 del 07/08), con score alto y resultado
negativo consistente. Es la única señal de este dataset compatible con
**(b) problema estructural** — coherente con la inversión de signo ya
cerrada en VALIDACIÓN ALPHA — pero N=4 no es prueba estadística por sí sola.

### 6. Fallos de integridad adicionales (menores)

- **`DURACION` negativa** en 2 filas (LINK, BNB: entrada 08:56 → salida
  01:00, `DURACION=-0.3d`). El cálculo no ajusta el cambio de día al cruzar
  medianoche.
- **`EST_ID_REF` vacío en el 100% de las operaciones** — ninguna está
  vinculada a una estrategia formal porque `03_ESTRATEGIAS` no tiene
  ninguna fila. Las operaciones saltan de scanner a ejecución sin pasar
  por la capa de "estrategia congelada" que `00_README` da por existente.
- **`04_BACKTESTING` vacía**: la VALIDACIÓN ALPHA (97 combinaciones,
  Monte Carlo/walk-forward) que el spec da por cerrada no dejó registro
  estructurado en el sistema — solo existe en prosa.

### 7. Base cripto: aún más pequeña que la de acciones

Solo 2 de los 20 scanners son `CRYPTO` (`SC-01` `EN_PRUEBAS`, `SC-02`
`PENDIENTE`), y entre ambos solo hay 2 operaciones certificadas (`SC-02`,
ambas `LOSS`). El plan QFEL-Cripto asume implícitamente que hay algo de base
cripto sobre la que capear una capa cualitativa — no la hay: es la parte con
menos datos de todo el sistema.

---

## Decisión

**(a) y (b) simultáneamente, con (a) dominante y (b) como señal a vigilar,
no a actuar todavía:**

- **(a) Ruido de muestra insuficiente: confirmado y dominante.** 7
  operaciones certificadas repartidas en 3 scanners no permiten ninguna
  conclusión estadística sobre ninguna estrategia individual. El gate
  operativo del sistema exige ≥20 operaciones por estrategia — la que más
  tiene (ST-16) llega a 4.
- **Los KPIs que se mostraban antes de esta auditoría (WR 14.3%, PF 0.00,
  P&L €0.00) no eran ni siquiera una medición fiable de esas 7 operaciones.**
  Con causa raíz identificada para cada exclusión (§1-§3): una columna nunca
  rellenada, un bug de reenvío por lotes reproducible, un error de precio de
  entrada confirmado por cruce con datos contemporáneos del mismo ticker.
- **(b) Señal de problema estructural: parcial, en ST-16 únicamente.** 0/4
  con el score de entrada más alto del sistema es la única evidencia de este
  dataset compatible con un problema de diseño (el score no discrimina, o
  discrimina al revés), coherente con el patrón ya cerrado en VALIDACIÓN
  ALPHA. No concluyente con N=4 — vigilancia prioritaria, no descarte.

**No se construye QFEL-Cripto ni Camino C todavía.** Camino C exige
explícitamente "≥2 estrategias con `RULESET_vX` validado en el pool" — hay 0.
Antes de añadir ninguna capa nueva:

1. **Corregir la ruta de escritura de operaciones** (fuera de este repo, en
   n8n/Hetzner): idempotencia por hash en el insert (evita repetir el bug de
   §2 con cualquier scanner futuro); rellenar `RESULTADO_EUR`, `TAMAÑO_POS`,
   `COMISION_USD`; validar `SCN_ID_REF` contra el catálogo antes de escribir.
2. **Portar `is_valid_operation()` (o su lógica) al dashboard real** —
   Apps Script sobre Google Sheets hoy, tabla/vista en PostgreSQL tras la
   migración — para que el dashboard deje de mostrar los números "sin
   filtrar" de forma permanente, no solo en esta auditoría puntual.
3. **Seguir acumulando en PAPER** hasta ≥20 operaciones certificadas por
   scanner antes de juzgar si alguna estrategia base tiene ventaja.
4. **Vigilancia prioritaria sobre ST-16**: más muestra certificada que
   cualquier otro scanner y la única señal (aunque débil) de problema
   estructural real.

`scripts/audit/audit_tarea0.py` + `scripts/audit/validation.py` quedan como
línea base reproducible y como el único punto de entrada para "operaciones
válidas" en el código de este repo. **Fase 0B (motor de validación
MC/permutación/walk-forward) debe partir de
`docs/auditoria/data/05_OPERACIONES_certified_20260921.csv` o de una
re-ejecución de `certify_operations()` sobre el export vigente — nunca de
`05_OPERACIONES` sin certificar.**
