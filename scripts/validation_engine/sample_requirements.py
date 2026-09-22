"""
Umbrales mínimos de muestra antes de que un gate estadístico tenga sentido.

Números y metodología completa en
docs/auditoria/2026-09-22_umbral_certificacion.md — este módulo solo
codifica la conclusión de ese análisis para que ningún gate pueda
ejecutarse "por accidente" con muestra insuficiente.

No editar estas constantes sin actualizar ese documento en el mismo commit.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class SampleAdequacy(str, Enum):
    SUFFICIENT = "sufficient"
    INSUFFICIENT = "insufficient"


@dataclass(frozen=True)
class SampleCheck:
    n_certified: int
    n_required: int
    adequacy: SampleAdequacy

    @property
    def ok(self) -> bool:
        return self.adequacy is SampleAdequacy.SUFFICIENT


# Gate operativo final (ya existente en el spec, sección 2.5): mínimo de
# operaciones CERTIFICADAS (no brutas) para considerar una estrategia
# individual operable en real.
MIN_N_CERTIFIED_OPERATIONAL_GATE = 20

# Gates estadísticos (B, C, D, ablation, permutación) necesitan más margen
# que el gate operativo puro porque cada uno consume grados de libertad
# (splits de walk-forward, tests de permutación, corrección por N
# hipótesis). Cifra interina hasta tener tasa de certificación empírica
# post-fix del pipeline — ver docs/auditoria/2026-09-22_umbral_certificacion.md
# sección "Decisión". Revisar cuando existan operaciones certificadas
# posteriores a la corrección del bug de idempotencia (ST-16).
MIN_N_CERTIFIED_STATISTICAL_GATE = 30


def check_sample(n_certified: int, n_required: int = MIN_N_CERTIFIED_STATISTICAL_GATE) -> SampleCheck:
    adequacy = SampleAdequacy.SUFFICIENT if n_certified >= n_required else SampleAdequacy.INSUFFICIENT
    return SampleCheck(n_certified=n_certified, n_required=n_required, adequacy=adequacy)
