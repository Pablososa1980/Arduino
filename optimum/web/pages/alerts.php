<?php
declare(strict_types=1);

/* Todas las veces que se superó el límite, en los suministros visibles para el usuario. */
$supplies = Auth::supplies(true);
$ids = array_map(static fn ($s) => (int) $s['id'], $supplies);
$id = (int) ($_GET['id'] ?? 0);
if ($id && !in_array($id, $ids, true)) {
    forbidden();
}
$filtro = $id ? [$id] : $ids;
$alertas = [];
if ($filtro) {
    $alertas = db()->query(
        'SELECT a.*, s.name, s.nis, s.billing_day FROM alerts a JOIN supplies s ON s.id = a.supply_id
         WHERE a.supply_id IN (' . implode(',', $filtro) . ') ORDER BY a.ts DESC LIMIT 500'
    )->fetchAll();
}
render_header('Alertas', 'alerts');
?>
<div class="page-head">
  <div><h1>Alertas</h1><div class="muted small">Intervalos de 15 minutos que superaron la potencia contratada más su tolerancia (últimos 500).</div></div>
  <?= $supplies ? supply_select($supplies, $id ?: null, 'alerts', [], true) : '' ?>
</div>
<section class="card">
  <?php if (!$alertas): ?>
    <div class="estado good" style="margin:0"><div><strong>Sin alertas</strong><span>No se registraron excesos sobre el límite.</span></div></div>
  <?php else: ?>
  <div class="tabla-scroll"><table>
    <thead><tr><th>Fecha y hora</th><th>Suministro</th><th class="n">kW</th><th class="n">Contratada</th><th class="n">Límite</th><th class="n">Exceso</th><th>Aviso por correo</th></tr></thead>
    <tbody>
    <?php foreach ($alertas as $a): ?>
      <tr>
        <td><a href="<?= e(app_url('supply', ['id' => $a['supply_id'], 'period' => period_of($a['billing_day'] === null ? null : (int) $a['billing_day'], (string) $a['ts'])])) ?>"><?= e(fecha_hora($a['ts'])) ?></a></td>
        <td><?= e($a['name']) ?> <span class="muted small">NIS <?= e($a['nis']) ?></span></td>
        <td class="n"><?= num($a['kw'], 1) ?></td><td class="n"><?= num($a['contracted_kw']) ?></td><td class="n"><?= num($a['limit_kw']) ?></td>
        <td class="n"><b style="color:var(--critical-text)">+<?= num((float) $a['kw'] - (float) $a['limit_kw'], 1) ?> kW</b></td>
        <td class="muted small"><?= e(fecha_hora($a['notified_at'])) ?></td>
      </tr>
    <?php endforeach; ?>
    </tbody>
  </table></div>
  <?php endif; ?>
</section>
<?php render_footer();
