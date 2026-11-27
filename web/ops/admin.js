/* Regional command (super admin) page. */
(async function () {
  const { $, $$, esc, fmt, badge, bar } = DW;
  const me = await DW.boot(['super_admin']);
  if (!me) return;
  let settings = {}, tab = 'alloc', lastAlloc = null, lastSim = null;
  const SUP = [['saline_bags', 'Saline'], ['diagnostic_kits', 'Kits'], ['hospital_beds', 'Beds']];

  // ---------------- tabs
  $$('#tabs button').forEach((b) => b.onclick = () => { tab = b.dataset.t; $$('#tabs button').forEach((x) => x.classList.toggle('on', x === b)); $$('[data-tab]').forEach((p) => p.classList.toggle('hide', p.dataset.tab !== tab)); load(); });

  // ---------------- settings bootstrap
  try { settings = await DW.api('/api/ops/settings'); } catch (e) { settings = {}; }
  $('#stock').value = settings.stock_pct ?? 100; $('#crews').value = settings.total_crews ?? 60;
  $('#buf').value = Math.round((settings.buffer ?? 0) * 100); $('#hz').value = settings.horizon ?? 1; $('#eq').checked = settings.equity !== false;
  const q = () => `stock_pct=${$('#stock').value}&crews=${$('#crews').value}&buffer=${$('#buf').value / 100}&horizon=${$('#hz').value}&equity=${$('#eq').checked ? 1 : 0}`;
  const labels = () => { $('#stockV').textContent = $('#stock').value + '%'; $('#crewsV').textContent = $('#crews').value; $('#bufV').textContent = $('#buf').value + '%'; };
  let tm; ['stock', 'crews', 'buf', 'hz', 'eq', 'cmp'].forEach((id) => $('#' + id).addEventListener('input', () => { labels(); clearTimeout(tm); tm = setTimeout(loadAlloc, 220); }));
  labels();

  $('#applyLive').onclick = async () => {
    try {
      settings = await DW.api('/api/ops/settings', { method: 'POST', body: { stock_pct: +$('#stock').value, total_crews: +$('#crews').value, buffer: $('#buf').value / 100, horizon: +$('#hz').value, equity: $('#eq').checked } });
      DW.toast('Live plan updated - commissioners and teams now see these limits. Re-generate tasks in Operations.');
    } catch (e) { DW.toast('Could not save: ' + e.message); }
  };

  // ---------------- allocation
  async function loadAlloc() {
    let a, base = null;
    try {
      a = await DW.api('/api/alloc?' + q());
      if ($('#cmp').checked) base = await DW.api(`/api/alloc?stock_pct=100&crews=${$('#crews').value}&buffer=${$('#buf').value / 100}&horizon=${$('#hz').value}`);
    } catch (e) { $('#warns').innerHTML = `<div class="CRITICAL">${esc(e.message)}</div>`; return; }
    lastAlloc = a;
    DW.setFallback(a.source); $('#srcTag').textContent = a.source === 'fallback' ? 'FALLBACK FORECAST' : 'ML MODEL'; $('#srcTag').className = 'badge ' + a.source;
    $('#weekTag').textContent = `data to ${a.origin} → planning week ${a.target_date}`;
    const t = a.totals;
    $('#allocKpis').innerHTML = SUP.map(([k, l]) => `<div class="kpi"><span class="eyebrow">${l}: allocated / required</span><b>${fmt(t[k].allocated)} / ${fmt(t[k].required)}</b>
      <small>stock ${fmt(t[k].available)} of ${fmt(t[k].full_stock)} at 100% · deficit <b style="display:inline;font-size:13px;color:${t[k].deficit ? '#a12626' : '#087c68'}">${fmt(t[k].deficit)}</b></small>${bar(t[k].required ? 100 * t[k].allocated / t[k].required : 100)}</div>`).join('') +
      `<div class="kpi"><span class="eyebrow">Spraying crews</span><b>${fmt(a.crews.assigned)} / ${fmt(a.crews.needed)}</b><small>${a.crews.unassigned_wards.length} wards without full crew · ${fmt(a.crews.unused)} unused</small>${bar(a.crews.needed ? 100 * a.crews.assigned / a.crews.needed : 100)}</div>`;
    $('#warns').innerHTML = a.warnings.length ? a.warnings.map((w) => `<div class="${w.level}">${badge(w.level)} ${badge(w.risk)} <b>${esc(w.ward_id)}</b> · ${fmt(w.fulfilment_pct)}% fulfilled<br><span class="muted">${esc(w.message.split(': ').slice(1).join(': '))}</span></div>`).join('')
      : '<div class="OK" style="border-left-color:#0c9b83;background:#f3fbf8">✓ Every ward is 100% supplied at this stock level.</div>';
    const sh = a.shorted_by_risk;
    $('#equity').innerHTML = `<table><tr><th>Risk band</th><th class="num">Wards shorted</th><th class="num">Units short</th></tr>${Object.entries(sh).map(([k, v]) => `<tr><td>${badge(k)}</td><td class="num">${v.wards}</td><td class="num">${fmt(v.units_short)}</td></tr>`).join('')}</table>
      <h3 class="mt" style="font-size:13px">Stock replenishment request per city</h3><table><tr><th>City</th>${SUP.map(([, l]) => `<th class="num">${l}</th>`).join('')}</tr>
      ${Object.entries(a.replenishment_by_city).map(([c, v]) => `<tr><td>${esc(c)}</td>${SUP.map(([k]) => `<td class="num">${v[k] ? '+' + fmt(v[k]) : '–'}</td>`).join('')}</tr>`).join('')}</table>`;
    const bmap = base ? Object.fromEntries(base.wards.map((w) => [w.ward_id, w])) : null;
    $('#allocTbl').innerHTML = `<tr><th>#</th><th>Ward</th><th>Risk</th><th class="num">Cases ±</th><th class="num">Density</th><th class="num">Priority</th>${SUP.map(([, l]) => `<th class="num">${l} alloc/req</th>`).join('')}<th>Fulfilled</th><th class="num">Crews</th><th>Status / what got cut</th></tr>` +
      a.wards.map((w) => `<tr class="${w.deficit_level !== 'OK' ? 'cut' : ''}"><td>${w.priority_rank}</td><td><b>${esc(w.ward_id)}</b><br><span class="muted small">${esc(w.city)}</span></td><td>${badge(w.risk)}</td>
        <td class="num">${fmt(w.predicted_cases, 1)} <span class="muted small">±${fmt(w.uncertainty_cases, 1)}</span></td><td class="num">${fmt(w.population_density_sqkm)}</td><td class="num">${fmt(w.priority_score, 1)}</td>
        ${SUP.map(([k]) => `<td class="num">${fmt(w.allocated[k])}/${fmt(w.required[k])}${bmap ? `<br><span class="muted small">was ${fmt(bmap[w.ward_id].allocated[k])}</span>` : ''}</td>`).join('')}
        <td style="min-width:90px">${bar(w.fulfilment_pct)}<span class="small">${fmt(w.fulfilment_pct)}%</span></td><td class="num">${w.crews_assigned}/${w.crews_needed}</td>
        <td>${badge(w.deficit_level)} <span class="small muted">${esc(w.what_got_cut)}</span></td></tr>`).join('');
  }

  // ---------------- overflow
  async function loadOverflow() {
    let o; try { o = await DW.api(`/api/overflow?horizon=${$('#hz').value}`); } catch (e) { return; }
    $('#capNote').textContent = o.summary.capacity_note;
    $('#gauges').innerHTML = o.cities.map((c) => `<div class="panel" style="padding:10px">${DW.gauge(c.utilisation_pct, c.city)}<div class="small muted" style="text-align:center">${c.bed_demand} demand / ${c.capacity} beds<br>${c.patients_routed} routed · ${c.surge ? `<b style="color:#a12626">surge ${c.unresolved_deficit}</b>` : `headroom ${c.headroom_after_routing}`}</div></div>`).join('');
    $('#transfers').innerHTML = o.transfers.length ? o.transfers.map((t) => `<div class="transfer"><b>${esc(t.from_ward)}</b><span class="arrow"></span><b>${esc(t.to_ward)}</b><span class="badge RECEIVING">${t.patients} pt</span><span class="muted small">${esc(t.city)}</span></div>`).join('') : '<p class="muted">No transfers needed this week.</p>';
    $('#surges').innerHTML = o.alerts.map((a) => `<div class="CRITICAL">${esc(a.message)}</div>`).join('');
    $('#bedTbl').innerHTML = `<tr><th>Ward</th><th class="num">Demand</th><th class="num">Capacity</th><th class="num">Deficit</th><th class="num">Sent</th><th class="num">Recv</th><th class="num">Net deficit</th><th class="num">Headroom</th><th>Status</th></tr>` +
      o.wards.map((w) => `<tr><td><b>${esc(w.ward_id)}</b><br><span class="small muted">${esc(w.city)}</span></td><td class="num">${w.bed_demand}</td><td class="num">${w.effective_capacity}</td><td class="num">${w.deficit}</td><td class="num">${w.sent}</td><td class="num">${w.received}</td><td class="num">${w.net_deficit}</td><td class="num">${w.remaining_headroom}</td><td>${badge(w.status)}</td></tr>`).join('');
  }

  // ---------------- simulator
  function renderSim(s) {
    lastSim = s;
    const c = s.compare;
    $('#simInfo').textContent = `${s.crews_used} crews used · ${s.method} · source: ${s.source}`;
    $('#simCompare').innerHTML = [['Cases (wk +2..+4)', 'cases', 1], ['Bed load', 'beds', 1], ['Saline bags', 'saline', 0]].map(([l, k, d]) => {
      const a = c.no_intervention[k], b = c.intervention[k];
      return `<div class="kpi"><span class="eyebrow">${l}</span><b>${fmt(b, d)} <span class="small muted">vs ${fmt(a, d)}</span></b><small>prevented ${fmt(a - b, d)} (${fmt(a ? 100 * (a - b) / a : 0, 1)}%)</small></div>`;
    }).join('');
    $('#simWeeks').innerHTML = `<table><tr><th>Week</th><th class="num">Baseline cases</th><th class="num">With crews</th><th class="num">Prevented</th><th class="num">Beds base → new</th><th class="num">Saline base → new</th></tr>` +
      s.by_week.map((w) => `<tr><td>+${w.horizon}</td><td class="num">${fmt(w.baseline_cases, 1)}</td><td class="num">${fmt(w.intervened_cases, 1)}</td><td class="num"><b>${fmt(w.cases_prevented, 2)}</b></td><td class="num">${fmt(w.beds_baseline, 1)} → ${fmt(w.beds_intervened, 1)}</td><td class="num">${fmt(w.saline_baseline)} → ${fmt(w.saline_intervened)}</td></tr>`).join('') + '</table>' +
      `<p class="small muted mt">Total: ${fmt(s.total.cases_prevented, 2)} cases, ${fmt(s.total.beds_saved, 2)} bed-weeks and ${fmt(s.total.saline_saved, 1)} saline bags saved · ROI ${fmt(s.total.roi, 2)} cases per crew.</p>`;
    if (s.roi_ranking) $('#roiChart').innerHTML = DW.barChart(s.roi_ranking.slice(0, 15).map((r) => ({ label: r.ward_id, value: r.roi_1_crew })), { label: 'ROI ranking', left: 110 });
    const dep = s.recommended_deployment || Object.fromEntries(s.wards.map((w) => [w.ward_id, w.crews]));
    const rank = s.roi_ranking || [];
    const byWard = Object.fromEntries(s.wards.map((w) => [w.ward_id, w]));
    const ids = rank.length ? rank.map((r) => r.ward_id) : Object.keys(byWard);
    $('#simTbl').innerHTML = `<tr><th>ROI rank</th><th>Ward</th><th class="num">ROI (1 crew)</th><th>Crews</th><th class="num">Prevented wk+2</th><th class="num">wk+3</th><th class="num">wk+4</th><th class="num">Total prevented</th><th class="num">ROI (deployed)</th></tr>` +
      ids.map((id, i) => { const w = byWard[id]; const r = rank[i] || {}; const wk = (h) => w ? fmt(w.weeks.find((x) => x.horizon === h)?.cases_prevented, 2) : '–';
        return `<tr><td>${r.rank || '–'}</td><td><b>${esc(id)}</b></td><td class="num">${fmt(r.roi_1_crew, 2)}</td><td><input type="number" min="0" max="4" value="${dep[id] || 0}" data-w="${esc(id)}" style="width:64px"></td>
        <td class="num">${wk(2)}</td><td class="num">${wk(3)}</td><td class="num">${wk(4)}</td><td class="num">${w ? '<b>' + fmt(w.cases_prevented, 2) + '</b>' : '–'}</td><td class="num">${w ? fmt(w.roi, 2) : '–'}</td></tr>`; }).join('');
  }
  $('#simGo').onclick = async () => { $('#simInfo').textContent = 'Running horizon models…'; try { renderSim(await DW.api('/api/simulate?crews=' + (+$('#simCrews').value || 0))); } catch (e) { $('#simInfo').textContent = e.message; } };
  $('#simMine').onclick = async () => {
    const dep = {}; $$('#simTbl input[data-w]').forEach((i) => { if (+i.value > 0) dep[i.dataset.w] = +i.value; });
    try { const s = await DW.api('/api/simulate', { method: 'POST', body: { deployment: dep, crew_cap: +$('#simCrews').value } }); s.roi_ranking = lastSim && lastSim.roi_ranking; s.recommended_deployment = dep; renderSim(s); }
    catch (e) { DW.toast(e.message); }
  };

  // ---------------- operations
  async function loadOps() {
    try {
      const p = await DW.api('/api/ops/progress');
      $('#progKpis').innerHTML = `<div class="kpi"><span class="eyebrow" data-i18n="Work completed">${DW.t('Work completed')}</span><b>${fmt(p.pct, 1)}%</b><small>${p.done} of ${p.total} tasks</small>${bar(p.pct)}</div>` +
        Object.entries(p.by_type).filter(([, v]) => v.total).map(([k, v]) => `<div class="kpi"><span class="eyebrow">${esc(DW.t(k))}</span><b>${fmt(v.pct, 1)}%</b><small>${v.done}/${v.total} done</small>${bar(v.pct)}</div>`).join('');
      $('#cityProg').innerHTML = Object.entries(p.by_city).map(([c, v]) => `<div class="mt"><div class="row" style="justify-content:space-between"><b>${esc(c)}</b><span class="small">${v.done}/${v.total} · ${fmt(v.pct, 1)}%</span></div>${bar(v.pct, true)}</div>`).join('') || '<p class="muted">No tasks yet - generate the plan.</p>';
      $('#lagging').innerHTML = p.lagging.length ? `<table><tr><th>Ward</th><th class="num">Done</th><th>Progress</th></tr>${p.lagging.map((r) => `<tr><td>${esc(r.ward_id)}</td><td class="num">${r.done}/${r.total}</td><td>${bar(r.pct)}</td></tr>`).join('')}</table>` : '<p class="muted">–</p>';
      $('#esc').innerHTML = p.escalated.length ? p.escalated.map((t) => `<div class="${t.escalations.includes('overdue') || t.escalations.includes('blocked') ? 'CRITICAL' : ''}">${t.escalations.map((e) => badge(e, e.replace('_', ' '))).join(' ')} <b>#${t.id} ${esc(t.ward_id)}</b> ${esc(DW.t(t.type))} · ${badge(t.status)} ${t.note ? '· ' + esc(t.note) : ''}</div>`).join('') : '<p class="muted">No escalations.</p>';
      const ob = await DW.api('/api/ops/outbox');
      $('#outbox').innerHTML = `<table><tr><th>Channel</th>${['queued', 'delivered', 'read', 'sent', 'failed'].map((s) => `<th class="num">${s}</th>`).join('')}</tr>${Object.entries(ob.status_counts).map(([ch, v]) => `<tr><td>${esc(ch)}</td>${['queued', 'delivered', 'read', 'sent', 'failed'].map((s) => `<td class="num">${v[s] || 0}</td>`).join('')}</tr>`).join('')}</table>
        <p class="small muted">Live adapters: ${ob.live_adapters.length ? esc(ob.live_adapters.join(', ')) : 'none configured - SMS/WhatsApp use click-to-send links; in-app delivery always works offline.'}</p>`;
    } catch (e) { /* offline: cached */ }
  }
  $('#genAll').onclick = async () => {
    $('#genOut').textContent = 'Generating tasks for all 60 wards…';
    try { const r = await DW.api('/api/ops/plan/generate', { method: 'POST', body: {} }); $('#genOut').textContent = `Week ${r.week}: ${r.created} new tasks, ${r.updated} updated (idempotent), ${r.notices} notices queued · source ${r.source}`; loadOps(); }
    catch (e) { $('#genOut').textContent = e.offline ? 'Offline - plan generation needs the local server. Cached plan still shown.' : e.message; }
  };
  $('#retry').onclick = async () => { try { const r = await DW.api('/api/ops/notify/retry', { method: 'POST', body: {} }); DW.toast(r.note || `Sent ${r.sent}, failed ${r.failed || 0}, still queued ${r.still_queued}`); loadOps(); } catch (e) { DW.toast(e.message); } };

  // ---------------- audit
  async function loadAudit() {
    try { const a = await DW.api('/api/ops/audit'); $('#auditTbl').innerHTML = '<tr><th>Time (UTC)</th><th>User</th><th>Role</th><th>Action</th><th>Detail</th></tr>' + a.audit.map((r) => `<tr><td class="small">${esc(r.ts)}</td><td>${esc(r.username)}</td><td>${esc(r.role)}</td><td><b>${esc(r.action)}</b></td><td class="small muted">${esc(r.detail)}</td></tr>`).join(''); } catch (e) { }
  }

  // ---------------- settings
  function fillSettings() {
    $('#sOrigin').value = settings.origin || ''; $('#sEsc').value = settings.escalation_hours ?? 12;
    const o = settings.stock_override || {}; $('#ovS').value = o.saline_bags || ''; $('#ovK').value = o.diagnostic_kits || ''; $('#ovB').value = o.hospital_beds || '';
    $('#sFallback').checked = !!settings.force_fallback; $('#sOffline').checked = !!settings.offline_sim;
  }
  $$('[data-o]').forEach((c) => c.onclick = () => { $('#sOrigin').value = c.dataset.o; });
  $('#saveSettings').onclick = async () => {
    const ov = {}; if ($('#ovS').value) ov.saline_bags = +$('#ovS').value; if ($('#ovK').value) ov.diagnostic_kits = +$('#ovK').value; if ($('#ovB').value) ov.hospital_beds = +$('#ovB').value;
    try { settings = await DW.api('/api/ops/settings', { method: 'POST', body: { origin: $('#sOrigin').value, escalation_hours: +$('#sEsc').value, stock_override: ov } }); fillSettings(); DW.toast('Settings saved'); } catch (e) { DW.toast(e.message); }
  };
  ['sFallback', 'sOffline'].forEach((id) => $('#' + id).onchange = async () => {
    try { settings = await DW.api('/api/ops/settings', { method: 'POST', body: { force_fallback: $('#sFallback').checked, offline_sim: $('#sOffline').checked } }); DW.toast('Switch updated'); loadHealth(); } catch (e) { DW.toast(e.message); }
  });
  async function loadHealth() {
    try { const h = await DW.api('/api/ops/health'); $('#health').innerHTML = `<pre class="code">${esc(JSON.stringify({ offline_capable: h.offline_capable, external_calls: h.external_calls, forecast_source: h.forecast_source, offline_sim: h.offline_sim, llm_used: h.llm_used, models_loaded: h.models_loaded, optional_live_delivery_code: h.self_check.optional_live_delivery_code }, null, 1))}</pre>`; } catch (e) { }
  }

  async function load() {
    if (tab === 'alloc') return loadAlloc();
    if (tab === 'overflow') return loadOverflow();
    if (tab === 'sim') { if (!lastSim) $('#simGo').click(); return; }
    if (tab === 'ops') return loadOps();
    if (tab === 'audit') return loadAudit();
    if (tab === 'settings') { fillSettings(); return loadHealth(); }
  }
  DW.refresh = load;
  DW.onLang = load;
  load();
})();
