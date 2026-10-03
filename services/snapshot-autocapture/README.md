# Captura automática de snapshots — despliegue

**Estado: NO DESPLEGADO.** Implementación real, lista para revisión. No tocar
el servidor hasta que se apruebe aquí, igual que con el fix de idempotencia
(`docs/pipeline/2026-09-22_fix_idempotencia_ingesta.md`).

Diseño completo: `docs/pipeline/2026-10-03_automatizacion_captura_snapshots.md`.
Bloqueante de "¿hace falta Playwright?" cerrado: `detectAutoTrigger()`,
`evaluateTicker()`, `NYSE_STRATEGIES`, `CRYPTO_STRATEGIES`,
`applyEventAdjustments` y `tickerHardNo` son aritmética/orquestación pura
sobre datos, sin DOM ni dependencia de navegador (verificado con
`docs/pipeline/check_autocapture_triggers.sh`).

## Estado tras la Pregunta 4 — 3 corregidos, 1 gap real bloqueante

Los tres puntos que eran estimación ya se confirmaron contra el código
real y están corregidos en `snapshot_autocapture.py`:

1. Shape de `POST /api/scan-batch` — corregido: `{"results": [{"ticker",
   "timestamp", "data", "error"?}]}`, con el `"error"` por-ticker manejado
   como omisión, no como fallo del batch.
2. `risk_pct` — **era incorrecto**, el campo real es `risk_per_share`.
3. Umbral de `detectAutoTrigger()` — corregido a las dos ramas reales
   (`AUTO_HIGH` score≥90 individual, `AUTO_MULTI` ≥2 estrategias del mismo
   `temporal_group` con score≥80 cada una — "mismo grupo" es una lectura,
   no una cita literal, confirmar si hace falta certeza total).

**Gap real descubierto al corregir el punto 1, no uno de los tres
originales: el cálculo del score (`evaluateTicker()` + `NYSE_STRATEGIES`/
`CRYPTO_STRATEGIES` + `applyEventAdjustments` + `tickerHardNo`) nunca se
portó a Python.** El shape real de `scan-batch` ("data" = indicadores en
bruto) demuestra que la asunción anterior (un `"score"` ya calculado en la
respuesta) era sencillamente incorrecta. `evaluate_ticker()` es ahora un
`NotImplementedError` explícito — verificado que el script falla ruidoso
en el primer ticker real en vez de fingir un resultado.

**Por esto el protocolo de verificación contra el servidor real (paso 3
más abajo) todavía no está escrito.** Ejecutarlo hoy fallaría de
inmediato en `evaluate_ticker()`. Antes de eso hace falta portar esa
función con los **cuerpos literales** de las cinco piezas — no otro
resumen en prosa, por la misma razón que `risk_per_share` ya se perdió en
una paráfrasis.

La forma de cerrarlos es la misma que ya ha funcionado en todo este diseño:
extender `docs/pipeline/check_autocapture_triggers.sh` (sección "Pregunta 4",
pendiente de añadir) para extraer el modelo Pydantic real de `create_snapshot`
y la firma de `scan_batch`, en vez de asumir los nombres de campo.

## Paso 1 — bind del proxy a 127.0.0.1 (BACKLOG entrada 2, ALTA)

Línea actual confirmada en `market_data_proxy.py` (DOC-IDEM, Hallazgo 4):

```python
uvicorn.run(app, host="0.0.0.0", port=8002)
```

Cambio:

```python
uvicorn.run(app, host="127.0.0.1", port=8002)
```

Es la opción preferida del diseño (§3.4): el proceso de captura corre en el
mismo host, no necesita red, y esto resuelve el hallazgo 2 del backlog sin
necesidad del token bearer — no hace falta autenticar tráfico que nunca sale
del host.

**Efecto colateral a tener en cuenta:** si hoy accedes a `/scanner` desde un
navegador fuera del propio Hetzner, dejará de ser alcanzable directamente.
Si todavía lo necesitas, hace falta un túnel SSH o un reverse proxy con su
propia autenticación antes de aplicar este cambio — decisión tuya, no la
asumo.

