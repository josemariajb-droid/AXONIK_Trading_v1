# Tarea 0 — Auditoría de 02_SCANNERS / 05_OPERACIONES

**Fecha:** 22/09/2026
**Fuente:** `AXONIK Decision Engine v2.xlsx` (snapshot del 21/09/2026, Google Drive)
**Script:** `scripts/audit/audit_tarea0.py` (reproducible sobre cualquier export futuro)
**Datos crudos usados:** `docs/auditoria/data/02_SCANNERS_20260921.csv`, `docs/auditoria/data/05_OPERACIONES_20260921.csv`

Pregunta que responde esta auditoría (spec QFEL-Cripto §0): los KPIs del dashboard
(WR 14.3%, PF 0.00, P&L €0.00, RR 0.98) — ¿son (a) ruido de muestra insuficiente
o (b) un problema estructural de las estrategias base?

---

## Contexto

- 20 scanners registrados, 14 `EN_PRUEBAS`, 0 `PRODUCCION` (confirma dashboard).
- 05_OPERACIONES contiene 14 filas, pero **no son 14 operaciones independientes**:
  4 pares están duplicados exactamente (mismo ticker, mismo precio de entrada/salida,
  mismo resultado, distinto `OP_ID`), y 2 filas más referencian un scanner que no
  existe en el catálogo.
- 03_ESTRATEGIAS, 04_BACKTESTING, 06_HIPOTESIS y 07_VERSIONES están **vacías**
  (0 filas de datos, solo cabecera). La capa formal de "estrategia congelada"
  (`RULESET_vX`) que exige Camino C no existe todavía en ningún sitio.

## Análisis

### 1. Los KPIs del dashboard están rotos, no son bajos

Las fórmulas del dashboard (`01_DASHBOARD`) son:

```
PROFIT FACTOR = SUMIF(RESULTADO_EUR>0) / ABS(SUMIF(RESULTADO_EUR<0))   → IFERROR → 0
P&L TOTAL     = SUM(RESULTADO_EUR)                                     → IFERROR → 0
```

La columna `RESULTADO_EUR` está **vacía en el 100% de las 14 filas** — nunca se
calcula ni se escribe. El resultado (0.00 / €0.00) es un artefacto de una columna
sin rellenar, no una medición de rendimiento real. Calculado en su lugar sobre
`RESULTADO_PCT` (que sí está poblado), el Profit Factor real es 1.81 (sobre las
14 filas) o 3.46 (sobre las 10 operaciones únicas) — números completamente
distintos del 0.00 mostrado.

**Acción de pipeline, no de estrategia:** hay que hacer que el proceso que
escribe en `05_OPERACIONES` (n8n / script de cierre de operación) calcule y
escriba `RESULTADO_EUR`, `TAMAÑO_POS` y `COMISION_USD` (las tres están vacías
en el 100% de las filas). Sin esto, el dashboard seguirá mintiendo
independientemente de si las estrategias tienen ventaja o no.

### 2. El Win Rate cuenta 4 operaciones duplicadas dos veces

`05_OPERACIONES` guarda una nota de sistema explícita en 4 filas:
`"data_lag_hours=28.88h (>24h) — excluido de métricas agregadas por defecto (R4)"`.
Esa regla (R4) existe como convención documentada pero **no está implementada**
en la fórmula del dashboard (`COUNTIF(RESULTADO,"WIN")/COUNTA(RESULTADO)` usa
las 14 filas sin filtrar). Las 4 filas marcadas son reinserciones exactas de
otras 4 (mismo ticker AAPL/AVGO/MSFT/NVDA, mismo precio, mismo resultado,
solo cambia `OP_ID` y hora de entrada) — el mismo trade contado dos veces,
duplicando cada pérdida.

| Cálculo | N | WIN | WR (wins/N) | WR (wins/(wins+loss)) | RR medio | PF |
|---|---|---|---|---|---|---|
| Como hoy (14, con duplicados) | 14 | 2 | 14.3% | 20.0% | 0.98 | 1.81* |
| Quitando los 4 duplicados R4 | 10 | 2 | 20.0% | 28.6% | 1.59 | 3.46* |

