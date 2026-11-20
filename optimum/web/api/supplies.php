<?php
declare(strict_types=1);

/*
 * GET api/supplies.php  (Authorization: Bearer <token>)
 * Lista de suministros activos que el orquestador tiene que descargar.
 * Agregar un suministro en el panel alcanza: el script lo toma solo al día siguiente.
 */
require __DIR__ . '/../app/api.php';

if ($_SERVER['REQUEST_METHOD'] !== 'GET') {
    header('Allow: GET');
    api_response(405, ['ok' => false, 'error' => 'Método no permitido.']);
}
api_token();

$filas = db()->query(
    "SELECT s.nis, s.name, s.meter_prefix, s.channel,
            (SELECT MAX(r.ts) FROM readings r WHERE r.supply_id = s.id) AS last_reading,
            (SELECT COUNT(*) FROM supply_contracts c WHERE c.supply_id = s.id) AS contracts
     FROM supplies s WHERE s.active = 1 ORDER BY s.nis"
)->fetchAll();

$suministros = [];
foreach ($filas as $f) {
    $suministros[] = [
        'nis' => $f['nis'],
        'name' => $f['name'],
        'meter_prefix' => $f['meter_prefix'],
        'channel' => $f['channel'],
        'last_reading' => $f['last_reading'],
        'ready' => (int) $f['contracts'] > 0,   // sin contrato cargado no se puede importar
    ];
}
api_response(200, ['ok' => true, 'supplies' => $suministros]);
