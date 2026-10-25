const CACHE = "tb-shell-__SW_VERSION__";
const SHELL = ["/", "/manifest.webmanifest", "/icons/icon.svg", "/icons/icon-192.png", ...__SW_ASSETS__];
const HOME = "/#ringkas";
const URGENT = new Set(["risk_breach", "kill_switch", "heartbeat_lost"]);

self.addEventListener("install", (event) => {
  event.waitUntil(
    caches
      .open(CACHE)
      .then((cache) => cache.addAll(SHELL))
      .then(() => self.skipWaiting()),
  );
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches
      .keys()
      .then((keys) => Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k))))
      .then(() => self.clients.claim()),
  );
});

self.addEventListener("fetch", (event) => {
  const request = event.request;
  const url = new URL(request.url);
  if (request.method !== "GET" || url.origin !== self.location.origin || url.pathname.startsWith("/gw/")) return;
  if (request.mode === "navigate") {
    event.respondWith(
      fetch(request)
        .then((response) => {
          if (response.ok) {
            const copy = response.clone();
            void caches.open(CACHE).then((cache) => cache.put("/", copy));
          }
          return response;
        })
        .catch(() => caches.match("/").then((cached) => cached ?? Response.error())),
    );
    return;
  }
  if (url.pathname.startsWith("/assets/") || url.pathname.startsWith("/icons/")) {
    event.respondWith(
      caches.match(request).then(
        (cached) =>
          cached ??
          fetch(request).then((response) => {
            if (response.ok) {
              const copy = response.clone();
              void caches.open(CACHE).then((cache) => cache.put(request, copy));
            }
            return response;
          }),
      ),
    );
  }
});

function sameOrigin(raw) {
  try {
    const url = new URL(raw, self.location.origin);
    return url.origin === self.location.origin ? url.href : new URL(HOME, self.location.origin).href;
  } catch {
    return new URL(HOME, self.location.origin).href;
  }
}

function parse(event) {
  try {
    return event.data ? event.data.json() : null;
  } catch {
    return { title: "Bot Trading", body: event.data.text() };
  }
}

self.addEventListener("push", (event) => {
  const data = parse(event) ?? {};
  const kind = data.kind ?? "info";
  const title = data.title ?? "Bot Trading";
  const options = {
    body: data.body ?? "Ada kabar baru dari bot. Buka aplikasi untuk detail.",
    tag: kind + ":" + (data.id ?? Date.now()),
    timestamp: data.ts ? Date.parse(data.ts) : Date.now(),
    icon: "/icons/icon-192.png",
    badge: "/icons/badge-96.png",
    data: { url: sameOrigin(data.url ?? HOME), kind },
    requireInteraction: URGENT.has(kind),
    renotify: false,
  };
  event.waitUntil(self.registration.showNotification(title, options));
});

self.addEventListener("notificationclick", (event) => {
  event.notification.close();
  const target = sameOrigin(event.notification.data?.url ?? HOME);
  event.waitUntil(
    self.clients.matchAll({ type: "window", includeUncontrolled: true }).then((list) => {
      for (const client of list) {
        if (new URL(client.url).origin === self.location.origin && "focus" in client) {
          return client.navigate(target).then((c) => (c ?? client).focus());
        }
      }
      return self.clients.openWindow(target);
    }),
  );
});
