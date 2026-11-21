<?php
declare(strict_types=1);

/* Cabecera, menú y pie comunes a todas las páginas. */

const ESTADOS = [
    'normal' => ['Normal', 'good'],
    'atencion' => ['Sobre la contratada (dentro de tolerancia)', 'warning'],
    'critico' => ['Supera la tolerancia', 'critical'],
    'sin_datos' => ['Sin datos', 'muted'],
];

function estado_badge(?string $estado): string
{
    [$txt, $cls] = ESTADOS[$estado ?? 'sin_datos'] ?? ESTADOS['sin_datos'];
    $ico = ['good' => '✓', 'warning' => '!', 'critical' => '✕', 'muted' => '–'][$cls];
    return '<span class="badge ' . $cls . '"><span class="badge-ico" aria-hidden="true">' . $ico . '</span>' . e($txt) . '</span>';
}

function render_header(string $title, string $active = ''): void
{
    $user = Auth::user();
    $flash = pull_flash();
    $appName = (string) config('app.name', 'Monitoreo de Potencia');
    $nav = [];
    if ($user) {
        $nav = [['dashboard', 'Inicio'], ['history', 'Histórico'], ['alerts', 'Alertas']];
        if (Auth::isAdmin()) {
            array_push($nav, ['supplies', 'Suministros'], ['users', 'Usuarios'], ['tokens', 'Tokens'], ['audit', 'Auditoría']);
        }
    }
    ?><!doctype html>
<html lang="es">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="robots" content="noindex, nofollow">
<title><?= e($title) ?> · <?= e($appName) ?></title>
<link rel="stylesheet" href="assets/app.css?v=2">
</head>
<body>
<?php if ($user): ?>
<header class="topbar">
  <a class="brand" href="<?= e(app_url('dashboard')) ?>"><span class="brand-mark" aria-hidden="true">⚡</span><?= e($appName) ?></a>
  <button class="nav-toggle" type="button" aria-label="Menú" onclick="document.body.classList.toggle('nav-open')">☰</button>
  <nav class="nav">
    <?php foreach ($nav as [$page, $label]): ?>
      <a href="<?= e(app_url($page)) ?>" class="<?= $active === $page ? 'active' : '' ?>"><?= e($label) ?></a>
    <?php endforeach; ?>
  </nav>
  <div class="user-menu">
    <span><?= e($user['full_name'] ?: $user['username']) ?><small><?= $user['role'] === 'admin' ? 'Administrador' : 'Consulta' ?></small></span>
    <form method="post" action="<?= e(app_url('logout')) ?>"><?= csrf_field() ?><button class="button ghost small" type="submit">Salir</button></form>
  </div>
</header>
<?php endif; ?>
<main class="<?= $user ? 'shell' : 'auth-shell' ?>">
<?php if ($flash): ?>
  <div class="flash <?= e($flash['type']) ?>" role="status"><?= e($flash['message']) ?></div>
<?php endif;
}

function render_footer(): void
{
    ?>
</main>
</body>
</html>
<?php
}

function not_found(string $mensaje = 'No encontrado.'): never
{
    http_response_code(404);
    render_header('No encontrado');
    echo '<section class="card"><h1>No encontrado</h1><p class="muted">' . e($mensaje) . '</p>'
        . '<a class="button" href="' . e(app_url('dashboard')) . '">Volver al inicio</a></section>';
    render_footer();
    exit;
}

function forbidden(): never
{
    http_response_code(403);
    render_header('Sin permiso');
    echo '<section class="card"><h1>Sin permiso</h1><p class="muted">No tiene acceso a este suministro.</p>'
        . '<a class="button" href="' . e(app_url('dashboard')) . '">Volver al inicio</a></section>';
    render_footer();
    exit;
}

/** Selector de suministro (para histórico/alertas). */
function supply_select(array $supplies, ?int $selected, string $page, array $extra = [], bool $todos = false): string
{
    $html = '<form method="get" class="inline-form"><input type="hidden" name="page" value="' . e($page) . '">';
    foreach ($extra as $k => $v) {
        $html .= '<input type="hidden" name="' . e($k) . '" value="' . e($v) . '">';
    }
    $html .= '<label>Suministro <select name="id" onchange="this.form.submit()">';
    if ($todos) {
        $html .= '<option value="">Todos</option>';
    }
    foreach ($supplies as $s) {
        $html .= '<option value="' . (int) $s['id'] . '"' . ((int) $s['id'] === $selected ? ' selected' : '') . '>'
            . e($s['name'] . ' · NIS ' . $s['nis']) . '</option>';
    }
    return $html . '</select></label><noscript><button class="button small">Ver</button></noscript></form>';
}

/** Mini barras de máximos diarios (SVG del lado servidor, para la portada). */
function mini_barras(array $diario, ?float $limite, ?float $contratada, int $ancho = 280, int $alto = 54): string
{
    if (!$diario || !$limite) {
        return '<div class="muted small">Sin lecturas todavía.</div>';
    }
    $vmax = max(array_merge([$limite], array_map(static fn ($d) => (float) $d[1], $diario))) * 1.05;
    $n = count($diario);
    $banda = $ancho / max($n, 1);
    $bw = max(2.0, min(10.0, $banda - 2));
    $y = static fn ($v) => $alto - $v / $vmax * $alto;
    $svg = '';
    foreach ($diario as $i => $d) {
        $kw = (float) $d[1];
        $color = $kw > $limite ? 'var(--critical)' : ($contratada && $kw > $contratada ? 'var(--warning)' : 'var(--series)');
        $x = $banda * ($i + 0.5) - $bw / 2;
        $svg .= sprintf('<rect x="%.1f" y="%.1f" width="%.1f" height="%.1f" rx="1.5" fill="%s"><title>%s: %s kW</title></rect>',
            $x, $y($kw), $bw, $alto - $y($kw), $color, e(date('d/m', strtotime((string) $d[0]))), num($kw, 1));
    }
    $svg .= sprintf('<line x1="0" x2="%d" y1="%.1f" y2="%.1f" stroke="var(--critical)" stroke-width="1.2" stroke-dasharray="4 3"/>',
        $ancho, $y($limite), $y($limite));
    return '<svg class="mini" viewBox="0 0 ' . $ancho . ' ' . $alto . '" preserveAspectRatio="none" role="img" aria-label="Máximos diarios del ciclo">' . $svg . '</svg>';
}

/** Datos para los gráficos JS, embebidos de forma segura. */
function json_script(string $id, array $data): string
{
    return '<script type="application/json" id="' . e($id) . '">'
        . str_replace('</', '<\/', (string) json_encode($data, JSON_UNESCAPED_UNICODE | JSON_UNESCAPED_SLASHES))
        . '</script>';
}
