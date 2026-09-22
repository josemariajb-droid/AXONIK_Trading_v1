"""
Único punto de verdad sobre qué filas de 05_OPERACIONES cuentan para
métricas agregadas (Win Rate, RR medio, Profit Factor, y cualquier gate
de validación posterior: Fase 0B en adelante).

Ningún otro módulo debe reimplementar este filtro. Si un cálculo nuevo
necesita "operaciones válidas", importa `is_valid_operation` /
`certify_operations` de aquí — no vuelve a escribir la condición.

Origen de las exclusiones: docs/auditoria/2026-09-22_auditoria_tarea0.md.
Este archivo no añade heurísticas estadísticas de outliers por su cuenta
(p.ej. "excluir RR>5"): solo excluye lo que la auditoría confirmó con
causa raíz identificada. Ampliar `CONFIRMED_INVALID_OPS` exige la misma
evidencia forense: comparación contra datos contemporáneos, no solo "es
un número grande".
"""
from __future__ import annotations

from enum import Enum
from typing import Iterable, Mapping, Sequence


class InvalidReason(str, Enum):
    DUPLICATE_BATCH_REPLAY = "duplicate_batch_replay"
    ENTRY_PRICE_INCONSISTENT = "entry_price_inconsistent"
    ORPHAN_SCANNER_REF = "orphan_scanner_ref"


# Registro auditable de operaciones con error de datos confirmado por
# causa raíz (no por umbral estadístico). Cada entrada debe tener su
# justificación en el informe de auditoría antes de añadirse aquí.
#
# 62f5e3386d05 (AAPL/ST-05, 2026-08-06): PRECIO_ENTRADA=220.0 es
# incompatible con el precio real de AAPL esa semana. Las dos operaciones
# AAPL/ST-16 de la misma semana (2026-08-07/08) registran entrada=313.33,
# y el PRECIO_SALIDA de esta operación (310.10) SÍ es consistente con ese
# rango real. El error está localizado en la captura de PRECIO_ENTRADA
# (dato obsoleto/cacheado o mapeo de símbolo incorrecto en el motor de
# ejecución PAPER), no en un movimiento de mercado real. RESULTADO_PCT
# (+40.96%) y RR_REAL (17.91) derivados de este par son artefactos de ese
# error, no una operación ganadora real.
CONFIRMED_INVALID_OPS: Mapping[str, InvalidReason] = {
    "62f5e3386d05": InvalidReason.ENTRY_PRICE_INCONSISTENT,
}


def known_scanner_prefixes(scanner_rows: Iterable[Sequence], scn_idx: Mapping[str, int]) -> set[str]:
    """Prefijos válidos (p.ej. 'ST-16', 'SC-02') extraídos de NOMBRE en 02_SCANNERS."""
    prefixes = set()
    for row in scanner_rows:
        nombre = row[scn_idx["NOMBRE"]] or ""
        prefix = nombre.split(" ", 1)[0] if nombre else ""
        if prefix:
            prefixes.add(prefix)
    return prefixes


def is_valid_operation(op: Mapping, known_scanners: set[str]) -> tuple[bool, InvalidReason | None]:
    """
    op: dict con al menos las claves op_id, scn_ref, notas (ver
        audit_tarea0.py:as_op_record).
    known_scanners: salida de known_scanner_prefixes().

    Devuelve (True, None) si la operación debe contar en métricas
    agregadas, o (False, motivo) si debe excluirse.
    """
    op_id = op["op_id"]
    if op_id in CONFIRMED_INVALID_OPS:
        return False, CONFIRMED_INVALID_OPS[op_id]

    notas = (op.get("notas") or "").lower()
    if "excluido" in notas:
        return False, InvalidReason.DUPLICATE_BATCH_REPLAY

    if op.get("scn_ref") not in known_scanners:
        return False, InvalidReason.ORPHAN_SCANNER_REF

    return True, None


def certify_operations(ops: Iterable[Mapping], known_scanners: set[str]):
    """
    Parte una lista de operaciones (dicts) en (validas, excluidas), donde
    cada excluida lleva anotado el motivo en op['exclusion_reason'].
    """
    validas, excluidas = [], []
    for op in ops:
        ok, reason = is_valid_operation(op, known_scanners)
        if ok:
            validas.append(op)
        else:
            excluidas.append({**op, "exclusion_reason": reason.value})
    return validas, excluidas
