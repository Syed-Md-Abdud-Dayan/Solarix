'use strict';
/* ================= Risk map: 60 wards, orbit + tiles, animated forecast =================
   Data: /api/map (falls back to /api/risk per city on older servers).
   Uses helpers from dashboard.js: $, api, fmt, dateFmt, escapeHtml. */
const rm = { h: 3, view: 'orbit', data: null, sel: null, off: new Set(), loaded: false, date: '2025-08-04', rain: 1,
  cache: new Map(), playing: false, timer: null, token: 0, refs: null, vb: null, dragged: false, shown: {} };
const RM_TIERS = ['Critical', 'High', 'Medium', 'Low'];
const RM_COL = { Critical: '#ff4d6a', High: '#ff9640', Medium: '#ffd447', Low: '#34e0a1' };
const RM_TXT = { Critical: '#fff', High: '#06141f', Medium: '#06141f', Low: '#06141f' };
const RM_W = 820, RM_H = 760, RM_CX = 410, RM_CY = 380;
const rmShort = id => id.replace(/_Ward_/, ' · W');
const rmKey = h => `${rm.date}|${rm.rain}|${h}`;
const rmSvg = () => $('#rmStage svg');

/* ---------- data ---------- */
async function rmFetch(h) {
  const k = rmKey(h); if (rm.cache.has(k)) return rm.cache.get(k);
  const q = new URLSearchParams({ horizon: h, as_of: rm.date, rain_mult: rm.rain });
  let data;
  try { data = await api('/api/map?' + q); }
  catch (e1) { /* older server without /api/map */
    const hl = await api('/api/health'), parts = [];
    for (const c of hl.cities) { const p = new URLSearchParams(q); p.set('city', c); parts.push(await api('/api/risk?' + p)); }
    const m = parts[0];
    data = { origin_date: m.origin_date, target_date: m.target_date, horizon: m.horizon, rain_mult: m.rain_mult, date_range: m.date_range, backtest: m.backtest, model: m.model,
      cities: parts.map(d => ({ city: d.city, risk: d.city_risk, counts: d.counts, expected_cases: d.city_expected_cases, wards: d.wards.length })),
      wards: parts.flatMap(d => d.wards.map(w => ({ ...w, city: d.city, ward_no: parseInt(w.ward_id.split('_').pop(), 10) }))) };
  }
  rm.cache.set(k, data); return data;
}
async function rmPrefetch() {
  const t = ++rm.token;
  for (let h = 1; h <= 12; h++) {
    if (t !== rm.token) return;
    try { await rmFetch(h); } catch (e) { return; }
    if (t === rm.token) { rmTrend(); if (rm.sel) rmSide(); }
  }
}
function rmCities() {
  const d = rm.data, by = {};
  d.wards.forEach(w => (by[w.city] = by[w.city] || []).push(w));
  return d.cities.map(c => ({ ...c, list: (by[c.city] || []).slice().sort((a, b) => a.ward_no - b.ward_no) })).filter(c => c.list.length);
}
const rmTop3 = () => new Set(rm.data.wards.slice().sort((a, b) => b.predicted_cases - a.predicted_cases).slice(0, 3).map(w => w.ward_id));

/* ---------- tooltip ---------- */
function rmTip(html, x, y) {
  const t = $('#rmTip'); t.innerHTML = html; t.classList.add('show');
  const w = t.offsetWidth, h = t.offsetHeight;
  t.style.left = Math.min(innerWidth - w - 8, x + 14) + 'px';
  t.style.top = Math.max(8, Math.min(innerHeight - h - 8, y + 14)) + 'px';
}
const rmHideTip = () => $('#rmTip').classList.remove('show');

