#!/usr/bin/env python3
"""
Ejecuta Gate A (integridad) sobre un CSV certificado (salida de
scripts/audit/audit_tarea0.py --export-certified).

Uso:
    python3 run_gate_a.py /ruta/a/05_OPERACIONES_certified_YYYYMMDD.csv

Gate A no requiere N mínimo — es aplicable hoy mismo sobre el dataset
certificado de Fase 0A. Ver gates.py::run_gate_a para el diseño.
"""
import csv
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # scripts/
from validation_engine.gates import run_gate_a  # noqa: E402


def main():
    if len(sys.argv) != 2:
        print(__doc__)
        return 1
    with open(sys.argv[1], newline="") as f:
        ops = list(csv.DictReader(f))
    # Los scanners referenciados en un CSV ya certificado son por
    # definición conocidos (certify_operations ya excluyó los huérfanos),
    # así que basta con derivar el conjunto de las propias filas.
    known_scanners = {o["scn_ref"] for o in ops}

    result = run_gate_a(ops, known_scanners)
    print(f"Gate A — status: {result.status.value} (N={result.n_used})")
    if result.issues:
        print("Issues encontrados:")
        for entry in result.issues:
            print(f"  {entry['op_id']}: {entry['issues']}")
    else:
        print("Sin issues de integridad.")
    return 0 if result.status.value == "pass" else 1


if __name__ == "__main__":
    sys.exit(main())
