<?php
declare(strict_types=1);

/* Tokens de la API para el script diario (solo admin). El token se muestra una sola vez. */
Auth::requireAdmin();

if ($_SERVER['REQUEST_METHOD'] === 'POST') {
    verify_csrf();
    $op = (string) ($_POST['op'] ?? '');
    if ($op === 'create') {
        $nombre = trim((string) ($_POST['name'] ?? '')) ?: 'orquestador';
        $token = rtrim(strtr(base64_encode(random_bytes(32)), '+/', '-_'), '=');
        db()->prepare('INSERT INTO api_tokens (name, token_hash) VALUES (?, ?)')->execute([substr($nombre, 0, 100), hash('sha256', $token)]);
        audit('token.created', 'api_token', db()->lastInsertId(), ['name' => $nombre]);
        $_SESSION['nuevo_token'] = $token;
    } elseif (in_array($op, ['revoke', 'activate'], true)) {
        $tid = (int) ($_POST['token_id'] ?? 0);
        db()->prepare('UPDATE api_tokens SET active = ? WHERE id = ?')->execute([$op === 'activate' ? 1 : 0, $tid]);
        audit('token.' . $op, 'api_token', (string) $tid);
        flash('success', $op === 'revoke' ? 'Token revocado: el script ya no puede usarlo.' : 'Token reactivado.');
    }
    redirect(app_url('tokens'));
}

$nuevo = $_SESSION['nuevo_token'] ?? null;
unset($_SESSION['nuevo_token']);
$tokens = db()->query('SELECT * FROM api_tokens ORDER BY active DESC, created_at DESC')->fetchAll();
render_header('Tokens de la API', 'tokens');
?>
<div class="page-head"><div><h1>Tokens de la API</h1>
  <div class="muted small">El script diario se identifica con un token. Se guarda solo su huella (hash): si se pierde, se genera otro.</div></div></div>

<?php if ($nuevo): ?>
  <section class="card" style="border-left:5px solid var(--good)">
    <h2>Token nuevo — copialo ahora, no se vuelve a mostrar</h2>
    <p class="muted small">En la PC del script ejecutá <code>python orquestador_diario.py --configurar</code> y pegalo cuando lo pida.</p>
    <div class="token-box"><?= e($nuevo) ?></div>
  </section>
<?php endif; ?>

<section class="card">
  <form method="post" class="inline-form"><?= csrf_field() ?><input type="hidden" name="op" value="create">
    <label>Nombre <input name="name" value="orquestador" maxlength="100"></label>
    <button class="button" type="submit">Generar token</button></form>
</section>

<section class="card"><div class="tabla-scroll"><table>
  <thead><tr><th>Nombre</th><th>Creado</th><th>Último uso</th><th>Estado</th><th></th></tr></thead><tbody>
  <?php foreach ($tokens as $t): ?>
    <tr><td><?= e($t['name']) ?></td><td class="small"><?= e(fecha_hora($t['created_at'])) ?></td><td class="small"><?= e(fecha_hora($t['last_used_at'])) ?></td>
      <td><?= $t['active'] ? '<span class="badge good">Activo</span>' : '<span class="badge off">Revocado</span>' ?></td>
      <td><form method="post"><?= csrf_field() ?><input type="hidden" name="token_id" value="<?= (int) $t['id'] ?>">
        <?php if ($t['active']): ?><input type="hidden" name="op" value="revoke"><button class="button danger small" onclick="return confirm('¿Revocar este token? El script deja de poder subir datos con él.')">Revocar</button>
        <?php else: ?><input type="hidden" name="op" value="activate"><button class="button ghost small">Reactivar</button><?php endif; ?></form></td></tr>
  <?php endforeach; ?>
  <?php if (!$tokens): ?><tr><td colspan="5" class="muted">Todavía no hay tokens. Generá uno para el script.</td></tr><?php endif; ?>
  </tbody></table></div></section>
<?php render_footer();
