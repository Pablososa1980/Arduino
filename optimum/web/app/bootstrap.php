<?php
declare(strict_types=1);

/*
 * Base común del panel: configuración, conexión a la base, sesión, CSRF,
 * auditoría y control de acceso. Adaptado del panel SEP2 (mismo criterio:
 * los permisos se validan SIEMPRE en el servidor).
 */

const APP_ROOT = __DIR__ . '/..';

$configPath = getenv('POTENCIA_CONFIG') ?: APP_ROOT . '/config/config.php';
if (!is_file($configPath)) {
    http_response_code(500);
    exit('Falta config/config.php. Copie config/config.example.php y complete los datos privados.');
}

/** @var array<string, mixed> $loadedConfig */
$loadedConfig = require $configPath;
$GLOBALS['app_config'] = $loadedConfig;

date_default_timezone_set((string) config('app.timezone', 'America/Asuncion'));

if (!defined('API_REQUEST') && PHP_SAPI !== 'cli') {
    session_name((string) config('app.session_name', 'potencia_panel'));
    session_set_cookie_params([
        'lifetime' => 0,
        'path' => '/',
        'secure' => !empty($_SERVER['HTTPS']) && $_SERVER['HTTPS'] !== 'off',
        'httponly' => true,
        'samesite' => 'Lax',
    ]);
    if (session_status() !== PHP_SESSION_ACTIVE) {
        session_start();
    }
    header('X-Content-Type-Options: nosniff');
    header('X-Frame-Options: SAMEORIGIN');
    header('Referrer-Policy: strict-origin-when-cross-origin');
}

function config(string $path, mixed $default = null): mixed
{
    $value = $GLOBALS['app_config'] ?? [];
    foreach (explode('.', $path) as $segment) {
        if (!is_array($value) || !array_key_exists($segment, $value)) {
            return $default;
        }
        $value = $value[$segment];
    }
    return $value;
}

function db(): PDO
{
    static $pdo = null;
    if ($pdo instanceof PDO) {
        return $pdo;
    }
    $host = (string) config('database.host', 'localhost');
    $port = (int) config('database.port', 3306);
    $name = (string) config('database.name');
    $charset = (string) config('database.charset', 'utf8mb4');
    $pdo = new PDO("mysql:host={$host};port={$port};dbname={$name};charset={$charset}",
        (string) config('database.user'), (string) config('database.password'), [
            PDO::ATTR_ERRMODE => PDO::ERRMODE_EXCEPTION,
            PDO::ATTR_DEFAULT_FETCH_MODE => PDO::FETCH_ASSOC,
            PDO::ATTR_EMULATE_PREPARES => false,
        ]);
    // El hosting corre MySQL en UTC: se alinea con la hora de Paraguay para NOW().
    $offset = (new DateTimeImmutable('now'))->format('P');
    $pdo->exec("SET time_zone = '{$offset}'");
    return $pdo;
}

function e(mixed $value): string
{
    return htmlspecialchars((string) $value, ENT_QUOTES | ENT_SUBSTITUTE, 'UTF-8');
}

/** @param array<string, scalar|null> $params */
function app_url(string $page = 'dashboard', array $params = []): string
{
    $params = array_filter($params, static fn ($v) => $v !== null && $v !== '');
    return 'index.php?' . http_build_query(['page' => $page] + $params);
}

function redirect(string $url): never
{
    header('Location: ' . $url);
    exit;
}

function csrf_token(): string
{
    if (empty($_SESSION['csrf_token'])) {
        $_SESSION['csrf_token'] = bin2hex(random_bytes(32));
    }
    return (string) $_SESSION['csrf_token'];
}

function csrf_field(): string
{
    return '<input type="hidden" name="_csrf" value="' . e(csrf_token()) . '">';
}

function verify_csrf(): void
{
    $token = $_POST['_csrf'] ?? '';
    if (!is_string($token) || !hash_equals(csrf_token(), $token)) {
        http_response_code(419);
        exit('La sesión del formulario venció. Actualice la página e intente nuevamente.');
    }
}

function flash(string $type, string $message): void
{
    $_SESSION['flash'] = ['type' => $type, 'message' => $message];
}

/** @return array{type:string,message:string}|null */
function pull_flash(): ?array
{
    $flash = $_SESSION['flash'] ?? null;
    unset($_SESSION['flash']);
    return is_array($flash) ? $flash : null;
}

function request_ip(): ?string
{
    $value = $_SERVER['REMOTE_ADDR'] ?? null;
    return is_string($value) ? substr($value, 0, 45) : null;
}

function audit(string $action, ?string $entityType = null, ?string $entityId = null, array $detail = []): void
{
    try {
        db()->prepare(
            'INSERT INTO audit_logs (user_id, action, entity_type, entity_id, ip_address, detail_text)
             VALUES (?, ?, ?, ?, ?, ?)'
        )->execute([
            Auth::id(), $action, $entityType, $entityId, request_ip(),
            $detail ? json_encode($detail, JSON_UNESCAPED_UNICODE | JSON_UNESCAPED_SLASHES) : null,
        ]);
    } catch (Throwable) {
        // La auditoría nunca bloquea la operación principal.
    }
}

