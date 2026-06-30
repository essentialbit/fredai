// FredAI Service Worker — enables PWA install on iOS/Android
// Caches the shell so the app loads offline; live data still requires network.
const CACHE  = "fredai-shell-v1";
const SHELL  = ["/", "/static/manifest.json"];

self.addEventListener("install", e => {
    e.waitUntil(caches.open(CACHE).then(c => c.addAll(SHELL).catch(() => {})));
    self.skipWaiting();
});

self.addEventListener("activate", e => {
    e.waitUntil(
        caches.keys().then(keys =>
            Promise.all(keys.filter(k => k !== CACHE).map(k => caches.delete(k)))
        )
    );
    self.clients.claim();
});

self.addEventListener("fetch", e => {
    // API and Socket.IO requests always go to network
    const url = new URL(e.request.url);
    if (url.pathname.startsWith("/api/") || url.pathname.startsWith("/socket.io/")) return;

    e.respondWith(
        fetch(e.request)
            .then(r => {
                // Cache successful GET responses for the shell
                if (e.request.method === "GET" && r.status === 200) {
                    const clone = r.clone();
                    caches.open(CACHE).then(c => c.put(e.request, clone));
                }
                return r;
            })
            .catch(() => caches.match(e.request))
    );
});