/* ---------- build (once per view) ---------- */
function rmBuildOrbit() {
  const cities = rmCities(), n = rm.data.wards.length, GAP = 1.8, R1 = 150, R2 = 290;
  const step = 2 * Math.PI / (n + GAP * cities.length), f = v => v.toFixed(1);
  const pt = (r, a) => [RM_CX + r * Math.cos(a), RM_CY + r * Math.sin(a)];
  let cur = -Math.PI / 2 + GAP * step / 2;
  cities.forEach(c => { c.pos = c.list.map((w, i) => ({ w, a: cur + (i + .5) * step })); c.mid = cur + c.list.length * step / 2; cur += (c.list.length + GAP) * step; });
  let seed = 7; const rnd = () => (seed = (seed * 16807) % 2147483647) / 2147483647;
  let g = `<svg viewBox="0 0 ${RM_W} ${RM_H}" role="group" aria-label="Orbit map of ${n} wards by predicted dengue risk">`;
  for (let i = 0; i < 90; i++) g += `<circle class="rm-star ${i % 4 === 0 ? 'rm-tw' : ''}" style="animation-delay:${(rnd() * 3).toFixed(1)}s" cx="${f(rnd() * RM_W)}" cy="${f(rnd() * RM_H)}" r="${(0.4 + rnd() * 1.1).toFixed(1)}" opacity="${(0.25 + rnd() * 0.5).toFixed(2)}"/>`;
  for (let i = 0; i < 120; i++) { const a = i / 120 * 2 * Math.PI, L = i % 5 === 0 ? 9 : 4, [x1, y1] = pt(330, a), [x2, y2] = pt(330 + L, a); g += `<line class="rm-tick" x1="${f(x1)}" y1="${f(y1)}" x2="${f(x2)}" y2="${f(y2)}"/>`; }
  g += [95, R1, R2, 330].map(r => `<circle class="rm-ring" cx="${RM_CX}" cy="${RM_CY}" r="${r}"/>`).join('');
  /* radar sweep: stacked wedges fading behind the leading edge */
  g += `<g class="rm-sweep" style="transform-origin:${RM_CX}px ${RM_CY}px">`;
  for (let i = 0; i < 8; i++) { const a1 = -i * 0.09, a2 = -(i + 1) * 0.09, [x1, y1] = pt(335, a1), [x2, y2] = pt(335, a2);
    g += `<path d="M${RM_CX} ${RM_CY} L${f(x1)} ${f(y1)} A335 335 0 0 0 ${f(x2)} ${f(y2)} Z" fill="#2ee6a6" opacity="${(0.2 - i * 0.022).toFixed(3)}"/>`; }
  g += `<line x1="${RM_CX}" y1="${RM_CY}" x2="${RM_CX + 335}" y2="${RM_CY}" stroke="#7ff5d6" stroke-opacity=".7" stroke-width="1.4"/></g>`;
  cities.forEach(c => {
    const [x1, y1] = pt(R1, c.mid);
    g += `<line class="rm-link rm-flow" data-c="${escapeHtml(c.city)}" x1="${RM_CX}" y1="${RM_CY}" x2="${f(x1)}" y2="${f(y1)}"/>`;
    c.pos.forEach(p => { const [x2, y2] = pt(R2, p.a); g += `<line class="rm-link" data-c="${escapeHtml(c.city)}" data-w="${p.w.ward_id}" x1="${f(x1)}" y1="${f(y1)}" x2="${f(x2)}" y2="${f(y2)}"/>`; });
  });
  g += `<g id="rmHot"></g>`;
  cities.forEach(c => c.pos.forEach((p, i) => { const w = p.w, [x, y] = pt(R2, p.a);
    g += `<g class="rm-node rm-pop" style="animation-delay:${(i * 0.012).toFixed(2)}s" data-ward="${w.ward_id}" data-city="${escapeHtml(c.city)}" tabindex="0" role="button">
      <circle class="rm-ripple" cx="${f(x)}" cy="${f(y)}"/><circle class="rm-halo" cx="${f(x)}" cy="${f(y)}"/><circle class="rm-core" cx="${f(x)}" cy="${f(y)}"/>
      <circle class="rm-topring" cx="${f(x)}" cy="${f(y)}"/><circle class="rm-sel" cx="${f(x)}" cy="${f(y)}"/><text class="rm-num" x="${f(x)}" y="${f(y + .5)}">${w.ward_no}</text></g>`; }));
  cities.forEach(c => { const [x, y] = pt(R1, c.mid);
    g += `<g class="rm-node rm-pop" data-city-node="${escapeHtml(c.city)}" data-city="${escapeHtml(c.city)}" tabindex="0" role="button">
      <circle class="rm-ripple" cx="${f(x)}" cy="${f(y)}"/><circle class="rm-halo" cx="${f(x)}" cy="${f(y)}"/><circle class="rm-core" cx="${f(x)}" cy="${f(y)}"/>
      <text class="rm-num" style="font-size:13px" x="${f(x)}" y="${f(y + .5)}">${c.wards}</text>
      <text class="rm-cname" x="${f(x)}" data-ny="1">${escapeHtml(c.city)}</text><text class="rm-csub" x="${f(x)}" data-sy="1"></text></g>`; });
  g += `<circle class="rm-hubglow" cx="${RM_CX}" cy="${RM_CY}" r="60"/><circle class="rm-hubglow b" cx="${RM_CX}" cy="${RM_CY}" r="60"/>
    <circle cx="${RM_CX}" cy="${RM_CY}" r="58" fill="#0A3C30" stroke="#3EBB9E" stroke-width="4" style="filter:drop-shadow(0 0 14px #2ee6a6)"/><circle cx="${RM_CX}" cy="${RM_CY}" r="43" fill="#fff"/>
    <clipPath id="rmHubClip"><circle cx="${RM_CX}" cy="${RM_CY}" r="43"/></clipPath><image href="assets/img/logo.png" clip-path="url(#rmHubClip)" x="${RM_CX - 36}" y="${RM_CY - 36}" width="72" height="72" preserveAspectRatio="xMidYMid meet"/></svg>`;
  rm.geo = { cities, pt, R1, R2 };
  return g;
}
function rmBuildTiles() {
  const cities = rmCities(); let i = 0;
  return `<div class="rm-tiles">${cities.map(c => `<section class="rm-cityblock" data-cb="${escapeHtml(c.city)}"><h4>${escapeHtml(c.city)} <small></small><span class="chip"></span></h4>
    <div class="rm-grid">${c.list.map(w => `<button class="rm-tile" style="animation-delay:${(i++ * 0.012).toFixed(2)}s" data-ward="${w.ward_id}"><span>${w.ward_no}</span><small></small></button>`).join('')}</div></section>`).join('')}</div>`;
}

