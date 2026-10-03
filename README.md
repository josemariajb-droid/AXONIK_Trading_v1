# AXONIK Trading v1

Sistema de trading algorítmico AXONIK: Decision Engine v2 (Google Sheets) +
n8n/PostgreSQL/Redis en Hetzner. Este repositorio contiene el código y la
documentación que acompaña a ese sistema (auditorías, módulos de validación,
pipelines de ingesta cualitativa).

## Estructura

- `docs/auditoria/` — auditorías del Decision Engine (datos, hallazgos,
  decisiones). Ver `2026-09-22_auditoria_tarea0.md` para la auditoría base
  de scanners/operaciones previa a QFEL-Cripto y Camino C, y
  `2026-09-22_umbral_certificacion.md` para el umbral de N bruto necesario
  antes de correr los gates estadísticos de Fase 0B.
- `docs/pipeline/` — diseños de corrección del pipeline de ingesta
  (n8n → Google Sheets), pendientes de aplicar en producción.
- `scripts/common/validation.py` — **única fuente de verdad** sobre qué
  operaciones de `05_OPERACIONES` son válidas para métricas agregadas
  (dashboard, reports, PF/WR, gates de Fase 0B). Cualquier código nuevo
  que necesite "operaciones válidas" importa `is_valid_operation` /
  `certify_operations` de ahí — no reimplementa el filtro. `services/validation-api`
  expone esta misma función por HTTP para que n8n (JavaScript) la consulte
  sin necesidad de reimplementarla.
- `scripts/audit/` — script de auditoría reproducible sobre exports del
  Decision Engine v2 (`audit_tarea0.py`).
- `scripts/validation_engine/` — Fase 0B: esqueleto de los gates de
  validación (A integridad, B asociación, C selección múltiple, D
  walk-forward, ablation, permutación). Gate A está implementado y es
  ejecutable ya; B/C/D/ablation/permutación son interfaces diseñadas pero
  no implementadas — devuelven `INSUFFICIENT_SAMPLE` de forma honesta por
  debajo del umbral en `sample_requirements.py`.
- `services/validation-api/` — microservicio FastAPI que envuelve
  `is_valid_operation()` por HTTP, para que el workflow de n8n la consulte
  en tiempo real en vez de reimplementar la regla en JavaScript. No
  desplegado todavía — ver `docs/pipeline/2026-09-22_fix_idempotencia_ingesta.md`.

## Principio rector

> La IA puede descubrir patrones. AXONIK no los cree hasta que los datos
> fuera de muestra los demuestran.
