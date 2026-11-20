<?php
declare(strict_types=1);

require_once __DIR__ . '/metrics.php';

/**
 * Importa un paquete "optimum-readings-v1" que manda el orquestador:
 *
 *   {
 *     "format": "optimum-readings-v1",
 *     "nis": "1379190",
 *     "period_start": "2026-11-01", "period_end": "2026-11-20",
 *     "unit": "W", "meter": "EGM4026367", "channel": "...", "source_file": "...",
 *     "readings": [["2026-11-01 00:00", 310.44, "Correcto"], ["2026-11-01 05:15", null, "Hueco"], ...]
 *   }
 *
 * Es idempotente: reenviar el mismo período reemplaza las lecturas (sirve para
 * rellenar huecos). Un valor real nunca se pisa con un hueco posterior.
 *
 * @return array<string,mixed>
 */
function import_readings_payload(array $payload, ?int $tokenId = null): array
{
    if (($payload['format'] ?? '') !== 'optimum-readings-v1') {
        throw new InvalidArgumentException('Formato de paquete no compatible (se espera optimum-readings-v1).');
    }
    $nis = trim((string) ($payload['nis'] ?? ''));
    if ($nis === '') {
        throw new InvalidArgumentException('Falta el NIS.');
    }
    foreach (['period_start', 'period_end'] as $campo) {
        $d = DateTimeImmutable::createFromFormat('!Y-m-d', (string) ($payload[$campo] ?? ''));
        if (!$d || $d->format('Y-m-d') !== (string) $payload[$campo]) {
            throw new InvalidArgumentException("{$campo} debe tener formato AAAA-MM-DD.");
        }
    }
    $readings = $payload['readings'] ?? null;
    if (!is_array($readings) || !$readings) {
        throw new InvalidArgumentException('El paquete no trae lecturas.');
    }
    if (count($readings) > 200000) {
        throw new LengthException('Demasiadas lecturas en un solo envío (máximo 200.000).');
    }
    $aW = match (strtolower(trim((string) ($payload['unit'] ?? 'W')))) {
        'w', '' => 1.0,
        'kw' => 1000.0,
        'mw' => 1000000.0,
        default => throw new InvalidArgumentException('Unidad desconocida: ' . $payload['unit']),
    };

    $stmt = db()->prepare('SELECT * FROM supplies WHERE nis = ? LIMIT 1');
    $stmt->execute([$nis]);
    $supply = $stmt->fetch();
    if (!$supply) {
        throw new InvalidArgumentException("El NIS {$nis} no está dado de alta en el panel.");
    }
    $supplyId = (int) $supply['id'];
    if (!supply_contracts($supplyId)) {
        throw new InvalidArgumentException("El NIS {$nis} no tiene cargada la potencia contratada / factor.");
    }

    // Validar y normalizar todas las filas antes de tocar la base.
    $filas = [];
    $periodos = [];
    foreach ($readings as $i => $r) {
        if (!is_array($r) || count($r) < 2) {
            throw new InvalidArgumentException("Lectura #{$i} mal formada.");
        }
        $ts = DateTimeImmutable::createFromFormat('!Y-m-d H:i', substr((string) $r[0], 0, 16));
        if (!$ts) {
            throw new InvalidArgumentException("Lectura #{$i}: fecha inválida ({$r[0]}).");
        }
        $valor = $r[1];
        if ($valor !== null && !is_numeric($valor)) {
            throw new InvalidArgumentException("Lectura #{$i}: valor no numérico.");
        }
        $estado = substr(trim((string) ($r[2] ?? '')), 0, 30);
        $filas[] = [$ts->format('Y-m-d H:i:00'), $valor === null ? null : (float) $valor * $aW, $estado];
        $periodos[$ts->format('Y-m')] = true;
    }

    $tsMin = min(array_column($filas, 0));
    $tsMax = max(array_column($filas, 0));
    $contar = db()->prepare('SELECT COUNT(*) FROM readings WHERE supply_id = ? AND ts BETWEEN ? AND ?');
    $afectadas = 0;
    db()->beginTransaction();
    try {
        $contar->execute([$supplyId, $tsMin, $tsMax]);
        $antes = (int) $contar->fetchColumn();
        foreach (array_chunk($filas, 500) as $lote) {
            $sql = 'INSERT INTO readings (supply_id, ts, raw_value, status) VALUES '
                . rtrim(str_repeat('(?,?,?,?),', count($lote)), ',')
                . ' ON DUPLICATE KEY UPDATE
                    status = IF(VALUES(raw_value) IS NULL AND raw_value IS NOT NULL, status, VALUES(status)),
                    raw_value = IF(VALUES(raw_value) IS NULL, raw_value, VALUES(raw_value))';
            $params = [];
            foreach ($lote as [$ts, $valor, $estado]) {
                array_push($params, $supplyId, $ts, $valor, $estado);
            }
            $st = db()->prepare($sql);
            $st->execute($params);
            // MySQL cuenta 1 por fila nueva, 2 por fila modificada y 0 si quedó igual.
            $afectadas += $st->rowCount();
        }
        $contar->execute([$supplyId, $tsMin, $tsMax]);
        $insertados = (int) $contar->fetchColumn() - $antes;
        $actualizados = max(0, intdiv($afectadas - $insertados, 2));
        if (!empty($payload['meter']) && $supply['meter_serial'] !== $payload['meter']) {
            db()->prepare('UPDATE supplies SET meter_serial = ? WHERE id = ?')
                ->execute([substr((string) $payload['meter'], 0, 40), $supplyId]);
        }

        $resumenes = [];
        foreach (array_keys($periodos) as $period) {
            $resumenes[$period] = recompute_month($supplyId, $period);
        }
        $pend = db()->prepare('SELECT COUNT(*) FROM alerts WHERE supply_id = ? AND notified_at IS NULL');
        $pend->execute([$supplyId]);
        $alertasNuevas = (int) $pend->fetchColumn();

        db()->prepare(
            'INSERT INTO import_runs (supply_id, token_id, period_start, period_end, readings_count,
                inserted_count, updated_count, new_alerts, meter, channel, source_file)
             VALUES (?,?,?,?,?,?,?,?,?,?,?)'
        )->execute([
            $supplyId, $tokenId, $payload['period_start'], $payload['period_end'], count($filas),
            $insertados, $actualizados, $alertasNuevas,
            isset($payload['meter']) ? substr((string) $payload['meter'], 0, 40) : null,
            isset($payload['channel']) ? substr((string) $payload['channel'], 0, 190) : null,
            isset($payload['source_file']) ? substr((string) $payload['source_file'], 0, 190) : null,
        ]);
        db()->commit();
    } catch (Throwable $e) {
        db()->rollBack();
        throw $e;
    }

    // El correo va fuera de la transacción: si falla, las lecturas ya quedaron guardadas.
    $avisadas = notify_pending_alerts($supplyId);

    $ultimo = end($resumenes);
    return [
        'nis' => $nis,
        'readings' => count($filas),
        'inserted' => $insertados,
        'updated' => $actualizados,
        'periods' => array_keys($periodos),
        'new_alerts' => $alertasNuevas,
        'mailed_alerts' => $avisadas,
        'status' => $ultimo['status'] ?? null,
        'max_kw' => $ultimo['max_kw'] ?? null,
        'limit_kw' => $ultimo['limit_kw'] ?? null,
    ];
}
