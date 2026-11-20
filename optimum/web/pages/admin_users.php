<?php
declare(strict_types=1);

/* Administración de usuarios y sus permisos por suministro (solo admin). */
Auth::requireAdmin();

$action = (string) ($_GET['action'] ?? '');
$id = (int) ($_GET['id'] ?? 0);

function user_by_id(int $id): ?array
{
    $q = db()->prepare('SELECT * FROM users WHERE id = ?');
    $q->execute([$id]);
    return $q->fetch() ?: null;
}

function active_admins_excluding(int $id): int
{
    $q = db()->prepare("SELECT COUNT(*) FROM users WHERE role = 'admin' AND active = 1 AND id <> ?");
    $q->execute([$id]);
    return (int) $q->fetchColumn();
}

if ($_SERVER['REQUEST_METHOD'] === 'POST') {
    verify_csrf();
    $existente = $id ? user_by_id($id) : null;
    if ($id && !$existente) {
        not_found();
    }
    $username = $existente ? $existente['username'] : trim((string) ($_POST['username'] ?? ''));
    $email = trim((string) ($_POST['email'] ?? ''));
    $nombre = trim((string) ($_POST['full_name'] ?? ''));
    $rol = ($_POST['role'] ?? '') === 'admin' ? 'admin' : 'consulta';
    $activo = isset($_POST['active']) ? 1 : 0;
    $alertas = isset($_POST['receive_alerts']) ? 1 : 0;
    $pass = (string) ($_POST['password'] ?? '');

    $errores = [];
    if (!$existente && !preg_match('/^[A-Za-z0-9._-]{3,60}$/', $username)) {
        $errores[] = 'Usuario inválido (3 a 60 caracteres: letras, números, punto, guion).';
    }
    if ($email !== '' && !filter_var($email, FILTER_VALIDATE_EMAIL)) {
        $errores[] = 'Correo inválido.';
    }
    if ($alertas && $email === '') {
        $errores[] = 'Para recibir alertas hace falta un correo.';
    }
    if ((!$existente && strlen($pass) < 10) || ($existente && $pass !== '' && strlen($pass) < 10)) {
        $errores[] = 'La contraseña debe tener al menos 10 caracteres.';
    }
    $dup = db()->prepare('SELECT id FROM users WHERE (username = ? OR (email IS NOT NULL AND email = ?)) AND id <> ?');
    $dup->execute([$username, $email ?: '-', $id]);
    if ($dup->fetchColumn()) {
        $errores[] = 'Ya existe un usuario con ese nombre o correo.';
    }
    // Candados: nunca quedarse sin administrador activo.
    if ($existente && $existente['role'] === 'admin' && ($rol !== 'admin' || !$activo) && active_admins_excluding($id) === 0) {
        $errores[] = 'Es el único administrador activo: no se le puede quitar el rol ni desactivar.';
    }

    // Permisos por suministro (solo aplican al rol consulta).
    $permisos = [];
    foreach ((array) ($_POST['perm'] ?? []) as $sid => $p) {
        $sid = (int) $sid;
        if (!empty($p['view'])) {
            $permisos[$sid] = !empty($p['download']) ? 1 : 0;
        } elseif (!empty($p['download'])) {
            $errores[] = 'No se puede dar "Descargar" sin "Ver" en el mismo suministro.';
            break;
        }
    }

    if ($errores) {
        flash('error', implode(' ', array_unique($errores)));
        $_SESSION['form_user'] = $_POST;
        redirect(app_url('users', ['action' => $id ? 'edit' : 'new', 'id' => $id ?: null]));
    }

    db()->beginTransaction();
    if ($existente) {
        db()->prepare('UPDATE users SET email=?, full_name=?, role=?, active=?, receive_alerts=? WHERE id=?')
            ->execute([$email ?: null, $nombre, $rol, $activo, $alertas, $id]);
        if ($pass !== '') {
            db()->prepare('UPDATE users SET password_hash = ? WHERE id = ?')->execute([password_hash($pass, PASSWORD_DEFAULT), $id]);
        }
    } else {
        db()->prepare('INSERT INTO users (username, email, full_name, role, password_hash, active, receive_alerts) VALUES (?,?,?,?,?,?,?)')
            ->execute([$username, $email ?: null, $nombre, $rol, password_hash($pass, PASSWORD_DEFAULT), $activo, $alertas]);
        $id = (int) db()->lastInsertId();
    }
    db()->prepare('DELETE FROM user_supply_permissions WHERE user_id = ?')->execute([$id]);
    if ($rol === 'consulta') {
        $ins = db()->prepare('INSERT INTO user_supply_permissions (user_id, supply_id, can_download) VALUES (?,?,?)');
        foreach ($permisos as $sid => $descarga) {
            $ins->execute([$id, $sid, $descarga]);
        }
    }
    db()->commit();
    audit($existente ? 'user.updated' : 'user.created', 'user', (string) $id,
        ['role' => $rol, 'active' => $activo, 'alerts' => $alertas, 'password_changed' => $pass !== '', 'supplies' => $permisos]);
    flash('success', $existente ? 'Usuario actualizado.' : 'Usuario creado.');
    redirect(app_url('users'));
}

