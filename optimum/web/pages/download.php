<?php
declare(strict_types=1);

/* Excel con las lecturas de 15 minutos de un mes (requiere permiso de descarga). */
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

$contratos = supply_contracts($id);
$serie = month_series($id, $period, $contratos);
if (!$serie) {
    not_found('No hay lecturas de ' . mes_texto($period) . '.');
}
$q = db()->prepare('SELECT * FROM monthly_summaries WHERE supply_id = ? AND period = ?');
$q->execute([$id, $period]);
$r = $q->fetch();

$estados = ['normal' => 'Normal', 'atencion' => 'Sobre la contratada', 'critico' => 'Supera la tolerancia'];
$filas = (static function () use ($serie, $contratos, $estados) {
    foreach ($serie as $p) {
        $c = contract_for($contratos, substr($p['ts'], 0, 10));
        yield [
            $p['ts'],
            $p['raw'],
            $c ? (float) $c['factor'] : null,
            $p['kw'] === null ? null : round($p['kw'], 3),
            $p['kw'] === null ? null : round($p['kw'] * INTERVAL_HOURS, 3),
            $c ? (float) $c['contracted_kw'] : null,
            $c ? round(contract_limit($c), 2) : null,
            $p['kw'] === null ? 'Sin lectura' : ($estados[$p['estado']] ?? ''),
            $p['status'],
        ];
    }
})();

$usuario = Auth::user();
$ruta = build_table_xlsx('Perfil ' . $period, [
    ['label' => 'Fecha y hora', 'type' => 'datetime', 'width' => 18],
    ['label' => 'Valor medidor (W)', 'type' => 'number', 'width' => 16],
    ['label' => 'Factor', 'type' => 'number', 'width' => 11],
    ['label' => 'Demanda (kW)', 'type' => 'number', 'width' => 14],
    ['label' => 'Energía (kWh)', 'type' => 'number', 'width' => 14],
    ['label' => 'Contratada (kW)', 'type' => 'number', 'width' => 15],
    ['label' => 'Límite (kW)', 'type' => 'number', 'width' => 13],
    ['label' => 'Estado', 'type' => 'text', 'width' => 22],
    ['label' => 'Lectura Optimum', 'type' => 'text', 'width' => 16],
], $filas, [
    "{$s['name']} · NIS {$s['nis']} · Medidor " . ($s['meter_serial'] ?: '—'),
    'Período: ' . mes_texto($period) . ' · Máxima: ' . num($r['max_kw'] ?? null, 1) . ' kW (' . fecha_hora($r['max_ts'] ?? null) . ')'
        . ' · Límite: ' . num($r['limit_kw'] ?? null) . ' kW',
    'kW = valor del medidor (W) × factor ÷ 1000 · Generado por ' . ($usuario['username'] ?? '') . ' el ' . date('d/m/Y H:i'),
]);
audit('download.readings', 'supply', (string) $id, ['period' => $period]);
stream_xlsx_download($ruta, "perfil_{$s['nis']}_{$period}.xlsx");