*PF recalculado sobre `RESULTADO_PCT`, no sobre la columna vacía `RESULTADO_EUR`.

### 3. El único otro "win" es un outlier que huele a error de datos, no a edge

De las 10 operaciones únicas solo hay 2 `WIN`. Una es GOOGL/ST-04 (+13.5%,
RR 1.16 — plausible). La otra es **AAPL/ST-05: entrada 220.00 → salida 310.10
en 0.1 días (~2.4h), +40.96%, RR 17.91**. Un movimiento del 41% en AAPL
(large cap, volatilidad diaria típica ~1-2%) en menos de 3 horas no es
físicamente plausible sin un evento extraordinario no registrado en `NOTAS`.
Todo apunta a un precio de salida corrupto (feed erróneo, timeframe mal
casado, o similar), no a una operación real.

Si se excluyen los 4 duplicados R4 y este outlier, quedan 9 operaciones:
1 WIN, 5 LOSS, 2 BREAKEVEN, 1 TIMEOUT → **WR 11.1%, RR medio −0.23, PF 0.86**.
Es decir: **toda la apariencia de rendimiento aceptable del sistema depende
de una sola fila de datos sospechosa.** Antes de sacar cualquier conclusión
sobre las estrategias, esa fila debe investigarse en el broker/feed origen
(paper IBKR/fuente de precio) y corregirse o descartarse.

### 4. La señal más fuerte del dataset: ST-16 en 0/4 con el score más alto

Agrupando las 10 operaciones únicas por scanner:

| Scanner | N | WIN | Score medio entrada | Resultados |
|---|---|---|---|---|
| ST-16 (Compresión en Tendencia) | 4 | 0 | 99 | LOSS, LOSS, TIMEOUT, LOSS |
| SC-02 (Altcoin Season Rotation) | 2 | 0 | 72 | LOSS, LOSS |
| SC-PB (no existe en 02_SCANNERS) | 2 | 0 | 62 | BREAKEVEN, BREAKEVEN |
| ST-04 (MACD Triple Confluencia) | 1 | 1 | 82 | WIN |
| ST-05 (Gap Continuidad Institucional) | 1 | 1 | 75 | WIN *(outlier, ver §3)* |

`ST-16` es el scanner con más muestra (4 de 9-10 operaciones limpias) y el
que exige el `SCORE_ENTRADA` más alto (95-100, el filtro de máxima
convicción del sistema) — y aun así **0 aciertos**. Esto es consistente con
la conclusión ya cerrada de VALIDACIÓN ALPHA ("cero edge explotable",
inversión de signo train/test): el score de entrada no está discriminando
nada, o discrimina al revés. Con N=4 no es prueba estadística, pero es la
única señal de este dataset que apunta a **(b) problema estructural** en
vez de solo ruido — y coincide con un patrón ya visto antes en este proyecto.

### 5. Fallos de integridad de datos adicionales (menores pero reales)

- **`SC-PB` no existe** en `02_SCANNERS` (solo `SC-01` y `SC-02` están
  definidos para `CRYPTO`). Dos operaciones (SUI, ATOM) referencian un
  scanner fantasma — o se borró sin dejar rastro en `07_VERSIONES` (que
  está vacía), o el pipeline permite escribir `SCN_ID_REF` sin validar
  contra el catálogo `11_LISTAS`/`02_SCANNERS`.
- **`DURACION` negativa** en 2 filas (LINK, BNB: entrada 08:56 → salida
  01:00, `DURACION=-0.3d`). El cálculo no ajusta el cambio de día al cruzar
  medianoche.
- **`EST_ID_REF` vacío en el 100% de las operaciones** — ninguna operación
  está vinculada a una estrategia formal de `03_ESTRATEGIAS` porque esa
  hoja no tiene ninguna fila. Las operaciones saltan directo de scanner a
  ejecución, sin pasar por la capa de "estrategia congelada" que el propio
  diseño del sistema (`00_README`) da por existente.