$supplies = db()->query('SELECT id, nis, name, active FROM supplies ORDER BY active DESC, name')->fetchAll();

if ($action === 'new' || ($action === 'edit' && $id)) {
    $u = $id ? user_by_id($id) : null;
    if ($id && !$u) {
        not_found();
    }
    $form = $_SESSION['form_user'] ?? null;
    unset($_SESSION['form_user']);
    $v = static fn (string $k, $def = '') => $form[$k] ?? ($u[$k] ?? $def);
    $actuales = [];
    if ($form) {
        foreach ((array) ($form['perm'] ?? []) as $sid => $p) {
            $actuales[(int) $sid] = ['view' => !empty($p['view']), 'download' => !empty($p['download'])];
        }
    } elseif ($u) {
        $q = db()->prepare('SELECT supply_id, can_download FROM user_supply_permissions WHERE user_id = ?');
        $q->execute([$id]);
        foreach ($q->fetchAll() as $p) {
            $actuales[(int) $p['supply_id']] = ['view' => true, 'download' => (bool) $p['can_download']];
        }
    }
    $esAdmin = $v('role', 'consulta') === 'admin';
    render_header($u ? 'Editar usuario' : 'Nuevo usuario', 'users');
    ?>
    <div class="page-head"><div><a class="small" href="<?= e(app_url('users')) ?>">← Usuarios</a>
      <h1><?= $u ? e($u['username']) : 'Nuevo usuario' ?></h1></div></div>
    <form method="post" class="card">
      <?= csrf_field() ?>
      <div class="form-grid" style="margin-top:0">
        <label>Usuario <?php if ($u): ?><input value="<?= e($u['username']) ?>" disabled><?php else: ?>
          <input name="username" value="<?= e($v('username')) ?>" required><?php endif; ?></label>
        <label>Nombre completo <input name="full_name" value="<?= e($v('full_name')) ?>"></label>
        <label>Correo <input type="email" name="email" value="<?= e($v('email')) ?>"></label>
        <label>Contraseña <?= $u ? '<span class="help">(dejar vacío para no cambiarla)</span>' : '<span class="help">(mínimo 10)</span>' ?>
          <input type="password" name="password" autocomplete="new-password" <?= $u ? '' : 'required minlength="10"' ?>></label>
        <label>Rol <select name="role" id="rol">
          <option value="consulta"<?= !$esAdmin ? ' selected' : '' ?>>Consulta — solo los suministros asignados</option>
          <option value="admin"<?= $esAdmin ? ' selected' : '' ?>>Administrador — ve y administra todo</option>
        </select></label>
        <div style="display:grid;gap:8px;align-content:end">
          <label class="check"><input type="checkbox" name="active" value="1"<?= $v('active', 1) ? ' checked' : '' ?>> Activo</label>
          <label class="check"><input type="checkbox" name="receive_alerts" value="1"<?= $v('receive_alerts', 0) ? ' checked' : '' ?>> Recibir alertas por correo</label>
        </div>
      </div>
      <fieldset style="margin-top:16px" id="permisos">
        <legend>Suministros que puede ver</legend>
        <p class="help" id="aviso-admin"<?= $esAdmin ? '' : ' hidden' ?>>Los administradores ven todos los suministros; estos permisos no se usan.</p>
        <?php if (!$supplies): ?><p class="muted">Todavía no hay suministros cargados.</p><?php else: ?>
        <div class="tabla-scroll"><table>
          <thead><tr><th>Suministro</th><th>Ver</th><th>Descargar Excel</th></tr></thead><tbody>
          <?php foreach ($supplies as $s): $p = $actuales[(int) $s['id']] ?? ['view' => false, 'download' => false]; ?>
            <tr class="perm-row"><td><?= e($s['name']) ?> <span class="muted small">NIS <?= e($s['nis']) ?><?= $s['active'] ? '' : ' · inactivo' ?></span></td>
              <td><input type="checkbox" name="perm[<?= (int) $s['id'] ?>][view]" value="1"<?= $p['view'] ? ' checked' : '' ?>></td>
              <td><input type="checkbox" name="perm[<?= (int) $s['id'] ?>][download]" value="1"<?= $p['download'] ? ' checked' : '' ?>></td></tr>
          <?php endforeach; ?>
        </tbody></table></div>
        <?php endif; ?>
      </fieldset>
      <div style="margin-top:14px"><button class="button" type="submit"><?= $u ? 'Guardar cambios' : 'Crear usuario' ?></button></div>
    </form>
    <script>
      document.getElementById('rol').addEventListener('change', e => {
        document.getElementById('aviso-admin').hidden = e.target.value !== 'admin'; });
    </script>
    <?php
    render_footer();
    exit;
}

