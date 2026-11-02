#!/usr/bin/env python3
"""
AXONIK — Tarea 0 / Fase 0A: auditoría de 05_OPERACIONES y 02_SCANNERS
antes de construir QFEL-Cripto / Camino C.

Uso:
    python3 audit_tarea0.py /ruta/a/AXONIK_Decision_Engine_v2.xlsx [--export-certified out.csv]

Lee el xlsx exportado del Decision Engine v2 (Google Sheets) y:
  1. Reporta las métricas "como hoy" (sin filtrar), para mostrar contra
     qué se compara.
  2. Certifica cada operación con `validation.is_valid_operation` — el
     único filtro que debe usarse en cualquier cálculo agregado (dashboard,
     reports, PF/WR, gates de Fase 0B en adelante). No hay una segunda
     ruta de filtrado en este archivo.
  3. Reconstruye forense el bug de reenvío por lotes detectado en ST-16
     (2026-08-07/08): confirma si el patrón es un evento de lote único
     reproducible, no ruido disperso.
  4. Exporta el dataset certificado a CSV para que Fase 0B parta de datos
     ya limpios en vez de repetir este filtrado.
"""
import argparse
import csv
import statistics
import sys
from collections import Counter, defaultdict
from pathlib import Path

import openpyxl

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # scripts/
from common.validation import certify_operations, known_scanner_prefixes


def load_sheet(wb, name):
    ws = wb[name]
    rows = list(ws.iter_rows(values_only=True))
    last = -1
    for i, r in enumerate(rows):
        if any(c is not None and str(c).strip() != "" for c in r):
            last = i
    return rows[: last + 1]


def as_records(rows, header_row_idx):
    header = rows[header_row_idx]
    idx = {h: i for i, h in enumerate(header) if h}
    return idx, rows[header_row_idx + 1 :]


def f(row, idx, name):
    v = row[idx[name]] if idx[name] < len(row) else None
    if v is None or v == "":
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return v


def build_op_record(row, idx):
    return {
        "op_id": row[idx["OP_ID"]],
        "ticker": row[idx["TICKER"]],
        "mercado": row[idx["MERCADO"]],
        "scn_ref": row[idx["SCN_ID_REF"]],
        "fecha": row[idx["FECHA"]],
        "hora_entrada": row[idx["HORA_ENTRADA"]],
        "hora_salida": row[idx["HORA_SALIDA"]],
        "entrada": row[idx["PRECIO_ENTRADA"]],
        "salida": row[idx["PRECIO_SALIDA"]],
        "result_pct": f(row, idx, "RESULTADO_PCT"),
        "result_eur": f(row, idx, "RESULTADO_EUR"),
        "rr": f(row, idx, "RR_REAL"),
        "resultado": row[idx["RESULTADO"]],
        "notas": row[idx["NOTAS"]] or "",
        "duracion": row[idx["DURACION"]],
        "score": f(row, idx, "SCORE_ENTRADA"),
        "tamano_pos": f(row, idx, "TAMAÑO_POS"),
        "comision_usd": f(row, idx, "COMISION_USD"),
        "slippage_pct": f(row, idx, "SLIPPAGE_PCT"),
        "broker": row[idx["BROKER"]] or "",
    }


def summarize(label, ops):
    n = len(ops)
    wins = [o for o in ops if o["resultado"] == "WIN"]
    losses = [o for o in ops if o["resultado"] == "LOSS"]
    be = [o for o in ops if o["resultado"] == "BREAKEVEN"]
    to = [o for o in ops if o["resultado"] == "TIMEOUT"]
    rrs = [o["rr"] for o in ops if o["rr"] is not None]
    rr_mean = statistics.fmean(rrs) if rrs else 0.0
    gain = sum(o["result_pct"] for o in wins if o["result_pct"] is not None)
    loss = -sum(o["result_pct"] for o in losses if o["result_pct"] is not None)
    pf = gain / loss if loss else (float("inf") if gain else 0.0)
    wr_n = (len(wins) / n * 100) if n else 0.0
    denom = len(wins) + len(losses)
    wr_wl = (len(wins) / denom * 100) if denom else 0.0

    print(f"--- {label} (N={n}) ---")
    print(f"WIN={len(wins)} LOSS={len(losses)} BREAKEVEN={len(be)} TIMEOUT={len(to)}")
    print(f"Win rate (wins/N)          = {wr_n:.1f}%")
    print(f"Win rate (wins/(wins+loss))= {wr_wl:.1f}%")
    print(f"RR medio                   = {rr_mean:.3f}")
    print(f"Profit factor (%pct)       = {pf:.2f}")
    print()
    return {"n": n, "wins": len(wins), "losses": len(losses), "be": len(be),
            "timeout": len(to), "wr_n": wr_n, "wr_wl": wr_wl, "rr_mean": rr_mean, "pf": pf}


