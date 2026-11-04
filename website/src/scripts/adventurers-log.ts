// Renders `AdventurersLog.astro` for one person: the level ring, lifetime/30-day tiles, streaks, XP-by-source bar,
// last-30-days chart and weekday/hour heat grid. The component's elements are addressed by `data-log-*` attributes
// on its root rather than ids, so the same markup and render code work mounted on any page.
import { escapeHtml, type HeroActivity, type HeroXPSources, type StatsHourCell } from "./api";
import { renderActivityChart as renderGroupedActivityChart } from "./activity-chart";

export type AdventurersLogPerson = { display_name: string; avatar_url: string | null; wow_class: string | null };

/** Looks up a required `[data-attr]` element within `scope`, throwing early if the markup drifts. */
export function requireLogElement<T extends Element = HTMLElement>(scope: ParentNode, attr: string): T {
  const node = scope.querySelector<T>(`[${attr}]`);
  if (!node) {
    throw new Error(`Missing [${attr}] in Adventurer's Log markup`);
  }
  return node;
}

const WEEKDAY_LABELS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];

function hourLabel(hour: number): string {
  return hour === 0 ? "12a" : hour < 12 ? `${hour}a` : hour === 12 ? "12p" : `${hour - 12}p`;
}

// A small hand-drawn flame, like the voice hearths' flame on the homepage, for the streak tiles.
function flameIcon(muted: boolean): string {
  return `<svg class="hero-streak-flame${muted ? " is-muted" : ""}" viewBox="0 0 24 24" aria-hidden="true"><path d="M12 2c1.2 3-2.6 4.2-2.6 7.4a2.6 2.6 0 0 0 5.2 0c0-.9-.6-1.7-.6-2.6 1.8 1 3 3 3 5.2a5 5 0 0 1-10 0c0-4.4 3.4-5.6 5-10z" fill="currentColor"></path></svg>`;
}

function activityTile(label: string, value: string, sub: string, rank: number | null, rankSuffix: string): string {
  const chip = rank !== null ? `<span class="hero-rank-chip">#${rank}${rankSuffix}</span>` : "";
  return `
    <div class="hero-activity-tile">
      <span class="hero-activity-tile-label">${escapeHtml(label)}</span>
      <span class="hero-activity-tile-value">${escapeHtml(value)}</span>
      <span class="hero-activity-tile-sub">${escapeHtml(sub)}${chip}</span>
    </div>`;
}

const XP_SOURCE_SEGMENTS: { key: keyof HeroXPSources; label: string; css: string }[] = [
  { key: "chat", label: "Chat", css: "xp-source-chat" },
  { key: "voice", label: "Voice", css: "xp-source-voice" },
  { key: "events", label: "Events", css: "xp-source-events" },
  { key: "groups", label: "Groups", css: "xp-source-groups" },
  { key: "earlier", label: "Earlier", css: "xp-source-earlier" },
];

function xpSourceBar(sources: HeroXPSources): string {
  const total = Math.max(
    1,
    XP_SOURCE_SEGMENTS.reduce((sum, s) => sum + sources[s.key], 0),
  );
  return XP_SOURCE_SEGMENTS.filter((s) => sources[s.key] > 0)
    .map((s) => `<span class="xp-source-segment ${s.css}" style="width:${(sources[s.key] / total) * 100}%"></span>`)
    .join("");
}

function xpSourceLegend(sources: HeroXPSources): string {
  return XP_SOURCE_SEGMENTS.map(
    (s) => `
      <li><span class="xp-source-dot ${s.css}" aria-hidden="true"></span>${escapeHtml(s.label)}<span class="groups-stat-value">${sources[s.key].toLocaleString()} XP</span></li>`,
  ).join("");
}

function renderActivityHeatmap(el: HTMLElement, cells: StatsHourCell[]): void {
  const max = Math.max(1, ...cells.map((c) => c.messages + c.voice_minutes));
  const byCell = new Map(cells.map((c) => [`${c.weekday}-${c.hour}`, c]));
  const gridCells: string[] = [`<span class="groups-heat-corner"></span>`];
  for (let hour = 0; hour < 24; hour++) {
    gridCells.push(`<span class="groups-heat-hour-label">${hour % 3 === 0 ? hourLabel(hour) : ""}</span>`);
  }
  for (let weekday = 0; weekday < 7; weekday++) {
    gridCells.push(`<span class="groups-heat-row-label">${WEEKDAY_LABELS[weekday]}</span>`);
    for (let hour = 0; hour < 24; hour++) {
      const cell = byCell.get(`${weekday}-${hour}`);
      const weight = cell ? cell.messages + cell.voice_minutes : 0;
      const alpha = weight === 0 ? 0 : 0.15 + 0.85 * (weight / max);
      const label = cell
        ? `${WEEKDAY_LABELS[weekday]} ${hourLabel(hour)} \u2014 ${cell.messages} message${cell.messages === 1 ? "" : "s"}, ${cell.voice_minutes} voice min`
        : `${WEEKDAY_LABELS[weekday]} ${hourLabel(hour)} \u2014 quiet`;
      gridCells.push(
        `<span class="groups-heat-cell" style="background:rgba(201,162,75,${alpha})" title="${escapeHtml(label)}" aria-label="${escapeHtml(label)}"></span>`,
      );
    }
  }
  el.innerHTML = gridCells.join("");
}

