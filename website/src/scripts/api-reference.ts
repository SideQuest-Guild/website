// The API reference: Scalar's renderer (@scalar/api-reference) reads the API's own OpenAPI document and draws it
// under the site's normal header, themed to match (src/styles/scalar-theme.css). Scalar's base stylesheet and the
// theme file are both large and specific to this one page, so they're lazy-imported and injected into a <style>
// only while this page is open, and removed the moment it's left (see onPage, src/scripts/page.ts).
import type { ApiReferenceInstance } from "@scalar/types/api-reference";
import { onPage } from "./page";

const SPEC_URL = "/schema/openapi.json";

const OPTIONS = {
  url: SPEC_URL,
  theme: "none" as const,
  layout: "modern" as const,
  withDefaultFonts: false,
  hideDarkModeToggle: true,
  forceDarkModeState: "dark" as const,
  showSidebar: true,
  hideModels: false,
  defaultOpenAllTags: false,
  defaultHttpClient: { targetKey: "shell" as const, clientKey: "curl" as const },
  showDeveloperTools: "never" as const,
  telemetry: false,
  // No "Ask AI" chat: it would send the spec and visitors' questions to Scalar's hosted agent.
  agent: { disabled: true },
};

onPage("#api-reference-mount", (signal) => {
  const mount = document.querySelector<HTMLElement>("#api-reference-mount");
  const fallback = document.querySelector<HTMLElement>("#api-reference-fallback");
  const header = document.querySelector<HTMLElement>(".api-reference-room .site-nav");
  if (!mount) {
    return;
  }

  // Our header is sticky on this page only (api-reference.astro); Scalar's own sidebar is sticky too, and this
  // keeps it from sliding under the header instead of stopping just below it.
  const sizeHeader = (): void =>
    mount.style.setProperty("--scalar-custom-header-height", `${header?.offsetHeight ?? 0}px`);
  const resize = new ResizeObserver(sizeHeader);
  if (header) {
    resize.observe(header);
  }
  sizeHeader();

  const styles = document.createElement("style");
  let reference: ApiReferenceInstance | null = null;
  let cancelled = false;

  Promise.all([
    import("@scalar/api-reference"),
    import("@scalar/api-reference/style.css?inline"),
    import("../styles/scalar-theme.css?inline"),
  ])
    .then(([{ createApiReference }, scalarCss, themeCss]) => {
      if (cancelled) {
        return;
      }
      styles.textContent = scalarCss.default + themeCss.default;
      document.head.append(styles);
      mount.classList.add("api-reference-mount");
      reference = createApiReference(mount, OPTIONS);
    })
    .catch(() => {
      if (!cancelled) {
        fallback?.removeAttribute("hidden");
      }
    });

  signal.addEventListener("abort", () => {
    cancelled = true;
    resize.disconnect();
    reference?.destroy();
    styles.remove();
    mount.classList.remove("api-reference-mount");
    mount.replaceChildren();
  });
});
