// Draws a character in 3D with Wowhead's model viewer (see privacy#who-else: the viewer script is a third party).
// The viewer script loads only when a visitor asks for the 3D view, since its files run to tens of megabytes. It
// expects jQuery and a few of Wowhead's own globals; its model files come through /api/modelviewer/, because Wowhead
// answers them only to its own pages.
import jQuery from "jquery";

import type { CharacterModel } from "./api";
import { loadWowheadTooltips } from "./items";

type ZamModelViewerOptions = {
  type: number;
  contentPath: string;
  container: unknown;
  aspect: number;
  hd: boolean;
  models: { id: number; type: number };
  charCustomization: { options: { optionId: number; choiceId: number }[] };
  items: [number, number][];
};

type ZamModelViewer = { destroy: () => void };

declare global {
  interface Window {
    // The constructor hands back a promise that settles once the model and its gear have loaded.
    ZamModelViewer?: new (options: ZamModelViewerOptions) => PromiseLike<ZamModelViewer>;
    WH?: { debug?: (...args: unknown[]) => void; WebP?: { getImageExtension: () => string } };
    jQuery?: JQueryStatic;
    $?: JQueryStatic;
  }
}

const VIEWER_SCRIPT = "https://wow.zamimg.com/modelviewer/live/viewer/viewer.min.js";
const MODEL_FILES = "/api/modelviewer/";
const WEBGL_VIEWER = 2;
const CHARACTER_MODEL = 16;

let libraryLoad: Promise<boolean> | null = null;

function loadScript(src: string): Promise<void> {
  const { promise, resolve, reject } = Promise.withResolvers<void>();
  const script = document.createElement("script");
  script.src = src;
  script.async = true;
  script.addEventListener("load", () => resolve(), { once: true });
  script.addEventListener("error", () => reject(new Error(`Could not load ${src}`)), { once: true });
  document.head.append(script);
  return promise;
}

async function loadLibrary(): Promise<boolean> {
  // Wowhead's tooltip script replaces window.WH outright, so it goes first; the viewer then also wants WH.debug.
  await loadWowheadTooltips();
  const wh = (window.WH ??= {});
  wh.debug ??= () => {};
  wh.WebP ??= { getImageExtension: () => ".webp" };
  window.jQuery = jQuery;
  window.$ = jQuery;
  await loadScript(VIEWER_SCRIPT);
  return typeof window.ZamModelViewer === "function";
}

/** Loads the viewer once per visit; resolves `false` if it couldn't (blocked, offline), so a retry starts over. */
function loadViewerLibrary(): Promise<boolean> {
  libraryLoad ??= loadLibrary().catch(() => false);
  void libraryLoad.then((loaded) => {
    if (!loaded) {
      libraryLoad = null;
    }
  });
  return libraryLoad;
}

/**
 * Draws `model` in `container`, sized to the container's box, resolving once it has loaded. Returns the viewer (call
 * `destroy` when the page goes), or `null` if Wowhead's viewer couldn't load.
 */
export async function showCharacterModel(
  container: HTMLElement,
  model: CharacterModel,
): Promise<ZamModelViewer | null> {
  const ViewerClass = (await loadViewerLibrary()) ? window.ZamModelViewer : undefined;
  if (!ViewerClass) {
    return null;
  }
  return new ViewerClass({
    type: WEBGL_VIEWER,
    contentPath: MODEL_FILES,
    container: jQuery(container),
    aspect: container.clientWidth / container.clientHeight,
    hd: true,
    models: { id: model.model_id, type: CHARACTER_MODEL },
    charCustomization: {
      options: model.customizations.map((c) => ({ optionId: c.option_id, choiceId: c.choice_id })),
    },
    items: model.items.map((item): [number, number] => [item.slot, item.display_id]),
  });
}