/* ---------- apply data to existing DOM (enables smooth morphing) ---------- */
function rmApply() {
  const d = rm.data, st = $('#rmStage'), top3 = rmTop3(), cities = rmCities();
  const maxW = Math.max(1, ...d.wards.map(w => w.predicted_cases)), maxC = Math.max(1, ...cities.map(c => c.expected_cases));
  const byId = {}; d.wards.forEach(w => byId[w.ward_id] = w);
  st.querySelectorAll('[data-ward]').forEach(el => {
    const w = byId[el.dataset.ward]; if (!w) return;
    el.dataset.risk = w.risk; el.style.setProperty('--c', RM_COL[w.risk]); el.style.setProperty('--t', RM_TXT[w.risk]);
    el.classList.toggle('dim', rm.off.has(w.risk)); el.classList.toggle('sel', rm.sel === w.ward_id); el.classList.toggle('top', top3.has(w.ward_id));
    el.setAttribute('aria-label', `${rmShort(w.ward_id)}, ${w.risk}, ${fmt(w.predicted_cases)} expected cases`);
    if (rm.view === 'orbit') {
      const r = 8 + 3.4 * Math.sqrt(w.predicted_cases / maxW), s = el.querySelectorAll('circle');
      [r, r + 6, r, r + 4, r + 5].forEach((v, i) => s[i].setAttribute('r', v.toFixed(1)));
    } else el.querySelector('small').textContent = fmt(w.predicted_cases);
  });
  cities.forEach(c => {
    if (rm.view === 'orbit') {
      const el = st.querySelector(`[data-city-node="${CSS.escape(c.city)}"]`); if (!el) return;
      const r = 16 + 12 * Math.sqrt(c.expected_cases / maxC), s = el.querySelectorAll('circle'), cx = +s[0].getAttribute('cx'), cy = +s[0].getAttribute('cy');
      el.dataset.risk = c.risk; el.style.setProperty('--c', RM_COL[c.risk]); el.style.setProperty('--t', RM_TXT[c.risk]);
      el.classList.toggle('dim', rm.off.has(c.risk));
      [r, r + 10, r].forEach((v, i) => s[i].setAttribute('r', v.toFixed(1)));
      el.querySelector('[data-ny]').setAttribute('y', (cy + r + 18).toFixed(1));
      const sub = el.querySelector('[data-sy]'); sub.setAttribute('y', (cy + r + 32).toFixed(1)); sub.textContent = `${fmt(c.expected_cases)} cases/wk`;
    } else {
      const b = st.querySelector(`[data-cb="${CSS.escape(c.city)}"]`); if (!b) return;
      b.querySelector('small').textContent = `${c.wards} wards · ${fmt(c.expected_cases)} cases/wk`;
      const ch = b.querySelector('.chip'); ch.textContent = c.risk.toUpperCase(); ch.style.setProperty('--rk', RM_COL[c.risk]);
    }
  });
  if (rm.view === 'orbit') {
    let hot = ''; const { cities: gc, pt, R2 } = rm.geo;
    gc.forEach(c => c.pos.forEach(p => { if (!top3.has(p.w.ward_id)) return; const [x, y] = pt(R2, p.a); hot += `<line class="rm-hot" x1="${RM_CX}" y1="${RM_CY}" x2="${x.toFixed(1)}" y2="${y.toFixed(1)}"/>`; }));
    $('#rmHot').innerHTML = hot;
  }
  rmLegend(); rmStats(); rmHud(); rmTrend();
  $('#rmCaption').textContent = `${d.wards.length} wards · forecast from ${dateFmt(d.origin_date)} · week of ${dateFmt(d.target_date)} · click a tile`;
  $('#rmHLabel').textContent = `+${rm.h} week${rm.h > 1 ? 's' : ''}`;
  $('#rmHorizon').value = rm.h;
  if (rm.sel) rmSide();
}

