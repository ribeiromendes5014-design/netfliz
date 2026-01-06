const CACHE_NAME = 'netfliz-shell-v1';
const OFFLINE_URL = '/portal/';
const SHELL_ASSETS = [
  '/',
  OFFLINE_URL,
  '/static/css/netflix.css',
];

self.addEventListener('install', (event) => {
  event.waitUntil(
    caches.open(CACHE_NAME).then((cache) => cache.addAll(SHELL_ASSETS))
  );
});

self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches.keys().then((keys) =>
      Promise.all(
        keys
          .filter((key) => key !== CACHE_NAME)
          .map((key) => caches.delete(key))
      )
    )
  );
});

self.addEventListener('fetch', (event) => {
  if (event.request.method !== 'GET') {
    return;
  }
  const requestURL = new URL(event.request.url);
  if (requestURL.origin !== self.location.origin) {
    return;
  }

  event.respondWith(
    fetch(event.request)
      .then((response) => {
        if (response?.ok) {
          const cloned = response.clone();
          caches.open(CACHE_NAME).then((cache) => cache.put(event.request, cloned));
        }
        return response;
      })
      .catch(() => caches.match(event.request).then((cached) => cached || caches.match(OFFLINE_URL)))
  );
});
