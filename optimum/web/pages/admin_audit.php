<?php
declare(strict_types=1);

/* Registro de auditoría y últimos envíos del script (solo admin). */
Auth::requireAdmin();

$eventos = db()->query(
    'SELECT a.*, u.username FROM audit_logs a LEFT JOIN users u ON u.id = a.user_id ORDER BY a.id DESC LIMIT 300'
)->fetchAll();
$envios = db()->query(
    'SELECT i.*, s.name, s.nis FROM import_runs i JOIN supplies s ON s.id = i.supply_id ORDER BY i.id DESC LIMIT 50'
)->fetchAll();
render_header('Auditoría', 'audit');
?>
<div class="page-head"><div><h1>Auditoría</h1><div class="muted small">Envíos del script y acciones de los usuarios.</div></div></div>

<section class="card">
  <h2>Últimos envíos del script</h2>
  <div class="tabla-scroll"><table>
    <thead><tr><th>Recibido</th><th>Suministro</th><th>Período</th><th class="n">Lecturas</th><th class="n">Nuevas</th><th class="n">Actualizadas</th><th class="n">Alertas</th><th>Archivo</th></tr></thead><tbody>
    <?php foreach ($envios as $i): ?>
      <tr><td class="small"><?= e(fecha_hora($i['created_at'])) ?></td><td><?= e($i['name']) ?> <span class="muted small">NIS <?= e($i['nis']) ?></span></td>
        <td class="small"><?= e(date('d/m', strtotime((string) $i['period_start']))) ?> – <?= e(date('d/m/Y', strtotime((string) $i['period_end']))) ?></td>
        <td class="n"><?= num($i['readings_count']) ?></td><td class="n"><?= num($i['inserted_count']) ?></td><td class="n"><?= num($i['updated_count']) ?></td>
        <td class="n"><?= (int) $i['new_alerts'] ?></td><td class="small muted"><?= e($i['source_file']) ?></td></tr>
    <?php endforeach; ?>
    <?php if (!$envios): ?><tr><td colspan="8" class="muted">Todavía no llegó ningún envío.</td></tr><?php endif; ?>
  </tbody></table></div>
</section>

<section class="card">
  <h2>Acciones</h2>
  <div class="tabla-scroll"><table>
    <thead><tr><th>Fecha</th><th>Usuario</th><th>Acción</th><th>Objeto</th><th>IP</th><th>Detalle</th></tr></thead><tbody>
    <?php foreach ($eventos as $ev): ?>
      <tr><td class="small"><?= e(fecha_hora($ev['created_at'])) ?></td><td><?= e($ev['username'] ?? '—') ?></td><td><code><?= e($ev['action']) ?></code></td>
        <td class="small"><?= e(trim(($ev['entity_type'] ?? '') . ' ' . ($ev['entity_id'] ?? ''))) ?></td><td class="small"><?= e($ev['ip_address']) ?></td>
        <td class="small muted" style="max-width:420px;overflow-wrap:anywhere"><?= e(mb_strimwidth((string) $ev['detail_text'], 0, 200, '…')) ?></td></tr>
    <?php endforeach; ?>
  </tbody></table></div>
</section>
<?php render_footer();
