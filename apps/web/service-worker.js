const CACHE = "saans-shell-v6";
const SHELL = ["/", "/assets/styles.css?v=6", "/assets/app.js?v=6", "/assets/manifest.webmanifest", "/assets/icon.svg"];
self.addEventListener("install", event => {
  event.waitUntil(caches.open(CACHE).then(cache => cache.addAll(SHELL)));
  self.skipWaiting();
});
self.addEventListener("activate", event => event.waitUntil(Promise.all([
  caches.keys().then(keys => Promise.all(keys.filter(k => k !== CACHE).map(k => caches.delete(k)))),
  self.clients.claim(),
])));
self.addEventListener("fetch", event => {
  const url = new URL(event.request.url);
  if (event.request.method !== "GET") return;
  if (url.origin === self.location.origin && url.pathname.startsWith("/v1/")) {
    event.respondWith(fetch(event.request).catch(() => caches.match(event.request)));
    return;
  }
  if (url.origin === self.location.origin) {
    event.respondWith((async () => {
      const cached = await caches.match(event.request);
      try {
        const response = await fetch(event.request);
        if (response.ok) {
          const copy = response.clone();
          await caches.open(CACHE).then(cache => cache.put(event.request, copy));
        }
        return response;
      } catch {
        return cached || Response.error();
      }
    })());
  }
});
self.addEventListener("push", event => {
  const data = event.data ? event.data.json() : {title: "Saans air alert", body: "Check the latest air quality."};
  event.waitUntil(self.registration.showNotification(data.title || "Saans air alert", {body: data.body, icon: "/assets/icon.svg", badge: "/assets/icon.svg", data: {url: data.url || "/"}}));
});
self.addEventListener("notificationclick", event => { event.notification.close(); event.waitUntil(clients.openWindow(event.notification.data.url || "/")); });
