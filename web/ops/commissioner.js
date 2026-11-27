/* Ward commissioner / secretary page (super admin can pick any ward). */
(async function () {
  const { $, $$, esc, fmt, badge, bar } = DW;
  const me = await DW.boot(['commissioner', 'secretary', 'super_admin']);
  if (!me) return;
  let ward = me.ward_id, plan = null, noticeLang = me.lang || 'en';
  const SUP = [['saline_bags', 'Saline bags'], ['diagnostic_kits', 'Diagnostic kits'], ['hospital_beds', 'Hospital beds']];

  async function loadPlan() {
    plan = await DW.api('/api/ops/plan');
    DW.setFallback(plan.source);
    if (me.role === 'super_admin') {
      const sel = $('#wardSel'); sel.classList.remove('hide');
      if (!sel.options.length) {
        sel.innerHTML = plan.allocation.wards.slice().sort((a, b) => a.ward_id.localeCompare(b.ward_id)).map((w) => `<option>${esc(w.ward_id)}</option>`).join('');
        ward = ward || new URLSearchParams(location.search).get('ward') || plan.allocation.wards[0].ward_id; sel.value = ward;
        sel.onchange = () => { ward = sel.value; render(); };
      }
    }
  }

  async function render() {
    if (!plan) return;
    const w = plan.allocation.wards.find((x) => x.ward_id === ward);
    if (!w) return;
    const b = plan.overflow.wards.find((x) => x.ward_id === ward) || {};
    const trend = plan.trends[ward] || [];
    $('#title').textContent = `${ward} · ${w.city}`;
    $('#briefEn').href = `/api/dispatch/${ward}?format=html&lang=en`; $('#briefBn').href = `/api/dispatch/${ward}?format=html&lang=bn`;
    const band = w.risk === 'Critical' || w.risk === 'High' ? 'High' : w.risk;
    $('#kpis').innerHTML = `
      <div class="kpi"><span class="eyebrow" data-i18n="Risk this week">${DW.t('Risk this week')}</span><b>${badge(w.risk)}</b><small>notice band: ${esc(DW.t(band))} · week ${esc(plan.target_date)}</small></div>
      <div class="kpi"><span class="eyebrow" data-i18n="Predicted cases">${DW.t('Predicted cases')}</span><b>${fmt(w.predicted_cases, 1)} <span class="small muted">±${fmt(w.uncertainty_cases, 1)}</span></b><small>priority rank ${w.priority_rank} of 60 · ${plan.source}</small></div>
      <div class="kpi"><span class="eyebrow">Supply fulfilment</span><b>${fmt(w.fulfilment_pct)}% ${badge(w.deficit_level)}</b>${bar(w.fulfilment_pct)}<small>regional stock ${fmt(plan.settings.stock_pct)}%</small></div>
      <div class="kpi"><span class="eyebrow">Spraying crews</span><b>${w.crews_assigned} / ${w.crews_needed}</b><small>${w.spray_sequence ? 'region sequence #' + w.spray_sequence : 'no spraying needed'}${w.crew_deficit > 0 ? ' · <b style="color:#a12626">short ' + w.crew_deficit + '</b>' : ''}</small></div>`;
    $('#chart').innerHTML = DW.lineChart(trend.map((t) => ({ x: '+' + t.horizon + 'w ' + t.target_date.slice(5), y: t.predicted_cases, lo: Math.max(0, t.predicted_cases - w.uncertainty_cases), hi: t.predicted_cases + w.uncertainty_cases })), { label: 'ward forecast' }) +
      `<div class="row small">${trend.map((t) => `${esc(t.target_date)} ${badge(t.risk)}`).join(' ')}</div>`;
    $('#supplies').innerHTML = `<table><tr><th>Item</th><th class="num" data-i18n="Required">${DW.t('Required')}</th><th class="num" data-i18n="Allocated">${DW.t('Allocated')}</th><th class="num" data-i18n="Deficit">${DW.t('Deficit')}</th><th>Fulfilled</th></tr>
      ${SUP.map(([k, l]) => `<tr><td>${l}</td><td class="num">${w.required[k]}</td><td class="num"><b>${w.allocated[k]}</b></td><td class="num">${w.deficit[k] ? '<b style="color:#a12626">' + w.deficit[k] + '</b>' : 0}</td><td>${bar(100 * w.fulfilment[k])}</td></tr>`).join('')}</table>
      ${w.deficit_level !== 'OK' ? `<div class="warnlist mt"><div class="${w.deficit_level}"><b>Supply deficit alert (${esc(w.deficit_level)})</b>: ${esc(w.what_got_cut)}</div></div>` : '<p class="small muted mt">✓ Fully supplied at the current regional stock level.</p>'}`;
    const out = plan.overflow.transfers.filter((t) => t.from_ward === ward), inn = plan.overflow.transfers.filter((t) => t.to_ward === ward);
    const city = plan.overflow.cities.find((c) => c.city === w.city) || {};
    $('#beds').innerHTML = `<div class="grid g2"><div>${DW.gauge(b.utilisation_pct, 'ward utilisation')}</div><div>${DW.gauge(city.utilisation_pct, w.city + ' pool')}</div></div>
      <table class="mt"><tr><td>Bed demand</td><td class="num">${b.bed_demand ?? '–'}</td><td>Assumed capacity</td><td class="num">${b.effective_capacity ?? '–'}</td></tr><tr><td>Deficit</td><td class="num">${b.deficit ?? 0}</td><td>Net after routing</td><td class="num">${b.net_deficit ?? 0}</td></tr></table>
      ${out.map((t) => `<div class="transfer mt"><b>${esc(ward)}</b><span class="arrow"></span><b>${esc(t.to_ward)}</b><span class="badge SENDING">send ${t.patients}</span></div>`).join('')}
      ${inn.map((t) => `<div class="transfer mt"><b>${esc(t.from_ward)}</b><span class="arrow"></span><b>${esc(ward)}</b><span class="badge RECEIVING">receive ${t.patients}</span></div>`).join('')}
      <p class="small muted">${esc(plan.overflow.summary.capacity_note)}</p>`;
    await Promise.all([renderTasks(), renderNotices(), renderActivity()]);
  }

  function taskSummary(t) {
    const p = t.payload || {};
    if (t.type === 'saline') return `Saline ${p.saline_bags}/${p.saline_required} · kits ${p.diagnostic_kits}/${p.kits_required}`;
    if (t.type === 'spraying') return `Crews ${p.crews_assigned}/${p.crews_needed} · city order #${t.sequence ?? '–'}`;
    if (t.type === 'bed_routing') return `Beds ${p.bed_demand} vs cap ${p.capacity} · send ${(p.send || []).map((s) => s.patients + '→' + s.to).join(', ') || '–'} · receive ${(p.receive || []).map((s) => s.patients + '←' + s.from).join(', ') || '–'}`;
    return esc(p.description || '');
  }

  async function renderTasks() {
    let tl; try { tl = await DW.api('/api/ops/tasks' + ($('#showCancelled').checked ? '?all=1' : '')); } catch (e) { return; }
    const ts = tl.tasks.filter((t) => t.ward_id === ward && t.week === plan.target_date || (t.ward_id === ward && t.source === 'manual'));
    const prog = { total: ts.filter((t) => t.status !== 'cancelled').length, done: ts.filter((t) => t.status === 'done').length };
    const pct = prog.total ? (100 * prog.done) / prog.total : 0;
    const byType = ['saline', 'spraying', 'bed_routing', 'other'].map((k) => { const x = ts.filter((t) => t.type === k && t.status !== 'cancelled'); return [k, x.length, x.filter((t) => t.status === 'done').length]; }).filter((x) => x[1]);
    $('#progress').innerHTML = `<div class="row" style="justify-content:space-between"><b style="font:800 26px Manrope">${fmt(pct, 0)}%</b><span class="muted">${prog.done} of ${prog.total} tasks done</span></div>${bar(pct, true)}
      ${byType.map(([k, n, d]) => `<div class="mt"><div class="row" style="justify-content:space-between"><span>${esc(DW.t(k))}</span><span class="small">${d}/${n}</span></div>${bar(n ? 100 * d / n : 0)}</div>`).join('')}
      ${ts.filter((t) => t.escalated).length ? `<div class="warnlist mt">${ts.filter((t) => t.escalated).map((t) => `<div class="CRITICAL">#${t.id} ${esc(DW.t(t.type))}: ${t.escalations.map((e) => e.replace('_', ' ')).join(', ')}</div>`).join('')}</div>` : ''}`;
    $('#tasks').innerHTML = ts.length ? ts.map((t) => `<div class="card-task ${t.escalated ? 'esc' : ''}">
        <div class="hd"><div class="row"><span class="seq">${t.type === 'spraying' && t.sequence ? t.sequence : '•'}</span><b>#${t.id} ${esc(DW.t(t.type))}</b>${badge(t.risk)}${badge(t.status)}${t.source !== 'auto' ? badge('acknowledged', t.source) : ''}${t.escalations.map((e) => badge(e, e.replace('_', ' '))).join('')}</div>
          <span class="small muted">team: ${esc(t.assigned_team)} · due ${esc((t.due_at || '').slice(0, 10))}</span></div>
        <div>${taskSummary(t)}</div>
        ${t.note ? `<div class="small"><b>Team note:</b> ${esc(t.note)}</div>` : ''}${t.proof ? `<div class="small"><b>Proof:</b> ${esc(t.proof)}</div>` : ''}
        ${t.override_reason ? `<div class="small muted">Override by ${esc(t.override_by)}: ${esc(t.override_reason)}</div>` : ''}
        <div class="row">
          <select data-reassign="${t.id}" style="width:auto"><option value="">Reassign…</option><option value="saline_team">Saline team</option><option value="spraying_team">Spraying team</option><option value="bed_team">Bed team</option></select>
          ${t.type === 'saline' || t.type === 'spraying' ? `<button class="btn sm" data-override="${t.id}">Override qty</button>` : ''}
          ${t.status !== 'cancelled' && t.status !== 'done' ? `<button class="btn sm" data-cancel="${t.id}">Cancel</button>` : ''}
        </div></div>`).join('') : '<p class="muted">No tasks for this week yet. Press "Generate this week\'s plan".</p>';
    $$('[data-reassign]').forEach((s) => s.onchange = () => s.value && update(+s.dataset.reassign, { assigned_team: s.value }));
    $$('[data-cancel]').forEach((b) => b.onclick = () => confirm('Cancel this task?') && update(+b.dataset.cancel, { status: 'cancelled' }));
    $$('[data-override]').forEach((b) => b.onclick = () => {
      const t = ts.find((x) => x.id === +b.dataset.override); const p = { ...t.payload };
      const field = t.type === 'saline' ? 'saline_bags' : 'crews_assigned';
      const v = prompt(`New ${field.replace('_', ' ')} (engine suggested ${p[field]}):`, p[field]); if (v === null) return;
      const reason = prompt('Reason for overriding the engine (required, recorded in the audit log):'); if (!reason) return DW.toast('Override cancelled: a reason is required');
      p[field] = +v; update(t.id, { payload: p, override_reason: reason });
    });
  }
  async function update(id, changes) {
    try { const r = await DW.act({ type: 'task_update', id, changes }); if (!r.queued) DW.toast('Task updated'); renderTasks(); renderActivity(); } catch (e) { DW.toast(e.message); }
  }

  async function renderNotices() {
    try {
      const d = await DW.api(`/api/dispatch/${ward}?lang=${noticeLang}`);
      $('#notices').innerHTML = d.sms.map((s, i) => {
        const wa = d.whatsapp[i];
        return `<div class="msg"><div class="row" style="justify-content:space-between"><b>${esc(s.team)} · SMS (${s.short_chars} chars, ${s.encoding})</b><span class="small muted">${esc(s.dispatch_id)}</span></div>${esc(s.short)}
          <details><summary class="small">Long SMS (${s.long_parts} parts) / WhatsApp</summary><pre class="code">${esc(s.long)}</pre><pre class="code">${esc(wa.text)}</pre></details>
          <div class="row"><a class="btn sm" href="${esc(wa.link)}" target="_blank" rel="noopener">WhatsApp ↗</a><a class="btn sm" href="${esc(s.link)}">SMS ↗</a><button class="btn sm" data-copy="${i}">Copy</button></div></div>`;
      }).join('');
      $$('[data-copy]').forEach((b) => b.onclick = () => { navigator.clipboard && navigator.clipboard.writeText(d.whatsapp[+b.dataset.copy].text); DW.toast('Copied'); });
    } catch (e) { $('#notices').innerHTML = '<p class="muted">Notices unavailable offline (open the brief from cache or the /exports folder).</p>'; }
  }
  $$('[data-lang]').forEach((b) => b.onclick = () => { noticeLang = b.dataset.lang; renderNotices(); });

  async function renderActivity() {
    try { const a = await DW.api('/api/ops/audit'); $('#activity').innerHTML = '<table>' + a.audit.slice(0, 60).map((r) => `<tr><td class="small muted">${esc(r.ts.replace('T', ' ').slice(5, 16))}</td><td><b>${esc(r.username)}</b> ${esc(r.action.replace(/_/g, ' '))}<br><span class="small muted">${esc(r.detail).slice(0, 140)}</span></td></tr>`).join('') + '</table>'; } catch (e) { }
  }

  $('#gen').onclick = async () => {
    try { const r = await DW.api('/api/ops/plan/generate', { method: 'POST', body: me.role === 'super_admin' ? { ward_ids: [ward] } : {} }); DW.toast(`Plan for week ${r.week}: ${r.created} new, ${r.updated} updated tasks; ${r.notices} notices queued`); render(); }
    catch (e) { DW.toast(e.offline ? 'Offline: plan generation needs the local server' : e.message); }
  };
  $('#send').onclick = async () => { try { const r = await DW.api('/api/ops/notify/retry', { method: 'POST', body: {} }); DW.toast(r.note || `Sent ${r.sent}, queued ${r.still_queued}`); } catch (e) { DW.toast(e.message); } };
  $('#nGo').onclick = async () => {
    try { await DW.api('/api/ops/tasks', { method: 'POST', body: { ward_id: ward, type: $('#nType').value, assigned_team: $('#nTeam').value, description: $('#nDesc').value } }); $('#nDesc').value = ''; DW.toast('Task created and team notified'); renderTasks(); }
    catch (e) { DW.toast(e.message); }
  };
  $('#showCancelled').onchange = renderTasks;

  DW.refresh = async () => { try { await loadPlan(); } catch (e) { } render(); };
  DW.onLang = render;
  await DW.refresh();
  setInterval(() => { if (!document.hidden) renderTasks(); }, 20000);
})();
