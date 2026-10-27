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
  build: { format: "directory" },
  // Astro.site: used for og:/canonical tags. Defaults to the local API origin.
  site: process.env.SITE_URL ?? "http://localhost:8000",
  integrations: [
    litestar({
      apiProxy: `http://127.0.0.1:${LITESTAR_PORT}`,
      apiPrefix: "/api",
    }),
  ],
});
