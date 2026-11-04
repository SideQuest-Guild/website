import { escapeHtml } from "./api";

export type ActivityChartPoint = { date: string; messages: number; voice_minutes: number };

export type ActivityChartOptions = {
  emptyMessage?: string;
  dateFormat?: Intl.DateTimeFormat;
  maxLabels?: number;
};

const DEFAULT_DATE_FORMAT = new Intl.DateTimeFormat(undefined, { month: "short", day: "numeric" });

/**
 * Renders a full-width, grouped-bar activity chart (gold messages bar + blue voice-hours
 * bar per point, with a legend) into `el`. The SVG viewBox is matched to the element's real
 * measured width so the chart never letterboxes, and bars/groups spread across the full
 * width rather than clustering when there are few points.
 */
export function renderActivityChart(
  el: HTMLElement,
  points: ActivityChartPoint[],
  options: ActivityChartOptions = {},
): void {
  const { emptyMessage = "No tracked activity yet.", dateFormat = DEFAULT_DATE_FORMAT, maxLabels = 6 } = options;
  if (points.length === 0) {
    el.innerHTML = `<p class="aside">${emptyMessage}</p>`;
    return;
  }
  const width = Math.max(280, Math.round(el.getBoundingClientRect().width) || 600);
  const height = 180;
  const padSide = 24;
  const padTop = 26;
  const padBottom = 32;
  const chartHeight = height - padTop - padBottom;
  const maxMessages = Math.max(1, ...points.map((p) => p.messages));
  const maxVoiceHours = Math.max(1, ...points.map((p) => p.voice_minutes / 60));
  const available = width - padSide * 2;
  const slot = available / points.length;
  const maxGroupWidth = 64;
  const groupWidth = Math.max(6, Math.min(maxGroupWidth, slot - 4));
  const barWidth = Math.max(1.5, (groupWidth - 2) / 2);
  const bars = points
    .map((p, i) => {
      const x = padSide + i * slot + (slot - groupWidth) / 2;
      const messageHeight = (p.messages / maxMessages) * chartHeight;
      const voiceHeight = (p.voice_minutes / 60 / maxVoiceHours) * chartHeight;
      const messageY = height - padBottom - messageHeight;
      const voiceY = height - padBottom - voiceHeight;
      return `
        <rect x="${x}" y="${messageY}" width="${barWidth}" height="${messageHeight}" style="fill:var(--gold-2, #c9a24b)" />
        <rect x="${x + barWidth + 2}" y="${voiceY}" width="${barWidth}" height="${voiceHeight}" style="fill:var(--royal-2, #2e4a85)" />`;
    })
    .join("");
  // Thin the axis labels out so they stay readable once a wide range packs many points into the row.
  const labelEvery = Math.max(1, Math.ceil(points.length / maxLabels));
  const labels = points
    .map((p, i) =>
      i % labelEvery === 0 || i === points.length - 1
        ? `<text x="${padSide + i * slot + slot / 2}" y="${height - 8}" text-anchor="middle" font-size="10" style="fill:var(--mist-2, #9aa)">${escapeHtml(dateFormat.format(new Date(`${p.date}T00:00:00`)))}</text>`
        : "",
    )
    .join("");
  el.innerHTML = `
    <svg viewBox="0 0 ${width} ${height}" preserveAspectRatio="xMidYMid meet" style="width:100%;height:${height}px">
      <text x="${padSide}" y="16" font-size="10" style="fill:var(--mist-2, #9aa)">Max ${maxMessages.toLocaleString()} messages \u00b7 ${maxVoiceHours.toFixed(1)}h voice</text>
      ${bars}
      ${labels}
    </svg>
    <div class="chart-legend">
      <span class="chart-legend-item"><span class="chart-legend-dot chart-legend-messages" aria-hidden="true"></span>Messages</span>
      <span class="chart-legend-item"><span class="chart-legend-dot chart-legend-voice" aria-hidden="true"></span>Voice hours</span>
    </div>
  `;
}
