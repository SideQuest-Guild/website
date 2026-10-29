// End-to-end tests: the built site in real browser engines at desktop and phone sizes, the API mocked
// (e2e/fixtures.ts). `npm run build` first; `npm run e2e` serves dist/ itself. `E2E_BASE_URL=https://…` runs the
// same tests against a deployed site instead (the API stays mocked, so only the pages and their code are live).
import { defineConfig, devices } from "@playwright/test";

const PORT = 4329;
const LIVE = process.env.E2E_BASE_URL;

export default defineConfig({
  testDir: "e2e",
  fullyParallel: true,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 1 : 0,
  reporter: process.env.CI ? [["github"], ["html", { open: "never" }]] : [["list"], ["html", { open: "never" }]],
  use: {
    baseURL: LIVE ?? `http://localhost:${PORT}`,
    // The service worker answers requests the API mock can't see; only the offline test turns it on.
    serviceWorkers: "block",
    screenshot: "only-on-failure",
    trace: "retain-on-failure",
  },
  projects: [
    { name: "desktop", use: { ...devices["Desktop Chrome"], viewport: { width: 1440, height: 900 } } },
    // WebKit is the engine of every iPhone browser; this is the closest thing to Safari on iOS.
    { name: "iphone", use: { ...devices["iPhone 15"] } },
    { name: "android", use: { ...devices["Pixel 7"] } },
    { name: "small-phone", use: { ...devices["iPhone SE"], viewport: { width: 320, height: 568 } } },
  ],
  webServer: LIVE
    ? undefined
    : {
        command: `npx astro preview --port ${PORT} --ignore-lock`,
        url: `http://localhost:${PORT}/`,
        reuseExistingServer: !process.env.CI,
      },
});
