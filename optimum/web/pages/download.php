<?php
declare(strict_types=1);

/* Excel con las lecturas de 15 minutos de un ciclo (requiere permiso de descarga). */
require_once __DIR__ . '/../app/xlsx_builder.php';

$id = (int) ($_GET['id'] ?? 0);
$period = (string) ($_GET['period'] ?? '');
if (!preg_match('/^\d{4}-\d{2}$/', $period)) {
    not_found('Período inválido.');
}
$stmt = db()->prepare('SELECT * FROM supplies WHERE id = ?');
$stmt->execute([$id]);
$s = $stmt->fetch();
if (!$s) {
    not_found();
}
if (!Auth::canSupply($id, true)) {
    forbidden();
}

$billing = $s['billing_day'] === null ? null : (int) $s['billing_day'];
$contratos = supply_contracts($id);
$serie = month_series($id, $period, $contratos);
if (!$serie) {
    not_found('No hay lecturas ' . period_phrase($billing, $period) . '.');
}
$q = db()->prepare('SELECT * FROM monthly_summaries WHERE supply_id = ? AND period = ?');
$q->execute([$id, $period]);
$r = $q->fetch();

$estados = ['normal' => 'Normal', 'atencion' => 'Sobre la contratada', 'critico' => 'Supera la tolerancia'];
// Factor: el de la fecha de cada lectura. Contratada y límite: los del ciclo (vigentes en su cierre).
$c = cycle_contract($contratos, $billing, $period);
$filas = (static function () use ($serie, $contratos, $estados, $c) {
    foreach ($serie as $p) {
        $f = contract_for($contratos, substr($p['ts'], 0, 10));
        yield [
            $p['ts'],
            $p['raw'],
            $f ? (float) $f['factor'] : null,
            $p['kw'] === null ? null : round($p['kw'], 3),
            $p['kw'] === null ? null : round($p['kw'] * INTERVAL_HOURS, 3),
            $c ? (float) $c['contracted_kw'] : null,
            $c ? round(contract_limit($c), 2) : null,
            // Exceso de potencia: solo si superó el límite, y se cuenta desde la contratada.
            ($c && $p['kw'] !== null && $p['kw'] > contract_limit($c)) ? round($p['kw'] - (float) $c['contracted_kw'], 3) : null,
            $p['kw'] === null ? 'Sin lectura' : ($estados[$p['estado']] ?? ''),
            $p['status'],
        ];
    }
})();

$usuario = Auth::user();
$ruta = build_table_xlsx('Perfil ' . $period, [
    ['label' => 'Fecha y hora', 'type' => 'datetime', 'width' => 18],
    ['label' => 'Potencia medidor (W)', 'type' => 'number', 'width' => 18],
    ['label' => 'Factor', 'type' => 'number', 'width' => 11],
    ['label' => 'Demanda (kW)', 'type' => 'number', 'width' => 14],
    ['label' => 'Energía (kWh)', 'type' => 'number', 'width' => 14],
    ['label' => 'Contratada (kW)', 'type' => 'number', 'width' => 15],
    ['label' => 'Límite (kW)', 'type' => 'number', 'width' => 13],
    ['label' => 'Exceso de potencia (kW)', 'type' => 'number', 'width' => 20],
    ['label' => 'Estado', 'type' => 'text', 'width' => 22],
    ['label' => 'Lectura MDC', 'type' => 'text', 'width' => 16],
], $filas, [
    "{$s['name']} · NIS {$s['nis']} · Medidor " . ($s['meter_serial'] ?: '—'),
    'Período: ' . period_label($billing, $period) . ' · Máxima: ' . num($r['max_kw'] ?? null, 1) . ' kW (' . fecha_hora($r['max_ts'] ?? null) . ')'
        . ' · Límite: ' . num($r['limit_kw'] ?? null) . ' kW',
    'kW = potencia del medidor (W) × factor ÷ 1000 (medidores que registran Wh por intervalo: W = Wh × 4) · Generado por ' . ($usuario['username'] ?? '') . ' el ' . date('d/m/Y H:i'),
]);
audit('download.readings', 'supply', (string) $id, ['period' => $period]);
stream_xlsx_download($ruta, "perfil_{$s['nis']}_{$period}.xlsx");
