// Static build to website/dist, which the Litestar backend serves at / (api/src/sidequest_api/lib/website.py).
import { defineConfig } from "astro/config";

export default defineConfig({
  output: "static",
  outDir: "dist",
  build: { format: "directory" },
});
