"""
Fase 0B — esqueleto de los gates de validación del spec QFEL-Cripto §2.5.

Diseño, no ejecución de B/C/D todavía: llamar a estos gates hoy sobre el
dataset certificado (N=7) debe devolver `INSUFFICIENT_SAMPLE` de forma
honesta, nunca un veredicto fabricado. Gate A es la excepción — es una
extensión directa de `common.validation.is_valid_operation` y no depende
de tamaño de muestra, así que está implementado y es ejecutable ya.

Cada gate importa exclusivamente de `common.validation` para lo que ya es
responsabilidad de esa capa (qué operación es válida). Ningún gate
reimplementa esa lógica.
"""
from __future__ import annotations

import sys
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Mapping, Sequence

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # scripts/
from common.validation import is_valid_operation  # noqa: E402
from validation_engine.sample_requirements import (  # noqa: E402
    MIN_N_CERTIFIED_STATISTICAL_GATE,
    check_sample,
)


class GateStatus(str, Enum):
    PASS = "pass"
    FAIL = "fail"
    INSUFFICIENT_SAMPLE = "insufficient_sample"


@dataclass
class GateResult:
    gate_id: str
    status: GateStatus
    n_used: int
    n_required: int
    details: dict = field(default_factory=dict)
    issues: list = field(default_factory=list)


# ---------------------------------------------------------------------------
# Gate A — Integridad. Extensión directa de is_valid_operation(): no repite
# sus tres motivos de exclusión, añade las comprobaciones de integridad del
# spec §2.5 que is_valid_operation no cubre (timestamps auditables,
# coste/slippage incorporado).
# ---------------------------------------------------------------------------

class IntegrityIssue(str, Enum):
    NEGATIVE_DURATION_SIGN = "negative_duration_sign"
    MISSING_COST_FIELDS = "missing_cost_fields"      # TAMAÑO_POS / COMISION_USD
    MISSING_SLIPPAGE = "missing_slippage"             # SLIPPAGE_PCT
    MISSING_BROKER_SOURCE = "missing_broker_source"   # BROKER (fuente reproducible)


def _duration_sign_ok(op: Mapping) -> bool:
    """
    DURACION debe ser >= 0. Hallazgo de la auditoría (Tarea 0 §6): LINK/BNB
    registran DURACION negativa porque el cálculo no ajusta el cruce de
    medianoche. Chequeo estructural, no estadístico — no depende de N.
    """
    duracion = op.get("duracion")
    if duracion is None:
        return True  # ausencia de dato se trata aparte, no aquí
    return not str(duracion).strip().startswith("-")


def _has_cost_fields(op: Mapping) -> bool:
    return op.get("tamano_pos") not in (None, "") and op.get("comision_usd") not in (None, "")


def _has_slippage(op: Mapping) -> bool:
    return op.get("slippage_pct") not in (None, "")


def _has_broker_source(op: Mapping) -> bool:
    return bool(op.get("broker"))


def gate_a_integrity_single(op: Mapping, known_scanners: set[str]) -> tuple[bool, list]:
    """Evalúa integridad de UNA operación. Devuelve (ok, issues)."""
    ok_cert, reason = is_valid_operation(op, known_scanners)
    issues: list = [] if ok_cert else [f"certification:{reason.value}"]

    if not _duration_sign_ok(op):
        issues.append(IntegrityIssue.NEGATIVE_DURATION_SIGN.value)
    if not _has_cost_fields(op):
        issues.append(IntegrityIssue.MISSING_COST_FIELDS.value)
    if not _has_slippage(op):
        issues.append(IntegrityIssue.MISSING_SLIPPAGE.value)
    if not _has_broker_source(op):
        issues.append(IntegrityIssue.MISSING_BROKER_SOURCE.value)

    return (ok_cert and not issues), issues


def run_gate_a(ops: Sequence[Mapping], known_scanners: set[str]) -> GateResult:
    """
    Gate A no tiene requisito de N — es integridad estructural, aplicable
    incluso a una sola operación. Reporta issues por operación; el status
    global es FAIL si cualquier operación certificada tiene un issue de
    integridad no cubierto por la certificación misma (coste/slippage/
    timestamps), PASS si todas las certificadas están limpias.

    Nota: hoy (dataset 2026-09-21) esto debe dar FAIL con
    missing_cost_fields/missing_slippage en el 100% de las filas, porque
    TAMAÑO_POS/COMISION_USD/SLIPPAGE_PCT están vacías en el pipeline
    actual (ver informe Fase 0A). Eso es correcto: el gate está haciendo
    su trabajo, no hay que "arreglarlo" para que pase — hay que arreglar
    el pipeline (docs/pipeline/2026-09-22_fix_idempotencia_ingesta.md).
    """
    per_op = {}
    all_issues: list = []
    for op in ops:
        ok, issues = gate_a_integrity_single(op, known_scanners)
        per_op[op["op_id"]] = {"ok": ok, "issues": issues}
        if issues:
            all_issues.append({"op_id": op["op_id"], "issues": issues})

    status = GateStatus.FAIL if all_issues else GateStatus.PASS
    return GateResult(
        gate_id="A_integrity",
        status=status,
        n_used=len(ops),
        n_required=0,
        details={"per_operation": per_op},
        issues=all_issues,
    )


# ---------------------------------------------------------------------------
# Gate B — Asociación estadística.
# SETUP + QUAL_FEATURE vs SETUP solo — ¿aporta información incremental?
# ---------------------------------------------------------------------------

