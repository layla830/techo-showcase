// 只缓存页面外壳，接口永远走网络
const C = "techo-showcase-v2";
const SHELL = ["./", "index.html", "style.css", "app.js", "stickers.js", "page.js", "icon.svg", "manifest.webmanifest"];
self.addEventListener("install", (e) => { e.waitUntil(caches.open(C).then((c) => c.addAll(SHELL))); self.skipWaiting(); });
self.addEventListener("activate", (e) => { e.waitUntil(caches.keys().then((ks) => Promise.all(ks.filter((k) => k !== C).map((k) => caches.delete(k))))); self.clients.claim(); });
self.addEventListener("fetch", (e) => {
  const u = new URL(e.request.url);
  if (e.request.method !== "GET" || u.pathname.includes("/api/")) return;
  // 先网络，断网再用缓存，免得改了样式用户看到旧的
  e.respondWith(fetch(e.request, { cache: "no-cache" }).then((r) => { const copy = r.clone(); caches.open(C).then((c) => c.put(e.request, copy)); return r; }).catch(() => caches.match(e.request)));
});
