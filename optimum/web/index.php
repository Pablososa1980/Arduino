<?php
declare(strict_types=1);

/*
 * Panel de Potencia — punto de entrada único: index.php?page=...
 * Cada página vive en pages/<nombre>.php (carpeta protegida por .htaccess).
 */
require __DIR__ . '/app/bootstrap.php';
require __DIR__ . '/app/metrics.php';
require __DIR__ . '/app/layout.php';

$rutas = [
    'login' => 'login', 'logout' => 'logout', 'setup' => 'setup',
    'dashboard' => 'dashboard', 'supply' => 'supply', 'history' => 'history', 'alerts' => 'alerts',
    'download' => 'download',
    'supplies' => 'admin_supplies', 'users' => 'admin_users', 'tokens' => 'admin_tokens', 'audit' => 'admin_audit',
];
$page = is_string($_GET['page'] ?? null) ? $_GET['page'] : 'dashboard';
if (!isset($rutas[$page])) {
    $page = 'dashboard';
}

// Instalación: mientras no exista ningún usuario, todo lleva a "setup".
try {
    $hayUsuarios = (int) db()->query('SELECT COUNT(*) FROM users')->fetchColumn() > 0;
} catch (PDOException $e) {
    http_response_code(500);
    exit('No se pudo conectar a la base de datos o falta crear las tablas (sql/schema.sql). Detalle: ' . e($e->getMessage()));
}
if (!$hayUsuarios && $page !== 'setup') {
    redirect(app_url('setup'));
}

if (!in_array($page, ['login', 'setup'], true)) {
    Auth::requireLogin();
}

require __DIR__ . '/pages/' . $rutas[$page] . '.php';
