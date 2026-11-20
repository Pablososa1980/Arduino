<?php
declare(strict_types=1);

/*
 * Cálculos de potencia. Toda la lógica de "cuántos kW son" y "superó o no la
 * tolerancia" vive acá, para que la usen igual la importación, las pantallas,
 * la descarga Excel y el recálculo cuando cambia un contrato.
 *
 *   kW = valor del medidor (W, secundario) × factor ÷ 1000
 *   límite = potencia contratada × (1 + tolerancia)
 */

const INTERVAL_HOURS = 0.25;   // lecturas de 15 minutos

/** @return list<array<string,mixed>> Contratos del suministro, del más viejo al más nuevo. */
function supply_contracts(int $supplyId): array
{
    $stmt = db()->prepare('SELECT * FROM supply_contracts WHERE supply_id = ? ORDER BY valid_from');
    $stmt->execute([$supplyId]);
    return $stmt->fetchAll();
}

/**
 * Contrato vigente en una fecha (AAAA-MM-DD). Si la fecha es anterior al
 * primer contrato cargado, se usa el primero (mejor eso que no mostrar nada).
 *
 * @param list<array<string,mixed>> $contracts
 */
function contract_for(array $contracts, string $date): ?array
{
    $elegido = $contracts[0] ?? null;
    foreach ($contracts as $c) {
        if ((string) $c['valid_from'] <= $date) {
            $elegido = $c;
        } else {
            break;
        }
    }
    return $elegido;
}

function contract_limit(array $contract): float
{
    return (float) $contract['contracted_kw'] * (1 + (float) $contract['tolerance_pct'] / 100);
}

function kw_status(float $kw, array $contract): string
{
    if ($kw > contract_limit($contract)) {
        return 'critico';
    }
    return $kw > (float) $contract['contracted_kw'] ? 'atencion' : 'normal';
}

/**
 * Serie de un mes: cada lectura con su kW ya calculado con el contrato vigente.
 *
 * @return list<array{ts:string,kw:?float,status:string,raw:?float,estado:?string}>
 */
function month_series(int $supplyId, string $period, ?array $contracts = null): array
{
    $contracts ??= supply_contracts($supplyId);
    $desde = $period . '-01 00:00:00';
    $hasta = (new DateTimeImmutable($desde))->modify('+1 month')->format('Y-m-d H:i:s');
    $stmt = db()->prepare(
        'SELECT ts, raw_value, status FROM readings WHERE supply_id = ? AND ts >= ? AND ts < ? ORDER BY ts'
    );
    $stmt->execute([$supplyId, $desde, $hasta]);

    $serie = [];
    $cache = [];
    foreach ($stmt as $r) {
        $fecha = substr((string) $r['ts'], 0, 10);
        $contrato = $cache[$fecha] ??= contract_for($contracts, $fecha);
        $hueco = $r['raw_value'] === null || strcasecmp((string) $r['status'], 'Hueco') === 0;
        $kw = ($hueco || !$contrato) ? null : (float) $r['raw_value'] * (float) $contrato['factor'] / 1000;
        $serie[] = [
            'ts' => (string) $r['ts'],
            'kw' => $kw,
            'raw' => $r['raw_value'] === null ? null : (float) $r['raw_value'],
            'status' => (string) $r['status'],
            'estado' => ($kw === null || !$contrato) ? null : kw_status($kw, $contrato),
        ];
    }
    return $serie;
}

/**
 * Recalcula el resumen de un mes y sincroniza sus alertas.
 * $silencioso = true: las alertas nuevas quedan como ya avisadas (se usa al
 * recalcular por un cambio de contrato, para no mandar correos de meses viejos).
 *
 * @return array<string,mixed> El resumen guardado.
 */