function rmCount(el, to, dec = 0) {
  const from = +(rm.shown[el.id] ?? 0), t0 = performance.now(); rm.shown[el.id] = to;
  const tick = now => { const k = Math.min(1, (now - t0) / 650), e = 1 - Math.pow(1 - k, 3); el.textContent = (from + (to - from) * e).toFixed(dec); if (k < 1) requestAnimationFrame(tick); };
  requestAnimationFrame(tick);
}
function rmStats() {
  const w = rm.data.wards, n = w.length, crit = w.filter(x => x.risk === 'Critical').length, hi = w.filter(x => x.risk === 'High' || x.risk === 'Critical').length;
  const tot = w.reduce((s, x) => s + x.predicted_cases, 0), top = w.slice().sort((a, b) => b.predicted_cases - a.predicted_cases)[0];
  rmCount($('#rmS1'), crit); $('#rmS1s').textContent = `of ${n} wards`; rmCount($('#rmS2'), Math.round(hi / n * 100)); rmCount($('#rmS3'), tot, 0);
  $('#rmS4').textContent = rmShort(top.ward_id); $('#rmS4s').textContent = `${fmt(top.predicted_cases)} cases/wk · ${top.risk}`; rm.hottest = top.ward_id;
}
function rmHud() { $('#rmHudWk').textContent = `+${rm.h} WK`; $('#rmHudDate').textContent = dateFmt(rm.data.target_date); }
function rmTrend() {
  const pts = []; for (let h = 1; h <= 12; h++) { const d = rm.cache.get(rmKey(h)); if (d) pts.push({ h, v: d.wards.reduce((s, w) => s + w.predicted_cases, 0) }); }
  const el = $('#rmTrend'); if (pts.length < 2) { el.innerHTML = ''; return; }
  const max = Math.max(...pts.map(p => p.v)), min = Math.min(...pts.map(p => p.v)), x = h => 6 + (h - 1) / 11 * 138, y = v => 38 - (v - min) / Math.max(1e-6, max - min) * 30;
  const line = pts.map(p => `${x(p.h).toFixed(1)},${y(p.v).toFixed(1)}`).join(' '), cur = pts.find(p => p.h === rm.h);
  el.innerHTML = `<defs><linearGradient id="rmTg" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#38d6ff" stop-opacity=".35"/><stop offset="1" stop-color="#38d6ff" stop-opacity="0"/></linearGradient></defs>
    <polygon class="rm-trend-a" points="${x(pts[0].h)},42 ${line} ${x(pts[pts.length - 1].h)},42"/><polyline class="rm-trend-l" points="${line}"/>${cur ? `<circle class="rm-trend-d" cx="${x(cur.h).toFixed(1)}" cy="${y(cur.v).toFixed(1)}" r="3.4"/>` : ''}`;
}
function rmLegend() {
  const cnt = {}; RM_TIERS.forEach(t => cnt[t] = rm.data.wards.filter(w => w.risk === t).length);
  $('#rmDist').innerHTML = RM_TIERS.map(t => `<i style="flex:${cnt[t]};--rk:${RM_COL[t]}" title="${t}: ${cnt[t]}"></i>`).join('');
  $('#rmLegend').innerHTML = RM_TIERS.map(t => `<button class="rm-chip ${rm.off.has(t) ? 'off' : ''}" data-tier="${t}" style="--rk:${RM_COL[t]}" aria-pressed="${!rm.off.has(t)}"><i></i>${t} <b>${cnt[t]}</b></button>`).join('');
}

