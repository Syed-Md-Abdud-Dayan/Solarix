const VERSION = 'dw-onsite-v2';
const SHELL = [
  '/', '/index.html', '/future.html', '/manifest.webmanifest',
  '/assets/css/dashboard.css', '/assets/css/riskmap.css', '/assets/css/accuracy.css', '/assets/css/chatbot.css', '/assets/css/mobile.css',
  '/assets/js/dashboard.js', '/assets/js/riskmap.js', '/assets/js/accuracy.js', '/assets/js/accuracy-data.js', '/assets/js/chatbot.js', '/assets/js/mobile.js',
  '/assets/img/logo.png', '/assets/img/favicon.png', '/assets/fonts/fonts.css',
  '/assets/fonts/dm-sans-latin-400.woff2', '/assets/fonts/dm-sans-latin-500.woff2', '/assets/fonts/dm-sans-latin-600.woff2', '/assets/fonts/dm-sans-latin-700.woff2',
  '/assets/fonts/manrope-latin-500.woff2', '/assets/fonts/manrope-latin-600.woff2', '/assets/fonts/manrope-latin-700.woff2', '/assets/fonts/manrope-latin-800.woff2',
  '/assets/fonts/noto-sans-bengali-bengali-400.woff2', '/assets/fonts/noto-sans-bengali-bengali-600.woff2', '/assets/fonts/noto-sans-bengali-bengali-700.woff2',
  '/ops/login.html', '/ops/admin.html', '/ops/commissioner.html', '/ops/team.html', '/ops/hospital.html',
  '/ops/ops.css', '/ops/ops.js', '/ops/admin.js', '/ops/commissioner.js',
  '/dashboard_data.json', '/classification_metrics.json',
];

self.addEventListener('install', (e) => {
  e.waitUntil(caches.open(VERSION).then((c) => Promise.all(SHELL.map((u) => c.add(u).catch(() => null)))).then(() => self.skipWaiting()));
});
self.addEventListener('activate', (e) => {
  e.waitUntil(caches.keys().then((ks) => Promise.all(ks.filter((k) => k !== VERSION).map((k) => caches.delete(k)))).then(() => self.clients.claim()));
});

function timeout(ms) { return new Promise((_, rej) => setTimeout(() => rej(new Error('timeout')), ms)); }

self.addEventListener('fetch', (e) => {
  const req = e.request;
  const url = new URL(req.url);
  if (req.method !== 'GET' || url.origin !== self.location.origin) return;
  if (url.pathname.startsWith('/api/')) {
    e.respondWith((async () => {
      const cache = await caches.open(VERSION);
      try {
        const res = await Promise.race([fetch(req), timeout(4000)]);
        if (res.ok) cache.put(req, res.clone());
        return res;
      } catch (err) {
        const hit = await cache.match(req);
        if (hit) {
          const h = new Headers(hit.headers); h.set('X-DW-Offline', '1');
          return new Response(await hit.blob(), { status: hit.status, headers: h });
        }
        return new Response(JSON.stringify({ error: 'offline', offline: true }), { status: 503, headers: { 'Content-Type': 'application/json', 'X-DW-Offline': '1' } });
      }
    })());
    return;
  }
  e.respondWith((async () => {
    const cache = await caches.open(VERSION);
    const res = await fetch(req, { cache: 'no-store' }).catch(() => null);
    if (res && res.ok) { cache.put(req, res.clone()); return res; }
    const hit = await cache.match(req, { ignoreSearch: true });
    if (hit) return hit;
    if (res) return res;
    if (req.mode === 'navigate') return (await cache.match(url.pathname.startsWith('/ops') ? '/ops/login.html' : '/index.html')) || Response.error();
    return Response.error();
  })());
});
