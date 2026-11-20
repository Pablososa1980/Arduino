<?php
declare(strict_types=1);

if (Auth::user()) {
    redirect(app_url('dashboard'));
}
$error = null;
if ($_SERVER['REQUEST_METHOD'] === 'POST') {
    verify_csrf();
    if (Auth::tooManyAttempts()) {
        $error = 'Demasiados intentos fallidos. Espere 15 minutos e intente de nuevo.';
    } elseif (Auth::attempt((string) ($_POST['username'] ?? ''), (string) ($_POST['password'] ?? ''))) {
        redirect(app_url('dashboard'));
    } else {
        $error = 'Usuario o contraseña incorrectos.';
    }
}
render_header('Ingresar');
?>
<section class="auth-card">
  <div class="brand"><span class="brand-mark" aria-hidden="true">⚡</span><?= e(config('app.name', 'Monitoreo de Potencia')) ?></div>
  <h1 style="margin-top:18px">Ingresar</h1>
  <p class="muted">Demanda de potencia de los suministros, comparada con la potencia contratada.</p>
  <?php if ($error): ?><div class="flash error"><?= e($error) ?></div><?php endif; ?>
  <form method="post" class="stack">
    <?= csrf_field() ?>
    <label>Usuario o correo <input name="username" autocomplete="username" required autofocus></label>
    <label>Contraseña <input type="password" name="password" autocomplete="current-password" required></label>
    <button class="button" type="submit">Ingresar</button>
  </form>
</section>
<?php render_footer();
