// Shipped instead of sw.js when the service worker is switched off in astro.config.mjs: it replaces any installed
// worker, deletes its caches, unregisters, and reloads open pages so they come straight from the network again.
self.addEventListener("install", () => self.skipWaiting());

self.addEventListener("activate", (event) => {
  event.waitUntil(
    (async () => {
      const ours = (await caches.keys()).filter((name) => name.startsWith("sq-"));
      await Promise.all(ours.map((name) => caches.delete(name)));
      await self.registration.unregister();
      for (const client of await self.clients.matchAll({ type: "window" })) {
        client.navigate(client.url);
      }
    })(),
  );
});