### Despliegue del bind

```bash
cp /opt/axonik/scripts/market_data_proxy.py /opt/axonik/scripts/market_data_proxy.py.bak.$(date +%Y%m%d_%H%M%S)
sha256sum /opt/axonik/scripts/market_data_proxy.py  # anotar antes de tocar nada

sed -i 's/host="0\.0\.0\.0", port=8002/host="127.0.0.1", port=8002/' /opt/axonik/scripts/market_data_proxy.py
python3 -m py_compile /opt/axonik/scripts/market_data_proxy.py

systemctl restart axonik-market-proxy
# Anotar T0, igual que en el Addendum 4 del fix de idempotencia.
```

### Verificación del bind

```bash
# Debe mostrar 127.0.0.1:8002, no 0.0.0.0:8002
ss -tlnp | grep 8002

# Desde el propio host, debe seguir respondiendo:
curl -s http://127.0.0.1:8002/api/health

# Desde fuera del host (otra máquina, o un curl con -4 a la IP pública),
# debe fallar con connection refused, no con un 200/404:
curl -sS --max-time 5 http://89.167.80.58:8002/api/health || echo "rechazado, como se espera"
```

Si todo lo anterior pasa, registrar el resultado como addendum en
`docs/pipeline/2026-10-03_automatizacion_captura_snapshots.md`, igual que el
Addendum 4 del otro documento.

## Paso 2 — instalar el script y las units (bloqueado: falta portar `evaluate_ticker()`, ver arriba)

```bash
cp snapshot_autocapture.py /opt/axonik/scripts/snapshot_autocapture.py
chmod +x /opt/axonik/scripts/snapshot_autocapture.py

mkdir -p /etc/axonik
cat > /etc/axonik/autocapture.env <<'EOF'
AXONIK_DECISION_ENGINE_SHEET_ID=<id real de la hoja — confirmar, no inventar>
AXONIK_PROXY_BASE=http://127.0.0.1:8002
EOF
chmod 600 /etc/axonik/autocapture.env

cp axonik-snapshot-autocapture.service axonik-snapshot-autocapture.timer /etc/systemd/system/
systemctl daemon-reload
```

**No habilitar el timer todavía** (`systemctl enable --now axonik-snapshot-autocapture.timer`)
— primero la verificación del paso 3.

## Paso 3 — verificación obligatoria antes de habilitar el timer

Mismo estándar que el protocolo de ST-16 (DOC-IDEM, Addendum 3 §1.4 y
Addendum 4): nada de "está desplegado" sin "está verificado".

```bash
# 1. Dry-run: no hace ningún POST, solo registra qué habría enviado.
#    Revisar que el universo de scanners y el payload tengan sentido.
python3 /opt/axonik/scripts/snapshot_autocapture.py --dry-run --force-window

# 2. Una sola vez, sin --dry-run, fuera de la franja de los timers del
#    evaluador (16:00-22:00 L-V, 18:30 todos los días) y con un ticker de
#    prueba si es posible (ZZTEST), confirmar la respuesta real:
python3 /opt/axonik/scripts/snapshot_autocapture.py --force-window

# 3. Confirmar en Postgres que la fila de prueba se creó con el hash v2
#    (Hallazgo 1 de DOC-IDEM) y limpiarla:
#    SELECT id, ticker, signal_hash, created_at FROM signal_snapshots
#      WHERE ticker = 'ZZTEST' ORDER BY id DESC LIMIT 5;
#    DELETE FROM signal_snapshots WHERE ticker = 'ZZTEST';

# 4. Solo entonces, habilitar el timer:
systemctl enable --now axonik-snapshot-autocapture.timer
systemctl list-timers axonik-snapshot-autocapture.timer
```

Registrar el resultado de estos 4 pasos como addendum en el documento de
diseño antes de considerar esto cerrado — igual que con el hallazgo 1.
