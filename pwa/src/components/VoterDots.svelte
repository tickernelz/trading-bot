<script lang="ts">
  import { decimal } from "../lib/format";
  import { t } from "../lib/i18n";
  import { choiceText } from "../lib/words";
  import type { Decision } from "../lib/types";

  let { decision }: { decision: Decision } = $props();

  let measured = $state(0);
  const W = $derived(Math.max(300, Math.round(measured || 360)));
  const PL = 12;
  const PR = 12;
  const TOP = 20;
  const ROW = 22;
  const x = (p: number) => PL + (W - PL - PR) * p;

  const placed = $derived.by(() => {
    const voters = decision.voters
      .filter((v) => v.status === "ok" && v.answers?.action?.probabilities)
      .map((v) => ({ id: v.voter_id, p: v.answers!.action.probabilities!.allow ?? 0, choice: v.answers!.action.choice ?? "" }))
      .sort((a, b) => a.p - b.p);
    const rows: number[][] = [];
    return voters.map((v) => {
      const cx = x(v.p);
      let level = rows.findIndex((r) => r.every((o) => Math.abs(o - cx) >= 34));
      if (level < 0) level = rows.push([]) - 1;
      rows[level].push(cx);
      return { ...v, cx, cy: TOP + level * ROW };
    });
  });
  const levels = $derived(Math.max(3, ...placed.map((v) => (v.cy - TOP) / ROW + 1)));
  const AX = $derived(TOP + levels * ROW + 6);
  const H = $derived(AX + 32);
  const action = $derived(decision.aggregate?.questions.action);
  const median = $derived(action?.median_probabilities?.allow ?? null);
  const label = $derived(
    t("dots.label", { voters: placed.map((v) => v.id + " " + decimal(v.p) + " " + choiceText(v.choice)).join(", ") }) +
      (median === null ? "" : " " + t("dots.median", { median: decimal(median), iqr: decimal(action!.spread.iqr) })),
  );
</script>

<div class="wrap" bind:clientWidth={measured}>
<svg viewBox="0 0 {W} {H}" width={W} height={H} role="img" aria-label={label}>
  <rect width={W} height={H} fill="var(--panel)" />
  {#if action}
    <rect x={x(action.spread.q25)} y="8" width={Math.max(2, x(action.spread.q75) - x(action.spread.q25))} height={AX - 12} fill="var(--rule)" />
  {/if}
  <line x1={x(0.5)} x2={x(0.5)} y1="8" y2={AX} stroke="var(--rule-strong)" stroke-dasharray="3 3" />
  <line x1={PL} x2={W - PR} y1={AX} y2={AX} stroke="var(--ink2)" />
  {#each [0, 0.5, 1] as tick (tick)}
    <line x1={x(tick)} x2={x(tick)} y1={AX - 4} y2={AX + 4} stroke="var(--ink2)" />
    <text x={x(tick)} y={AX + 20} text-anchor={tick === 0 ? "start" : tick === 1 ? "end" : "middle"}>{tick === 0 ? "0 " + t("choice.skip") : tick === 1 ? "1 " + t("choice.allow") : decimal(0.5, 1)}</text>
  {/each}
  {#if median !== null}
    <line x1={x(median)} x2={x(median)} y1="8" y2={AX} stroke="var(--ink)" stroke-width="3" />
  {/if}
  {#each placed as v (v.id)}
    <circle cx={v.cx} cy={v.cy} r="6" fill={v.choice === "allow" ? "var(--ink)" : "var(--bg)"} stroke="var(--ink)" stroke-width="2" />
    <text x={v.cx + 9} y={v.cy + 4} class="id">{v.id}</text>
  {/each}
</svg>
</div>
<p class="note">{t("dots.legend")}</p>

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
  .id {
    fill: var(--ink);
    font-weight: 600;
  }
  .note {
    padding: var(--space-2) 0 var(--space-3);
  }
</style>
