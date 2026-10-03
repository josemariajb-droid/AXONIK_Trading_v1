# Umbral mínimo de N brutas antes de correr gates B/C/D

**Fecha:** 22/09/2026
**Depende de:** `docs/auditoria/2026-09-22_auditoria_tarea0.md` (tasas de exclusión por motivo)
**Consume este análisis:** `scripts/validation_engine/sample_requirements.py::MIN_N_CERTIFIED_STATISTICAL_GATE`

## Contexto

El gate operativo del spec exige ≥20 operaciones **certificadas** por
estrategia, no brutas. De las 14 filas brutas de `05_OPERACIONES`, solo 7
certificaron (§4 del informe de auditoría) — una tasa de certificación del
50%. Si esa tasa se mantuviera, harían falta ~40 operaciones brutas por
estrategia para llegar a 20 certificadas. Antes de fijar ese número hay
que separar qué parte del 50% de pérdida es un defecto de pipeline ya
identificado (y por tanto corregible a ~0%) y qué parte es incertidumbre
genuina por tamaño de muestra.

## Análisis

### Descomposición de las 7 exclusiones (14 brutas → 7 certificadas)

| Motivo | N | Causa raíz | ¿Eliminable con la corrección de pipeline (punto 1)? |
|---|---|---|---|
| `duplicate_batch_replay` | 4 | Fallo de idempotencia en la escritura n8n→Sheets (evento de lote único, ST-16) | Sí — directamente, es la causa que se corrige |
| `orphan_scanner_ref` | 2 | `SCN_ID_REF` no validado contra catálogo al escribir | Sí, si se añade validación de catálogo en el mismo cambio |
| `entry_price_inconsistent` | 1 | Precio de entrada corrupto (AAPL/ST-05) — causa raíz no confirmada, podría ser el mismo problema de caché que produjo el reenvío de lote, o uno distinto | No confirmado — tratar como persistente hasta probar lo contrario |

Los dos primeros motivos (6 de 7 exclusiones) tienen causa raíz
identificada y corregible en la ruta de escritura. El tercero (1 de 7) no
tiene causa raíz confirmada todavía — no se puede asumir que desaparece
solo porque se arregla la idempotencia.

### Cuánta incertidumbre hay con una sola observación

`entry_price_inconsistent` ocurrió 1 vez en 14 filas brutas. Con una
muestra así de pequeña, la tasa real no está en 7.1% (1/14) — ese es solo
el punto central. Intervalo de confianza al 95% (Wilson): **[1.3%, 31.5%]**.
Es decir, con los datos actuales la tasa real de este defecto podría ser
tan baja como 1 en 80 operaciones o tan alta como 1 en 3 — no hay forma de
saberlo con N=14.

### Estimación de N bruto necesario según escenario

Asumiendo que la corrección de pipeline (punto 1) elimina
`duplicate_batch_replay` y `orphan_scanner_ref` por completo, y que
`entry_price_inconsistent` persiste a alguna tasa `p`:

| Escenario | Tasa de defecto asumida | N bruto para 20 certificadas |
|---|---|---|
| Optimista (punto central, 1/14) | 7.1% | 22 |
| Pesimista (límite superior IC95%) | 31.5% | 30 |
| Sin corregir el pipeline (tasa actual, 50%) | 50.0% | 40 |

## Decisión

**Umbral interino: 30 operaciones brutas certificables por scanner/estrategia**
antes de correr los gates B, C, D, ablation o permutación
(`sample_requirements.py::MIN_N_CERTIFIED_STATISTICAL_GATE = 30`). Cubre el
escenario pesimista asumiendo que la corrección de idempotencia + validación
de catálogo (punto 1) se despliega antes de seguir acumulando. Nota: este
número es de **operaciones certificadas**, no brutas — con tasa de defecto
optimista casi coincide (22 brutas ≈ 20 certificadas); con la pesimista, 30
brutas ≈ 20-21 certificadas. Se usa 30 como cifra única de trabajo para no
manejar dos umbrales distintos por escenario.

Si el pipeline **no** se corrige antes de seguir acumulando en PAPER, el
umbral real es 40 brutas, no 30 — motivo de más para que el punto 1
(idempotencia) sea la prioridad inmediata, como se pidió.

**Esto no es definitivo.** En cuanto existan operaciones brutas
posteriores a la corrección de pipeline, recalcular la tasa de
certificación empírica real (¿sigue apareciendo `entry_price_inconsistent`
o no?) y sustituir esta estimación basada en un solo evento histórico por
una medida directa. Actualizar `MIN_N_CERTIFIED_STATISTICAL_GATE` en el
mismo commit que actualice este documento.