$usuarios = db()->query(
    "SELECT u.*, (SELECT GROUP_CONCAT(CONCAT(s.nis, IF(p.can_download, ' (D)', '')) ORDER BY s.nis SEPARATOR ', ')
                  FROM user_supply_permissions p JOIN supplies s ON s.id = p.supply_id WHERE p.user_id = u.id) AS permisos
     FROM users u ORDER BY u.active DESC, u.role, u.username"
)->fetchAll();
render_header('Usuarios', 'users');
?>
<div class="page-head">
  <div><h1>Usuarios</h1><div class="muted small">Administrador: ve todo. Consulta: solo los suministros asignados ("D" = puede descargar Excel).</div></div>
  <a class="button" href="<?= e(app_url('users', ['action' => 'new'])) ?>">+ Nuevo usuario</a>
</div>
<section class="card"><div class="tabla-scroll"><table>
  <thead><tr><th>Usuario</th><th>Nombre</th><th>Rol</th><th>Suministros</th><th>Alertas</th><th>Último ingreso</th><th>Estado</th><th></th></tr></thead>
  <tbody>
  <?php foreach ($usuarios as $u): ?>
    <tr><td><?= e($u['username']) ?><br><span class="muted small"><?= e($u['email']) ?></span></td><td><?= e($u['full_name']) ?></td>
      <td><?= $u['role'] === 'admin' ? 'Administrador' : 'Consulta' ?></td>
      <td class="small"><?= $u['role'] === 'admin' ? '<span class="muted">Todos</span>' : e($u['permisos'] ?: '—') ?></td>
      <td><?= $u['receive_alerts'] ? 'Sí' : 'No' ?></td><td class="small"><?= e(fecha_hora($u['last_login_at'])) ?></td>
      <td><?= $u['active'] ? '<span class="badge good">Activo</span>' : '<span class="badge off">Inactivo</span>' ?></td>
      <td><a class="button ghost small" href="<?= e(app_url('users', ['action' => 'edit', 'id' => $u['id']])) ?>">Editar</a></td></tr>
  <?php endforeach; ?>
  </tbody>
</table></div></section>
<?php render_footer();
