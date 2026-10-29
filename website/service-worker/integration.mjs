// Writes dist/sw.js after the build: service-worker/sw.js with this build's page list, scripts, fonts and asset
// names prepended, or the self-removing sw-off.js when the worker is switched off.
import { readdir, readFile, writeFile } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";

const PRECACHED = /\.(js|css|woff2)$/;

// Every `<dir>/index.html` is a page at `/<dir>/`; 404.html is only ever served by the origin for a miss.
async function pagePaths(root) {
  const files = await readdir(root, { recursive: true });
  return files
    .map((file) => file.split(path.sep).join("/"))
    .filter((file) => file === "index.html" || file.endsWith("/index.html"))
    .map((file) => `/${file.slice(0, -"index.html".length)}`)
    .toSorted();
}

/** @param {{ enabled: boolean, build: string }} options */
export default function serviceWorker({ enabled, build }) {
  return {
    name: "sidequest-service-worker",
    hooks: {
      "astro:build:done": async ({ dir, logger }) => {
        const out = fileURLToPath(dir);
        const target = path.join(out, "sw.js");
        if (!enabled) {
          await writeFile(target, await readFile(new URL("sw-off.js", import.meta.url), "utf8"));
          logger.warn("service worker switched off: shipping the self-removing sw.js");
          return;
        }
        const pages = await pagePaths(out);
        const assets = (await readdir(path.join(out, "_astro"))).toSorted().map((name) => `/_astro/${name}`);
        const precache = assets.filter((asset) => PRECACHED.test(asset));
        const constants = [
          `const BUILD = ${JSON.stringify(build)};`,
          `const PAGES = ${JSON.stringify(pages)};`,
          `const PRECACHE = ${JSON.stringify(precache)};`,
          `const ASSETS = ${JSON.stringify(assets)};`,
        ].join("\n");
        await writeFile(target, `${constants}\n${await readFile(new URL("sw.js", import.meta.url), "utf8")}`);
        logger.info(`sw.js: build ${build}, ${pages.length} pages, ${precache.length} scripts and fonts precached`);
      },
    },
  };
}
