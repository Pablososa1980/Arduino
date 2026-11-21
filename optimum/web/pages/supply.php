<?php
declare(strict_types=1);

/* Detalle mensual de un suministro: KPIs, curva de 15 min, máximos diarios, excesos. */
$id = (int) ($_GET['id'] ?? 0);
$stmt = db()->prepare('SELECT * FROM supplies WHERE id = ?');
$stmt->execute([$id]);
$s = $stmt->fetch();
if (!$s) {
    not_found('El suministro no existe.');
}
if (!Auth::canSupply($id)) {
    forbidden();
}

$billing = $s['billing_day'] === null ? null : (int) $s['billing_day'];
$periodos = db()->prepare('SELECT period FROM monthly_summaries WHERE supply_id = ? ORDER BY period DESC');
$periodos->execute([$id]);
$periodos = $periodos->fetchAll(PDO::FETCH_COLUMN);
$period = is_string($_GET['period'] ?? null) && preg_match('/^\d{4}-\d{2}$/', $_GET['period']) ? $_GET['period'] : ($periodos[0] ?? null);
if ($period !== null && $periodos && !in_array($period, $periodos, true)) {
    not_found('No hay datos ' . period_phrase($billing, $period) . ' para este suministro.');
}

$r = null;
$serie = [];
if ($period) {
    $q = db()->prepare('SELECT * FROM monthly_summaries WHERE supply_id = ? AND period = ?');
    $q->execute([$id, $period]);
    $r = $q->fetch();
    $serie = month_series($id, $period);
}
$contratos = supply_contracts($id);
$puedeDescargar = Auth::canSupply($id, true);

$excesos = [];
$top = [];
if ($period) {
    $q = db()->prepare('SELECT * FROM alerts WHERE supply_id = ? AND ts >= ? AND ts < ? ORDER BY ts');
    $q->execute([$id, ...cycle_range($billing, $period)]);
    $excesos = $q->fetchAll();
    $validos = array_values(array_filter($serie, static fn ($p) => $p['kw'] !== null));
    usort($validos, static fn ($a, $b) => $b['kw'] <=> $a['kw']);
    $top = array_slice($validos, 0, 10);
}

render_header($s['name'], 'dashboard');
$estado = $r['status'] ?? 'sin_datos';
$cls = ESTADOS[$estado][1];
$margen = $r && $r['max_kw'] !== null ? (float) $r['limit_kw'] - (float) $r['max_kw'] : null;
?>
<div class="page-head">
  <div>
    <a href="<?= e(app_url('dashboard')) ?>" class="small">← Todos los suministros</a>
    <h1><?= e($s['name']) ?> · NIS <?= e($s['nis']) ?></h1>
    <div class="muted small">
      <?= $s['client'] ? e($s['client']) . ' · ' : '' ?>Medidor <?= e($s['meter_serial'] ?: '—') ?>
      · <?= $billing ? 'Cierre día ' . $billing : 'Mes calendario' ?>
      <?php if ($r): ?> · Factor <?= num(contract_for($contratos, substr((string) $r['last_ts'], 0, 10))['factor'] ?? null, 2) ?>
      · Contratada <b><?= num($r['contracted_kw']) ?> kW</b> · Tolerancia <b><?= num($r['tolerance_pct']) ?> %</b> (límite <b><?= num($r['limit_kw']) ?> kW</b>)<?php endif; ?>
    </div>
  </div>
  <div class="inline-form">
    <?php if ($periodos): ?>
    <form method="get" class="inline-form">
      <input type="hidden" name="page" value="supply"><input type="hidden" name="id" value="<?= $id ?>">
      <label><?= $billing ? 'Ciclo de facturación' : 'Período' ?> <select name="period" onchange="this.form.submit()">
        <?php foreach ($periodos as $p): ?><option value="<?= e($p) ?>"<?= $p === $period ? ' selected' : '' ?>><?= e(ucfirst(period_label($billing, $p))) ?></option><?php endforeach; ?>
      </select></label>
      <noscript><button class="button small">Ver</button></noscript>
    </form>
    <?php endif; ?>
    <?php if ($puedeDescargar && $period): ?>
      <a class="button ghost" href="<?= e(app_url('download', ['id' => $id, 'period' => $period])) ?>">Descargar Excel</a>
    <?php endif; ?>
    <a class="button ghost" href="<?= e(app_url('history', ['id' => $id])) ?>">Histórico</a>
  </div>
