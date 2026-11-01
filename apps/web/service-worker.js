const CACHE = "saans-shell-v2";
const SHELL = ["/", "/assets/styles.css", "/assets/app.js", "/assets/manifest.webmanifest", "/assets/icon.svg"];
self.addEventListener("install", event => event.waitUntil(caches.open(CACHE).then(cache => cache.addAll(SHELL))));
self.addEventListener("activate", event => event.waitUntil(caches.keys().then(keys => Promise.all(keys.filter(k => k !== CACHE).map(k => caches.delete(k))))));
self.addEventListener("fetch", event => {
  const url = new URL(event.request.url);
  if (event.request.method !== "GET") return;
  if (url.origin === self.location.origin && url.pathname.startsWith("/v1/")) {
    event.respondWith(fetch(event.request).catch(() => caches.match(event.request)));
    return;
  }
  if (url.origin === self.location.origin) {
    event.respondWith(caches.match(event.request).then(cached => cached || fetch(event.request).then(response => {
      const copy = response.clone(); caches.open(CACHE).then(cache => cache.put(event.request, copy)); return response;
    })));
  }
});
self.addEventListener("push", event => {
  const data = event.data ? event.data.json() : {title: "Saans air alert", body: "Check the latest air quality."};
  event.waitUntil(self.registration.showNotification(data.title || "Saans air alert", {body: data.body, icon: "/assets/icon.svg", badge: "/assets/icon.svg", data: {url: data.url || "/"}}));
});
self.addEventListener("notificationclick", event => { event.notification.close(); event.waitUntil(clients.openWindow(event.notification.data.url || "/")); });