function recompute_month(int $supplyId, string $period, bool $silencioso = false): array
{
    $contracts = supply_contracts($supplyId);
    $serie = month_series($supplyId, $period, $contracts);

    $max = null;
    $energia = 0.0;
    $horas = 0.0;
    $huecos = 0;
    $sobreContratada = 0;
    $excesos = [];
    $diario = [];

    foreach ($serie as $p) {
        if ($p['kw'] === null) {
            $huecos++;
            continue;
        }
        $kw = $p['kw'];
        $contrato = contract_for($contracts, substr($p['ts'], 0, 10));
        $energia += $kw * INTERVAL_HOURS;
        $horas += INTERVAL_HOURS;
        if ($max === null || $kw > $max['kw']) {
            $max = $p;
        }
        if ($kw > (float) $contrato['contracted_kw']) {
            $sobreContratada++;
        }
        if ($kw > contract_limit($contrato)) {
            $excesos[] = [$p['ts'], $kw, (float) $contrato['contracted_kw'], contract_limit($contrato)];
        }
        $dia = substr($p['ts'], 0, 10);
        if (!isset($diario[$dia]) || $kw > $diario[$dia][1]) {
            $diario[$dia] = [$dia, round($kw, 1), substr($p['ts'], 11, 5), $p['estado']];
        }
    }

    $fin = (new DateTimeImmutable($period . '-01'))->modify('last day of this month')->format('Y-m-d');
    $contratoFin = $contracts ? contract_for($contracts, $fin) : null;
    $estado = $max === null ? 'sin_datos'
        : ($excesos ? 'critico' : ($sobreContratada ? 'atencion' : 'normal'));

    $resumen = [
        'supply_id' => $supplyId,
        'period' => $period,
        'first_ts' => $serie[0]['ts'] ?? null,
        'last_ts' => $serie ? $serie[count($serie) - 1]['ts'] : null,
        'readings_count' => count($serie),
        'gap_count' => $huecos,
        'max_kw' => $max ? round($max['kw'], 2) : null,
        'max_ts' => $max['ts'] ?? null,
        'avg_kw' => $horas > 0 ? round($energia / $horas, 2) : null,
        'energy_kwh' => $horas > 0 ? round($energia, 2) : null,
        'contracted_kw' => $contratoFin['contracted_kw'] ?? null,
        'limit_kw' => $contratoFin ? round(contract_limit($contratoFin), 2) : null,
        'tolerance_pct' => $contratoFin['tolerance_pct'] ?? null,
        'over_contract_count' => $sobreContratada,
        'over_limit_count' => count($excesos),
        'status' => $estado,
        'daily_json' => json_encode(array_values($diario), JSON_UNESCAPED_SLASHES),
    ];

    $cols = array_keys($resumen);
    $sql = 'INSERT INTO monthly_summaries (' . implode(',', $cols) . ') VALUES (' . rtrim(str_repeat('?,', count($cols)), ',') . ')
            ON DUPLICATE KEY UPDATE ' . implode(',', array_map(static fn ($c) => "{$c} = VALUES({$c})",
            array_diff($cols, ['supply_id', 'period'])));
    db()->prepare($sql)->execute(array_values($resumen));

    // Alertas: agregar las nuevas y quitar las que ya no corresponden
    // (por ejemplo, si se corrigió la potencia contratada).
    $desde = $period . '-01 00:00:00';
    $hasta = (new DateTimeImmutable($desde))->modify('+1 month')->format('Y-m-d H:i:s');
    $tsExcesos = array_map(static fn ($x) => $x[0], $excesos);
    $ins = db()->prepare(
        'INSERT INTO alerts (supply_id, ts, kw, contracted_kw, limit_kw, notified_at) VALUES (?, ?, ?, ?, ?, ?)
         ON DUPLICATE KEY UPDATE kw = VALUES(kw), contracted_kw = VALUES(contracted_kw), limit_kw = VALUES(limit_kw)'
    );
    foreach ($excesos as [$ts, $kw, $contratada, $limite]) {
        $ins->execute([$supplyId, $ts, round($kw, 2), $contratada, round($limite, 2), $silencioso ? date('Y-m-d H:i:s') : null]);
    }
    $existentes = db()->prepare('SELECT id, ts FROM alerts WHERE supply_id = ? AND ts >= ? AND ts < ?');
    $existentes->execute([$supplyId, $desde, $hasta]);
    $borrar = db()->prepare('DELETE FROM alerts WHERE id = ?');
    $vigentes = array_flip($tsExcesos);
    foreach ($existentes->fetchAll() as $a) {
        if (!isset($vigentes[(string) $a['ts']])) {
            $borrar->execute([(int) $a['id']]);
        }
    }
    return $resumen;
}

