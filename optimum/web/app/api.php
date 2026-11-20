<?php
declare(strict_types=1);

/* Utilidades comunes de los endpoints de la API (token Bearer, respuesta JSON). */

define('API_REQUEST', true);
require __DIR__ . '/bootstrap.php';

header('Content-Type: application/json; charset=utf-8');
header('Cache-Control: no-store');

function api_response(int $status, array $body): never
{
    http_response_code($status);
    echo json_encode($body, JSON_UNESCAPED_UNICODE | JSON_UNESCAPED_SLASHES);
    exit;
}

/** Valida el token Bearer y devuelve su fila de api_tokens. */
function api_token(): array
{
    $auth = (string) ($_SERVER['HTTP_AUTHORIZATION'] ?? $_SERVER['REDIRECT_HTTP_AUTHORIZATION'] ?? '');
    if ($auth === '' && function_exists('getallheaders')) {
        foreach (getallheaders() as $k => $v) {
            if (strcasecmp($k, 'Authorization') === 0) {
                $auth = (string) $v;
            }
        }
    }
    if (!preg_match('/^Bearer\s+(.+)$/i', $auth, $m)) {
        api_response(401, ['ok' => false, 'error' => 'Falta el token Bearer.']);
    }
    $stmt = db()->prepare(
        'SELECT id, name FROM api_tokens WHERE token_hash = ? AND active = 1
         AND (expires_at IS NULL OR expires_at > NOW()) LIMIT 1'
    );
    $stmt->execute([hash('sha256', trim($m[1]))]);
    $token = $stmt->fetch();
    if (!$token) {
        api_response(401, ['ok' => false, 'error' => 'Token inválido o vencido.']);
    }
    db()->prepare('UPDATE api_tokens SET last_used_at = NOW() WHERE id = ?')->execute([(int) $token['id']]);
    return $token;
}
