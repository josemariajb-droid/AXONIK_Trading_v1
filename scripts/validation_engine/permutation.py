"""
Fase 0B — test de permutación (spec QFEL-Cripto §2.5, "Más:").

Feature real vs. feature aleatorizada: si el sistema rinde igual con la
feature cualitativa barajada al azar que con la real, la feature no aporta
edge — es la misma disciplina que ya cerró VALIDACIÓN ALPHA para las
estrategias base (97 combinaciones, cero edge explotable tras
permutación/Monte Carlo). Esto aplica esa misma disciplina a cada feature
cualitativa nueva antes de dejarla influir el Decision Engine.

Diseño, no ejecución: mismo motivo que ablation.py — no hay feature
cualitativa real ingerida todavía, y aunque la hubiera, no correr con
N por debajo del umbral (sample_requirements.py).
"""
from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Sequence

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # scripts/
from validation_engine.gates import GateResult, GateStatus  # noqa: E402
from validation_engine.sample_requirements import (  # noqa: E402
    MIN_N_CERTIFIED_STATISTICAL_GATE,
    check_sample,
)


@dataclass
class PermutationInput:
    """
    returns: resultados certificados del sistema con la feature real.
    feature_values: valores de la feature cualitativa alineados 1:1 con
        `returns` (mismo orden temporal).
    score_fn: dado (returns, feature_values), devuelve el estadístico de
        rendimiento a comparar (p.ej. Sharpe, expectancy). Se aplica igual
        a la feature real y a cada barajado.
    n_permutations: número de barajados aleatorios de feature_values.
    """
    returns: Sequence[float]
    feature_values: Sequence[float]
    score_fn: Callable[[Sequence[float], Sequence[float]], float]
    n_permutations: int = 1000
    feature_version: str = ""


@dataclass
class PermutationResult:
    gate: GateResult
    real_score: float | None = None
    permuted_scores: list | None = None
    p_value: float | None = None  # fracción de barajados que igualan/superan el real


def run_permutation_test(data: PermutationInput,
                          min_n: int = MIN_N_CERTIFIED_STATISTICAL_GATE) -> PermutationResult:
    """
    Diseño previsto: `p_value` = P(score_barajado >= score_real). Umbral de
    decisión sugerido p<0.05 para considerar que la feature aporta señal
    no explicable por azar — mismo criterio que VALIDACIÓN ALPHA. No basta
    con "el real es el más alto": con `n_permutations` grande, reportar
    también el percentil exacto del score real dentro de la distribución
    barajada, no solo el p-valor puntual.

    No implementado — ver nota en ablation.run_ablation.
    """
    n = min(len(data.returns), len(data.feature_values))
    check = check_sample(n, min_n)
    if not check.ok:
        gate = GateResult(
            gate_id="permutation", status=GateStatus.INSUFFICIENT_SAMPLE,
            n_used=n, n_required=min_n,
            details={"n_permutations": data.n_permutations, "feature_version": data.feature_version},
        )
        return PermutationResult(gate=gate)
    raise NotImplementedError("Permutation test: barajado y cálculo de p-valor no implementado.")
