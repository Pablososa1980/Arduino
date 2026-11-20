<?php
declare(strict_types=1);

/*
 * Copiar este archivo como config.php (misma carpeta) y completar los datos.
 * config.php NUNCA se sube a GitHub.
 */
return [
    'app' => [
        'name' => 'Monitoreo de Potencia',
        'base_url' => 'https://tudominio.com',          // sin barra final (va en los correos de alerta)
        'timezone' => 'America/Asuncion',
        'session_name' => 'potencia_panel',
        // Clave de instalación: se pide una sola vez para crear el primer administrador.
        // Poné una cadena larga y aleatoria (y borrala o cambiala después si querés).
        'setup_key' => 'CAMBIAR-POR-UNA-CLAVE-LARGA-Y-ALEATORIA',
    ],
    'database' => [
        // hPanel > Bases de datos > Administración de MySQL
        'host' => 'localhost',
        'port' => 3306,
        'name' => 'u000000000_potencia',
        'user' => 'u000000000_potencia',
        'password' => 'CAMBIAR_CONTRASENA',
        'charset' => 'utf8mb4',
    ],
    'mail' => [
        // Correo de alertas (usa mail() del hosting). Crear antes la casilla en hPanel > Correos.
        'enabled' => false,
        'from' => 'alertas@tudominio.com',
        'from_name' => 'Monitoreo de Potencia',
    ],
];
