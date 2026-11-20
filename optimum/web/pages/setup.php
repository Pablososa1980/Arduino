<?php
declare(strict_types=1);

/* Crea el primer administrador. Solo funciona mientras la tabla users está vacía. */
if ((int) db()->query('SELECT COUNT(*) FROM users')->fetchColumn() > 0) {
    redirect(app_url('login'));
}
$errores = [];
$clave = (string) config('app.setup_key', '');
$claveSegura = strlen($clave) >= 20 && !str_starts_with($clave, 'CAMBIAR');

if ($_SERVER['REQUEST_METHOD'] === 'POST' && $claveSegura) {
    verify_csrf();
    $usuario = trim((string) ($_POST['username'] ?? ''));
    $nombre = trim((string) ($_POST['full_name'] ?? ''));
    $correo = trim((string) ($_POST['email'] ?? ''));
    $pass = (string) ($_POST['password'] ?? '');
    if (!hash_equals($clave, (string) ($_POST['setup_key'] ?? ''))) {
        $errores[] = 'La clave de instalación no coincide con la de config.php.';
        audit('setup.failed');
    }
    if (!preg_match('/^[A-Za-z0-9._-]{3,60}$/', $usuario)) {
        $errores[] = 'El usuario debe tener entre 3 y 60 caracteres (letras, números, punto, guion).';
    }
    if ($correo !== '' && !filter_var($correo, FILTER_VALIDATE_EMAIL)) {
        $errores[] = 'El correo no es válido.';
    }
    if (strlen($pass) < 10) {
        $errores[] = 'La contraseña debe tener al menos 10 caracteres.';
    }
    if (!$errores) {
        db()->prepare(
            "INSERT INTO users (username, email, full_name, role, password_hash, receive_alerts) VALUES (?, ?, ?, 'admin', ?, ?)"
        )->execute([$usuario, $correo ?: null, $nombre, password_hash($pass, PASSWORD_DEFAULT), $correo !== '' ? 1 : 0]);
        Auth::attempt($usuario, $pass);
        audit('setup.admin_created', 'user', (string) Auth::id());
        flash('success', 'Administrador creado. Siguiente paso: dar de alta el primer suministro.');
        redirect(app_url('supplies', ['action' => 'new']));
    }
}
render_header('Instalación');
?>
<section class="auth-card wide">
  <div class="brand"><span class="brand-mark" aria-hidden="true">⚡</span><?= e(config('app.name', 'Monitoreo de Potencia')) ?></div>
  <h1 style="margin-top:18px">Instalación inicial</h1>
  <?php if (!$claveSegura): ?>
    <div class="flash error">Antes de continuar, poné una <b>setup_key</b> larga (20+ caracteres) en <code>config/config.php</code>.</div>
  <?php else: ?>
    <p class="muted">Creá el usuario administrador. Esta pantalla desaparece en cuanto exista el primer usuario.</p>
    <?php foreach ($errores as $err): ?><div class="flash error"><?= e($err) ?></div><?php endforeach; ?>
    <form method="post" class="form-grid">
      <?= csrf_field() ?>
      <label class="full">Clave de instalación (setup_key de config.php) <input type="password" name="setup_key" required></label>
      <label>Usuario <input name="username" value="<?= e($_POST['username'] ?? '') ?>" required></label>
      <label>Nombre completo <input name="full_name" value="<?= e($_POST['full_name'] ?? '') ?>"></label>
      <label>Correo (para recibir alertas) <input type="email" name="email" value="<?= e($_POST['email'] ?? '') ?>"></label>
      <label>Contraseña (mínimo 10) <input type="password" name="password" minlength="10" required></label>
      <div class="full"><button class="button" type="submit">Crear administrador</button></div>
    </form>
  <?php endif; ?>
</section>
<?php render_footer();
