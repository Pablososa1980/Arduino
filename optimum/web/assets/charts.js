/* Gráficos del panel (SVG puro, sin librerías ni CDN: funciona aunque la red bloquee CDNs). */
(function () {
  'use strict';
  const NS = 'http://www.w3.org/2000/svg';
  const NF = (n, d = 1) => Number(n).toLocaleString('es-PY', { minimumFractionDigits: d, maximumFractionDigits: d });
  const F0 = n => NF(n, 0);
  const aFecha = s => typeof s === 'number' ? new Date(s) : new Date(String(s).replace(' ', 'T'));
  const fechaLarga = s => { const d = aFecha(s);
    return d.toLocaleDateString('es-PY', { weekday: 'short', day: '2-digit', month: '2-digit', year: 'numeric' }) + ' ' +
      d.toLocaleTimeString('es-PY', { hour: '2-digit', minute: '2-digit', hour12: false }); };
  const ESTADOS = {
    normal: { txt: 'Normal', color: '--good', barra: '--series' },
    atencion: { txt: 'Sobre la contratada (dentro de tolerancia)', color: '--warning', barra: '--warning' },
    critico: { txt: 'Supera la tolerancia', color: '--critical', barra: '--critical' },
  };
  const MESES = ['ene', 'feb', 'mar', 'abr', 'may', 'jun', 'jul', 'ago', 'sep', 'oct', 'nov', 'dic'];

  function el(tag, attrs = {}, parent) { const e = document.createElementNS(NS, tag);
    for (const k in attrs) e.setAttribute(k, attrs[k]); if (parent) parent.appendChild(e); return e; }
  function niceStep(v) { const p = Math.pow(10, Math.floor(Math.log10(v || 1))); const n = v / p;
    return (n <= 1 ? 1 : n <= 2 ? 2 : n <= 2.5 ? 2.5 : n <= 5 ? 5 : 10) * p; }
  function escala(vmax) { const s = niceStep(vmax / 5); return { step: s, max: Math.ceil(vmax / s) * s }; }
  function ejeY(svg, y, w, m, esc) {
    const g = el('g', { class: 'grid' }, svg), a = el('g', { class: 'axis' }, svg);
    for (let v = 0; v <= esc.max + 1e-9; v += esc.step) {
      el('line', { x1: m.l, x2: w - m.r, y1: y(v), y2: y(v) }, g);
      el('text', { x: m.l - 8, y: y(v) + 4, 'text-anchor': 'end' }, a).textContent = F0(v);
    }
  }
  function refs(svg, y, w, m, D) {
    [['contratada', D.contratada, `Contratada ${F0(D.contratada)} kW`],
     ['limite', D.limite, `Límite +${F0(D.tolerancia)} % · ${F0(D.limite)} kW`]].forEach(([cls, v, txt]) => {
      if (!v) return; const g = el('g', { class: 'ref ' + cls }, svg);
      el('line', { x1: m.l, x2: w - m.r, y1: y(v), y2: y(v) }, g);
      el('text', { x: m.l + 6, y: y(v) - 6 }, g).textContent = txt;
    });
  }
  function tooltip(cont) { const t = document.createElement('div'); t.className = 'tip'; cont.appendChild(t); return t; }
  function ubicar(tip, cont, x, y) {
    const w = tip.offsetWidth, cw = cont.clientWidth;
    let left = x + 14; if (left + w > cw) left = Math.max(x - w - 14, 0);
    tip.style.left = left + 'px'; tip.style.top = Math.max(y - tip.offsetHeight - 10, 0) + 'px'; tip.style.opacity = 1;
  }
  const estadoDe = (kw, D) => kw > D.limite ? 'critico' : kw > D.contratada ? 'atencion' : 'normal';
  const lineaEstado = e => e ? `<div class="e"><span class="dot" style="background:var(${ESTADOS[e].color})"></span>${ESTADOS[e].txt}</div>` : '';

  /* ---------- Curva de carga de 15 minutos ---------- */
  function curva(cont, D, rango) {
    cont.innerHTML = '';
    const todos = D.puntos.map(([t, kw, e]) => [aFecha(t).getTime(), kw, e]);
    if (!todos.length) { cont.innerHTML = '<p class="muted">Sin lecturas en este período.</p>'; return; }
    const fin = todos[todos.length - 1][0];
    const desde = rango === 'todo' ? todos[0][0] : fin - Number(rango) * 86400000;
    const pts = todos.filter(p => p[0] >= desde);
    const w = cont.clientWidth, h = Math.max(260, Math.min(380, w * 0.42)), m = { l: 52, r: 12, t: 14, b: 28 };
    const svg = el('svg', { viewBox: `0 0 ${w} ${h}`, height: h, role: 'img', 'aria-label': 'Curva de carga en kW' }, cont);
    const esc = escala(Math.max(D.limite || 0, ...pts.map(p => p[1] || 0)) * 1.08);
    const t0 = pts[0][0], t1 = pts[pts.length - 1][0];
    const x = t => m.l + (t - t0) / (t1 - t0 || 1) * (w - m.l - m.r);
    const y = v => m.t + (1 - v / esc.max) * (h - m.t - m.b);
    ejeY(svg, y, w, m, esc);
    const ax = el('g', { class: 'axis' }, svg);
    const dias = []; const d0 = new Date(t0); d0.setHours(0, 0, 0, 0);
    for (let t = d0.getTime(); t <= t1; t += 86400000) if (t >= t0) dias.push(t);
    const cada = Math.max(1, Math.ceil(dias.length / Math.max(1, Math.floor((w - m.l - m.r) / 52))));
    dias.forEach((t, i) => { if (i % cada) return;
      el('text', { x: x(t), y: h - 8, 'text-anchor': 'middle' }, ax).textContent =
        new Date(t).toLocaleDateString('es-PY', { day: '2-digit', month: '2-digit' }); });
    refs(svg, y, w, m, D);
    let dL = '', dA = '', tramo = [];
    const P = p => `${x(p[0]).toFixed(1)},${y(p[1]).toFixed(1)}`;
    const cerrar = () => { if (tramo.length) { dL += 'M' + tramo.map(P).join('L');
      dA += `M${x(tramo[0][0]).toFixed(1)},${y(0)}L` + tramo.map(P).join('L') + `L${x(tramo[tramo.length - 1][0]).toFixed(1)},${y(0)}Z`; }
      tramo = []; };
    pts.forEach(p => p[1] === null ? cerrar() : tramo.push(p)); cerrar();
    el('path', { d: dA, fill: 'var(--series-soft)' }, svg);
    el('path', { d: dL, fill: 'none', stroke: 'var(--series)', 'stroke-width': 1.6, 'stroke-linejoin': 'round' }, svg);
    pts.filter(p => p[2] === 'critico').forEach(p =>
      el('circle', { cx: x(p[0]), cy: y(p[1]), r: 4.5, fill: 'var(--critical)', stroke: 'var(--surface)', 'stroke-width': 2 }, svg));
    const pm = pts.reduce((a, b) => (b[1] ?? -1) > (a[1] ?? -1) ? b : a);
    if (pm[1] !== null) {
      el('circle', { cx: x(pm[0]), cy: y(pm[1]), r: 4.5, fill: pm[2] === 'critico' ? 'var(--critical)' : 'var(--series)', stroke: 'var(--surface)', 'stroke-width': 2 }, svg);
      let ly = y(pm[1]) - 10;
      if ([D.contratada, D.limite].some(v => v && Math.abs(ly - 4 - y(v)) < 12)) ly = y(pm[1]) + 18;
      el('text', { x: x(pm[0]), y: ly, class: 'lbl', fill: 'var(--text)',
        'text-anchor': x(pm[0]) > w - 120 ? 'end' : x(pm[0]) < m.l + 60 ? 'start' : 'middle' }, svg).textContent = `Máx. ${F0(pm[1])} kW`;
    }
    const cruz = el('line', { y1: m.t, y2: h - m.b, stroke: 'var(--text-3)', 'stroke-width': 1, opacity: 0 }, svg);
    const punto = el('circle', { r: 5, fill: 'var(--series)', stroke: 'var(--surface)', 'stroke-width': 2, opacity: 0 }, svg);
    const hit = el('rect', { x: m.l, y: m.t, width: w - m.l - m.r, height: h - m.t - m.b, fill: 'transparent' }, svg);
    const tip = tooltip(cont);
    const mover = ev => {
      const r = svg.getBoundingClientRect(); const px = (ev.touches ? ev.touches[0].clientX : ev.clientX) - r.left;
      const t = t0 + (px - m.l) / (w - m.l - m.r) * (t1 - t0);
      let lo = 0, hi = pts.length - 1; while (hi - lo > 1) { const mid = (lo + hi) >> 1; pts[mid][0] < t ? lo = mid : hi = mid; }
      const p = Math.abs(pts[lo][0] - t) < Math.abs(pts[hi][0] - t) ? pts[lo] : pts[hi];
      const cx = x(p[0]); cruz.setAttribute('x1', cx); cruz.setAttribute('x2', cx); cruz.setAttribute('opacity', 1);
      if (p[1] === null) { punto.setAttribute('opacity', 0);
        tip.innerHTML = `${fechaLarga(p[0])}<br><b>Sin lectura</b> <span style="color:var(--text-3)">(hueco)</span>`;
      } else { punto.setAttribute('cx', cx); punto.setAttribute('cy', y(p[1])); punto.setAttribute('opacity', 1);
        tip.innerHTML = `${fechaLarga(p[0])}<br><b>${NF(p[1])} kW</b>` +
          (D.contratada ? ` · ${NF(p[1] / D.contratada * 100)} % de la contratada` : '') + lineaEstado(p[2]); }
      ubicar(tip, cont, cx, p[1] === null ? m.t + 40 : y(p[1]));
    };
    hit.addEventListener('mousemove', mover); hit.addEventListener('touchmove', mover, { passive: true });
    hit.addEventListener('mouseleave', () => { tip.style.opacity = 0; cruz.setAttribute('opacity', 0); punto.setAttribute('opacity', 0); });
  }

  /* ---------- Barras genéricas (máximos diarios / mensuales) ---------- */
  function barras(cont, items, D, rotulo, detalle) {
    cont.innerHTML = '';
    if (!items.length) { cont.innerHTML = '<p class="muted">Sin datos.</p>'; return; }
    const w = cont.clientWidth, h = Math.max(220, Math.min(300, w * 0.32)), m = { l: 52, r: 12, t: 14, b: 28 };
    const svg = el('svg', { viewBox: `0 0 ${w} ${h}`, height: h, role: 'img', 'aria-label': 'Demanda máxima en kW' }, cont);
    const esc = escala(Math.max(D.limite || 0, ...items.map(d => Math.max(d.kw, d.limite || 0))) * 1.08);
    const y = v => m.t + (1 - v / esc.max) * (h - m.t - m.b);
    ejeY(svg, y, w, m, esc);
    const n = items.length, banda = (w - m.l - m.r) / n, bw = Math.max(4, Math.min(40, banda - 2));
    const tip = tooltip(cont), ax = el('g', { class: 'axis' }, svg);
    const cada = Math.max(1, Math.ceil(n / Math.max(1, Math.floor((w - m.l - m.r) / 46))));
    items.forEach((d, i) => {
      const cx = m.l + banda * (i + .5), top = y(d.kw), base = y(0), r = Math.min(4, bw / 2);
      const path = `M${cx - bw / 2},${base}V${top + r}Q${cx - bw / 2},${top} ${cx - bw / 2 + r},${top}H${cx + bw / 2 - r}Q${cx + bw / 2},${top} ${cx + bw / 2},${top + r}V${base}Z`;
      const bar = el('path', { d: path, fill: `var(${(ESTADOS[d.estado] || ESTADOS.normal).barra})` }, svg);
      if (i % cada === 0) el('text', { x: cx, y: h - 8, 'text-anchor': 'middle' }, ax).textContent = rotulo(d);
      const hit = el('rect', { x: cx - banda / 2, y: m.t, width: banda, height: h - m.t - m.b, fill: 'transparent' }, svg);
      if (D.porBarra) {   // histórico: cada mes con SU contratada y SU límite
        [[d.contratada, 'var(--text-2)'], [d.limite, 'var(--critical)']].forEach(([v, col]) => { if (!v) return;
          el('line', { x1: cx - banda / 2 + 3, x2: cx + banda / 2 - 3, y1: y(v), y2: y(v), stroke: col, 'stroke-width': 2, 'stroke-dasharray': '5 3' }, svg); });
      }
      if (d.href) { hit.style.cursor = 'pointer'; hit.addEventListener('click', () => { location.href = d.href; }); }
      hit.addEventListener('mouseenter', () => { bar.setAttribute('opacity', .8); tip.innerHTML = detalle(d) + lineaEstado(d.estado); ubicar(tip, cont, cx, top); });
      hit.addEventListener('mouseleave', () => { bar.setAttribute('opacity', 1); tip.style.opacity = 0; });
    });
    if (!D.porBarra) refs(svg, y, w, m, D);
  }

  function diario(cont, D) {
    const items = (D.diario || []).map(([dia, kw, hora, estado]) => ({ dia, kw, hora, estado }));
    barras(cont, items, D,
      d => aFecha(d.dia + ' 00:00').toLocaleDateString('es-PY', { day: '2-digit', month: '2-digit' }),
      d => `${aFecha(d.dia + ' 00:00').toLocaleDateString('es-PY', { weekday: 'long', day: '2-digit', month: '2-digit' })}<br>` +
        `<b>${NF(d.kw)} kW</b> a las ${d.hora}` + (D.contratada ? ` · ${NF(d.kw / D.contratada * 100)} %` : ''));
  }

  function mensual(cont, M) {
    const items = M.meses.map(m => ({ period: m.period, kw: m.max_kw, estado: m.status, href: m.href, limite: m.limit_kw, contratada: m.contracted_kw }));
    barras(cont, items, { porBarra: true },
      d => { const [a, mm] = d.period.split('-'); return `${MESES[+mm - 1]} ${a.slice(2)}`; },
      d => { const [a, mm] = d.period.split('-');
        return `${MESES[+mm - 1]} ${a}<br><b>${NF(d.kw)} kW</b> máx.` + (d.contratada ? ` · ${NF(d.kw / d.contratada * 100)} % de ${F0(d.contratada)} kW` : '') +
          (d.limite ? `<br><span style="color:var(--text-3)">Límite de ese mes: ${F0(d.limite)} kW</span>` : ''); });
  }

  /* ---------- Arranque: busca los contenedores de la página ---------- */
  function iniciar() {
    const datos = document.getElementById('datos-mes');
    if (datos) {
      const D = JSON.parse(datos.textContent); let rango = 'todo';
      const cCurva = document.getElementById('curva'), cDiario = document.getElementById('diario');
      const dibujar = () => { if (cCurva) curva(cCurva, D, rango); if (cDiario) diario(cDiario, D); };
      const botones = document.getElementById('rango');
      if (botones) botones.addEventListener('click', e => { const b = e.target.closest('button'); if (!b) return;
        rango = b.dataset.r; botones.querySelectorAll('button').forEach(x => x.setAttribute('aria-pressed', x === b)); if (cCurva) curva(cCurva, D, rango); });
      dibujar(); let rz; addEventListener('resize', () => { clearTimeout(rz); rz = setTimeout(dibujar, 120); });
    }
    const hist = document.getElementById('datos-historico');
    if (hist) {
      const M = JSON.parse(hist.textContent), c = document.getElementById('mensual');
      const dib = () => mensual(c, M); dib(); let rz; addEventListener('resize', () => { clearTimeout(rz); rz = setTimeout(dib, 120); });
    }
  }
  document.readyState === 'loading' ? document.addEventListener('DOMContentLoaded', iniciar) : iniciar();
})();
