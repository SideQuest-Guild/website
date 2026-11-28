// Pure helpers for the guild market report (/market/): level-band filtering, money formatting, the change arrow,
// zone lines, the trend sparkline and large-count formatting. No DOM and no runtime import from api.ts here (so
// `node --test` can resolve this module directly); the page script (pages/market/index.astro) renders markup and
// talks to the API.
import type { MarketPoint, MarketZone } from "./api";

/** `localStorage` key for the gathering level filter, remembered across visits. */
export const MARKET_LEVEL_BAND_KEY = "sq-market-level-band";

export type MarketLevelBand = { id: string; label: string; min: number; max: number };

/** The level bands the gathering level filter offers, matching the bot's own bands (local://market-contract.md). */
export const MARKET_LEVEL_BANDS: MarketLevelBand[] = [
  { id: "all", label: "All levels", min: 1, max: 60 },
  { id: "1-24", label: "1-24", min: 1, max: 24 },
  { id: "25-44", label: "25-44", min: 25, max: 44 },
  { id: "45-60", label: "45-60", min: 45, max: 60 },
];

/** Whether a gathering pick's own level range overlaps a level band; `"all"` always matches. */
export function levelBandOverlaps(bandId: string, pickMinLevel: number, pickMaxLevel: number): boolean {
  if (bandId === "all") {
    return true;
  }
  const band = MARKET_LEVEL_BANDS.find((candidate) => candidate.id === bandId);
  if (!band) {
    return true;
  }
  return pickMinLevel <= band.max && pickMaxLevel >= band.min;
}

/** A daily sale count, which can run into the thousands on a busy item: under 10 keeps one decimal ("1.7"), 10
 * and up rounds to a whole number with a thousands separator ("3,847"). */
export function formatCount(n: number): string {
  if (n < 10) {
    return n.toFixed(1);
  }
  return Math.round(n).toLocaleString("en-US");
}

/** The muted cooldown note under a craft pick whose recipe is cooldown-gated (transmutes); `null` for an
 * uncapped recipe, which gets no note at all. */
export function cooldownLabel(cooldownHours: number | null): string {
  if (cooldownHours === null) {
    return "";
  }
  if (cooldownHours === 24) {
    return "Once a day";
  }
  if (cooldownHours % 24 === 0) {
    return `Once every ${cooldownHours / 24} days`;
  }
  return `Once every ${cooldownHours} hours`;
}

export type MarketChangeDirection = "up" | "down" | "flat";

/** The up/down/flat arrow and percent text for a row's price change; never color alone (the direction class carries
 * an arrow glyph, not just a color), and the figure is always signed so a screen reader hears "up" or "down". */
export function changeArrow(changePct: number | null): {
  symbol: string;
  text: string;
  direction: MarketChangeDirection;
} {
  if (changePct === null) {
    return { symbol: "", text: "No change yet", direction: "flat" };
  }
  if (Math.abs(changePct) < 1) {
    return { symbol: "\u2014", text: "Steady", direction: "flat" };
  }
  const rounded = Math.round(changePct * 10) / 10;
  const direction: MarketChangeDirection = rounded > 0 ? "up" : "down";
  const symbol = direction === "up" ? "\u25b2" : "\u25bc";
  return { symbol, text: `${direction === "up" ? "+" : ""}${rounded}%`, direction };
}

/** The "Where" column for a gathering pick: its zones, lowest level first, each with its level range, compact
 * enough to wrap in a narrow column (the caller adds the full line as a `title` tooltip for the overflow). */
export function zoneLine(zones: MarketZone[]): string {
  return zones.map((zone) => `${zone.name} ${zone.min_level}-${zone.max_level}`).join(", ");
}

/** Market money, in copper, the way the report and the bot's daily post both show it: whole gold with a thousands
 * separator from 100g, gold and silver rounded from 1g, whole silver from 10s, and silver plus copper below that
 * (just copper when there's no silver). Distinct from `copperToGold` (api.ts), which the rest of the site uses. */
export function formatMarketMoney(copper: number): string {
  const sign = copper < 0 ? "-" : "";
  const abs = Math.abs(copper);
  if (abs >= 1_000_000) {
    return `${sign}${Math.round(abs / 10000).toLocaleString("en-US")}g`;
  }
  if (abs >= 10000) {
    const totalSilver = Math.round(abs / 100);
    const gold = Math.floor(totalSilver / 100);
    if (gold >= 100) {
      return `${sign}${gold.toLocaleString("en-US")}g`;
    }
    const silver = totalSilver % 100;
    return silver > 0 ? `${sign}${gold}g ${silver}s` : `${sign}${gold}g`;
  }
  if (abs >= 1000) {
    return `${sign}${Math.round(abs / 100)}s`;
  }
  const silver = Math.floor(abs / 100);
  const bronze = Math.round(abs % 100);
  if (silver > 0 && bronze > 0) {
    return `${sign}${silver}s ${bronze}c`;
  }
  return silver > 0 ? `${sign}${silver}s` : `${sign}${bronze}c`;
}

/** A small inline sparkline SVG for a report pick's trend (`MarketPoint[]`, oldest first). Returns "" for fewer
 * than two points, too little to draw a line. */
export function marketSparkline(trend: MarketPoint[]): string {
  if (trend.length < 2) {
    return "";
  }
  const width = 160;
  const height = 36;
  const pad = 3;
  const prices = trend.map((point) => point.price);
  const min = Math.min(...prices);
  const max = Math.max(...prices);
  const span = max - min || 1;
  const stepX = (width - pad * 2) / (trend.length - 1);
  const points = trend
    .map((point, i) => {
      const x = pad + i * stepX;
      const y = height - pad - ((point.price - min) / span) * (height - pad * 2);
      return `${x.toFixed(1)},${y.toFixed(1)}`;
    })
    .join(" ");
  return `
    <svg class="market-sparkline" viewBox="0 0 ${width} ${height}" preserveAspectRatio="none" role="img" aria-label="Price trend, last ${trend.length} days">
      <polyline points="${points}" fill="none" stroke="var(--gold-2, #c9a24b)" stroke-width="2" />
    </svg>`;
}