/** Formato paraguayo: 1.234,5 */
function num(float|int|string|null $value, int $decimals = 0): string
{
    if ($value === null || $value === '') {
        return '—';
    }
    return number_format((float) $value, $decimals, ',', '.');
}

function fecha_hora(?string $ts): string
{
    if (!$ts) {
        return '—';
    }
    $d = new DateTimeImmutable($ts);
    return $d->format('d/m/Y H:i');
}

function mes_texto(string $period): string
{
    static $meses = ['enero', 'febrero', 'marzo', 'abril', 'mayo', 'junio', 'julio', 'agosto',
        'septiembre', 'octubre', 'noviembre', 'diciembre'];
    [$y, $m] = array_map('intval', explode('-', $period)) + [0, 0];
    return ($meses[$m - 1] ?? '?') . ' ' . $y;
}

final class Auth
{
    private static ?array $user = null;

    public static function user(): ?array
    {
        if (self::$user !== null) {
            return self::$user;
        }
        $id = $_SESSION['user_id'] ?? null;
        if (!is_numeric($id)) {
            return null;
        }
        $stmt = db()->prepare('SELECT id, username, email, full_name, role, active FROM users WHERE id = ? LIMIT 1');
        $stmt->execute([(int) $id]);
        $user = $stmt->fetch();
        if (!$user || !(bool) $user['active']) {
            self::logout(false);
            return null;
        }
        return self::$user = $user;
    }

    public static function id(): ?int
    {
        if (PHP_SAPI === 'cli' || defined('API_REQUEST')) {
            return null;
        }
        $user = self::user();
        return $user ? (int) $user['id'] : null;
    }

    public static function isAdmin(): bool
    {
        return (self::user()['role'] ?? '') === 'admin';
    }

    /** Bloqueo simple contra fuerza bruta: 10 intentos fallidos por IP en 15 minutos. */
    public static function tooManyAttempts(): bool
    {
        $stmt = db()->prepare(
            "SELECT COUNT(*) FROM audit_logs WHERE action = 'auth.login_failed' AND ip_address = ?
             AND created_at > (NOW() - INTERVAL 15 MINUTE)"
        );
        $stmt->execute([request_ip()]);
        return (int) $stmt->fetchColumn() >= 10;
    }

    public static function attempt(string $username, string $password): bool
    {
        $stmt = db()->prepare(
            'SELECT id, active, password_hash FROM users WHERE username = ? OR email = ? LIMIT 1'
        );
        $identifier = trim($username);
        $stmt->execute([$identifier, $identifier]);
        $user = $stmt->fetch();
        if (!$user || !(bool) $user['active'] || !password_verify($password, (string) $user['password_hash'])) {
            audit('auth.login_failed', 'user', null, ['identifier' => $identifier]);
            return false;
        }
        session_regenerate_id(true);
        $_SESSION['user_id'] = (int) $user['id'];
        self::$user = null;
        db()->prepare('UPDATE users SET last_login_at = NOW() WHERE id = ?')->execute([(int) $user['id']]);
        audit('auth.login', 'user', (string) $user['id']);
        return true;
    }

    public static function logout(bool $record = true): void
    {
        if ($record && isset($_SESSION['user_id'])) {
            audit('auth.logout', 'user', (string) $_SESSION['user_id']);
        }
        $_SESSION = [];
        if (session_status() === PHP_SESSION_ACTIVE) {
            session_regenerate_id(true);
        }
        self::$user = null;
    }

    public static function requireLogin(): void
    {
        if (!self::user()) {
            flash('error', 'Inicie sesión para acceder al panel.');
            redirect(app_url('login'));
        }
    }

    public static function requireAdmin(): void
    {
        self::requireLogin();
        if (!self::isAdmin()) {
            http_response_code(403);
            exit('No tiene permisos de administración.');
        }
    }

    /** ¿Puede ver (o descargar) este suministro? El admin puede todo. */
    public static function canSupply(int $supplyId, bool $download = false): bool
    {
        if (self::isAdmin()) {
            return true;
        }
        $sql = 'SELECT 1 FROM user_supply_permissions p JOIN supplies s ON s.id = p.supply_id
                WHERE p.user_id = ? AND p.supply_id = ?' . ($download ? ' AND p.can_download = 1' : '') . ' LIMIT 1';
        $stmt = db()->prepare($sql);
        $stmt->execute([self::id(), $supplyId]);
        return (bool) $stmt->fetchColumn();
    }

    /** @return list<array<string,mixed>> Suministros que el usuario puede ver. */
    public static function supplies(bool $includeInactive = false): array
    {
        $filtro = $includeInactive ? '' : ' AND s.active = 1';
        if (self::isAdmin()) {
            return db()->query("SELECT s.* FROM supplies s WHERE 1=1{$filtro} ORDER BY s.name")->fetchAll();
        }
        $stmt = db()->prepare(
            "SELECT s.*, p.can_download FROM supplies s JOIN user_supply_permissions p ON p.supply_id = s.id
             WHERE p.user_id = ?{$filtro} ORDER BY s.name"
        );
        $stmt->execute([self::id()]);
        return $stmt->fetchAll();
    }
}
