// Shared formatting helpers for repeating event series ("Every Friday, 7:00 PM CDT"), used by
// /events/, /events/detail/, officers/index.astro and raid-gate.ts. Weekday indices match the API:
// 0 = Monday .. 6 = Sunday.
import type { SeriesRef, SeriesRule } from "./api";

const WEEKDAY_NAMES = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"];
export const WEEKDAY_SHORT_LABELS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];

/** Joins weekday indices into names ("Friday", "Tuesday and Friday", "Mon, Wed, and Fri" style lists). */
function joinWeekdayNames(weekdays: number[]): string {
  const names = weekdays.toSorted((a, b) => a - b).map((d) => WEEKDAY_NAMES[d] ?? "");
  if (names.length <= 1) {
    return names[0] ?? "";
  }
  if (names.length === 2) {
    return `${names[0]} and ${names[1]}`;
  }
  return `${names.slice(0, -1).join(", ")}, and ${names[names.length - 1]}`;
}

/** "Every Friday" / "Every Tuesday and Friday" / "Every other Friday" (interval_weeks === 2). */
export function weekdayPhrase(weekdays: number[], intervalWeeks: number): string {
  const joined = joinWeekdayNames(weekdays);
  return intervalWeeks === 2 ? `Every other ${joined}` : `Every ${joined}`;
}

/** Formats the series' wall-clock time at `anchorIso` in the series' own timezone, e.g. "7:00 PM CDT". */
export function seriesTimeText(timezone: string, anchorIso: string): string {
  return new Intl.DateTimeFormat(undefined, {
    hour: "numeric",
    minute: "2-digit",
    timeZoneName: "short",
    timeZone: timezone,
  }).format(new Date(anchorIso));
}

/**
 * Approximates the UTC instant for a given wall-clock date + "HH:MM" time in an IANA timezone,
 * for series that have no upcoming occurrence to anchor off of (e.g. an ended series' first date).
 */
export function zonedWallTimeToUtc(dateIso: string, time: string, timeZone: string): Date {
  const [hh, mm] = time.split(":").map(Number);
  const [y, m, d] = dateIso.split("-").map(Number);
  const guess = new Date(Date.UTC(y, (m ?? 1) - 1, d ?? 1, hh ?? 0, mm ?? 0));
  const asTz = new Date(guess.toLocaleString("en-US", { timeZone }));
  const asUtc = new Date(guess.toLocaleString("en-US", { timeZone: "UTC" }));
  return new Date(guess.getTime() + (asUtc.getTime() - asTz.getTime()));
}

/** Full rule text for a `SeriesRef` (an occurrence's series), e.g. "Every Friday, 7:00 PM CDT". */
export function seriesRefText(series: SeriesRef, anchorIso: string): string {
  return `${weekdayPhrase(series.weekdays, series.interval_weeks)}, ${seriesTimeText(series.timezone, anchorIso)}`;
}

/**
 * Full rule text for an `EventSeriesSummary.rule`, anchored on `next_starts_at` when available,
 * falling back to an estimate from `starts_on` + `start_time` for series with no upcoming night.
 */
export function seriesRuleText(rule: SeriesRule, nextStartsAt: string | null): string {
  const anchor = nextStartsAt ?? zonedWallTimeToUtc(rule.starts_on, rule.start_time, rule.timezone).toISOString();
  return `${weekdayPhrase(rule.weekdays, rule.interval_weeks)}, ${seriesTimeText(rule.timezone, anchor)}`;
}
