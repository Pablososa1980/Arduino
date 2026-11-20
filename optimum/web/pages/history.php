<?php
declare(strict_types=1);

/* Histórico mensual de un suministro: máximo de cada mes vs. límite, y condiciones contractuales. */
$supplies = Auth::supplies(true);
if (!$supplies) {
    render_header('Histórico', 'history');
    echo '<section class="card"><h2>Sin suministros</h2><p class="muted">No hay suministros para mostrar.</p></section>';
    render_footer();
    exit;
}
$id = (int) ($_GET['id'] ?? $supplies[0]['id']);
$s = null;
foreach ($supplies as $x) {
    if ((int) $x['id'] === $id) {
        $s = $x;
    }
}
if (!$s) {
    Auth::canSupply($id) ? not_found() : forbidden();
}

$q = db()->prepare('SELECT * FROM monthly_summaries WHERE supply_id = ? ORDER BY period');
$q->execute([$id]);
$meses = $q->fetchAll();
$contratos = supply_contracts($id);

render_header('Histórico ' . $s['name'], 'history');
?>
<div class="page-head">
  <div><h1>Histórico · <?= e($s['name']) ?></h1><div class="muted small">NIS <?= e($s['nis']) ?> · Máxima demanda de cada mes frente al límite vigente.</div></div>
  <?= supply_select($supplies, $id, 'history') ?>
</div>

<?php if (!$meses): ?>
  <section class="card"><p class="muted">Todavía no hay meses con datos.</p></section>
<?php else: ?>
  <section class="card">
    <h2>Demanda máxima por mes</h2>
    <div class="nota">Clic en una barra para ver el detalle del mes. Sobre cada barra, las marcas punteadas muestran la contratada (gris) y el límite (rojo) que regían ese mes.</div>
    <div class="leyenda">
      <span><svg width="22" height="8"><line x1="0" x2="22" y1="4" y2="4" stroke="var(--text-2)" stroke-width="2" stroke-dasharray="5 3"/></svg>Contratada del mes</span>
      <span><svg width="22" height="8"><line x1="0" x2="22" y1="4" y2="4" stroke="var(--critical)" stroke-width="2" stroke-dasharray="5 3"/></svg>Límite del mes</span>
    </div>
    <div class="chart" id="mensual"></div>
  </section>

  <section class="card">
    <h2>Meses</h2>
    <div class="tabla-scroll"><table>
      <thead><tr><th>Mes</th><th class="n">Máx. kW</th><th>Fecha del máximo</th><th class="n">Contratada</th><th class="n">Límite</th>
        <th class="n">% contr.</th><th class="n">Energía MWh</th><th class="n">Sobre límite</th><th class="n">Huecos</th><th>Estado</th></tr></thead>
      <tbody>
      <?php foreach (array_reverse($meses) as $m): ?>
        <tr>
          <td><a href="<?= e(app_url('supply', ['id' => $id, 'period' => $m['period']])) ?>"><?= e(ucfirst(mes_texto($m['period']))) ?></a></td>
          <td class="n"><?= num($m['max_kw'], 1) ?></td><td><?= e(fecha_hora($m['max_ts'])) ?></td>
          <td class="n"><?= num($m['contracted_kw']) ?></td><td class="n"><?= num($m['limit_kw']) ?></td>
          <td class="n"><?= $m['contracted_kw'] && $m['max_kw'] !== null ? num((float) $m['max_kw'] / (float) $m['contracted_kw'] * 100, 1) : '—' ?></td>
          <td class="n"><?= num((float) $m['energy_kwh'] / 1000, 1) ?></td>
          <td class="n"><?= (int) $m['over_limit_count'] ?></td><td class="n"><?= (int) $m['gap_count'] ?></td>
          <td><?= estado_badge($m['status']) ?></td>
        </tr>
      <?php endforeach; ?>
      </tbody>
    </table></div>
  </section>
  <?= json_script('datos-historico', ['meses' => array_map(static fn ($m) => [
      'period' => $m['period'], 'max_kw' => (float) $m['max_kw'], 'limit_kw' => (float) $m['limit_kw'],
      'contracted_kw' => (float) $m['contracted_kw'], 'tolerance_pct' => (float) $m['tolerance_pct'],
      'status' => $m['status'], 'href' => app_url('supply', ['id' => $id, 'period' => $m['period']]),
  ], array_values(array_filter($meses, static fn ($m) => $m['max_kw'] !== null)))]) ?>
  <script src="assets/charts.js?v=2"></script>
<?php endif; ?>

<section class="card">
  <h2>Condiciones contractuales</h2>
  <div class="nota">Cada mes se evalúa con la condición vigente en esa fecha.</div>
  <div class="tabla-scroll"><table>
    <thead><tr><th>Vigente desde</th><th class="n">Factor</th><th class="n">Contratada kW</th><th class="n">Tolerancia</th><th class="n">Límite kW</th><th>Nota</th></tr></thead>
    <tbody>
    <?php foreach (array_reverse($contratos) as $c): ?>
      <tr><td><?= e(date('d/m/Y', strtotime((string) $c['valid_from']))) ?></td><td class="n"><?= num($c['factor'], 2) ?></td>
        <td class="n"><?= num($c['contracted_kw']) ?></td><td class="n"><?= num($c['tolerance_pct'], 1) ?> %</td>
        <td class="n"><?= num(contract_limit($c)) ?></td><td><?= e($c['notes']) ?></td></tr>
    <?php endforeach; ?>
    </tbody>
  </table></div>
</section>
<?php render_footer();
