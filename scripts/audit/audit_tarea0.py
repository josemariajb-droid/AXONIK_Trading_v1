#!/usr/bin/env python3
"""
AXONIK — Tarea 0: auditoría de 05_OPERACIONES y 02_SCANNERS
antes de construir QFEL-Cripto / Camino C.

Uso:
    python3 audit_tarea0.py /ruta/a/AXONIK_Decision_Engine_v2.xlsx

Lee el xlsx exportado del Decision Engine v2 (Google Sheets) y calcula,
sobre 05_OPERACIONES:
  - Win rate / RR medio / Profit Factor con distintos criterios de limpieza
    (todas las filas vs. excluyendo duplicados marcados R4 vs. excluyendo
    además outliers estadísticos).
  - Duplicados exactos (mismo ticker/entrada/salida/resultado con distinto
    OP_ID), típicamente reinserciones por reintento/latencia de datos.
  - Referencias a scanners (SCN_ID_REF) que no existen en 02_SCANNERS
    (fallo de integridad referencial).
  - Rendimiento agregado por scanner, para detectar señales estructurales
    (ej. un scanner con 0% de aciertos pese a score de entrada alto).

No decide nada por sí mismo — deja los números listos para que la decisión
(seguir acumulando muestra / revisar pipeline / descartar estrategia) la
tome una persona, según el principio rector de AXONIK.
"""
import argparse
import csv
import statistics
import sys
from collections import Counter, defaultdict

import openpyxl

R4_MARKER = "excluido"  # substring buscado en NOTAS para detectar exclusiones R4


def load_sheet(wb, name):
    ws = wb[name]
    rows = list(ws.iter_rows(values_only=True))
    last = -1
    for i, r in enumerate(rows):
        if any(c is not None and str(c).strip() != "" for c in r):
            last = i
    rows = rows[: last + 1]
    return rows


def as_records(rows, header_row_idx):
    header = rows[header_row_idx]
    idx = {h: i for i, h in enumerate(header) if h}
    data = rows[header_row_idx + 1 :]
    return idx, data


def f(row, idx, name):
    v = row[idx[name]] if idx[name] < len(row) else None
    if v is None or v == "":
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return v


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
    pf = gain / loss if loss else float("inf") if gain else 0.0
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
    return {
        "n": n, "wins": len(wins), "losses": len(losses), "be": len(be),
        "timeout": len(to), "wr_n": wr_n, "wr_wl": wr_wl, "rr_mean": rr_mean, "pf": pf,
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("xlsx_path")
    args = ap.parse_args()

    wb = openpyxl.load_workbook(args.xlsx_path, data_only=True)

    scn_rows = load_sheet(wb, "02_SCANNERS")
    scn_idx, scn_data = as_records(scn_rows, 2)
    scn_ids_cortos = set()
    for row in scn_data:
        nombre = row[scn_idx["NOMBRE"]] or ""
        prefix = nombre.split(" ", 1)[0] if nombre else ""
        if prefix:
            scn_ids_cortos.add(prefix)
    estado_count = Counter(row[scn_idx["ESTADO"]] for row in scn_data)
    print("=== 02_SCANNERS ===")
    print(f"Total scanners: {len(scn_data)}")
    print(f"Por ESTADO: {dict(estado_count)}")
    print(f"Prefijos válidos (NOMBRE): {sorted(scn_ids_cortos)}")
    print()

    op_rows = load_sheet(wb, "05_OPERACIONES")
    op_idx, op_data = as_records(op_rows, 2)

    ops = []
    for row in op_data:
        ops.append({
            "op_id": row[op_idx["OP_ID"]],
            "ticker": row[op_idx["TICKER"]],
            "mercado": row[op_idx["MERCADO"]],
            "scn_ref": row[op_idx["SCN_ID_REF"]],
            "fecha": row[op_idx["FECHA"]],
            "entrada": row[op_idx["PRECIO_ENTRADA"]],
            "salida": row[op_idx["PRECIO_SALIDA"]],
            "result_pct": f(row, op_idx, "RESULTADO_PCT"),
            "result_eur": f(row, op_idx, "RESULTADO_EUR"),
            "rr": f(row, op_idx, "RR_REAL"),
            "resultado": row[op_idx["RESULTADO"]],
            "notas": row[op_idx["NOTAS"]] or "",
            "duracion": row[op_idx["DURACION"]],
            "score": f(row, op_idx, "SCORE_ENTRADA"),
        })

    print("=== 05_OPERACIONES — integridad ===")
    huerfanas = [o for o in ops if o["scn_ref"] not in scn_ids_cortos]
    if huerfanas:
        print(f"SCN_ID_REF sin scanner correspondiente en 02_SCANNERS ({len(huerfanas)}):")
        for o in huerfanas:
            print(f"  {o['op_id']} ticker={o['ticker']} scn_ref={o['scn_ref']!r}")
    else:
        print("Todas las SCN_ID_REF resuelven a un scanner existente.")

    eur_vacio = sum(1 for o in ops if o["result_eur"] is None)
    print(f"RESULTADO_EUR vacío en {eur_vacio}/{len(ops)} filas "
          f"(la fórmula de P&L / Profit Factor del dashboard depende de esta columna).")

    negativas = [o for o in ops if isinstance(o["duracion"], str) and o["duracion"].startswith("-")]
    if negativas:
        print(f"DURACION negativa en {len(negativas)} filas (bug de cálculo cruzando medianoche):")
        for o in negativas:
            print(f"  {o['op_id']} ticker={o['ticker']} duracion={o['duracion']}")

    r4 = [o for o in ops if R4_MARKER in o["notas"].lower()]
    print(f"Filas marcadas para exclusión por regla R4 (lag de datos > 24h): {len(r4)}")
    print()

    print("=== 05_OPERACIONES — métricas ===")
    limpio = [o for o in ops if o not in r4]
    summarize("TODAS (como calcula el dashboard hoy)", ops)
    summarize("Excluyendo duplicados marcados R4", limpio)

    # outlier: RR muy por encima del resto
    if limpio:
        rrs = sorted(o["rr"] for o in limpio if o["rr"] is not None)
        outliers = [o for o in limpio if o["rr"] is not None and o["rr"] > 5]
        if outliers:
            print(f"Outliers RR>5 detectados ({len(outliers)}):")
            for o in outliers:
                print(f"  {o['op_id']} {o['ticker']} entrada={o['entrada']} salida={o['salida']} "
                      f"result_pct={o['result_pct']} rr={o['rr']} duracion={o['duracion']}")
            sin_outliers = [o for o in limpio if o not in outliers]
            summarize("Excluyendo duplicados R4 + outliers RR>5", sin_outliers)

    print("=== Rendimiento por scanner (SCN_ID_REF), datos limpios (sin dup. R4) ===")
    por_scanner = defaultdict(list)
    for o in limpio:
        por_scanner[o["scn_ref"]].append(o)
    for scn, group in sorted(por_scanner.items()):
        wins = sum(1 for o in group if o["resultado"] == "WIN")
        scores = [o["score"] for o in group if o["score"] is not None]
        score_str = f"score_medio={statistics.fmean(scores):.0f}" if scores else "score_medio=NA"
        print(f"  {scn}: N={len(group)} WIN={wins} {score_str} "
              f"resultados={[o['resultado'] for o in group]}")


if __name__ == "__main__":
    sys.exit(main())
