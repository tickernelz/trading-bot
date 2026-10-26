<script lang="ts">
  import { MINUS, parseTs, percent, signedPercent } from "../lib/format";
  import { t } from "../lib/i18n";

  let {
    points,
    start,
    limitPct,
    from,
    stale = false,
  }: { points: [string, number][]; start: number; limitPct: number; from: string; stale?: boolean } = $props();

  let measured = $state(0);
  const W = $derived(Math.max(280, Math.round(measured || 640)));
  const H = 150;
  const PL = 44;
  const PR = 10;
  const PT = 10;
  const PB = 22;
  const DAY = 86400000;

  const t0 = $derived(parseTs(from));
  const values = $derived(points.map(([ts, eq]) => [parseTs(ts), ((eq - start) / start) * 100] as const));
  const last = $derived(values.at(-1)?.[1] ?? 0);
  const ymin = $derived(Math.min(-limitPct * 1.25, ...values.map((v) => v[1] - 0.1)));
  const ymax = $derived(Math.max(limitPct * 0.5, ...values.map((v) => v[1] + 0.1)));
  const x = (t: number) => PL + ((W - PL - PR) * (t - t0)) / DAY;
  const y = (v: number) => PT + ((H - PT - PB) * (ymax - v)) / (ymax - ymin);
  const line = $derived(values.map(([t, v]) => x(t).toFixed(1) + "," + y(v).toFixed(1)).join(" "));
  const ticks = [0, 6, 12, 18, 24];
  const label = $derived(
    t("trace.label", { value: signedPercent(last), limit: MINUS + percent(limitPct, 1) }),
  );
</script>

<div class="wrap" bind:clientWidth={measured}>
<svg viewBox="0 0 {W} {H}" width={W} height={H} role="img" aria-label={label} class:stale>
  <rect width={W} height={H} fill="var(--panel)" />
  {#each ticks as h (h)}
    <line x1={x(t0 + h * 3600000)} x2={x(t0 + h * 3600000)} y1={PT} y2={H - PB} stroke="var(--rule)" />
    <text x={x(t0 + h * 3600000)} y={H - 6} text-anchor="middle" class="tick">{String(h % 24).padStart(2, "0")}</text>
  {/each}
  <line x1={PL} x2={W - PR} y1={y(0)} y2={y(0)} stroke="var(--ink2)" />
  <text x={PL - 6} y={y(0) + 4} text-anchor="end" class="tick">0</text>
  <line x1={PL} x2={W - PR} y1={y(-limitPct)} y2={y(-limitPct)} stroke="var(--sig)" stroke-width="2" stroke-dasharray="6 4" />
  <text x={PL - 6} y={y(-limitPct) + 4} text-anchor="end" class="tick lim">{MINUS}{percent(limitPct, 1)}</text>
  <text x={W - PR - 4} y={y(-limitPct) - 6} text-anchor="end" class="lim">{t("trace.daily_limit")}</text>
  {#if values.length > 1}
    <polyline points={line} fill="none" stroke={stale ? "var(--ink2)" : "var(--ink)"} stroke-width="2" stroke-linejoin="round" />
    <circle cx={x(values.at(-1)![0])} cy={y(last)} r="4" fill={stale ? "var(--ink2)" : "var(--ink)"} />
  {/if}
</svg>
</div>

<style>
  .wrap {
    width: 100%;
  }
  svg {
    display: block;
    width: 100%;
    height: auto;
  }
  text {
    font-family: inherit;
    font-size: 12px;
    fill: var(--ink2);
  }
  .lim {
    fill: var(--loss);
    font-weight: 600;
  }
</style>
