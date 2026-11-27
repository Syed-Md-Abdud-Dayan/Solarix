/* Dengue Watch operations UI - shared helpers.
 * - api(): fetch with session cookie + CSRF; on failure serves the last good response
 *   from localStorage and shows the "Offline mode" banner.
 * - act(): state-changing actions; if offline they are queued (idempotent key) and
 *   replayed through /api/ops/batch when the connection returns.
 * - Kill-switch demo: makes the UI behave exactly as if the server/internet were gone.
 * - EN / বাংলা toggle for all [data-i18n] labels.
 */
(function () {
  const LS = window.localStorage;
  const DW = (window.DW = {});
  const $ = (s, r = document) => r.querySelector(s);
  const $$ = (s, r = document) => Array.from(r.querySelectorAll(s));
  DW.$ = $; DW.$$ = $$;
  DW.esc = (s) => String(s ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  DW.fmt = (n, d = 0) => (n == null || isNaN(n) ? '–' : Number(n).toLocaleString('en-US', { maximumFractionDigits: d, minimumFractionDigits: 0 }));
  DW.badge = (v, label) => `<span class="badge ${DW.esc(v)}">${DW.esc(label ?? DW.t(v))}</span>`;
  DW.bar = (pct, big) => { const c = pct < 60 ? 'c' : pct < 100 ? 'w' : ''; return `<div class="bar ${c} ${big ? 'big-bar' : ''}"><i style="width:${Math.max(0, Math.min(100, pct))}%"></i></div>`; };

  // ---------------------------------------------------------------- i18n
  const BN = {
    'Critical': 'সংকটপূর্ণ', 'High': 'উচ্চ', 'Medium': 'মাঝারি', 'Low': 'নিম্ন', 'OK': 'পর্যাপ্ত', 'WARNING': 'সতর্কতা', 'CRITICAL': 'সংকট',
    'assigned': 'বরাদ্দ', 'acknowledged': 'স্বীকৃত', 'in_progress': 'চলছে', 'done': 'সম্পন্ন', 'blocked': 'আটকে আছে', 'cancelled': 'বাতিল',
    'saline': 'স্যালাইন ও কিট', 'spraying': 'স্প্রে', 'bed_routing': 'বেড ও স্থানান্তর', 'other': 'অন্যান্য',
    'Acknowledge': 'স্বীকার করুন', 'Start': 'শুরু', 'Done': 'সম্পন্ন', 'Blocked': 'আটকে আছে', 'Save note': 'নোট সংরক্ষণ',
    'Inbox': 'ইনবক্স', 'My tasks': 'আমার কাজ', 'Logout': 'লগআউট', 'Offline kill-switch demo': 'অফলাইন কিল-সুইচ ডেমো',
    'Allocation': 'বরাদ্দ', 'Hospital overflow': 'হাসপাতাল ওভারফ্লো', 'Simulator': 'সিমুলেটর', 'Operations': 'অপারেশন', 'Audit log': 'অডিট লগ', 'Settings': 'সেটিংস',
    'Generate this week\'s plan': 'এই সপ্তাহের পরিকল্পনা তৈরি', 'Send / retry notices': 'নোটিশ পাঠান / পুনরায় চেষ্টা', 'Download brief': 'ব্রিফ ডাউনলোড',
    'Predicted cases': 'পূর্বাভাসিত রোগী', 'Required': 'প্রয়োজন', 'Allocated': 'বরাদ্দ', 'Deficit': 'ঘাটতি', 'Work completed': 'কাজ সম্পন্ন',
    'Tasks': 'কাজসমূহ', 'Activity': 'কার্যক্রম', 'Forecast': 'পূর্বাভাস', 'Supplies': 'সরবরাহ', 'Beds': 'বেড', 'Transfers': 'স্থানান্তর',
    'Accept': 'গ্রহণ', 'Decline': 'প্রত্যাখ্যান', 'Save': 'সংরক্ষণ', 'Risk this week': 'এই সপ্তাহের ঝুঁকি', 'Dispatch notices': 'প্রেরণ নোটিশ',
    'Offline mode - showing last synced plan': 'অফলাইন মোড - সর্বশেষ সিঙ্ক করা পরিকল্পনা দেখানো হচ্ছে',
    'Model fallback active: deterministic seasonal forecast': 'মডেল বিকল্প চালু: নির্ধারিত মৌসুমি পূর্বাভাস',
    'actions queued offline - will sync automatically': 'টি কাজ অফলাইনে জমা - সংযোগ ফিরলে স্বয়ংক্রিয়ভাবে সিঙ্ক হবে',
    'Hospital portal': 'হাসপাতাল পোর্টাল', 'Team panel': 'দল প্যানেল', 'Commissioner': 'কমিশনার', 'Regional command': 'আঞ্চলিক কমান্ড', 'Public dashboard': 'পাবলিক ড্যাশবোর্ড',
  };
  DW.lang = () => LS.getItem('dw-lang') || 'en';
  const EN = { saline: 'Saline & kits', spraying: 'Spraying', bed_routing: 'Bed routing', other: 'Other', in_progress: 'in progress' };
  DW.t = (k) => (DW.lang() === 'bn' && BN[k]) || EN[k] || k;
  DW.applyI18n = () => {
    document.documentElement.lang = DW.lang();
    $$('[data-i18n]').forEach((el) => { const k = el.getAttribute('data-i18n'); el.textContent = DW.t(k); });
  };
  DW.toggleLang = () => { LS.setItem('dw-lang', DW.lang() === 'bn' ? 'en' : 'bn'); DW.applyI18n(); if (DW.onLang) DW.onLang(); };

  // ---------------------------------------------------------------- offline plumbing
  DW.killed = () => LS.getItem('dw-killswitch') === '1';
  DW.offline = false;
  function setOffline(on) {
    DW.offline = on;
    const b = $('#bnOffline'); if (b) b.classList.toggle('show', on);
    const d = $('#netDot'); if (d) d.classList.toggle('off', on);
    const s = $('#netTxt'); if (s) s.textContent = on ? (DW.killed() ? 'Kill-switch ON (simulated offline)' : 'Offline') : 'Online · local server';
  }
  DW.setFallback = (src) => { const b = $('#bnFallback'); if (b) b.classList.toggle('show', src === 'fallback'); };

  DW.api = async function (path, opts = {}) {
    const key = 'dw-cache:' + path;
    try {
      if (DW.killed()) throw new Error('kill-switch');
      const headers = { 'Content-Type': 'application/json' };
      const csrf = LS.getItem('dw-csrf'); if (csrf) headers['X-CSRF-Token'] = csrf;
      const res = await fetch(path, { method: opts.method || 'GET', headers, credentials: 'same-origin',
        body: opts.body ? JSON.stringify(opts.body) : undefined, cache: 'no-store' });
      const ct = res.headers.get('Content-Type') || '';
      const data = ct.includes('json') ? await res.json() : await res.text();
      if (res.headers.get('X-DW-Offline') === '1') {           // served by the service worker cache
        if (!res.ok) throw new Error('offline');
        setOffline(true); if (data && typeof data === 'object') data.__offline = true; return data;
      }
      if (res.status === 401 && !opts.noRedirect) { location.href = '/ops/login.html?next=' + encodeURIComponent(location.pathname); throw new Error('login'); }
      if (!res.ok) { const e = new Error((data && data.error) || res.statusText); e.status = res.status; throw e; }
      if ((opts.method || 'GET') === 'GET') { try { LS.setItem(key, JSON.stringify({ t: Date.now(), data })); } catch (e) { /* quota */ } }
      setOffline(false);
      return data;
    } catch (e) {
      if (e.status || e.message === 'login') throw e;           // real server answer, not a network problem
      setOffline(true);
      if ((opts.method || 'GET') === 'GET') {
        const c = LS.getItem(key);
        if (c) { const v = JSON.parse(c); v.data.__offline = true; v.data.__cached_at = v.t; return v.data; }
      }
      throw Object.assign(new Error('offline'), { offline: true });
    }
  };

  // queue of offline actions (replayed via /api/ops/batch with idempotency keys)
  const Q = 'dw-queue';
  DW.queue = () => JSON.parse(LS.getItem(Q) || '[]');
  function saveQueue(q) { LS.setItem(Q, JSON.stringify(q)); const b = $('#bnQueue'); if (b) { b.classList.toggle('show', q.length > 0); b.textContent = `${q.length} ${DW.t('actions queued offline - will sync automatically')}`; } }
  DW.act = async function (action) {
    action.key = action.key || (Date.now().toString(36) + Math.random().toString(36).slice(2, 8));
    try {
      if (DW.killed()) throw Object.assign(new Error('kill'), { offline: true });
      const r = await DW.api('/api/ops/batch', { method: 'POST', body: { actions: [action] } });
      const res = r.results[0];
      if (!res.ok) throw new Error(res.error);
      return { ok: true };
    } catch (e) {
      if (!e.offline && e.message !== 'offline') throw e;
      const q = DW.queue(); q.push(action); saveQueue(q);
      DW.toast('Saved offline - will sync when the connection returns');
      return { ok: true, queued: true };
    }
  };
  DW.flushQueue = async function () {
    const q = DW.queue();
    if (!q.length || DW.killed()) return;
    try {
      const r = await DW.api('/api/ops/batch', { method: 'POST', body: { actions: q } });
      saveQueue([]);
      DW.toast(`Synced ${r.results.filter((x) => x.ok).length} offline action(s)`);
      if (DW.refresh) DW.refresh();
    } catch (e) { /* still offline */ }
  };
  window.addEventListener('online', () => DW.flushQueue());
  setInterval(() => DW.flushQueue(), 15000);

  DW.toast = (msg) => {
    let t = $('#toast'); if (!t) { t = document.createElement('div'); t.id = 'toast'; t.className = 'toast'; document.body.appendChild(t); }
    t.textContent = msg; t.classList.add('show'); clearTimeout(t._h); t._h = setTimeout(() => t.classList.remove('show'), 3200);
  };

  // ---------------------------------------------------------------- layout + auth
  const NAV = {
    super_admin: [['/ops/admin.html', 'Regional command'], ['/ops/commissioner.html', 'Commissioner'], ['/ops/team.html', 'Team panel'], ['/ops/hospital.html', 'Hospital portal']],
    commissioner: [['/ops/commissioner.html', 'Commissioner']], secretary: [['/ops/commissioner.html', 'Commissioner']],
    saline_team: [['/ops/team.html', 'Team panel']], spraying_team: [['/ops/team.html', 'Team panel']], bed_team: [['/ops/team.html', 'Team panel']],
    hospital: [['/ops/hospital.html', 'Hospital portal']],
  };
  DW.layout = function (user) {
    const side = $('#side');
    const links = (NAV[user.role] || []).map(([h, l]) => `<a href="${h}" class="${location.pathname === h ? 'active' : ''}" data-i18n="${l}">${DW.t(l)}</a>`).join('');
    side.innerHTML = `
      <a class="brand" href="/"><img src="/assets/img/logo.png" alt=""><span>DENGUE<span class="brand-light">WATCH</span><small>OPERATIONS COMMAND</small></span></a>
      <div class="side-label">WORKSPACE</div>
      <nav class="side-nav">${links}<a href="/" data-i18n="Public dashboard">${DW.t('Public dashboard')}</a></nav>
      <div class="side-bottom">
        <div class="side-box"><b>${DW.esc(user.display_name || user.username)}</b>${DW.esc(user.role_label)}${user.ward_id ? ' · ' + DW.esc(user.ward_id) : user.city ? ' · ' + DW.esc(user.city) : ''}
          <div class="row" style="margin-top:8px"><button class="btn sm" id="langBtn">EN / বাংলা</button><button class="btn sm" id="logoutBtn" data-i18n="Logout">${DW.t('Logout')}</button></div></div>
        <div class="side-box"><div class="row"><i class="dot" id="netDot"></i><span id="netTxt">Online · local server</span></div>
          <label class="switch"><span data-i18n="Offline kill-switch demo">${DW.t('Offline kill-switch demo')}</span><input type="checkbox" id="killSw" ${DW.killed() ? 'checked' : ''}></label></div>
      </div>`;
    $('#langBtn').onclick = DW.toggleLang;
    $('#logoutBtn').onclick = async () => { try { await DW.api('/api/ops/logout', { method: 'POST', noRedirect: true }); } catch (e) { } LS.removeItem('dw-csrf'); LS.removeItem('dw-me'); location.href = '/ops/login.html'; };
    $('#killSw').onchange = (e) => { LS.setItem('dw-killswitch', e.target.checked ? '1' : '0'); DW.toast(e.target.checked ? 'Kill-switch ON: no network calls, cached plan + offline queue' : 'Kill-switch OFF: reconnecting'); if (!e.target.checked) DW.flushQueue(); if (DW.refresh) DW.refresh(); };
    const banners = document.createElement('div');
    banners.innerHTML = `<div class="banner offline" id="bnOffline">⚠ <span data-i18n="Offline mode - showing last synced plan">${DW.t('Offline mode - showing last synced plan')}</span></div>
      <div class="banner fallback" id="bnFallback">ⓘ <span data-i18n="Model fallback active: deterministic seasonal forecast">${DW.t('Model fallback active: deterministic seasonal forecast')}</span></div>
      <div class="banner queue" id="bnQueue"></div>`;
    $('main').insertBefore(banners, $('main').children[1] || null);
    saveQueue(DW.queue());
    setOffline(DW.killed());
    DW.applyI18n();
  };

  DW.boot = async function (allowed) {
    let me;
    try {
      const r = await DW.api('/api/ops/me');
      me = r.user; LS.setItem('dw-csrf', r.csrf); LS.setItem('dw-me', JSON.stringify(me));
    } catch (e) {
      const cached = LS.getItem('dw-me');
      if (!cached) { location.href = '/ops/login.html'; return null; }
      me = JSON.parse(cached);
    }
    if (allowed && !allowed.includes(me.role)) { location.href = me.home; return null; }
    DW.me = me;
    DW.layout(me);
    return me;
  };

  // ---------------------------------------------------------------- tiny SVG charts
  DW.lineChart = function (series, opts = {}) {
    // series: [{x:label, y, lo, hi}]
    const W = opts.w || 520, H = opts.h || 170, P = 30;
    if (!series.length) return '';
    const maxY = Math.max(1, ...series.map((s) => s.hi ?? s.y)) * 1.1;
    const X = (i) => P + (i * (W - 2 * P)) / Math.max(1, series.length - 1);
    const Y = (v) => H - P + 6 - (v / maxY) * (H - P - 10);
    const band = series.map((s, i) => `${X(i)},${Y(s.hi ?? s.y)}`).join(' ') + ' ' + series.slice().reverse().map((s, j) => `${X(series.length - 1 - j)},${Y(s.lo ?? s.y)}`).join(' ');
    const line = series.map((s, i) => `${i ? 'L' : 'M'}${X(i)},${Y(s.y)}`).join(' ');
    const pts = series.map((s, i) => `<circle cx="${X(i)}" cy="${Y(s.y)}" r="4" fill="#0c9b83"><title>${DW.esc(s.x)}: ${DW.fmt(s.y, 1)}</title></circle><text x="${X(i)}" y="${Y(s.y) - 9}" font-size="11" text-anchor="middle" fill="#132b3b">${DW.fmt(s.y, 1)}</text><text x="${X(i)}" y="${H - 6}" font-size="10" text-anchor="middle" fill="#718392">${DW.esc(s.x)}</text>`).join('');
    return `<svg viewBox="0 0 ${W} ${H}" width="100%" role="img" aria-label="${DW.esc(opts.label || 'chart')}"><polygon points="${band}" fill="#0c9b8322"/><path d="${line}" fill="none" stroke="#0c9b83" stroke-width="2.5"/>${pts}</svg>`;
  };
  DW.barChart = function (rows, opts = {}) {
    // rows: [{label, value, value2?}] horizontal bars
    const W = opts.w || 560, rowH = 22, H = rows.length * rowH + 10, L = opts.left || 120;
    const max = Math.max(1e-9, ...rows.map((r) => Math.max(r.value, r.value2 || 0)));
    const bars = rows.map((r, i) => {
      const y = 5 + i * rowH, w = ((W - L - 50) * r.value) / max;
      return `<text x="${L - 6}" y="${y + 14}" font-size="11" text-anchor="end" fill="#132b3b">${DW.esc(r.label)}</text>
        <rect x="${L}" y="${y + 3}" width="${Math.max(1, w)}" height="14" rx="4" fill="${r.color || '#0c9b83'}"><title>${DW.esc(r.label)}: ${DW.fmt(r.value, 2)}</title></rect>
        <text x="${L + w + 5}" y="${y + 14}" font-size="11" fill="#456070">${DW.fmt(r.value, 2)}</text>`;
    }).join('');
    return `<svg viewBox="0 0 ${W} ${H}" width="100%" role="img" aria-label="${DW.esc(opts.label || 'bar chart')}">${bars}</svg>`;
  };
  DW.gauge = function (pct, label) {
    const v = Math.max(0, Math.min(150, pct || 0)), a = (Math.min(v, 150) / 150) * Math.PI;
    const x = 60 - 48 * Math.cos(a), y = 62 - 48 * Math.sin(a);
    const col = v > 100 ? '#d85d5d' : v > 85 ? '#d38a2c' : '#0c9b83';
    return `<div class="gauge"><svg viewBox="0 0 120 72" width="140"><path d="M12 62 A48 48 0 0 1 108 62" fill="none" stroke="#eaf0f2" stroke-width="11" stroke-linecap="round"/>
      <path d="M12 62 A48 48 0 0 1 ${x.toFixed(1)} ${y.toFixed(1)}" fill="none" stroke="${col}" stroke-width="11" stroke-linecap="round"/>
      <text x="60" y="58" text-anchor="middle" font-size="17" font-weight="800" fill="#132b3b">${DW.fmt(pct, 0)}%</text></svg><b style="font-size:12px">${DW.esc(label)}</b></div>`;
  };

  // register the service worker (offline app shell + last API responses)
  if ('serviceWorker' in navigator) window.addEventListener('load', () => navigator.serviceWorker.register('/sw.js').catch(() => {}));
})();
