"""
Compara el oráculo Node (docs/pipeline/generar_oraculo_evaluate_js.sh,
fixtures en docs/pipeline/fixtures_js/oraculo_evaluate/) contra el
endpoint REAL desplegado: peticiones HTTP de verdad a
POST http://<AXONIK_PROXY_BASE>/api/evaluate-ticker.

A diferencia de test_evaluate_ticker_endpoint.py (TestClient in-process,
sin red), este test llama al servidor real a propósito -- el objetivo es
verificar que lo que de verdad corre en producción coincide con el JS
real del navegador ejecutado bajo Node, no una app FastAPI de prueba.
Por eso NO puede ejecutarse en este sandbox ni en CI: se auto-omite
(pytest.skip) si no hay fixtures o si <AXONIK_PROXY_BASE>/api/health no
responde -- mismo motivo por el que VERIFICACION_NAVEGADOR_VS_ENDPOINT.md
ya avisaba que esta sesión no tiene acceso al servidor real.

Ejecutar esto a mano (o desde la sesión con acceso al Hetzner) tras:
  1. Aplicar docs/pipeline/deploy_evaluate_endpoint.sh en el servidor.
  2. Ejecutar docs/pipeline/generar_oraculo_evaluate_js.sh en el
     servidor (produce docs/pipeline/fixtures_js/oraculo_evaluate/).
  3. cd services/snapshot-autocapture && pytest test_oraculo_vs_endpoint.py -s

Tolerancia numérica: 1e-9 (mismo criterio que
test_evaluate_ticker_endpoint.py). Compara exactamente lo que pedía
VERIFICACION_NAVEGADOR_VS_ENDPOINT.md (Paso D): hardNo, globalVerdict,
globalScore y, por estrategia, id/applicable/score/verdict -- más el
resultado de detect_auto_trigger(), que la verificación manual nunca
llegó a cubrir.
"""
from __future__ import annotations

import json
import math
import os
from pathlib import Path

import pytest
import requests

import evaluate_ticker_logic as etl

PROXY_BASE = os.environ.get("AXONIK_PROXY_BASE", "http://127.0.0.1:8002")
FIXTURES_DIR = (
    Path(__file__).parent.parent.parent / "docs" / "pipeline" / "fixtures_js" / "oraculo_evaluate"
)
# DEFAULT_SETTINGS real (Pregunta 6d) -- solo las 3 claves que de verdad
# consume evaluateTicker()/tickerHardNo(), mismo valor que usa el driver
# de Node del oráculo.
SETTINGS = {"priceMin": 8, "atrMax": 4, "rvolMin": 1}


def _discover_tickers() -> list[str]:
    if not FIXTURES_DIR.is_dir():
        return []
    suffix = "_evaluate_output.json"
    return sorted(p.name[: -len(suffix)] for p in FIXTURES_DIR.glob(f"*{suffix}"))


TICKERS = _discover_tickers()

# Rellenado por test_endpoint_real_coincide_con_oraculo (un ticker por
# parametrización) y leído por test_informe_cobertura_detect_auto_trigger
# -- depende del orden de ejecución dentro de este módulo (pytest corre
# los tests en orden de declaración por defecto); no pensado para
# pytest-xdist ni para ejecutarse de forma aislada por nombre.
_coverage: dict[str, str] = {}


@pytest.fixture(scope="module", autouse=True)
def _require_real_server():
    if not TICKERS:
        pytest.skip(
            f"No hay fixtures en {FIXTURES_DIR} -- ejecutar primero "
            f"docs/pipeline/generar_oraculo_evaluate_js.sh contra el servidor real."
        )
    try:
        resp = requests.get(f"{PROXY_BASE}/api/health", timeout=3)
        resp.raise_for_status()
    except Exception as e:
        pytest.skip(
            f"No se puede alcanzar {PROXY_BASE}/api/health ({e!r}) -- esta prueba "
            f"necesita el proxy real corriendo (a propósito no se simula con "
            f"TestClient: el objetivo es verificar el servidor real). Ejecutar "
            f"desde la sesión con acceso al Hetzner."
        )


