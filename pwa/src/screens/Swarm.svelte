<script lang="ts">
  import VoterDots from "../components/VoterDots.svelte";
  import { gateway } from "../lib/gateway.svelte";
  import { clock, dayClock, decimal } from "../lib/format";
  import type { Decision, VoterRecord } from "../lib/types";

  const g = gateway;
  let pickedId = $state<string | null>(null);
  const decision = $derived<Decision | null>(g.decisions.find((d) => d.decision_id === pickedId) ?? g.decisions[0] ?? null);
  const action = $derived(decision?.aggregate?.questions.action ?? null);

  const REASON: Record<string, string> = {
    quorum_not_met: "kuorum tidak terpenuhi",
    spread_too_wide: "sebaran terlalu lebar, voter tidak sepakat",
  };

  function outcome(d: Decision): string {
    if (d.status === "skip") return "dilewati: " + (REASON[d.reason ?? ""] ?? d.reason ?? "-");
    return d.verdict;
  }

  function answerOf(v: VoterRecord): string {
    if (v.status !== "ok") return v.status === "timeout" ? "waktu habis" : v.status === "invalid" ? "jawaban tidak sah" : "gagal";
    return v.answers?.action?.choice ?? "-";
  }
</script>

{#if decision}
  <section class="verdict" class:skip={decision.status === "skip"} aria-label="Hasil keputusan">
    <p class="small">Kandidat entry {decision.pair} · kandel {dayClock(decision.candle)}</p>
    <p class="big">{outcome(decision)}</p>
    <p class="small">{decision.mode === "shadow" ? "Mode bayangan: hasil hanya dicatat, order tidak berubah." : "Mode gerbang: hasil ini menentukan entry."}</p>
  </section>

  <h2 class="sec">Sebaran jawaban <span class="meta">peluang izinkan per voter</span></h2>
  <div class="pad"><VoterDots {decision} /></div>

  <dl class="rows">
    <div><dt>Kuorum</dt><dd class="num" class:warn-text={decision.answered < decision.required}>{decision.answered} dari {decision.voters.length} menjawab (min {decision.required}){decision.answered >= decision.required ? ", terpenuhi" : ", gagal"}</dd></div>
    {#if action}
      <div><dt>Median peluang izinkan</dt><dd class="num">{decimal(action.median_probabilities?.izinkan ?? 0)}</dd></div>
      <div><dt>Sebaran (selisih kuartil)</dt><dd class="num" class:warn-text={action.spread.iqr > decision.iqr_limit}>{decimal(action.spread.iqr)} dari batas {decimal(decision.iqr_limit)}</dd></div>
      <div><dt>Suara</dt><dd class="num">{Object.entries(action.votes ?? {}).map(([k, n]) => k + " " + n).join(" · ")}</dd></div>
    {/if}
  </dl>

  <h2 class="sec">Jawaban voter <span class="meta">urutan opsi diacak per voter</span></h2>
  <table class="table">
    <thead><tr><th>Voter</th><th>Jawaban</th><th class="n">P(izinkan)</th></tr></thead>
    <tbody>
      {#each decision.voters as v (v.voter_id)}
        <tr class:dropped={v.status !== "ok"}>
          <td><b>{v.voter_id}</b> {v.provider}<br /><span class="muted small">{v.model ?? "-"} · {decimal(v.latency_s, 1)} dtk</span></td>
          <td>{answerOf(v)}{#if v.answers?.news_aligned?.noul !== undefined}<br /><span class="muted small">searah berita {decimal(v.answers.news_aligned.noul)}</span>{/if}</td>
          <td class="n num">{v.status === "ok" ? decimal(v.answers?.action?.probabilities?.izinkan ?? 0) : "dibuang"}</td>
        </tr>
      {/each}
    </tbody>
  </table>

  <h2 class="sec">Keputusan sebelumnya</h2>
  <ul class="history">
    {#each g.decisions as d (d.decision_id)}
      <li>
        <button type="button" aria-pressed={d.decision_id === decision.decision_id} onclick={() => (pickedId = d.decision_id)}>
          <span class="num muted">{clock(d.ts)}</span>
          <b>{d.pair}</b>
          <span class:warn-text={d.status === "skip" && d.reason === "quorum_not_met"}>{outcome(d)}</span>
        </button>
      </li>
    {/each}
  </ul>
{:else}
  <p class="note empty">Belum ada keputusan swarm. Swarm menilai kandidat entry saat kandel 1 jam tertutup dan strategi memberi sinyal masuk; hasilnya muncul di sini bersama jawaban tiap voter.</p>
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