/* ---------- side panel ---------- */
function rmSpark(id) {
  const pts = []; for (let h = 1; h <= 12; h++) { const d = rm.cache.get(rmKey(h)), w = d && d.wards.find(x => x.ward_id === id); if (w) pts.push({ h, v: w.predicted_cases, r: w.risk }); }
  if (pts.length < 2) return '<div class="rm-sub">Loading the 12-week trajectory…</div>';
  const max = Math.max(...pts.map(p => p.v)) * 1.1, min = Math.min(...pts.map(p => p.v)) * 0.9, x = h => 10 + (h - 1) / 11 * 280, y = v => 52 - (v - min) / Math.max(1e-6, max - min) * 44;
  return `<svg class="rm-spark" viewBox="0 0 300 70" role="img" aria-label="Expected cases for the next 12 weeks"><polyline class="l" points="${pts.map(p => `${x(p.h).toFixed(1)},${y(p.v).toFixed(1)}`).join(' ')}"/>
    ${pts.map(p => `<circle cx="${x(p.h).toFixed(1)}" cy="${y(p.v).toFixed(1)}" r="${p.h === rm.h ? 5 : 3}" fill="${RM_COL[p.r]}" stroke="${p.h === rm.h ? '#fff' : '#06141f'}" stroke-width="1.5"><title>+${p.h} wk: ${fmt(p.v)} cases · ${p.r}</title></circle>`).join('')}
    <text x="10" y="67">+1 wk</text><text x="290" y="67" text-anchor="end">+12 wk</text></svg>`;
}
function rmSide() {
  const el = $('#rmSide'), d = rm.data, w = d && d.wards.find(x => x.ward_id === rm.sel);
  if (!w) { if (!el.dataset.city) el.innerHTML = `<div class="rm-empty"><b>Click a tile or a node</b>Pick any ward to see its expected cases, a 12-week trajectory, risk drivers and weather. Click a city to list its wards. Press Play to watch the forecast unfold week by week.</div>`; return; }
  el.dataset.city = '';
  const second = w.actual_cases == null ? `<div><small>RAIN · 4 WEEKS</small><b>${fmt(w.rain_4w_mm)} mm</b></div>` : `<div><small>ACTUALLY REPORTED</small><b>${w.actual_cases}</b></div>`;
  el.innerHTML = `<h4>${escapeHtml(w.ward_id)}</h4><div class="rm-sub">${escapeHtml(w.city)} · week of ${dateFmt(d.target_date)}</div>
    <div class="rm-big" style="--rk:${RM_COL[w.risk]}"><b>${w.risk}</b><span>${fmt(w.predicted_cases)} expected cases per week</span></div>
    <div class="rm-kv"><div><small>CASES AT ORIGIN</small><b>${w.cases_at_origin}</b></div>${second}
      <div><small>TEMP · HUMIDITY</small><b>${fmt(w.temperature_c)}° · ${Math.round(w.humidity_pct)}%</b></div><div><small>WATER-LOGGING</small><b>${w.water_logging_risk_index}</b></div></div>
    <h5>NEXT 12 WEEKS</h5>${rmSpark(w.ward_id)}
    <h5>WHY THIS RISK</h5><ul class="drv">${w.drivers.slice(0, 4).map(x => `<li class="${x.level}"><b>${escapeHtml(x.label)}</b> — ${escapeHtml(x.detail)}</li>`).join('')}</ul>
    <button class="btn btn-outline" style="margin-top:14px;width:100%" data-go="wards">Open ward explorer →</button>`;
}
function rmCityDetail(name) {
  const c = rmCities().find(x => x.city === name); if (!c) return;
  const el = $('#rmSide'); el.dataset.city = name;
  el.innerHTML = `<h4>${escapeHtml(c.city)}</h4><div class="rm-sub">${c.wards} wards · ${fmt(c.expected_cases)} expected cases/wk</div>
    <div class="rm-big" style="--rk:${RM_COL[c.risk]}"><b>${c.risk}</b><span>${c.counts.Critical} Critical · ${c.counts.High} High · ${c.counts.Medium} Medium · ${c.counts.Low} Low</span></div>
    <h5>WARDS, HIGHEST FIRST</h5><div class="rm-wardlist">${c.list.slice().sort((a, b) => b.predicted_cases - a.predicted_cases).map(w => `<button data-ward="${w.ward_id}" style="--rk:${RM_COL[w.risk]}"><i></i>Ward ${w.ward_no}<span>${fmt(w.predicted_cases)}</span></button>`).join('')}</div>`;
}