def _load_candles_payload(ticker: str) -> dict:
    """Reconstruye el shape de 'candles' que espera el endpoint
    ({"1d": {"candles":[...], "periods":N}, ...}) a partir de los
    ficheros <TICKER>_<TF>_candles.json que ya escribió el oráculo --
    mismas velas congeladas, nunca pedidas una segunda vez."""
    payload = {}
    for tf in ("1d", "1h", "15m"):
        p = FIXTURES_DIR / f"{ticker}_{tf}_candles.json"
        if not p.is_file():
            continue
        candles = json.loads(p.read_text())
        payload[tf] = {"candles": candles, "periods": len(candles)}
    return payload


def _load_oracle_result(ticker: str) -> dict | None:
    raw = json.loads((FIXTURES_DIR / f"{ticker}_evaluate_output.json").read_text())
    return etl.sentinel_to_nan(raw)


def _load_oracle_trigger(ticker: str) -> dict | None:
    raw = json.loads((FIXTURES_DIR / f"{ticker}_trigger_output.json").read_text())
    return etl.sentinel_to_nan(raw)


def _summary(r: dict | None) -> dict:
    if r is None:
        return {"hardNo": None, "globalVerdict": None, "globalScore": None, "strategies": []}
    return {
        "hardNo": r["hardNo"],
        "globalVerdict": r["globalVerdict"],
        "globalScore": r["globalScore"],
        "strategies": sorted(
            (s["id"], s["applicable"], s.get("score"), s["verdict"]) for s in r["strategies"]
        ),
    }


def _assert_close(actual, expected, path="$", rel_tol=1e-9):
    if isinstance(expected, float) and math.isnan(expected):
        assert isinstance(actual, float) and math.isnan(actual), f"{path}: esperado NaN, salió {actual!r}"
        return
    if isinstance(expected, (int, float)) and not isinstance(expected, bool):
        assert isinstance(actual, (int, float)) and math.isclose(actual, expected, rel_tol=rel_tol), (
            f"{path}: {actual!r} != {expected!r}"
        )
        return
    assert actual == expected, f"{path}: {actual!r} != {expected!r}"


def _assert_summary_matches(endpoint_summary: dict, oracle_summary: dict, path: str) -> None:
    for key in ("hardNo", "globalVerdict"):
        assert endpoint_summary[key] == oracle_summary[key], (
            f"{path}.{key}: endpoint={endpoint_summary[key]!r} oráculo={oracle_summary[key]!r}"
        )
    _assert_close(endpoint_summary["globalScore"], oracle_summary["globalScore"], f"{path}.globalScore")
    assert len(endpoint_summary["strategies"]) == len(oracle_summary["strategies"]), (
        f"{path}.strategies: distinto número de estrategias -- "
        f"endpoint={endpoint_summary['strategies']!r} oráculo={oracle_summary['strategies']!r}"
    )
    for (e_id, e_app, e_score, e_verdict), (o_id, o_app, o_score, o_verdict) in zip(
        endpoint_summary["strategies"], oracle_summary["strategies"]
    ):
        assert e_id == o_id, f"{path}.strategies: {e_id!r} != {o_id!r}"
        assert e_app == o_app, f"{path}.strategies[{e_id}].applicable: {e_app!r} != {o_app!r}"
        assert e_verdict == o_verdict, f"{path}.strategies[{e_id}].verdict: {e_verdict!r} != {o_verdict!r}"
        _assert_close(e_score, o_score, f"{path}.strategies[{e_id}].score")