/** Fills in an `AdventurersLog.astro` root with one person's activity. Callers own the section's and body's
 * visibility and loading/error status (via `[data-log-status]`/`[data-log-body]`, found with `requireLogElement`);
 * this only renders once the data is ready. */
export function renderAdventurersLog(root: HTMLElement, person: AdventurersLogPerson, activity: HeroActivity): void {
  const portraitEl = requireLogElement(root, "data-log-portrait");
  const ringFillEl = requireLogElement(root, "data-log-ring-fill") as unknown as SVGCircleElement;
  const avatarImg = requireLogElement<HTMLImageElement>(root, "data-log-avatar");
  const avatarFallback = requireLogElement(root, "data-log-avatar-fallback");
  const levelEl = requireLogElement(root, "data-log-level");
  const levelFill = requireLogElement<HTMLElement>(root, "data-log-level-fill");
  const levelLabel = requireLogElement(root, "data-log-level-label");
  const rankEl = requireLogElement(root, "data-log-rank");
  const rewardEl = requireLogElement(root, "data-log-reward");
  const tilesEl = requireLogElement(root, "data-log-tiles");
  const streakEl = requireLogElement(root, "data-log-streak");
  const xpBarEl = requireLogElement(root, "data-log-xp-bar");
  const xpLegendEl = requireLogElement(root, "data-log-xp-legend");
  const chartEl = requireLogElement<HTMLElement>(root, "data-log-chart");
  const heatGridEl = requireLogElement<HTMLElement>(root, "data-log-heat-grid");

  portraitEl.style.setProperty("--class-color", person.wow_class ? `var(--c-${person.wow_class})` : "transparent");
  if (person.avatar_url) {
    avatarImg.src = person.avatar_url;
    avatarImg.hidden = false;
    avatarFallback.hidden = true;
  } else {
    avatarImg.hidden = true;
    avatarFallback.hidden = false;
    avatarFallback.textContent = person.display_name.trim().charAt(0).toUpperCase() || "?";
  }

  levelEl.textContent = `Lv. ${activity.level}`;
  const haveNextLevel = activity.xp_for_next_level > 0;
  const pct = haveNextLevel
    ? Math.min(100, Math.round((activity.xp_into_level / activity.xp_for_next_level) * 100))
    : 100;
  levelFill.style.width = `${pct}%`;
  levelLabel.textContent = haveNextLevel
    ? `${activity.xp_into_level.toLocaleString()} / ${activity.xp_for_next_level.toLocaleString()} XP`
    : `${activity.xp.toLocaleString()} XP`;
  // The ring's own radius drives the circumference, so the markup's r can change without touching this math.
  const ringCircumference = 2 * Math.PI * ringFillEl.r.baseVal.value;
  ringFillEl.style.strokeDasharray = `${ringCircumference}`;
  ringFillEl.style.strokeDashoffset = `${ringCircumference * (1 - pct / 100)}`;
  rankEl.textContent =
    activity.xp_rank !== null ? `#${activity.xp_rank} of ${activity.ranked_members} by XP` : "Not yet ranked by XP";
  rewardEl.textContent = activity.next_reward
    ? `Next reward at level ${activity.next_reward.level}: ${activity.next_reward.role_name}`
    : "";

  tilesEl.innerHTML = [
    activityTile(
      "Messages",
      activity.message_count.toLocaleString(),
      `${activity.messages_30d.toLocaleString()} in 30 days`,
      activity.chat_rank_30d,
      " in 30d",
    ),
    activityTile(
      "Voice hours",
      `${(activity.voice_minutes / 60).toFixed(1)}h`,
      `${(activity.voice_minutes_30d / 60).toFixed(1)}h in 30 days`,
      activity.voice_rank_30d,
      " in 30d",
    ),
    activityTile("Events attended", String(activity.events_attended), "All time", null, ""),
    activityTile("Groups joined", String(activity.groups_joined), "All time", null, ""),
  ].join("");

  streakEl.innerHTML = `
    <div class="hero-streak-tile">
      ${flameIcon(activity.current_streak_days === 0)}
      <span class="hero-streak-text">
        <span class="hero-activity-tile-label">Current streak</span>
        <span class="hero-activity-tile-value">${activity.current_streak_days} day${activity.current_streak_days === 1 ? "" : "s"}</span>
      </span>
    </div>
    <div class="hero-streak-tile">
      ${flameIcon(activity.longest_streak_days === 0)}
      <span class="hero-streak-text">
        <span class="hero-activity-tile-label">Longest streak</span>
        <span class="hero-activity-tile-value">${activity.longest_streak_days} day${activity.longest_streak_days === 1 ? "" : "s"}</span>
      </span>
    </div>`;

  xpBarEl.innerHTML = xpSourceBar(activity.xp_sources);
  xpLegendEl.innerHTML = xpSourceLegend(activity.xp_sources);

  renderGroupedActivityChart(
    chartEl,
    activity.days.map((d) => ({ date: d.day, messages: d.messages, voice_minutes: d.voice_minutes })),
  );
  renderActivityHeatmap(heatGridEl, activity.heatmap);
}
