(function () {
  'use strict';
  const root = document.documentElement;
  const intro = document.getElementById('intro');
  if (!intro) return;
  if (!root.classList.contains('intro-on')) { intro.remove(); return; }

  const shell = document.querySelector('.shell');
  if (shell) shell.setAttribute('inert', '');
  const reduce = window.matchMedia('(prefers-reduced-motion: reduce)').matches;

  function rng(seed) {
    return function () {
      seed |= 0; seed = seed + 0x6D2B79F5 | 0;
      let t = Math.imul(seed ^ seed >>> 15, 1 | seed);
      t = t + Math.imul(t ^ t >>> 7, 61 | t) ^ t;
      return ((t ^ t >>> 14) >>> 0) / 4294967296;
    };
  }
  function pines(seed, base, minH, maxH, gap) {
    const r = rng(seed); let d = '';
    for (let x = -40; x < 1480; x += gap * (0.6 + r() * 0.8)) {
      const h = minH + r() * (maxH - minH), w = h * (0.42 + r() * 0.12);
      const p = [[x - w / 2, base], [x - w * 0.2, base - h * 0.34], [x - w * 0.4, base - h * 0.34], [x - w * 0.14, base - h * 0.64],
        [x - w * 0.29, base - h * 0.64], [x, base - h], [x + w * 0.29, base - h * 0.64], [x + w * 0.14, base - h * 0.64],
        [x + w * 0.4, base - h * 0.34], [x + w * 0.2, base - h * 0.34], [x + w / 2, base]];
      d += 'M' + p.map(q => q[0].toFixed(1) + ' ' + q[1].toFixed(1)).join('L') + 'Z';
    }
    return d + `M-40 ${base}H1480V400H-40Z`;
  }
  const trees = intro.querySelector('.intro-trees');
  if (trees) {
    trees.innerHTML =
      `<path fill="#1c4a2c" opacity=".55" d="${pines(7, 250, 120, 210, 46)}"/>` +
      `<path fill="#143923" d="${pines(21, 300, 110, 200, 52)}"/>` +
      `<path fill="#0d2818" d="${pines(42, 350, 120, 230, 64)}"/>` +
      `<path fill="#081a0f" d="${pines(77, 400, 90, 190, 80)}"/>`;
  }
  if (!reduce) {
    const r = rng(5);
    for (let i = 0; i < 18; i++) {
      const f = document.createElement('i');
      f.className = 'firefly';
      f.style.cssText = `left:${(r() * 100).toFixed(1)}%;top:${(45 + r() * 50).toFixed(1)}%;--d:${(4 + r() * 5).toFixed(1)}s;--dl:${(r() * 5).toFixed(1)}s;--dx:${(r() * 60 - 30).toFixed(0)}px;--dy:${(-20 - r() * 40).toFixed(0)}px`;
      intro.appendChild(f);
    }
  }

  const stage = intro.querySelector('.intro-stage');
  const start = intro.querySelector('.intro-start');
  const timers = [];
  const at = (ms, fn) => timers.push(setTimeout(fn, ms));
  const add = c => intro.classList.add(c);

  function reveal() {
    timers.forEach(clearTimeout);
    intro.classList.remove('slap', 'fly');
    add('hit'); add('reveal');
    start.focus({ preventScroll: true });
  }

  if (reduce) {
    reveal();
  } else {
    add('fly');
    at(2900, () => add('slap'));
    at(3200, () => { add('hit'); stage.classList.add('shake'); if (navigator.vibrate) try { navigator.vibrate(40); } catch (e) {} });
    at(3650, () => add('lift'));
    at(4000, () => { add('reveal'); start.focus({ preventScroll: true }); });
  }

  function enter() {
    timers.forEach(clearTimeout);
    try { sessionStorage.setItem('dw.intro', '1'); } catch (e) {}
    add('leave');
    if (shell) shell.removeAttribute('inert');
    setTimeout(() => { root.classList.remove('intro-on'); intro.remove(); }, reduce ? 0 : 600);
  }
  start.addEventListener('click', enter);
  intro.querySelector('.intro-skip').addEventListener('click', () => {
    if (intro.classList.contains('reveal')) enter(); else reveal();
  });
  intro.addEventListener('keydown', e => { if (e.key === 'Escape') enter(); });
})();
