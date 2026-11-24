<?php
declare(strict_types=1);

/* Administración de suministros y sus condiciones contractuales (solo admin). */
Auth::requireAdmin();

$action = (string) ($_GET['action'] ?? '');
$id = (int) ($_GET['id'] ?? 0);

function supply_by_id(int $id): ?array
{
    $q = db()->prepare('SELECT * FROM supplies WHERE id = ?');
    $q->execute([$id]);
    return $q->fetch() ?: null;
}

function decimal_input(string $campo): ?float
{
    $v = str_replace(' ', '', trim((string) ($_POST[$campo] ?? '')));
    // Acepta "1815,78", "1815.78" y "1.815,78"
    if (preg_match('/^\d{1,3}(\.\d{3})+(,\d+)?$/', $v)) {
        $v = str_replace(['.', ','], ['', '.'], $v);
    } else {
        $v = str_replace(',', '.', $v);
    }
    return is_numeric($v) ? (float) $v : null;
}

// ---------------- Acciones POST ----------------
if ($_SERVER['REQUEST_METHOD'] === 'POST') {
    verify_csrf();
    $op = (string) ($_POST['op'] ?? '');

    if ($op === 'save_supply') {
        $datos = [
            'nis' => trim((string) ($_POST['nis'] ?? '')),
            'name' => trim((string) ($_POST['name'] ?? '')),
            'client' => trim((string) ($_POST['client'] ?? '')) ?: null,
            'meter_prefix' => trim((string) ($_POST['meter_prefix'] ?? 'EGM')) ?: 'EGM',
            'channel' => trim((string) ($_POST['channel'] ?? '')),
            'billing_day' => trim((string) ($_POST['billing_day'] ?? '')) === '' ? null : (int) $_POST['billing_day'],
            'active' => isset($_POST['active']) ? 1 : 0,
            'notes' => trim((string) ($_POST['notes'] ?? '')) ?: null,
        ];
        $errores = [];
        if (!preg_match('/^[0-9A-Za-z-]{3,20}$/', $datos['nis'])) {
            $errores[] = 'El NIS / Punto de Medida debe tener entre 3 y 20 caracteres alfanuméricos.';
        }
        if ($datos['name'] === '') {
            $errores[] = 'Falta el nombre del suministro.';
        }
        if ($datos['channel'] === '') {
            $errores[] = 'Falta el canal del MDC.';
        }
        if ($datos['billing_day'] !== null && ($datos['billing_day'] < 1 || $datos['billing_day'] > 31)) {
            $errores[] = 'El día de cierre debe estar entre 1 y 31 (o vacío para mes calendario).';
        }
        $dup = db()->prepare('SELECT id FROM supplies WHERE nis = ? AND id <> ?');
        $dup->execute([$datos['nis'], $id]);
        if ($dup->fetchColumn()) {
            $errores[] = 'Ya existe otro suministro con ese NIS.';
        }
        // Al crear, la primera condición contractual es obligatoria.
        $contrato = null;
        if (!$id) {
            $contrato = [
                'valid_from' => (string) ($_POST['valid_from'] ?? ''),
                'factor' => decimal_input('factor'),
                'contracted_kw' => decimal_input('contracted_kw'),
                'tolerance_pct' => decimal_input('tolerance_pct'),
            ];
            if (!DateTimeImmutable::createFromFormat('!Y-m-d', $contrato['valid_from'])) {
                $errores[] = 'Fecha "vigente desde" inválida.';
            }
            if (!$contrato['factor'] || $contrato['factor'] <= 0) {
                $errores[] = 'El factor multiplicador debe ser mayor a 0.';
            }
            if (!$contrato['contracted_kw'] || $contrato['contracted_kw'] <= 0) {
                $errores[] = 'La potencia contratada debe ser mayor a 0.';
            }
            if ($contrato['tolerance_pct'] === null || $contrato['tolerance_pct'] < 0 || $contrato['tolerance_pct'] > 100) {
                $errores[] = 'La tolerancia debe estar entre 0 y 100 %.';
            }
        }
        if ($errores) {
            flash('error', implode(' ', $errores));
            $_SESSION['form_supply'] = $_POST;
            redirect(app_url('supplies', ['action' => $id ? 'edit' : 'new', 'id' => $id ?: null]));
        }
        if ($id) {
            $anterior = supply_by_id($id);
            db()->prepare('UPDATE supplies SET nis=?, name=?, client=?, meter_prefix=?, channel=?, billing_day=?, active=?, notes=? WHERE id=?')
                ->execute([...array_values($datos), $id]);
            audit('supply.updated', 'supply', (string) $id, $datos);
            $cierreAnterior = $anterior['billing_day'] === null ? null : (int) $anterior['billing_day'];
            if ($cierreAnterior !== $datos['billing_day']) {
                // Cambió el día de cierre: se rearman todos los ciclos del histórico.
                $n = recompute_supply($id);
                flash('success', "Suministro actualizado. Con el nuevo día de cierre se recalcularon {$n} ciclo(s) del histórico.");
            } else {
                flash('success', 'Suministro actualizado.');
            }
        } else {
            db()->beginTransaction();
            db()->prepare('INSERT INTO supplies (nis, name, client, meter_prefix, channel, billing_day, active, notes) VALUES (?,?,?,?,?,?,?,?)')
                ->execute(array_values($datos));
            $id = (int) db()->lastInsertId();
            db()->prepare('INSERT INTO supply_contracts (supply_id, valid_from, factor, contracted_kw, tolerance_pct, notes, created_by)
                           VALUES (?,?,?,?,?,?,?)')
                ->execute([$id, $contrato['valid_from'], $contrato['factor'], $contrato['contracted_kw'], $contrato['tolerance_pct'],
                    'Condición inicial', Auth::id()]);
            db()->commit();
            audit('supply.created', 'supply', (string) $id, $datos + $contrato);
            flash('success', 'Suministro creado. El script lo va a descargar en su próxima corrida.');
        }
        redirect(app_url('supplies', ['action' => 'edit', 'id' => $id]));
    }

    if ($op === 'add_contract' && $id && supply_by_id($id)) {
        $c = [
            'valid_from' => (string) ($_POST['valid_from'] ?? ''),
            'factor' => decimal_input('factor'),
            'contracted_kw' => decimal_input('contracted_kw'),
            'tolerance_pct' => decimal_input('tolerance_pct'),
            'notes' => trim((string) ($_POST['notes'] ?? '')) ?: null,
        ];
        $ok = DateTimeImmutable::createFromFormat('!Y-m-d', $c['valid_from']) && $c['factor'] > 0 && $c['contracted_kw'] > 0
            && $c['tolerance_pct'] !== null && $c['tolerance_pct'] >= 0 && $c['tolerance_pct'] <= 100;
        if (!$ok) {
            flash('error', 'Revisá los datos de la condición contractual (fecha, factor, potencia y tolerancia).');
        } else {
            db()->prepare('INSERT INTO supply_contracts (supply_id, valid_from, factor, contracted_kw, tolerance_pct, notes, created_by)
                           VALUES (?,?,?,?,?,?,?)
                           ON DUPLICATE KEY UPDATE factor=VALUES(factor), contracted_kw=VALUES(contracted_kw),
                             tolerance_pct=VALUES(tolerance_pct), notes=VALUES(notes), created_by=VALUES(created_by)')
                ->execute([$id, $c['valid_from'], $c['factor'], $c['contracted_kw'], $c['tolerance_pct'], $c['notes'], Auth::id()]);
            $n = recompute_supply($id);
            audit('contract.saved', 'supply', (string) $id, $c);
            flash('success', "Condición contractual guardada. Se recalcularon {$n} ciclo(s) del histórico.");
        }
        redirect(app_url('supplies', ['action' => 'edit', 'id' => $id]));
    }

    if ($op === 'delete_contract' && $id) {
        $cid = (int) ($_POST['contract_id'] ?? 0);
        $cuantos = db()->prepare('SELECT COUNT(*) FROM supply_contracts WHERE supply_id = ?');
        $cuantos->execute([$id]);
        if ((int) $cuantos->fetchColumn() <= 1) {
            flash('error', 'No se puede borrar la única condición contractual del suministro.');
        } else {
            db()->prepare('DELETE FROM supply_contracts WHERE id = ? AND supply_id = ?')->execute([$cid, $id]);
            $n = recompute_supply($id);
            audit('contract.deleted', 'supply', (string) $id, ['contract_id' => $cid]);
            flash('success', "Condición eliminada. Se recalcularon {$n} ciclo(s).");
        }
        redirect(app_url('supplies', ['action' => 'edit', 'id' => $id]));
    }
    redirect(app_url('supplies'));
}

// ---------------- Formulario alta / edición ----------------
if ($action === 'new' || ($action === 'edit' && $id)) {
    $s = $id ? supply_by_id($id) : null;
    if ($id && !$s) {
        not_found();
    }
    $form = $_SESSION['form_supply'] ?? null;
    unset($_SESSION['form_supply']);
    $v = static fn (string $k, $def = '') => $form[$k] ?? ($s[$k] ?? $def);
    $contratos = $id ? supply_contracts($id) : [];
    render_header($s ? 'Editar suministro' : 'Nuevo suministro', 'supplies');
    ?>
    <div class="page-head"><div><a class="small" href="<?= e(app_url('supplies')) ?>">← Suministros</a>
      <h1><?= $s ? e($s['name']) . ' · NIS ' . e($s['nis']) : 'Nuevo suministro' ?></h1></div>
      <?php if ($s): ?><a class="button ghost" href="<?= e(app_url('supply', ['id' => $id])) ?>">Ver panel del suministro</a><?php endif; ?></div>

    <section class="card">
      <h2>Datos del suministro</h2>
      <form method="post" class="form-grid">
        <?= csrf_field() ?><input type="hidden" name="op" value="save_supply">
        <label>NIS / Punto de Medida en el MDC <input name="nis" value="<?= e($v('nis')) ?>" required></label>
        <label>Nombre <input name="name" value="<?= e($v('name')) ?>" required placeholder="Ej.: Planta industrial X"></label>
        <label>Cliente (opcional) <input name="client" value="<?= e($v('client')) ?>"></label>
        <label>Prefijo del medidor
          <input name="meter_prefix" value="<?= e($v('meter_prefix', 'EGM')) ?>">
          <span class="help">En el MDC se elige el medidor que empieza con esto (EGM…, o el número de serie de un ACE6000, p. ej. 0175). Con «Todos» se toman todos los medidores del punto.</span></label>
        <label>Día de cierre de facturación
          <input type="number" name="billing_day" min="1" max="31" value="<?= e($v('billing_day')) ?>" placeholder="Vacío = mes calendario">
          <span class="help">Ej.: con cierre 15, el ciclo de noviembre va del 16/10 al 15/11 (incluye el día 15).
            Vacío: del 1 al último día del mes. Si el mes no tiene ese día, cierra el último día.</span></label>
        <label class="full">Canal del MDC <input name="channel" list="canales-mdc" value="<?= e($v('channel', 'Sum Li Active Power + (QI+QIV) (last average 1)- 0 x')) ?>" required>
          <datalist id="canales-mdc">
            <option value="Sum Li Active Power + (QI+QIV) (last average 1)- 0 x">Medidores EGM: potencia (W)</option>
            <option value="Sum Li Active Power + (QI+QIV) (time integral 5) - 0">Actaris ACE6000: energía por intervalo (Wh)</option>
          </datalist>
          <span class="help">EGM: «(last average 1)», viene en W. Actaris ACE6000: «(time integral 5)», viene en Wh por intervalo y se convierte sola a potencia media (Wh × 4 en 15 min).</span></label>
        <?php if (!$s): ?>
          <fieldset class="full"><legend>Condición contractual inicial</legend>
            <div class="form-grid" style="margin-top:0">
              <label>Vigente desde <input type="date" name="valid_from" value="<?= e($form['valid_from'] ?? date('Y-m-01')) ?>" required></label>
              <label>Factor multiplicador <input name="factor" inputmode="decimal" value="<?= e($form['factor'] ?? '') ?>" placeholder="1815,78" required></label>
              <label>Potencia contratada (kW) <input name="contracted_kw" inputmode="decimal" value="<?= e($form['contracted_kw'] ?? '') ?>" placeholder="1520" required></label>
              <label>Tolerancia (%) <input name="tolerance_pct" inputmode="decimal" value="<?= e($form['tolerance_pct'] ?? '10') ?>" required></label>
            </div>
          </fieldset>
        <?php endif; ?>
        <label class="full">Notas <textarea name="notes" rows="2"><?= e($v('notes')) ?></textarea></label>
        <label class="check"><input type="checkbox" name="active" value="1"<?= $v('active', 1) ? ' checked' : '' ?>> Activo (el script lo descarga todos los días)</label>
        <div class="full"><button class="button" type="submit"><?= $s ? 'Guardar cambios' : 'Crear suministro' ?></button></div>
      </form>
    </section>

    <?php if ($s): ?>
    <section class="card">
      <h2>Condiciones contractuales</h2>
      <div class="nota">Si cambia la potencia contratada, el factor o la tolerancia, agregá una condición nueva con su fecha de vigencia:
        las lecturas anteriores se siguen evaluando con la condición de su momento. Al guardar se recalcula todo el histórico.</div>
      <div class="tabla-scroll"><table>
        <thead><tr><th>Vigente desde</th><th class="n">Factor</th><th class="n">Contratada kW</th><th class="n">Tolerancia</th><th class="n">Límite kW</th><th>Nota</th><th></th></tr></thead>
        <tbody>
        <?php foreach (array_reverse($contratos) as $c): ?>
          <tr><td><?= e(date('d/m/Y', strtotime((string) $c['valid_from']))) ?></td><td class="n"><?= num($c['factor'], 4) ?></td>
            <td class="n"><?= num($c['contracted_kw'], 2) ?></td><td class="n"><?= num($c['tolerance_pct'], 2) ?> %</td>
            <td class="n"><?= num(contract_limit($c), 2) ?></td><td><?= e($c['notes']) ?></td>
            <td><?php if (count($contratos) > 1): ?>
              <form method="post" onsubmit="return confirm('¿Borrar esta condición? Se recalcula el histórico.')"><?= csrf_field() ?>
                <input type="hidden" name="op" value="delete_contract"><input type="hidden" name="contract_id" value="<?= (int) $c['id'] ?>">
                <button class="button danger small">Borrar</button></form><?php endif; ?></td></tr>
        <?php endforeach; ?>
        </tbody>
      </table></div>
      <form method="post" class="form-grid">
        <?= csrf_field() ?><input type="hidden" name="op" value="add_contract">
        <label>Vigente desde <input type="date" name="valid_from" value="<?= e(date('Y-m-01')) ?>" required></label>
        <label>Factor <input name="factor" inputmode="decimal" value="<?= e(rtrim(rtrim((string) (end($contratos)['factor'] ?? ''), '0'), '.')) ?>" required></label>
        <label>Potencia contratada (kW) <input name="contracted_kw" inputmode="decimal" required></label>
        <label>Tolerancia (%) <input name="tolerance_pct" inputmode="decimal" value="<?= e(rtrim(rtrim((string) (end($contratos)['tolerance_pct'] ?? '10'), '0'), '.')) ?>" required></label>
        <label class="full">Nota <span class="help">(ej.: "Ampliación de potencia, resolución N°...")</span><input name="notes"></label>
        <div class="full"><button class="button" type="submit">Agregar condición</button></div>
      </form>
    </section>
    <?php endif;
    render_footer();
    exit;
}

// ---------------- Listado ----------------
$lista = db()->query(
    "SELECT s.*,
       (SELECT contracted_kw FROM supply_contracts c WHERE c.supply_id = s.id ORDER BY valid_from DESC LIMIT 1) AS contracted_kw,
       (SELECT tolerance_pct FROM supply_contracts c WHERE c.supply_id = s.id ORDER BY valid_from DESC LIMIT 1) AS tolerance_pct,
       (SELECT factor FROM supply_contracts c WHERE c.supply_id = s.id ORDER BY valid_from DESC LIMIT 1) AS factor,
       (SELECT MAX(created_at) FROM import_runs i WHERE i.supply_id = s.id) AS last_import,
       (SELECT COUNT(*) FROM user_supply_permissions p WHERE p.supply_id = s.id) AS users_count
     FROM supplies s ORDER BY s.active DESC, s.name"
)->fetchAll();
render_header('Suministros', 'supplies');
?>
<div class="page-head">
  <div><h1>Suministros</h1><div class="muted small">Los activos se descargan del MDC todos los días. Para agregar uno nuevo no hace falta tocar el script.</div></div>
  <a class="button" href="<?= e(app_url('supplies', ['action' => 'new'])) ?>">+ Agregar suministro</a>
</div>
<section class="card"><div class="tabla-scroll"><table>
  <thead><tr><th>Nombre</th><th>NIS</th><th>Medidor</th><th class="n">Factor</th><th class="n">Contratada kW</th><th class="n">Tolerancia</th>
    <th>Cierre</th><th>Último envío</th><th class="n">Usuarios</th><th>Estado</th><th></th></tr></thead>
  <tbody>
  <?php foreach ($lista as $s): ?>
    <tr><td><?= e($s['name']) ?><?php if ($s['client']): ?><br><span class="muted small"><?= e($s['client']) ?></span><?php endif; ?></td>
      <td><?= e($s['nis']) ?></td><td><?= e($s['meter_serial'] ?: $s['meter_prefix'] . '…') ?></td>
      <td class="n"><?= num($s['factor'], 2) ?></td><td class="n"><?= num($s['contracted_kw']) ?></td><td class="n"><?= num($s['tolerance_pct'], 1) ?> %</td>
      <td class="small"><?= $s['billing_day'] ? 'Día ' . (int) $s['billing_day'] : '<span class="muted">Mes calendario</span>' ?></td>
      <td class="small"><?= e(fecha_hora($s['last_import'])) ?></td><td class="n"><?= (int) $s['users_count'] ?></td>
      <td><?= $s['active'] ? '<span class="badge good">Activo</span>' : '<span class="badge off">Inactivo</span>' ?></td>
      <td><a class="button ghost small" href="<?= e(app_url('supplies', ['action' => 'edit', 'id' => $s['id']])) ?>">Editar</a></td></tr>
  <?php endforeach; ?>
  <?php if (!$lista): ?><tr><td colspan="11" class="muted">Todavía no hay suministros.</td></tr><?php endif; ?>
  </tbody>
</table></div></section>
<?php render_footer();
