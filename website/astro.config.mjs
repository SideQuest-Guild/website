// Static build to website/dist, served by Litestar's static-files router in production
// (api/src/sidequest_api/lib/website.py). In dev (VITE_DEV_MODE=1), Litestar's VitePlugin
// proxies this Astro dev server through its own origin instead (api/src/sidequest_api/app.py)
// so /api, /auth and the site share cookies on http://localhost:8000.
import { defineConfig } from "astro/config";
import litestar from "litestar-vite-plugin/astro";

// Backend port for Astro's dev-time /api proxy and HMR websocket target (default 8000).
const LITESTAR_PORT = process.env.LITESTAR_PORT ?? "8000";

export default defineConfig({
  output: "static",
  outDir: "dist",
  // CSS goes inside each page (about 10 KB compressed) so the first paint never waits on a second request; the
  // pages are cached at Cloudflare's edge, so this costs nothing on the critical path.
  build: { format: "directory", inlineStylesheets: "always" },
  // Astro.site: used for og:/canonical tags. Defaults to the local API origin.
  site: process.env.SITE_URL ?? "http://localhost:8000",
  integrations: [
    litestar({
      apiProxy: `http://127.0.0.1:${LITESTAR_PORT}`,
      apiPrefix: "/api",
    }),
  ],
});
