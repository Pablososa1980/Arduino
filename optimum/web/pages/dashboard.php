<?php
declare(strict_types=1);

/* Portada: una tarjeta por suministro visible, con su ciclo de facturación más reciente. */
$supplies = Auth::supplies();
$resumenes = [];
if ($supplies) {
    $ids = implode(',', array_map(static fn ($s) => (int) $s['id'], $supplies));
    $filas = db()->query(
        "SELECT ms.* FROM monthly_summaries ms
         JOIN (SELECT supply_id, MAX(period) AS period FROM monthly_summaries WHERE supply_id IN ({$ids}) GROUP BY supply_id) ult
           ON ult.supply_id = ms.supply_id AND ult.period = ms.period"
    )->fetchAll();
    foreach ($filas as $f) {
        $resumenes[(int) $f['supply_id']] = $f;
    }
}
$orden = ['critico' => 0, 'atencion' => 1, 'normal' => 2, 'sin_datos' => 3];
usort($supplies, static function ($a, $b) use ($resumenes, $orden) {
    $ea = $orden[$resumenes[(int) $a['id']]['status'] ?? 'sin_datos'];
    $eb = $orden[$resumenes[(int) $b['id']]['status'] ?? 'sin_datos'];
    return [$ea, $a['name']] <=> [$eb, $b['name']];
});
$criticos = count(array_filter($resumenes, static fn ($r) => $r['status'] === 'critico'));
$ultimaImportacion = db()->query('SELECT MAX(created_at) FROM import_runs')->fetchColumn();

render_header('Inicio', 'dashboard');
?>
<div class="page-head">
  <div><h1>Suministros</h1><div class="muted">Demanda máxima del ciclo de facturación en curso, comparada con la potencia contratada y su tolerancia.</div></div>
  <div class="muted small">Última actualización de datos: <?= e(fecha_hora($ultimaImportacion ?: null)) ?></div>
</div>

<?php if (!$supplies): ?>
  <section class="card">
    <h2>No hay suministros para mostrar</h2>
    <?php if (Auth::isAdmin()): ?>
      <p class="muted">Empezá dando de alta el primer suministro con su factor y potencia contratada.</p>
      <a class="button" href="<?= e(app_url('supplies', ['action' => 'new'])) ?>">Agregar suministro</a>
    <?php else: ?>
      <p class="muted">Todavía no tenés suministros asignados. Pedile acceso al administrador.</p>
    <?php endif; ?>
  </section>
<?php else: ?>
  <?php if ($criticos): ?>
    <div class="estado critical"><div><strong><?= $criticos ?> suministro(s) superan la tolerancia en el ciclo actual</strong><span>Revisá el detalle de los marcados en rojo.</span></div></div>
  <?php elseif ($resumenes): ?>
    <div class="estado good"><div><strong>Todos los suministros dentro de la tolerancia</strong><span><?= count($supplies) ?> suministro(s) monitoreado(s).</span></div></div>
  <?php endif; ?>

  <section class="suministros">
  <?php foreach ($supplies as $s):
      $r = $resumenes[(int) $s['id']] ?? null;
      $estado = $r['status'] ?? 'sin_datos';
      $cls = ESTADOS[$estado][1];
      $diario = $r ? (json_decode((string) $r['daily_json'], true) ?: []) : [];
      $margen = $r && $r['limit_kw'] !== null && $r['max_kw'] !== null ? (float) $r['limit_kw'] - (float) $r['max_kw'] : null; ?>
    <article class="suministro <?= $cls ?>">
      <div class="cab">
        <div><div class="muted small">NIS <?= e($s['nis']) ?><?= $s['meter_serial'] ? ' · Medidor ' . e($s['meter_serial']) : '' ?></div>
          <h2><?= e($s['name']) ?></h2><?php if ($s['client']): ?><div class="muted small"><?= e($s['client']) ?></div><?php endif; ?></div>
        <?= estado_badge($estado) ?>
      </div>
      <?php if ($r): ?>
        <div class="fila">
          <div><div class="muted small">Demanda máxima · <?= e(period_label($s['billing_day'] === null ? null : (int) $s['billing_day'], $r['period'], true)) ?></div>
            <div class="v"><?= num($r['max_kw']) ?><small>kW</small></div>
            <div class="muted small"><?= $r['contracted_kw'] ? num((float) $r['max_kw'] / (float) $r['contracted_kw'] * 100, 1) . ' % de la contratada' : '' ?></div></div>
          <div><div class="muted small">Contratada / límite</div>
            <div class="v"><?= num($r['contracted_kw']) ?><small>/ <?= num($r['limit_kw']) ?> kW</small></div>
            <div class="muted small">Tolerancia <?= num($r['tolerance_pct']) ?> %</div></div>
        </div>
        <div class="muted small">Máximos diarios del ciclo</div>
        <?= mini_barras($diario, $r['limit_kw'] !== null ? (float) $r['limit_kw'] : null, $r['contracted_kw'] !== null ? (float) $r['contracted_kw'] : null) ?>
        <div class="small"><?php if ($margen !== null && $margen >= 0): ?>Margen hasta el límite: <b><?= num($margen) ?> kW</b>
          <?php elseif ($margen !== null): ?><b style="color:var(--critical-text)">Exceso de potencia: <?= num((float) $r['max_kw'] - (float) $r['contracted_kw']) ?> kW</b><?php endif; ?>
          · Intervalos sobre el límite: <b><?= (int) $r['over_limit_count'] ?></b></div>
        <div class="muted small">Datos hasta <?= e(fecha_hora($r['last_ts'])) ?></div>
      <?php else: ?>
        <p class="muted small">Todavía no llegaron lecturas de este suministro.</p>
      <?php endif; ?>
      <div class="acciones">
        <a class="button small" href="<?= e(app_url('supply', ['id' => $s['id']])) ?>">Ver detalle</a>
        <a class="button ghost small" href="<?= e(app_url('history', ['id' => $s['id']])) ?>">Histórico</a>
      </div>
    </article>
  <?php endforeach; ?>
  </section>
<?php endif; ?>
<?php render_footer();
