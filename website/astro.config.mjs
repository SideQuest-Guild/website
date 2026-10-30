// Static build to website/dist, served by Litestar's static-files router in production
// (api/src/sidequest_api/lib/website.py). In dev (VITE_DEV_MODE=1), Litestar's VitePlugin
// proxies this Astro dev server through its own origin instead (api/src/sidequest_api/app.py)
// so /api, /auth and the site share cookies on http://localhost:8000.
import { randomUUID } from "node:crypto";
import { defineConfig } from "astro/config";
import litestar from "litestar-vite-plugin/astro";
import serviceWorker from "./service-worker/integration.mjs";

// Packages pulled in only by the API reference page's lazy-loaded Scalar renderer (Scalar itself, and the Vue it's
// built on); bundled into one predictably-named chunk so the service worker can leave it out of the install-time
// precache (service-worker/integration.mjs).
const SCALAR_PACKAGES = /node_modules\/(@scalar\/|@vue\/|@vueuse\/|vue-demi\/|vue-sonner\/|vue\/)/;
// Backend port for Astro's dev-time /api proxy and HMR websocket target (default 8000).
const LITESTAR_PORT = process.env.LITESTAR_PORT ?? "8000";

// Kill switch: false ships a sw.js that deletes its caches and unregisters itself, and pages stop registering one.
const SERVICE_WORKER = true;
// Every page carries this in <meta name="sq-build">; the service worker only caches pages from its own build.
const BUILD_ID = randomUUID().slice(0, 8);

export default defineConfig({
  output: "static",
  outDir: "dist",
  // CSS goes inside each page (about 10 KB compressed) so the first paint never waits on a second request; the
  // pages are cached at Cloudflare's edge, so this costs nothing on the critical path.
  build: { format: "directory", inlineStylesheets: "always" },
  // Astro.site: used for og:/canonical tags. Defaults to the local API origin.
  site: process.env.SITE_URL ?? "http://localhost:8000",
  // With the ClientRouter, hovering a link fetches its page ahead of the click (free once the service worker has it).
  prefetch: { prefetchAll: true, defaultStrategy: "hover" },
  integrations: [
    litestar({
      apiProxy: `http://127.0.0.1:${LITESTAR_PORT}`,
      apiPrefix: "/api",
    }),
    serviceWorker({ enabled: SERVICE_WORKER, build: BUILD_ID }),
  ],
  vite: {
    define: {
      SQ_BUILD: JSON.stringify(BUILD_ID),
      SQ_SERVICE_WORKER: JSON.stringify(SERVICE_WORKER),
    },
    build: {
      rollupOptions: {
        output: {
          // Scalar (the API reference's renderer) is only ever imported from that one page's script; a
          // predictable chunk name lets the service worker (service-worker/integration.mjs) leave it out of
          // every other visitor's install-time precache.
          manualChunks(id) {
            if (SCALAR_PACKAGES.test(id)) {
              return "scalar-reference";
            }
          },
        },
      },
    },
  },
});