@pytest.mark.parametrize("ticker", TICKERS)
def test_endpoint_real_coincide_con_oraculo(ticker):
    """Condición de cierre del paso 3 (README de este servicio): el
    endpoint real, con las MISMAS velas, debe dar el MISMO resultado que
    evaluateTicker()/detectAutoTrigger() ejecutados de verdad bajo Node
    -- comparación campo a campo, no una aproximación."""
    candles = _load_candles_payload(ticker)
    resp = requests.post(
        f"{PROXY_BASE}/api/evaluate-ticker",
        json={
            "ticker": ticker, "mode": "NYSE", "candles": candles,
            "funda": None, "settings": SETTINGS,
            "btc_gate_on": False, "insider_summary": None,
        },
        timeout=30,
    )
    assert resp.status_code == 200, resp.text
    endpoint_result = etl.sentinel_to_nan(resp.json())
    oracle_result = _load_oracle_result(ticker)

    _assert_summary_matches(_summary(endpoint_result), _summary(oracle_result), f"evaluate[{ticker}]")

    # detect_auto_trigger() se compara aparte -- VERIFICACION_NAVEGADOR_VS_ENDPOINT.md
    # (versión anterior) nunca llegó a cubrir esto, solo el resumen de evaluateTicker().
    endpoint_trigger = etl.detect_auto_trigger(endpoint_result)
    oracle_trigger = _load_oracle_trigger(ticker)
    assert (endpoint_trigger is None) == (oracle_trigger is None), (
        f"trigger[{ticker}]: endpoint={endpoint_trigger!r} oráculo={oracle_trigger!r}"
    )
    if endpoint_trigger is not None:
        assert endpoint_trigger["type"] == oracle_trigger["type"], f"trigger[{ticker}].type"
        assert sorted(s["id"] for s in endpoint_trigger["strategies"]) == sorted(
            s["id"] for s in oracle_trigger["strategies"]
        ), f"trigger[{ticker}].strategies"

    _coverage[ticker] = endpoint_trigger["type"] if endpoint_trigger else "ninguno"


def test_informe_cobertura_detect_auto_trigger():
    """No verifica nada nuevo -- informa, con los datos reales de los
    tickers probados arriba, qué ramas de detectAutoTrigger() quedaron
    ejercitadas hoy: AUTO_MULTI, AUTO_HIGH o ninguna. Una rama que no
    aparezca en una ejecución concreta (p.ej. ningún ticker del universo
    real llegó a 2 estrategias del mismo grupo con score>=80 ese día) NO
    es una laguna de pruebas: sigue cubierta por los tests unitarios
    sintéticos de test_evaluate_ticker_logic.py, que construyen los dos
    casos a mano sin depender de que el mercado real los produzca.
    Este informe es un dato del día de la ejecución, no un sustituto de
    esos tests unitarios."""
    if not _coverage:
        pytest.skip("test_endpoint_real_coincide_con_oraculo no se ejecutó -- sin cobertura que informar.")

    by_type: dict[str, list[str]] = {}
    for ticker, t in _coverage.items():
        by_type.setdefault(t, []).append(ticker)

    lines = [f"Cobertura real de detectAutoTrigger() -- {len(_coverage)} ticker(s) probados hoy:"]
    for t in ("AUTO_MULTI", "AUTO_HIGH", "ninguno"):
        tickers = by_type.get(t, [])
        lines.append(f"  {t}: {len(tickers)} ticker(s) -- {', '.join(tickers) if tickers else '(ninguno hoy)'}")
    for t in ("AUTO_MULTI", "AUTO_HIGH"):
        if t not in by_type:
            lines.append(
                f"  AVISO: ningún ticker real de esta ejecución disparó {t} -- esa rama solo "
                f"queda cubierta por los tests unitarios sintéticos de "
                f"test_evaluate_ticker_logic.py, no por datos reales hoy."
            )
    report = "\n".join(lines)
    print("\n" + report)

    report_path = FIXTURES_DIR / "_comparacion_resultado.txt"
    report_path.write_text(report + "\n")
    print(f"\nEscrito: {report_path} -- comitear junto con los fixtures del oráculo.")