/* ---------- interactions ---------- */
function rmFocus(city, ward) {
  const svg = rmSvg(); if (!svg) return; svg.classList.add('fx');
  svg.querySelectorAll('.rm-node').forEach(n => n.classList.toggle('fade', n.dataset.city !== city));
  svg.querySelectorAll('.rm-link').forEach(l => l.classList.toggle('lit', l.dataset.c === city && (!ward || !l.dataset.w || l.dataset.w === ward)));
}
function rmUnfocus() { const svg = rmSvg(); if (!svg) return; svg.classList.remove('fx'); svg.querySelectorAll('.fade,.lit').forEach(n => n.classList.remove('fade', 'lit')); }
function rmSelectWard(id) { rm.sel = id; rmApply(); rmSide(); }
function rmBind() {
  const st = $('#rmStage'), d = rm.data;
  st.querySelectorAll('[data-ward]').forEach(el => {
    const w = d.wards.find(x => x.ward_id === el.dataset.ward), act = () => { if (!rm.dragged) rmSelectWard(w.ward_id); };
    el.addEventListener('click', act);
    el.addEventListener('keydown', e => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); rmSelectWard(w.ward_id); } });
    el.addEventListener('pointerenter', () => rm.view === 'orbit' && rmFocus(w.city, w.ward_id));
    el.addEventListener('pointermove', e => { const cur = rm.data.wards.find(x => x.ward_id === w.ward_id); rmTip(`<b>${escapeHtml(cur.city)} · Ward ${cur.ward_no}</b>${cur.risk} · ${fmt(cur.predicted_cases)} expected cases/wk<br>Click for details`, e.clientX, e.clientY); });
    el.addEventListener('pointerleave', () => { rmHideTip(); rmUnfocus(); });
  });
  st.querySelectorAll('[data-city-node]').forEach(el => {
    const name = el.dataset.cityNode, open = () => { if (rm.dragged) return; rm.sel = null; rmApply(); rmCityDetail(name); };
    el.addEventListener('click', open);
    el.addEventListener('keydown', e => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); open(); } });
    el.addEventListener('pointerenter', () => rmFocus(name));
    el.addEventListener('pointermove', e => { const c = rmCities().find(x => x.city === name); rmTip(`<b>${escapeHtml(c.city)}</b>${c.risk} · ${c.counts.Critical + c.counts.High} of ${c.wards} wards High or Critical<br>${fmt(c.expected_cases)} expected cases/wk`, e.clientX, e.clientY); });
    el.addEventListener('pointerleave', () => { rmHideTip(); rmUnfocus(); });
  });
  const svg = rmSvg(); if (!svg) return;
  rmSetVB(rm.vb || { x: 0, y: 0, w: RM_W, h: RM_H });
  let drag = null;
  svg.addEventListener('pointerdown', e => { drag = { x: e.clientX, y: e.clientY, vb: { ...rm.vb }, moved: false }; rm.dragged = false; });
  addEventListener('pointermove', e => {
    if (!drag || !(e.buttons & 1)) return; const dx = e.clientX - drag.x, dy = e.clientY - drag.y;
    if (!drag.moved && Math.hypot(dx, dy) < 5) return; drag.moved = true; rm.dragged = true; svg.classList.add('drag');
    const k = drag.vb.w / svg.getBoundingClientRect().width; rmSetVB({ ...drag.vb, x: drag.vb.x - dx * k, y: drag.vb.y - dy * k });
  });
  addEventListener('pointerup', () => { if (drag && drag.moved) setTimeout(() => rm.dragged = false, 0); drag = null; svg.classList.remove('drag'); });
  svg.addEventListener('wheel', e => { e.preventDefault(); rmZoom(e.deltaY < 0 ? 0.85 : 1.18, e.clientX, e.clientY); }, { passive: false });
}
function rmSetVB(v) {
  v.w = Math.min(RM_W, Math.max(RM_W / 4, v.w)); v.h = v.w * RM_H / RM_W;
  v.x = Math.min(RM_W - v.w, Math.max(0, v.x)); v.y = Math.min(RM_H - v.h, Math.max(0, v.y));
  rm.vb = v; const svg = rmSvg(); if (svg) svg.setAttribute('viewBox', `${v.x.toFixed(1)} ${v.y.toFixed(1)} ${v.w.toFixed(1)} ${v.h.toFixed(1)}`);
}
function rmZoom(f, cx, cy) {
  const svg = rmSvg(), v = rm.vb; if (!svg || !v) return; const r = svg.getBoundingClientRect();
  const px = cx == null ? .5 : (cx - r.left) / r.width, py = cy == null ? .5 : (cy - r.top) / r.height, nw = Math.min(RM_W, Math.max(RM_W / 4, v.w * f)), nh = nw * RM_H / RM_W;
  rmSetVB({ x: v.x + (v.w - nw) * px, y: v.y + (v.h - nh) * py, w: nw, h: nh });
}