@dataclass
class AssociationInput:
    """
    baseline: resultados (p.ej. RESULTADO_PCT o R-múltiplo) de operaciones
        del SETUP sin la feature cualitativa.
    with_feature: mismos resultados, para el subconjunto donde la feature
        cualitativa estaba presente/activa.
    Ambos deben venir ya certificados (`common.validation.certify_operations`).
    """
    baseline: Sequence[float]
    with_feature: Sequence[float]
    feature_version: str  # p.ej. "QF_CRYPTO_001_v1.0" — trazabilidad del spec §2.3


def run_gate_b_association(data: AssociationInput,
                            min_n: int = MIN_N_CERTIFIED_STATISTICAL_GATE) -> GateResult:
    """
    Test de asociación incremental (spec §2.5, Gate B). Diseño previsto:
    comparar distribución de resultados baseline vs. with_feature con un
    test no paramétrico (p.ej. Mann-Whitney U o bootstrap de la diferencia
    de medias), reportando tamaño de efecto + intervalo de confianza, no
    solo un p-valor.

    No implementado todavía — deliberado (instrucción explícita: no
    ejecutar B/C/D hasta cumplir el umbral de N). Si algún día se llama
    con muestra suficiente y sigue sin implementación, el NotImplementedError
    es la señal correcta de "esto falta", no un resultado silencioso.
    """
    n = min(len(data.baseline), len(data.with_feature))
    check = check_sample(n, min_n)
    if not check.ok:
        return GateResult(
            gate_id="B_association", status=GateStatus.INSUFFICIENT_SAMPLE,
            n_used=n, n_required=min_n,
            details={"feature_version": data.feature_version},
        )
    raise NotImplementedError(
        "Gate B tiene muestra suficiente pero el test estadístico no está "
        "implementado todavía. No lo implementes solo para 'hacerlo pasar' "
        "— esto solo puede ocurrir hoy si min_n se bajó artificialmente."
    )


# ---------------------------------------------------------------------------
# Gate C — Corrección por selección múltiple.
# DSR, White's SPA/Hansen — registrar N hipótesis probadas, N variantes de
# feature, N thresholds.
# ---------------------------------------------------------------------------

@dataclass
class MultipleTestingInput:
    per_hypothesis_returns: Mapping[str, Sequence[float]]  # hypothesis_id -> resultados
    n_variants_tested: int   # variantes de feature probadas (no solo las que "funcionaron")
    n_thresholds_tested: int  # umbrales de score/filtro probados


def run_gate_c_multiple_testing(data: MultipleTestingInput,
                                 min_n: int = MIN_N_CERTIFIED_STATISTICAL_GATE) -> GateResult:
    """
    Deflated Sharpe Ratio (Bailey & López de Prado) + White's Reality
    Check / Hansen's SPA sobre `per_hypothesis_returns`. Diseño previsto:
    exige registrar `n_variants_tested` y `n_thresholds_tested` de forma
    explícita (no inferida) porque el DSR es sensible al número real de
    hipótesis probadas, incluidas las descartadas — coherente con
    VALIDACIÓN ALPHA (97 combinaciones probadas, no solo las 11 finales).

    No implementado — ver nota en run_gate_b_association.
    """
    n = min((len(v) for v in data.per_hypothesis_returns.values()), default=0)
    check = check_sample(n, min_n)
    if not check.ok:
        return GateResult(
            gate_id="C_multiple_testing", status=GateStatus.INSUFFICIENT_SAMPLE,
            n_used=n, n_required=min_n,
            details={
                "n_hypotheses": len(data.per_hypothesis_returns),
                "n_variants_tested": data.n_variants_tested,
                "n_thresholds_tested": data.n_thresholds_tested,
            },
        )
    raise NotImplementedError("Gate C: DSR/SPA no implementado. Ver docstring.")


# ---------------------------------------------------------------------------
# Gate D — Walk-forward + CPCV/PBO.
# Holdout final intocable tras uso — ninguna modificación posterior.
# ---------------------------------------------------------------------------

@dataclass
class WalkForwardInput:
    ops_by_time: Sequence[Mapping]  # operaciones certificadas, ordenadas por fecha
    n_folds: int
    holdout_locked: bool  # True una vez el holdout se ha consultado — no se puede volver a False


def run_gate_d_walkforward(data: WalkForwardInput,
                            min_n: int = MIN_N_CERTIFIED_STATISTICAL_GATE) -> GateResult:
    """
    Walk-forward con Combinatorial Purged Cross-Validation (CPCV) +
    Probability of Backtest Overfitting (PBO, López de Prado). Diseño
    previsto: `n_folds` particiones purgadas por tiempo, holdout final
    consultado una única vez y marcado `holdout_locked=True` de forma
    permanente (append-only, igual que el Pattern Log del spec §2.4) —
    cualquier gate D posterior sobre el mismo holdout debe fallar por
    diseño, no solo por convención.

    No implementado — ver nota en run_gate_b_association.
    """
    n = len(data.ops_by_time)
    check = check_sample(n, min_n)
    if not check.ok:
        return GateResult(
            gate_id="D_walkforward", status=GateStatus.INSUFFICIENT_SAMPLE,
            n_used=n, n_required=min_n,
            details={"n_folds": data.n_folds, "holdout_locked": data.holdout_locked},
        )
    if data.holdout_locked:
        return GateResult(
            gate_id="D_walkforward", status=GateStatus.FAIL,
            n_used=n, n_required=min_n,
            details={}, issues=["holdout ya consultado — no se puede re-ejecutar"],
        )
    raise NotImplementedError("Gate D: CPCV/PBO no implementado. Ver docstring.")
