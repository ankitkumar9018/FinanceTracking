// Simple service worker for offline caching
const CACHE_NAME = "ft-cache-v7";

self.addEventListener("install", (event) => {
  // Skip waiting to activate immediately
  self.skipWaiting();
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches.keys().then((keys) =>
      Promise.all(
        keys.filter((key) => key !== CACHE_NAME).map((key) => caches.delete(key))
      )
    )
  );
  self.clients.claim();
});

self.addEventListener("fetch", (event) => {
  const { request } = event;

  // Skip non-GET requests
  if (request.method !== "GET") return;

  // Skip chrome-extension and other non-http(s) requests
  if (!request.url.startsWith("http")) return;

  // Skip caching for JS/CSS chunks - let browser handle these normally
  // This prevents stale cache issues after rebuilds
  if (request.url.includes("/_next/static/")) {
    return; // Don't intercept - use normal browser fetch
  }

  // Network-first for API calls and navigation (no caching — live data required)
  if (request.url.includes("/api/") || request.mode === "navigate") {
    event.respondWith(
      fetch(request).catch(() => {
        return caches.match(request);
      })
    );
    return;
  }

  // For other requests (images, fonts, etc.), cache on fetch for offline fallback
  event.respondWith(
    caches.open(CACHE_NAME).then((cache) =>
      fetch(request)
        .then((response) => {
          if (response.ok) {
            cache.put(request, response.clone());
          }
          return response;
        })
        .catch(() => cache.match(request))
    )
  );
});
