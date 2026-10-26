<script lang="ts">
  import VoterDots from "../components/VoterDots.svelte";
  import { gateway } from "../lib/gateway.svelte";
  import { clock, dayClock, decimal } from "../lib/format";
  import { t } from "../lib/i18n";
  import type { Decision } from "../lib/types";
  import { answerText, choiceText, verdictText } from "../lib/words";

  const g = gateway;
  let pickedId = $state<string | null>(null);
  const decision = $derived<Decision | null>(g.decisions.find((d) => d.decision_id === pickedId) ?? g.decisions[0] ?? null);
  const action = $derived(decision?.aggregate?.questions.action ?? null);
</script>

{#if decision}
  <section class="verdict" class:skip={decision.status === "skip"} aria-label={t("swarm.result")}>
    <p class="small">{t("swarm.candidate", { pair: decision.pair, at: dayClock(decision.candle) })}</p>
    <p class="big">{verdictText(decision)}</p>
    <p class="small">{decision.mode === "shadow" ? t("swarm.mode_shadow") : t("swarm.mode_gate")}</p>
  </section>

  <h2 class="sec">{t("swarm.spread")} <span class="meta">{t("swarm.spread_meta")}</span></h2>
  <div class="pad"><VoterDots {decision} /></div>

  <dl class="rows">
    <div><dt>{t("ringkas.quorum")}</dt><dd class="num" class:warn-text={decision.answered < decision.required}>{t("tm.quorum", { answered: decision.answered, total: decision.voters.length, required: decision.required })}{decision.answered >= decision.required ? t("swarm.quorum_met") : t("swarm.quorum_failed")}</dd></div>
    {#if action}
      <div><dt>{t("swarm.median")}</dt><dd class="num">{decimal(action.median_probabilities?.izinkan ?? 0)}</dd></div>
      <div><dt>{t("swarm.iqr")}</dt><dd class="num" class:warn-text={action.spread.iqr > decision.iqr_limit}>{t("swarm.iqr_value", { iqr: decimal(action.spread.iqr), limit: decimal(decision.iqr_limit) })}</dd></div>
      <div><dt>{t("swarm.votes")}</dt><dd class="num">{Object.entries(action.votes ?? {}).map(([k, n]) => choiceText(k) + " " + n).join(" · ")}</dd></div>
    {/if}
  </dl>

  <h2 class="sec">{t("swarm.answers")} <span class="meta">{t("swarm.answers_meta")}</span></h2>
  <table class="table">
    <thead><tr><th>Voter</th><th>{t("swarm.col_answer")}</th><th class="n">{t("swarm.col_p")}</th></tr></thead>
    <tbody>
      {#each decision.voters as v (v.voter_id)}
        <tr class:dropped={v.status !== "ok"}>
          <td><b>{v.voter_id}</b> {v.provider}<br /><span class="muted small">{v.model ?? "-"} · {t("dur.s", { n: decimal(v.latency_s, 1) })}</span></td>
          <td>{answerText(v)}{#if v.answers?.news_aligned?.noul !== undefined}<br /><span class="muted small">{t("swarm.news_aligned", { v: decimal(v.answers.news_aligned.noul) })}</span>{/if}</td>
          <td class="n num">{v.status === "ok" ? decimal(v.answers?.action?.probabilities?.izinkan ?? 0) : t("swarm.dropped")}</td>
        </tr>
      {/each}
    </tbody>
  </table>

  <h2 class="sec">{t("swarm.previous")}</h2>
  <ul class="history">
    {#each g.decisions as d (d.decision_id)}
      <li>
        <button type="button" aria-pressed={d.decision_id === decision.decision_id} onclick={() => (pickedId = d.decision_id)}>
          <span class="num muted">{clock(d.ts)}</span>
          <b>{d.pair}</b>
          <span class:warn-text={d.status === "skip" && d.reason === "quorum_not_met"}>{verdictText(d)}</span>
        </button>
      </li>
    {/each}
  </ul>
{:else if g.panelFaults.decisions}
  <p class="note empty warn-text">{t("swarm.load_failed", { code: g.panelFaults.decisions.code })}</p>
{:else}
  <p class="note empty">{t("swarm.empty")}</p>
{/if}

<style>
  .verdict {
    padding: var(--space-4);
    background: var(--panel);
    border-bottom: 1px solid var(--rule);
  }
  .verdict p {
    margin: 0;
  }
  .verdict .big {
    margin: 4px 0;
    font-size: var(--step-2);
    font-weight: 650;
  }
  .verdict.skip .big {
    color: var(--loss);
  }
  .small {
    font-size: var(--step--1);
    color: var(--ink2);
  }
  .pad {
    padding: 0 var(--space-4);
  }
  .dropped td {
    color: var(--ink2);
  }
  .history {
    margin: 0;
    padding: 0 0 var(--space-4);
    list-style: none;
  }
  .history button {
    display: grid;
    grid-template-columns: 3.4em 5.6em 1fr;
    gap: var(--space-2);
    width: 100%;
    min-height: 44px;
    padding: 8px var(--space-4);
    border: 0;
    border-top: 1px solid var(--rule);
    background: transparent;
    text-align: left;
    font-size: var(--step-0);
    cursor: pointer;
  }
  .history button:hover {
    background: var(--panel);
  }
  .history button[aria-pressed="true"] {
    background: var(--panel);
    box-shadow: inset 0 0 0 1.5px var(--ink);
    font-weight: 600;
  }
  .empty {
    padding-top: var(--space-5);
  }
</style>