</div>

<?php if (!$r): ?>
  <section class="card"><h2>Sin lecturas todavía</h2><p class="muted">Cuando el script diario envíe datos de este suministro, aparecen acá.</p></section>
<?php else:
  $msg = [
      'normal' => 'La demanda máxima ' . period_phrase($billing, $period) . ' (' . num($r['max_kw']) . ' kW) está por debajo de la potencia contratada. Margen hasta el límite: ' . num($margen) . ' kW.',
      'atencion' => 'La demanda superó la contratada en ' . (int) $r['over_contract_count'] . ' intervalo(s), sin pasar el límite de tolerancia (' . num($r['limit_kw']) . ' kW).',
      'critico' => 'Se superó el límite de tolerancia (' . num($r['limit_kw']) . ' kW) en ' . (int) $r['over_limit_count'] . ' intervalo(s). Máximo: ' . num($r['max_kw']) . ' kW, exceso de potencia de ' . num((float) $r['max_kw'] - (float) $r['contracted_kw'], 1) . ' kW sobre la contratada (' . num($r['contracted_kw']) . ' kW).',
      'sin_datos' => 'Sin lecturas válidas en el período.',
  ][$estado]; ?>
  <div class="estado <?= $cls ?>"><div><strong><?= e(ESTADOS[$estado][0]) ?></strong><span><?= e($msg) ?></span></div></div>

  <div class="kpis">
    <div class="kpi"><div class="l">Demanda máxima</div><div class="v"><?= num($r['max_kw']) ?><small>kW</small></div>
      <div class="d"><?= num((float) $r['max_kw'] / (float) $r['contracted_kw'] * 100, 1) ?> % · <?= e(fecha_hora($r['max_ts'])) ?></div></div>
    <?php if ($margen >= 0): ?>
    <div class="kpi"><div class="l">Margen hasta el límite</div>
      <div class="v"><?= num($margen) ?><small>kW</small></div><div class="d">Límite <?= num($r['limit_kw']) ?> kW</div></div>
    <?php else: ?>
    <div class="kpi"><div class="l">Exceso de potencia</div>
      <div class="v" style="color:var(--critical-text)"><?= num((float) $r['max_kw'] - (float) $r['contracted_kw'], 1) ?><small>kW</small></div>
      <div class="d">Máxima − contratada (<?= num($r['contracted_kw']) ?> kW). Superó el límite de <?= num($r['limit_kw']) ?> kW</div></div>
    <?php endif; ?>
    <div class="kpi"><div class="l">Energía del período</div><div class="v"><?= num((float) $r['energy_kwh'] / 1000, 1) ?><small>MWh</small></div>
      <div class="d">Promedio <?= num($r['avg_kw']) ?> kW</div></div>
    <div class="kpi"><div class="l">Factor de carga</div><div class="v"><?= $r['max_kw'] > 0 ? num((float) $r['avg_kw'] / (float) $r['max_kw'] * 100, 1) : '—' ?><small>%</small></div>
      <div class="d">Promedio ÷ máxima</div></div>
    <div class="kpi"><div class="l">Intervalos sobre la contratada</div><div class="v"><?= (int) $r['over_contract_count'] ?></div>
      <div class="d">De <?= num((int) $r['readings_count'] - (int) $r['gap_count']) ?> lecturas válidas</div></div>
    <div class="kpi"><div class="l">Intervalos sobre el límite</div><div class="v"><?= (int) $r['over_limit_count'] ?></div>
      <div class="d"><?= (int) $r['over_limit_count'] ? 'Generan alerta' : 'Sin alertas' ?></div></div>
    <div class="kpi"><div class="l">Huecos sin lectura</div><div class="v"><?= (int) $r['gap_count'] ?></div>
      <div class="d"><?= $r['readings_count'] ? num((int) $r['gap_count'] / (int) $r['readings_count'] * 100, 1) : 0 ?> % del período</div></div>
  </div>

  <section class="card">
    <h2>Curva de carga</h2>
    <div class="nota">Demanda en kW cada 15 minutos (valor del medidor × factor). Los huecos sin lectura quedan cortados.</div>
    <div class="rango" id="rango">
      <button type="button" data-r="todo" aria-pressed="true"><?= $billing ? 'Todo el ciclo' : 'Todo el mes' ?></button>
      <button type="button" data-r="7" aria-pressed="false">Últimos 7 días</button>
      <button type="button" data-r="2" aria-pressed="false">Últimas 48 h</button>
    </div>
    <div class="leyenda">
      <span><span class="dot" style="background:var(--series)"></span>Demanda (kW)</span>
      <span><svg width="22" height="8"><line x1="0" x2="22" y1="4" y2="4" stroke="var(--text-2)" stroke-width="1.5" stroke-dasharray="6 4"/></svg>Potencia contratada</span>
      <span><svg width="22" height="8"><line x1="0" x2="22" y1="4" y2="4" stroke="var(--critical)" stroke-width="1.5" stroke-dasharray="6 4"/></svg>Límite de tolerancia</span>
      <?php if ($excesos): ?><span><span class="dot" style="background:var(--critical)"></span>Intervalo sobre el límite</span><?php endif; ?>
    </div>
    <div class="chart" id="curva"></div>
  </section>

  <section class="card">
    <h2>Demanda máxima diaria</h2>
    <div class="nota">El pico de cada día frente a la potencia contratada y el límite.</div>
    <div class="leyenda">
      <span><span class="dot" style="border-radius:2px;background:var(--series)"></span>Normal</span>
      <span><span class="dot" style="border-radius:2px;background:var(--warning)"></span>Sobre la contratada</span>
      <span><span class="dot" style="border-radius:2px;background:var(--critical)"></span>Supera la tolerancia</span>
    </div>
    <div class="chart" id="diario"></div>
  </section>

  <details<?= $excesos ? ' open' : '' ?>><summary>Intervalos que superaron el límite (<?= count($excesos) ?: 'ninguno' ?>)</summary>
    <?php if ($excesos): ?><div class="tabla-scroll"><table>
      <thead><tr><th>Fecha y hora</th><th class="n">kW</th><th class="n">Contratada kW</th><th class="n">Límite kW</th><th class="n">Exceso de potencia</th><th class="n">% contratada</th></tr></thead><tbody>
      <?php foreach ($excesos as $a): ?><tr><td><?= e(fecha_hora($a['ts'])) ?></td><td class="n"><?= num($a['kw'], 1) ?></td>
        <td class="n"><?= num($a['contracted_kw']) ?></td><td class="n"><?= num($a['limit_kw']) ?></td>
        <td class="n"><b style="color:var(--critical-text)">+<?= num((float) $a['kw'] - (float) $a['contracted_kw'], 1) ?> kW</b></td>
        <td class="n"><?= num((float) $a['kw'] / (float) $a['contracted_kw'] * 100, 1) ?></td></tr><?php endforeach; ?>
    </tbody></table></div>
    <?php else: ?><p class="muted">No hubo intervalos por encima del límite en el período.</p><?php endif; ?>
  </details>
  <details><summary>Las 10 demandas más altas</summary><div class="tabla-scroll"><table>
    <thead><tr><th>Fecha y hora</th><th class="n">kW</th><th>Estado</th></tr></thead><tbody>
    <?php foreach ($top as $p): ?><tr><td><?= e(fecha_hora($p['ts'])) ?></td><td class="n"><?= num($p['kw'], 1) ?></td><td><?= estado_badge($p['estado']) ?></td></tr><?php endforeach; ?>
  </tbody></table></div></details>

  <?= json_script('datos-mes', [
      'puntos' => array_map(static fn ($p) => [$p['ts'], $p['kw'] === null ? null : round($p['kw'], 1), $p['estado']], $serie),
      'contratada' => (float) $r['contracted_kw'],
      'limite' => (float) $r['limit_kw'],
      'tolerancia' => (float) $r['tolerance_pct'],
      'diario' => json_decode((string) $r['daily_json'], true) ?: [],
  ]) ?>
  <script src="assets/charts.js?v=3"></script>
<?php endif; ?>
<?php render_footer();
