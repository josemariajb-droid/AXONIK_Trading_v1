"""
Microservicio de validación en tiempo real para el pipeline de escritura
de 05_OPERACIONES (n8n → Google Sheets).

Existe por una razón concreta: n8n ejecuta JavaScript (Code node), no
Python, así que no puede importar `scripts/common/validation.py`
directamente. En vez de portar `is_valid_operation()` a JS a mano (lo que
crearía exactamente la reimplementación paralela que Fase 0A eliminó
dentro del repo Python), este servicio envuelve el módulo Python real por
HTTP — sigue habiendo UNA sola implementación de la regla, n8n solo la
consulta.

Uso previsto en el workflow de n8n que escribe en 05_OPERACIONES: llamar
POST /validate justo antes del nodo "Google Sheets Append", con el mismo
payload que se va a escribir, y escribir el resultado en dos columnas
nuevas (VALIDACION_ESTADO, VALIDACION_MOTIVO) en la misma fila — así el
dashboard puede filtrar por esa columna en vez de mantener su propia
lógica de exclusión (ver docs/pipeline/2026-09-22_fix_idempotencia_ingesta.md).

Despliegue: no aplicado todavía — ver ese mismo documento, sección
"Bloqueo de acceso". Este archivo + su Dockerfile están listos para
añadirse al docker-compose.yml existente en el Hetzner
(servicio nuevo en axonik_axonik_net, sin credenciales adicionales).
"""
from __future__ import annotations

import sys
from pathlib import Path

from fastapi import FastAPI
from pydantic import BaseModel

# Dos layouts posibles: local (services/validation-api/app.py, scripts/
# vive en la raíz del repo, 2 niveles arriba) o contenedor (Dockerfile
# copia scripts/common a /app/scripts/common, 1 nivel arriba). Se prueban
# ambos en vez de asumir uno solo.
_here = Path(__file__).resolve().parent
for _candidate in (_here.parent.parent / "scripts", _here / "scripts"):
    if (_candidate / "common" / "validation.py").exists():
        sys.path.insert(0, str(_candidate))
        break
else:
    raise RuntimeError("No se encontró scripts/common/validation.py en ningún layout conocido")

from common.validation import is_valid_operation  # noqa: E402

app = FastAPI(title="AXONIK validation-api", version="1.0.0")


class OperationPayload(BaseModel):
    op_id: str
    scn_ref: str
    notas: str = ""
    known_scanners: list[str]


class ValidationResponse(BaseModel):
    valid: bool
    reason: str | None


@app.post("/validate", response_model=ValidationResponse)
def validate(payload: OperationPayload) -> ValidationResponse:
    op = {"op_id": payload.op_id, "scn_ref": payload.scn_ref, "notas": payload.notas}
    ok, reason = is_valid_operation(op, set(payload.known_scanners))
    return ValidationResponse(valid=ok, reason=reason.value if reason else None)


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}
