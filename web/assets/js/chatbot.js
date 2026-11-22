/* Dengue Watch chatbot UI: talks to POST /api/chat. All text is rendered with textContent (no HTML injection). */
(function () {
  'use strict';
  const el = (s) => document.querySelector(s);
  const log = el('#chatLog'), input = el('#chatInput'), form = el('#chatForm'), sendBtn = el('#chatSend');
  if (!log || !form) return;
  const KEY = 'dw.chat.v2';
  const I18N = {
    en: { title: 'Dengue assistant', ph: 'Ask in English or বাংলা, e.g. risk in Dhaka North next 4 weeks', ask: 'Ask', clear: 'Clear', copy: 'Copy', copied: 'Copied',
          err: 'Sorry - I could not reach the server. If someone is seriously ill, go to a hospital now (DGHS hotline 16263, emergency 999).', you: 'You', ctx: 'Talking about', sub: 'Dengue facts, danger signs and care, plus live risk answers from the trained models. English & বাংলা. Not a doctor - it cannot diagnose.',
          emerg: '<b>Emergency?</b> Severe belly pain, repeated vomiting, bleeding, drowsiness, fast breathing or cold skin with fever: go to a hospital now. DGHS hotline 16263 · Emergency 999' },
    bn: { title: 'ডেঙ্গু সহকারী', ph: 'ইংরেজি বা বাংলায় লিখুন, যেমন ঢাকা উত্তরে আগামী ৪ সপ্তাহের ঝুঁকি', ask: 'জিজ্ঞাসা', clear: 'মুছুন', copy: 'কপি', copied: 'কপি হয়েছে',
          err: 'দুঃখিত, সার্ভারে পৌঁছাতে পারিনি। কেউ গুরুতর অসুস্থ হলে এখনই হাসপাতালে যান (স্বাস্থ্য হটলাইন ১৬২৬৩, জরুরি ৯৯৯)।', you: 'আপনি', ctx: 'আলোচনা', sub: 'ডেঙ্গুর তথ্য, বিপদ-চিহ্ন ও যত্ন, সঙ্গে প্রশিক্ষিত মডেল থেকে সরাসরি ঝুঁকির উত্তর। আমি চিকিৎসক নই - রোগ নির্ণয় করতে পারি না।',
          emerg: '<b>জরুরি?</b> জ্বরের সঙ্গে তীব্র পেটব্যথা, বারবার বমি, রক্তক্ষরণ, ঝিমুনি, দ্রুত শ্বাস বা ঠান্ডা ত্বক হলে এখনই হাসপাতালে যান। স্বাস্থ্য হটলাইন ১৬২৬৩ · জরুরি ৯৯৯' },
  };
  let st = { msgs: [], context: {}, lang: 'auto' };
  try { const s = JSON.parse(localStorage.getItem(KEY) || 'null'); if (s && Array.isArray(s.msgs)) st = Object.assign(st, s); } catch (_) {}
  const save = () => { try { localStorage.setItem(KEY, JSON.stringify({ msgs: st.msgs.slice(-30), context: st.context, lang: st.lang })); } catch (_) {} };
  const uiLang = () => (st.lang === 'bn' || (st.lang === 'auto' && st.context.lang === 'bn')) ? 'bn' : 'en';

  function h(tag, attrs, ...kids) {
    const n = document.createElement(tag);
    for (const [k, v] of Object.entries(attrs || {})) { if (v == null) continue; if (k === 'class') n.className = v; else n.setAttribute(k, v); }
    for (const k of kids.flat()) if (k != null) n.append(k.nodeType ? k : document.createTextNode(String(k)));
    return n;
  }
  const RISK = new Set(['Critical', 'High', 'Medium', 'Low', 'সংকটজনক', 'উচ্চ', 'মাঝারি', 'নিম্ন']);

  function renderBot(m) {
    const r = m.reply || {}, box = h('div', { class: 'msg bot ' + (m.severity || 'info'), lang: m.lang || 'en' });
    if (r.title) box.append(h('h4', null, r.title));
    if (r.text) box.append(h('p', null, r.text));
    if (r.bullets && r.bullets.length) box.append(h('ul', null, r.bullets.map((b) => h('li', null, b))));
    if (r.table && r.table.rows && r.table.rows.length) {
      const t = h('table', null, h('thead', null, h('tr', null, r.table.columns.map((c) => h('th', null, c)))),
        h('tbody', null, r.table.rows.map((row) => h('tr', null, row.map((c) => RISK.has(c) ? h('td', null, h('span', { class: 'risk-pill r-' + c }, c)) : h('td', null, c))))));
      box.append(h('div', { class: 'tbl' }, t));
    }
    (r.notes || []).forEach((n) => box.append(h('div', { class: 'note' }, n)));
    const L = I18N[m.lang === 'bn' ? 'bn' : 'en'];
    const meta = h('div', { class: 'meta' }, h('span', null, [(m.sources || []).length ? 'Source: ' + m.sources.join(' · ') : '', m.disclaimer ? (m.sources && m.sources.length ? ' — ' : '') + m.disclaimer : ''].join('')));
    const cp = h('button', { type: 'button', 'aria-label': L.copy }, L.copy);
    cp.addEventListener('click', async () => {
      const txt = [r.title, r.text, ...(r.bullets || []), ...(r.notes || [])].filter(Boolean).join('\n');
      try { await navigator.clipboard.writeText(txt); cp.textContent = L.copied; setTimeout(() => (cp.textContent = L.copy), 1500); } catch (_) {}
    });
    meta.append(cp); box.append(meta);
    return box;
  }

  function render() {
    log.replaceChildren(...st.msgs.map((m) => m.who === 'user' ? h('div', { class: 'msg user', lang: m.lang || null }, m.text) : renderBot(m)));
    log.scrollTop = log.scrollHeight;
    const L = I18N[uiLang()];
    input.placeholder = L.ph; sendBtn.textContent = L.ask; el('#clearChat').textContent = L.clear; el('#chatTitle').textContent = L.title; el('#chatSub').textContent = L.sub;
    const em = el('#chatEmerg'); em.replaceChildren(...new DOMParser().parseFromString(L.emerg, 'text/html').body.childNodes); em.lang = uiLang();
    document.querySelectorAll('#chatLang button').forEach((b) => b.classList.toggle('on', b.dataset.l === st.lang));
    const last = [...st.msgs].reverse().find((m) => m.who === 'bot');
    chips(last ? last.suggestions : null);
    const c = st.context, bits = [c.city, c.ward_id, c.horizon ? c.horizon + ' wk' : null].filter(Boolean), cx = el('#chatCtx');
    cx.hidden = !bits.length; cx.replaceChildren(...(bits.length ? [document.createTextNode(L.ctx + ': '), ...bits.map((b) => h('span', null, b))] : []));
  }

  async function chips(list) {
    const box = el('#suggest');
    if (!list || !list.length) {
      try { const r = await fetch('/api/chat/suggestions'); const j = await r.json(); list = (j[uiLang()] || j.en).slice(0, 6).map((s) => ({ label: s, text: s })); } catch (_) { list = []; }
    }
    box.replaceChildren(...list.map((s) => { const b = h('button', { type: 'button' }, s.label); b.addEventListener('click', () => send(s.text)); return b; }));
  }

  let busy = false;
  async function send(text) {
    text = (text || '').trim(); if (!text || busy) return;
    busy = true; input.disabled = sendBtn.disabled = true;
    st.msgs.push({ who: 'user', text, lang: /[ঀ-৿]/.test(text) ? 'bn' : 'en' }); render();
    const typing = h('div', { class: 'msg bot', 'aria-label': 'typing' }, h('span', { class: 'typing' }, h('i'), h('i'), h('i'))); log.append(typing); log.scrollTop = log.scrollHeight;
    const t0 = Date.now();
    try {
      const resp = await fetch('/api/chat', { method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ message: text, context: st.context, lang: st.lang === 'auto' ? undefined : st.lang }) });
      const j = await resp.json();
      if (!resp.ok) throw new Error(j.error || 'HTTP ' + resp.status);
      await new Promise((r) => setTimeout(r, Math.max(0, 350 - (Date.now() - t0)))); // avoid flicker
      st.context = j.context || st.context;
      st.msgs.push({ who: 'bot', reply: j.reply, severity: j.severity, lang: j.lang, suggestions: j.suggestions, sources: j.sources, disclaimer: j.disclaimer });
    } catch (e) {
      const L = I18N[st.lang === 'bn' ? 'bn' : 'en'];
      st.msgs.push({ who: 'bot', severity: 'caution', lang: st.lang === 'bn' ? 'bn' : 'en', reply: { text: L.err, bullets: [], notes: [String(e.message || e)] }, suggestions: [] });
    }
    busy = false; input.disabled = sendBtn.disabled = false; save(); render(); input.focus();
  }

  form.addEventListener('submit', (e) => { e.preventDefault(); const v = input.value; input.value = ''; send(v); });
  el('#clearChat').addEventListener('click', () => { st.msgs = []; st.context = {}; save(); start(); });
  el('#chatLang').addEventListener('click', (e) => { const b = e.target.closest('button'); if (!b) return; st.lang = b.dataset.l; save(); render(); });
  function start() {
    if (!st.msgs.length) {
      const bn = st.lang === 'bn';
      st.msgs.push({ who: 'bot', lang: bn ? 'bn' : 'en', severity: 'info', suggestions: [], sources: [], reply: {
        title: bn ? 'আসসালামু আলাইকুম' : 'Hello, I am the Dengue Watch assistant',
        text: bn ? 'ডেঙ্গুর লক্ষণ, সতর্কসংকেত, প্রতিরোধ ও যত্ন নিয়ে এবং মডেল থেকে শহর/ওয়ার্ডভিত্তিক ঝুঁকি, ভবিষ্যৎ পূর্বাভাস ও বৃষ্টির পরিস্থিতি নিয়ে প্রশ্ন করুন।'
          : 'Ask me about dengue symptoms, warning signs, prevention and home care - or about risk by city and ward, future seasons and rainfall what-ifs from the trained models.',
        bullets: bn ? ['জ্বরের সঙ্গে পেটব্যথা, বারবার বমি, রক্তক্ষরণ বা ঝিমুনি হলে এখনই হাসপাতালে যান।'] : ['If there is fever with belly pain, repeated vomiting, bleeding or drowsiness, go to a hospital now.'], notes: [] } });
    }
    render();
  }
  start();
})();
