// ABDS PWA Service Worker
const CACHE_VERSION = 'abds-v27';
const APP_SHELL_CACHE = `app-shell-${CACHE_VERSION}`;
const DATA_CACHE = `data-${CACHE_VERSION}`;
const IMAGE_CACHE = 'card-images-v1';

const APP_SHELL_FILES = [
  './',
  './index.html',
  './mobile.html',
  './decks.html',
  './decks_mobile.html',
  './manifest.json',
  './icons/icon-192.png',
  './icons/icon-512.png',
];

const DATA_FILES = [
  './data/card_index.json',
  './data/card_details.json',
  './data/link_index.json',
  './data/tactics_cards.json',
  './data/version.json',
];

// Install: pre-cache app shell and data
self.addEventListener('install', (event) => {
  event.waitUntil(
    Promise.all([
      caches.open(APP_SHELL_CACHE).then(cache => cache.addAll(APP_SHELL_FILES)),
      caches.open(DATA_CACHE).then(cache =>
        Promise.all(DATA_FILES.map(url =>
          fetch(url).then(res => {
            if (res.ok) return cache.put(url, res);
          }).catch(() => {})
        ))
      ),
    ]).then(() => self.skipWaiting())
  );
});

// Activate: clean up ALL old caches (except image cache)
self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches.keys().then(keys =>
      Promise.all(
        keys
          .filter(k => k !== APP_SHELL_CACHE && k !== DATA_CACHE && k !== IMAGE_CACHE)
          .map(k => caches.delete(k))
      )
    ).then(() => self.clients.claim())
  );
});

// Fetch strategy
self.addEventListener('fetch', (event) => {
  const url = new URL(event.request.url);

  // Card images from official site — Cache First (opaque, on-demand)
  if (url.hostname === 'www.gundam-ab.com' && url.pathname.startsWith('/images/')) {
    event.respondWith(
      caches.open(IMAGE_CACHE).then(cache =>
        cache.match(event.request).then(cached => {
          if (cached) return cached;
          return fetch(event.request, { mode: 'no-cors' }).then(response => {
            if (response.status === 0 || response.ok) {
              cache.put(event.request, response.clone());
            }
            return response;
          }).catch(() => new Response('', { status: 404 }));
        })
      )
    );
    return;
  }

  // Only handle same-origin requests below
  if (url.origin !== self.location.origin) return;

  // Data JSON: strip query params for cache key
  const isData = url.pathname.includes('/data/') && url.pathname.endsWith('.json');
  const cacheUrl = isData ? url.origin + url.pathname : event.request.url;

  // All same-origin requests — Network First, cache fallback
  event.respondWith(
    fetch(event.request).then(response => {
      if (response.ok) {
        const cacheName = isData ? DATA_CACHE : APP_SHELL_CACHE;
        const cacheReq = isData ? new Request(cacheUrl) : event.request;
        caches.open(cacheName).then(cache => cache.put(cacheReq, response.clone()));
      }
      return response;
    }).catch(() => {
      const cacheReq = isData ? new Request(cacheUrl) : event.request;
      return caches.match(cacheReq).then(cached => cached || new Response('Offline', { status: 503 }));
    })
  );
});

// Message handler for version check
self.addEventListener('message', (event) => {
  if (event.data && event.data.type === 'CHECK_UPDATE') {
    fetch('./data/version.json', { cache: 'no-store' })
      .then(r => r.json())
      .then(data => {
        event.source.postMessage({ type: 'VERSION_INFO', data });
      })
      .catch(() => {});
  }
});