/* ---------- lifecycle ---------- */
function rmBuild() {
  const st = $('#rmStage'); $('#rmStageWrap').classList.toggle('is-tiles', rm.view === 'tiles');
  st.innerHTML = rm.view === 'orbit' ? rmBuildOrbit() : rmBuildTiles();
  rm.shown = {}; rmBind(); rmApply();
  $('#rmFoot').innerHTML = rm.view === 'orbit'
    ? 'Schematic network, not geographic. Cities orbit the hub and wards orbit their city. Colour is the model risk tier, ward size follows expected cases and pulsing rings mark Critical wards. Dashed gold lines point to the 3 highest-risk wards. Scroll to zoom, drag to pan, hover to trace a ward to the hub.'
    : 'Tiles are grouped by city and show the ward number and expected cases per week. ★ marks the 3 highest-risk wards.';
}
async function rmSetH(h) {
  rm.h = h; const busy = $('#rmBusy'), key = rmKey(h);
  if (!rm.cache.has(key)) busy.classList.add('on');
  try { rm.data = await rmFetch(h); } finally { busy.classList.remove('on'); }
  if (rm.h !== h) return;
  if (!rm.loaded) { rm.loaded = true; rmBuild(); } else rmApply();
  $('#rmDate').min = rm.data.date_range.min; $('#rmDate').max = rm.data.date_range.max;
}
async function rmLoad(first) {
  try { await rmSetH(rm.h); if (first || true) rmPrefetch(); }
  catch (e) { rm.loaded = false; $('#rmStage').innerHTML = `<div class="rm-err"><b>Could not load the map.</b> ${escapeHtml(e.message)}<br>Stop any old server (Ctrl+C), then start the updated one with <code>python app.py</code> and open http://127.0.0.1:5000.</div>`; }
}
function rmPlay(on) {
  rm.playing = on; $('#rmPlay').textContent = on ? '❚❚ Pause' : '▶ Play forecast'; clearTimeout(rm.timer);
  if (!on) return;
  const step = async () => { if (!rm.playing) return; try { await rmSetH(rm.h >= 12 ? 1 : rm.h + 1); } catch (e) { return rmPlay(false); } rm.timer = setTimeout(step, 1300); };
  step();
}
function rmInit() {
  $('#rmDate').value = rm.date;
  $('#rmView').addEventListener('click', e => { const b = e.target.closest('button'); if (!b || b.dataset.v === rm.view) return; rm.view = b.dataset.v; document.querySelectorAll('#rmView button').forEach(x => x.classList.toggle('on', x === b)); if (rm.data) rmBuild(); });
  $('#rmHorizon').addEventListener('input', () => { rmPlay(false); const h = +$('#rmHorizon').value; $('#rmHLabel').textContent = `+${h} week${h > 1 ? 's' : ''}`; rmSetH(h).catch(() => {}); });
  $('#rmPlay').addEventListener('click', () => rmPlay(!rm.playing));
  $('#rmDate').addEventListener('change', () => { rm.date = $('#rmDate').value; rmPlay(false); rm.cache.clear(); rmLoad(); });
  $('#rmRain').addEventListener('input', () => { const v = +$('#rmRain').value; $('#rmRainVal').textContent = v === 1 ? '×1.0 (as recorded)' : `×${v.toFixed(1)}`; });
  $('#rmRain').addEventListener('change', () => { rm.rain = +$('#rmRain').value; rmPlay(false); rm.cache.clear(); rmLoad(); });
  $('#rmLegend').addEventListener('click', e => { const b = e.target.closest('[data-tier]'); if (!b) return; const t = b.dataset.tier; rm.off.has(t) ? rm.off.delete(t) : rm.off.add(t); rmApply(); });
  $('#rmSide').addEventListener('click', e => { const b = e.target.closest('[data-ward]'); if (b) rmSelectWard(b.dataset.ward); });
  $('#rmS4b').addEventListener('click', () => rm.hottest && rmSelectWard(rm.hottest));
  $('#rmZoomIn').addEventListener('click', () => rmZoom(0.7)); $('#rmZoomOut').addEventListener('click', () => rmZoom(1.4));
  $('#rmReset').addEventListener('click', () => rmSetVB({ x: 0, y: 0, w: RM_W, h: RM_H }));
  $('#rmFull').addEventListener('click', () => { const w = $('#rmStageWrap'); document.fullscreenElement ? document.exitFullscreen() : w.requestFullscreen && w.requestFullscreen(); });
  rmSide();
  const maybe = () => { const on = (location.hash || '').slice(1) === 'map'; if (on && !rm.loaded && !rm.busy) { rm.busy = true; rmLoad(true).finally(() => rm.busy = false); } if (!on) rmPlay(false); };
  window.addEventListener('hashchange', maybe); maybe();
}
document.addEventListener('DOMContentLoaded', rmInit);