- **`04_BACKTESTING` vacía**: la VALIDACIÓN ALPHA (97 combinaciones,
  Monte Carlo/walk-forward) que el spec da por cerrada no dejó ningún
  registro estructurado en el propio sistema — solo existe en prosa. Sin
  esto, no hay forma de auditar automáticamente esa validación desde aquí.

### 6. Base cripto: aún más pequeña que la de acciones

Solo 2 de los 20 scanners son `CRYPTO` (`SC-01` `EN_PRUEBAS`, `SC-02`
`PENDIENTE`), y entre ambos solo hay 2 operaciones limpias registradas
(las de `SC-02`, ambas `LOSS`). El plan QFEL-Cripto asume implícitamente
que hay algo de base cripto sobre la que capear una capa cualitativa — no
la hay: es la parte con menos datos de todo el sistema.

---

## Decisión

**(a) y (b) simultáneamente, pero no como se planteó la pregunta:**

- **(a) Ruido de muestra insuficiente: confirmado y dominante.** 6-10
  operaciones repartidas en 5 scanners distintos no permiten ninguna
  conclusión estadística sobre ninguna estrategia individual. El propio
  gate operativo del sistema exige ≥20 operaciones — ninguna estrategia
  llega ni a una cuarta parte de eso.
- **Pero antes de eso: los KPIs mostrados hoy (WR 14.3%, PF 0.00, P&L
  €0.00) no son ni siquiera una medición fiable de esas 6-10 operaciones.**
  Son un artefacto de: (1) una columna nunca rellenada (`RESULTADO_EUR`),
  (2) una regla de exclusión de duplicados documentada pero no aplicada
  (R4), y (3) un outlier de datos sin investigar que sostiene sobre sus
  hombros el único resultado positivo aparte de una operación plausible.
- **(b) Señal de problema estructural: parcial, en ST-16 únicamente.**
  0/4 con el score de entrada más alto del sistema es la única evidencia
  de este dataset que apunta a un problema de diseño (el score no
  discrimina, o discrimina al revés) en vez de solo ruido. No es
  concluyente con N=4, pero es coherente con el patrón ya cerrado en
  VALIDACIÓN ALPHA y merece seguimiento prioritario cuando haya más
  muestra — no descarte inmediato, pero sí vigilancia activa.

**No se construye QFEL-Cripto ni Camino C todavía.** Condición explícita
del propio spec para Camino C ("≥2 estrategias con `RULESET_vX` validado
en el pool") no se cumple: hay 0. Antes de añadir ninguna capa nueva:

1. **Arreglar el pipeline de escritura de operaciones** (fuera de este
   repo, en n8n/Hetzner): rellenar `RESULTADO_EUR`, `TAMAÑO_POS`,
   `COMISION_USD`; aplicar la regla R4 como filtro real en las fórmulas
   del dashboard, no solo como nota; deduplicar reinserciones por lag de
   datos en vez de limitarse a anotarlas; validar `SCN_ID_REF` contra el
   catálogo antes de escribir.
2. **Investigar la operación AAPL/ST-05** (+41% en 2.4h) contra el feed de
   precios origen antes de contarla en ninguna métrica.
3. **Seguir acumulando en PAPER** hasta ≥20 operaciones por scanner antes
   de juzgar si alguna estrategia base tiene ventaja — con la muestra
   actual, cualquier veredicto ("funciona" / "no funciona") no sería
   defendible.
4. **Vigilancia prioritaria sobre ST-16**: es el scanner con más muestra y
   el único con una señal (aunque débil) de problema estructural real.

Este documento y `scripts/audit/audit_tarea0.py` quedan como línea base
reproducible: cuando haya más operaciones, re-ejecutar el script sobre el
export actualizado del Decision Engine para repetir este análisis con
mayor N.
