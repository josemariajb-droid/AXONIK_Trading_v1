# AXONIK Trading v1

Sistema de trading algorítmico AXONIK: Decision Engine v2 (Google Sheets) +
n8n/PostgreSQL/Redis en Hetzner. Este repositorio contiene el código y la
documentación que acompaña a ese sistema (auditorías, módulos de validación,
pipelines de ingesta cualitativa).

## Estructura

- `docs/auditoria/` — auditorías del Decision Engine (datos, hallazgos,
  decisiones). Ver `2026-09-22_auditoria_tarea0.md` para la auditoría base
  de scanners/operaciones previa a QFEL-Cripto y Camino C.
- `scripts/audit/` — scripts reproducibles de auditoría sobre exports del
  Decision Engine v2.

## Principio rector

> La IA puede descubrir patrones. AXONIK no los cree hasta que los datos
> fuera de muestra los demuestran.
