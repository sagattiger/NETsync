// NETsync service worker: makes the app installable and shows an offline page when NETsync can't be reached.
// It never caches the app or any data: monitoring must always be live, and a new version must show at once.
const OFFLINE = "/offline.html";
const CACHE = "netsync-offline-v1";

self.addEventListener("install", (event) => {
  event.waitUntil(caches.open(CACHE).then((c) => c.addAll([OFFLINE, "/icon-192.png"])).then(() => self.skipWaiting()));
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches.keys()
      .then((keys) => Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k))))
      .then(() => self.clients.claim()),
  );
});

self.addEventListener("fetch", (event) => {
  const req = event.request;
  if (req.mode !== "navigate") return; // API calls, assets, WebSockets: straight to the network
  event.respondWith(fetch(req).catch(() => caches.match(OFFLINE)));
});