/** Recalcula todos los meses con lecturas de un suministro (tras cambiar un contrato). */
function recompute_supply(int $supplyId): int
{
    $stmt = db()->prepare(
        "SELECT DISTINCT DATE_FORMAT(ts, '%Y-%m') AS period FROM readings WHERE supply_id = ? ORDER BY period"
    );
    $stmt->execute([$supplyId]);
    $n = 0;
    foreach ($stmt->fetchAll(PDO::FETCH_COLUMN) as $period) {
        recompute_month($supplyId, (string) $period, true);
        $n++;
    }
    return $n;
}

/**
 * Envía por correo las alertas pendientes de un suministro a los usuarios que
 * tienen "recibir alertas" y pueden ver ese suministro. Devuelve cuántas se avisaron.
 */
function notify_pending_alerts(int $supplyId): int
{
    $stmt = db()->prepare('SELECT * FROM alerts WHERE supply_id = ? AND notified_at IS NULL ORDER BY ts');
    $stmt->execute([$supplyId]);
    $pendientes = $stmt->fetchAll();
    if (!$pendientes) {
        return 0;
    }
    $supply = db()->prepare('SELECT * FROM supplies WHERE id = ?');
    $supply->execute([$supplyId]);
    $s = $supply->fetch();

    $dest = db()->prepare(
        "SELECT DISTINCT u.email FROM users u
         LEFT JOIN user_supply_permissions p ON p.user_id = u.id AND p.supply_id = ?
         WHERE u.active = 1 AND u.receive_alerts = 1 AND u.email IS NOT NULL AND u.email <> ''
           AND (u.role = 'admin' OR p.supply_id IS NOT NULL)"
    );
    $dest->execute([$supplyId]);
    $correos = $dest->fetchAll(PDO::FETCH_COLUMN);

    $enviado = false;
    if ($correos && config('mail.enabled', false)) {
        $max = array_reduce($pendientes, static fn ($c, $a) => $c === null || $a['kw'] > $c['kw'] ? $a : $c);
        $asunto = sprintf('ALERTA potencia NIS %s: %s kW (límite %s kW)', $s['nis'], num($max['kw']), num($max['limit_kw']));
        $lineas = [
            "El suministro {$s['name']} (NIS {$s['nis']}) superó el límite de tolerancia de potencia.",
            '',
            'Intervalos nuevos sobre el límite: ' . count($pendientes),
        ];
        foreach (array_slice($pendientes, 0, 30) as $a) {
            $lineas[] = sprintf('  %s   %s kW   (límite %s kW, contratada %s kW)',
                fecha_hora($a['ts']), num($a['kw'], 1), num($a['limit_kw']), num($a['contracted_kw']));
        }
        if (count($pendientes) > 30) {
            $lineas[] = '  ... y ' . (count($pendientes) - 30) . ' más';
        }
        $base = rtrim((string) config('app.base_url', ''), '/');
        if ($base) {
            $lineas[] = '';
            $lineas[] = "Ver detalle: {$base}/index.php?page=supply&id={$supplyId}&period=" . substr((string) $max['ts'], 0, 7);
        }
        $desde = (string) config('mail.from', '');
        $cabeceras = [
            'From: ' . (config('mail.from_name') ? '"' . config('mail.from_name') . '" ' : '') . "<{$desde}>",
            'Content-Type: text/plain; charset=UTF-8',
            'Content-Transfer-Encoding: 8bit',
        ];
        $enviado = mail(implode(',', $correos), '=?UTF-8?B?' . base64_encode($asunto) . '?=',
            implode("\r\n", $lineas), implode("\r\n", $cabeceras), $desde ? "-f{$desde}" : '');
        audit($enviado ? 'alert.mail_sent' : 'alert.mail_failed', 'supply', (string) $supplyId,
            ['destinatarios' => count($correos), 'alertas' => count($pendientes)]);
    }
    // Se marcan como tratadas aunque no haya destinatarios o el correo esté
    // desactivado: así, al activarlo más adelante, no llega una avalancha vieja.
    $ids = array_map(static fn ($a) => (int) $a['id'], $pendientes);
    db()->prepare('UPDATE alerts SET notified_at = NOW() WHERE id IN (' . implode(',', $ids) . ')')->execute();
    return $enviado ? count($pendientes) : 0;
}