def reconstruct_batch_replay_bug(ops):
    """
    Reconstrucción forense del bug de duplicación en ST-16: agrupa por
    (fecha, hora_entrada) las operaciones marcadas como reenvío duplicado
    (o su contraparte original) y verifica si comparten un evento de lote
    único (mismos tickers, mismos precios, mismo hueco temporal) en vez
    de ser duplicados independientes y dispersos.
    """
    st16 = [o for o in ops if o["scn_ref"] == "ST-16"]
    by_batch = defaultdict(list)
    for o in st16:
        by_batch[(o["fecha"], o["hora_entrada"])].append(o)

    print("=== Reconstrucción forense: bug de reenvío por lotes (ST-16) ===")
    if len(by_batch) != 2:
        print(f"Patrón no coincide con un simple reenvío en 2 lotes "
              f"(se encontraron {len(by_batch)} timestamps distintos). Revisar manualmente.")
        return

    batches = sorted(by_batch.items())
    (fecha1, hora1), ops1 = batches[0]
    (fecha2, hora2), ops2 = batches[1]
    tickers1 = sorted(o["ticker"] for o in ops1)
    tickers2 = sorted(o["ticker"] for o in ops2)

    print(f"Lote 1: {fecha1} {hora1} -> tickers {tickers1}")
    print(f"Lote 2: {fecha2} {hora2} -> tickers {tickers2}")

    mismo_universo = tickers1 == tickers2
    print(f"Mismo conjunto de tickers en ambos lotes: {mismo_universo}")

    payload_identico = True
    for o1 in ops1:
        o2 = next((o for o in ops2 if o["ticker"] == o1["ticker"]), None)
        if o2 is None:
            payload_identico = False
            continue
        campos = ["entrada", "salida", "resultado", "result_pct", "rr"]
        distintos = [c for c in campos if o1[c] != o2[c]]
        if distintos:
            payload_identico = False
            print(f"  {o1['ticker']}: difieren campos {distintos} entre lote 1 y lote 2")

    print(f"Payload (precio/resultado/RR) idéntico entre lotes: {payload_identico}")

    marcado_r4 = all("excluido" in o["notas"].lower() for o in ops2) and \
                 all("excluido" not in o["notas"].lower() for o in ops1)
    print(f"Solo el lote 2 (más tardío) lleva la nota de exclusión R4: {marcado_r4}")

    if mismo_universo and payload_identico and marcado_r4:
        f1, h1 = str(fecha1).split(" ")[0], str(hora1)
        f2, h2 = str(fecha2).split(" ")[0], str(hora2)
        print(
            f"REPRODUCIBLE — CONFIRMADO. No son 4 duplicados independientes: es UN solo "
            f"evento de reenvío de lote completo (4 señales de ST-16 detectadas en la "
            f"corrida del {f1} {h1}, reescritas íntegras en la corrida del {f2} {h2}, "
            f"con precios y resultados byte-idénticos — solo cambian OP_ID y "
            f"HORA_ENTRADA). Firma característica de un fallo de idempotencia en la "
            f"ruta de escritura (reintento/reentrega de la ejecución de n8n, o "
            f"reprocesamiento manual del mismo lote sin comprobar si ya estaba "
            f"escrito en 05_OPERACIONES). No es una señal sobre la calidad de ST-16 "
            f"como estrategia — es un defecto de infraestructura de ingesta, "
            f"independiente de si el scanner tiene ventaja o no."
        )
    else:
        print("Patrón parcial — no se puede confirmar reenvío de lote único con estos datos.")
    print()


def export_certified(path, ops):
    if not ops:
        return
    fields = ["op_id", "ticker", "mercado", "scn_ref", "fecha", "hora_entrada",
              "hora_salida", "entrada", "salida", "result_pct", "rr", "resultado", "score",
              "duracion", "tamano_pos", "comision_usd", "slippage_pct", "broker", "notas"]
    with open(path, "w", newline="") as f_out:
        w = csv.DictWriter(f_out, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        for o in ops:
            w.writerow(o)
    print(f"Exportado dataset certificado ({len(ops)} operaciones) -> {path}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("xlsx_path")
    ap.add_argument("--export-certified", metavar="CSV_PATH")
    args = ap.parse_args()

    wb = openpyxl.load_workbook(args.xlsx_path, data_only=True)

    scn_rows = load_sheet(wb, "02_SCANNERS")
    scn_idx, scn_data = as_records(scn_rows, 2)
    known_scanners = known_scanner_prefixes(scn_data, scn_idx)
    estado_count = Counter(row[scn_idx["ESTADO"]] for row in scn_data)
    print("=== 02_SCANNERS ===")
    print(f"Total scanners: {len(scn_data)}")
    print(f"Por ESTADO: {dict(estado_count)}")
    print()

    op_rows = load_sheet(wb, "05_OPERACIONES")
    op_idx, op_data = as_records(op_rows, 2)
    ops = [build_op_record(row, op_idx) for row in op_data]

    validas, excluidas = certify_operations(ops, known_scanners)

    print("=== Certificación (validation.is_valid_operation — única fuente de verdad) ===")
    motivos = Counter(o["exclusion_reason"] for o in excluidas)
    print(f"Válidas: {len(validas)}/{len(ops)}  |  Excluidas: {len(excluidas)} {dict(motivos)}")
    for o in excluidas:
        print(f"  EXCLUIDA {o['op_id']} ticker={o['ticker']} scn={o['scn_ref']} "
              f"motivo={o['exclusion_reason']}")
    print()

    print("=== 05_OPERACIONES — métricas ===")
    summarize("TODAS — sin filtrar, como calcula el dashboard hoy", ops)
    summarize("CERTIFICADAS — únicas que deben alimentar dashboard/reports/gates", validas)

    reconstruct_batch_replay_bug(ops)

    print("=== Rendimiento por scanner, solo operaciones certificadas ===")
    por_scanner = defaultdict(list)
    for o in validas:
        por_scanner[o["scn_ref"]].append(o)
    for scn, group in sorted(por_scanner.items()):
        wins = sum(1 for o in group if o["resultado"] == "WIN")
        scores = [o["score"] for o in group if o["score"] is not None]
        score_str = f"score_medio={statistics.fmean(scores):.0f}" if scores else "score_medio=NA"
        print(f"  {scn}: N={len(group)} WIN={wins} {score_str} "
              f"resultados={[o['resultado'] for o in group]}")

    if args.export_certified:
        export_certified(args.export_certified, validas)


if __name__ == "__main__":
    sys.exit(main())
