<script lang="ts">
  import VoterDots from "./VoterDots.svelte";
  import { dayClock, decimal } from "../lib/format";
  import { t } from "../lib/i18n";
  import type { Decision } from "../lib/types";
  import { answerText, verdictText } from "../lib/words";

  let {
    steps,
    index,
    older,
    onstep,
    onclose,
  }: { steps: Decision[]; index: number; older: number; onstep: (index: number) => void; onclose: () => void } = $props();

  const d = $derived(steps[index]);
  const action = $derived(d?.aggregate?.questions.action ?? null);
</script>

<section class="machine" aria-label={t("tm.title")}>
  <div class="bar">
    <button class="btn secondary" type="button" disabled={index <= 0} onclick={() => onstep(index - 1)} aria-label={t("tm.older")}>&larr;</button>
    <input
      type="range"
      min="0"
      max={Math.max(0, steps.length - 1)}
      step="1"
      value={index}
      aria-label={t("tm.slider")}
      aria-valuetext={d ? t("tm.position", { i: index + 1, n: steps.length, at: dayClock(d.candle) }) : ""}
      oninput={(e) => onstep(Number((e.currentTarget as HTMLInputElement).value))}
    />
    <button class="btn secondary" type="button" disabled={index >= steps.length - 1} onclick={() => onstep(index + 1)} aria-label={t("tm.newer")}>&rarr;</button>
    <button class="btn secondary" type="button" onclick={onclose}>{t("tm.now")}</button>
  </div>
  {#if d}
    <p class="small"><span class="num">{t("tm.position", { i: index + 1, n: steps.length, at: dayClock(d.candle) })}</span></p>
    <p class="verdict" class:skip={d.status === "skip"}>{verdictText(d)}</p>
    <p class="small muted">
      {[
        d.mode === "shadow" ? t("tm.mode_shadow") : t("tm.mode_gate"),
        t("tm.quorum", { answered: d.answered, total: d.voters.length, required: d.required }),
        ...(action ? [t("tm.median", { median: decimal(action.median_probabilities?.allow ?? 0), iqr: decimal(action.spread.iqr) })] : []),
      ].join(" · ")}
    </p>
    <VoterDots decision={d} />
    <ul class="answers">
      {#each d.voters as v (v.voter_id)}
        <li class:dropped={v.status !== "ok"}><b>{v.voter_id}</b> <span class="muted">{v.provider}</span> {answerText(v)}</li>
      {/each}
    </ul>
  {:else}
    <p class="note">{t("tm.empty")}</p>
  {/if}
  {#if older > 0}
    <p class="note small">{t("tm.older_hidden", { n: older })}</p>
  {/if}
</section>

<style>
  .machine {
    padding: var(--space-3) var(--space-4);
    background: var(--panel);
    border-bottom: 1px solid var(--rule);
  }
  .bar {
    display: grid;
    grid-template-columns: 44px 1fr 44px auto;
    gap: var(--space-2);
    align-items: center;
  }
  .bar .btn {
    min-height: 44px;
    padding-inline: var(--space-2);
  }
  input[type="range"] {
    width: 100%;
    min-height: 44px;
    accent-color: var(--ink);
  }
  p {
    margin: var(--space-2) 0 0;
  }
  .small {
    font-size: var(--step--1);
  }
  .verdict {
    font-size: var(--step-2);
    font-weight: 600;
  }
  .verdict.skip {
    color: var(--ink2);
  }
  .answers {
    display: flex;
    flex-wrap: wrap;
    gap: var(--space-1) var(--space-4);
    margin: var(--space-2) 0 0;
    padding: 0;
    list-style: none;
    font-size: var(--step--1);
  }
  .dropped {
    color: var(--ink2);
    text-decoration: line-through;
  }
</style>
