<?php
declare(strict_types=1);

/*
 * POST api/readings-import.php  (Authorization: Bearer <token>, cuerpo JSON)
 * Recibe las lecturas de 15 minutos de un suministro (formato optimum-readings-v1).
 */
require __DIR__ . '/../app/api.php';
require __DIR__ . '/../app/importer.php';

if ($_SERVER['REQUEST_METHOD'] !== 'POST') {
    header('Allow: POST');
    api_response(405, ['ok' => false, 'error' => 'Método no permitido.']);
}
$token = api_token();

$payload = json_decode((string) file_get_contents('php://input'), true);
if (!is_array($payload)) {
    api_response(400, ['ok' => false, 'error' => 'El cuerpo debe ser JSON válido.']);
}

try {
    $resultado = import_readings_payload($payload, (int) $token['id']);
    api_response(200, ['ok' => true] + $resultado);
} catch (InvalidArgumentException $e) {
    api_response(422, ['ok' => false, 'error' => $e->getMessage()]);
} catch (LengthException $e) {
    api_response(413, ['ok' => false, 'error' => $e->getMessage()]);
} catch (Throwable $e) {
    error_log('[potencia] import: ' . $e->getMessage());
    api_response(500, ['ok' => false, 'error' => 'Error interno al importar: ' . $e->getMessage()]);
}
