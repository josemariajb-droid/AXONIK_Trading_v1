"""
Fase 0B — ablation test (spec QFEL-Cripto §2.5, "Más:").

Compara el sistema base contra el sistema + cada feature cualitativa
(funding, news, ETF flows) individualmente y en combinación, para separar
qué feature aporta información real de cuál es ruido que el resto del
sistema absorbe. Aplica tanto a features de acciones (Form 4/Finviz) como
a las de cripto (funding rate, ETF flows, news — sección 2.1 del spec).

Diseño, no ejecución: no tiene sentido correr esto hasta que exista al
menos una feature cualitativa real ingerida (Fase 1-2 del spec, todavía no
construidas) Y suficiente N certificado por variante. Ver
sample_requirements.py y docs/auditoria/2026-09-22_umbral_certificacion.md.
"""
from __future__ import annotations

import sys
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Mapping, Sequence

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # scripts/
from validation_engine.gates import GateResult, GateStatus  # noqa: E402
from validation_engine.sample_requirements import (  # noqa: E402
    MIN_N_CERTIFIED_STATISTICAL_GATE,
    check_sample,
)


class Variant(str, Enum):
    """Combinaciones que el spec pide comparar explícitamente."""
    BASE = "base"
    BASE_PLUS_FUNDING = "base+funding"
    BASE_PLUS_NEWS = "base+news"
    BASE_PLUS_ETF = "base+etf"
    BASE_PLUS_ALL = "base+funding+news+etf"


@dataclass
class AblationInput:
    """returns_by_variant[Variant.BASE] = resultados certificados del SETUP
    solo; el resto son el mismo SETUP + esa combinación de features."""
    returns_by_variant: Mapping[Variant, Sequence[float]]
    feature_version: str


@dataclass
class AblationResult:
    gate: GateResult
    # variant -> (mean_return, contribución incremental vs BASE)
    per_variant: dict = field(default_factory=dict)


def run_ablation(data: AblationInput,
                  min_n: int = MIN_N_CERTIFIED_STATISTICAL_GATE) -> AblationResult:
    """
    Diseño previsto: para cada variante != BASE, calcular la diferencia de
    rendimiento certificado frente a BASE con su intervalo de confianza
    (bootstrap), no solo la media. Una feature que no mueve la aguja fuera
    del intervalo de BASE se descarta — coherente con el principio rector
    del proyecto ("no se crea un patrón hasta que los datos fuera de
    muestra lo demuestran").

    No implementado — el NotImplementedError solo se alcanza si ya hay
    muestra suficiente en todas las variantes, lo cual hoy es imposible
    (no existe ninguna feature cualitativa ingerida todavía).
    """
    n_min_across_variants = min((len(v) for v in data.returns_by_variant.values()), default=0)
    check = check_sample(n_min_across_variants, min_n)
    if not check.ok:
        gate = GateResult(
            gate_id="ablation", status=GateStatus.INSUFFICIENT_SAMPLE,
            n_used=n_min_across_variants, n_required=min_n,
            details={"variants_present": [v.value for v in data.returns_by_variant],
                     "feature_version": data.feature_version},
        )
        return AblationResult(gate=gate)
    raise NotImplementedError("Ablation test: cálculo de contribución incremental no implementado.")
