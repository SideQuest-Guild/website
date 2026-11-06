// Small decorative class/spec icons drawn next to a character's name wherever the site already shows class color
// or a class/spec label: the characters roster and character page, the Hall of Heroes boards, and raid sign-up
// rows. Fetches GET /api/game/classes once per visit (cached in memory and sessionStorage, Battle.net-backed, so a
// 503 just means no icons this visit) and looks class/spec up locally; icons are `alt=""` since the adjacent text
// already names the class.
import { apiFetch, type CharClass, type GameClass } from "./api";

const STORAGE_KEY = "sq-game-classes";

let loaded: Promise<GameClass[]> | null = null;

function readCache(): GameClass[] | null {
  try {
    const raw = sessionStorage.getItem(STORAGE_KEY);
    return raw ? (JSON.parse(raw) as GameClass[]) : null;
  } catch {
    return null; // storage blocked or malformed; fetch instead
  }
}

function writeCache(classes: GameClass[]): void {
  try {
    sessionStorage.setItem(STORAGE_KEY, JSON.stringify(classes));
  } catch {
    // storage full or blocked; the in-memory cache still serves the rest of this visit
  }
}

/** Loads the class/spec art catalog once per visit; call before rendering rows that draw icons. Resolves to `[]`
 * (no icons) if Battle.net isn't configured or didn't answer, never throws. */
export function loadGameArt(): Promise<GameClass[]> {
  if (!loaded) {
    loaded = (async () => {
      const cached = readCache();
      if (cached) {
        return cached;
      }
      try {
        const classes = await apiFetch<GameClass[]>("/api/game/classes");
        writeCache(classes);
        return classes;
      } catch {
        return [];
      }
    })();
  }
  return loaded;
}

/** A small decorative `<img>` for a class, or `""` if the class is unknown or has no art loaded. */
export function classIconHtml(classes: GameClass[], wowClass: string | null | undefined, size = 20): string {
  if (!wowClass) {
    return "";
  }
  const entry = classes.find((c) => c.class === (wowClass as CharClass));
  if (!entry?.icon_url) {
    return "";
  }
  return `<img class="class-icon" src="${entry.icon_url}" alt="" width="${size}" height="${size}" loading="lazy" />`;
}

/** A small decorative `<img>` for a spec, matched by class and spec name (case-insensitive), or `""`. */
export function specIconHtml(
  classes: GameClass[],
  wowClass: string | null | undefined,
  specName: string | null | undefined,
  size = 20,
): string {
  if (!wowClass || !specName) {
    return "";
  }
  const entry = classes.find((c) => c.class === (wowClass as CharClass));
  const spec = entry?.specs.find((s) => s.name.toLowerCase() === specName.toLowerCase());
  if (!spec?.icon_url) {
    return "";
  }
  return `<img class="spec-icon" src="${spec.icon_url}" alt="" width="${size}" height="${size}" loading="lazy" />`;
}
