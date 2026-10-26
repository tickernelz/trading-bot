<script lang="ts">
  import Outcome from "../components/Outcome.svelte";
  import VoterDots from "../components/VoterDots.svelte";
  import { explainRead } from "../lib/control";
  import { decisionsPath, outcomeView, type DecisionFilter } from "../lib/decisions";
  import { dayClock, decimal } from "../lib/format";
  import { gateway } from "../lib/gateway.svelte";
  import { faultOf, type Fault } from "../lib/state";
  import type { Decision, VoterRecord } from "../lib/types";

  const g = gateway;
  const PAGE = 30;
  let filter = $state<DecisionFilter>("semua");
  let items = $state<Decision[]>([]);
  let loading = $state(false);
  let fault = $state<Fault | null>(null);
  let more = $state(true);
  let pickedId = $state<string | null>(null);

  async function load(append: boolean) {
    loading = true;
    const before = append ? (items.at(-1)?.ts ?? null) : null;
    try {
      const page = await g.api.get<Decision[]>(decisionsPath(filter, before, null, PAGE));
      items = append ? [...items, ...page.filter((d) => !items.some((x) => x.decision_id === d.decision_id))] : page;
      more = page.length === PAGE;
      fault = null;
    } catch (error) {
      fault = faultOf(error, Date.now());
      if (!append && items.length === 0) items = g.decisions.filter(matches);
    } finally {
      loading = false;
    }
  }

  function matches(d: Decision): boolean {
    return filter === "semua" || d.status === filter;
  }

  $effect(() => {
    void filter;
    void load(false);
  });

  $effect(() => {
    const latest = g.decisions[0];
    if (latest && matches(latest) && !items.some((d) => d.decision_id === latest.decision_id)) items = [latest, ...items];
  });

  const decision = $derived<Decision | null>(items.find((d) => d.decision_id === pickedId) ?? items[0] ?? null);
  const action = $derived(decision?.aggregate?.questions.action ?? null);
  const view = $derived(outcomeView(decision?.outcome));

  const REASON: Record<string, string> = {
    quorum_not_met: "kuorum tidak terpenuhi",
    spread_too_wide: "sebaran terlalu lebar, voter tidak sepakat",
  };

  const FILTERS: { id: DecisionFilter; label: string }[] = [
    { id: "semua", label: "Semua" },
    { id: "skip", label: "Dilewati" },
    { id: "ok", label: "Dinilai" },
  ];

  function outcome(d: Decision): string {
    if (d.status === "skip") return "dilewati: " + (REASON[d.reason ?? ""] ?? d.reason ?? "-");
    return d.verdict;
  }

  function answerOf(v: VoterRecord): string {
    if (v.status !== "ok") return v.status === "timeout" ? "waktu habis" : v.status === "invalid" ? "jawaban tidak sah" : "gagal";
    return v.answers?.action?.choice ?? "-";
  }
</script>

<div class="chips" role="group" aria-label="Saring keputusan">
  {#each FILTERS as f (f.id)}
    <button class="chip" type="button" aria-pressed={filter === f.id} onclick={() => { filter = f.id; pickedId = null; }}>{f.label}</button>
  {/each}
</div>

{#if loading && items.length === 0}
  <div class="skel-rows" aria-busy="true" aria-label="Memuat keputusan swarm"><span class="skeleton" style="width: 50%; height: 1.6em"></span><span class="skeleton" style="width: 80%"></span><span class="skeleton" style="width: 65%"></span></div>
{:else if decision}
  <section class="verdict" class:skip={decision.status === "skip"} aria-label="Hasil keputusan">
    <p class="small">Kandidat entry {decision.pair} · kandel {dayClock(decision.candle)}</p>
    <p class="big">{outcome(decision)}</p>
    <p class="small">{decision.mode === "shadow" ? "Mode bayangan: hasil hanya dicatat, order tidak berubah." : "Mode gerbang: hasil ini menentukan entry."}</p>
  </section>

  <h2 class="sec">Hasil sesudahnya <span class="meta">{decision.bot ? "Bot " + decision.bot : ""}</span></h2>
  {#if view}
    <div class="after" class:pending={!view.settled}>
      <p><b>{view.headline}</b>{#if view.value !== null}: <Outcome value={view.value} />{/if}</p>
      <p class="small">{view.note}</p>
    </div>
  {:else}
    <p class="note">Gateway belum mengirim hasil sesudahnya untuk keputusan ini.</p>
  {/if}

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

  <h2 class="sec">Keputusan <span class="meta num">{items.length} dimuat</span></h2>
  <ul class="history">
    {#each items as d (d.decision_id)}
      {@const o = outcomeView(d.outcome)}
      <li>
        <button type="button" aria-pressed={d.decision_id === decision.decision_id} onclick={() => (pickedId = d.decision_id)}>
          <span class="num muted">{dayClock(d.ts)}</span>
          <b>{d.pair}</b>
          <span class:warn-text={d.status === "skip" && d.reason === "quorum_not_met"}>{outcome(d)}</span>
          <span class="after-mark">{#if o?.settled && o.value !== null}<Outcome value={o.value} word={false} />{:else if o}<span class="muted">menunggu</span>{/if}</span>
        </button>
      </li>
    {/each}
  </ul>
  {#if fault}<p class="note warn-text">Sebagian keputusan gagal dimuat ({fault.code}). {explainRead(fault)}</p>{/if}
  {#if more}
    <div class="inline-actions"><button class="btn quiet" type="button" disabled={loading} aria-busy={loading} onclick={() => load(true)}>{loading ? "Memuat…" : "Muat keputusan lebih lama"}</button></div>
  {/if}
{:else if fault}
  <p class="note empty warn-text">Keputusan swarm gagal dimuat dari gateway ({fault.code}). {explainRead(fault)}</p>
  <div class="inline-actions"><button class="btn quiet" type="button" onclick={() => load(false)}>Coba lagi</button></div>
{:else if filter !== "semua"}
  <p class="note empty">Tidak ada keputusan dengan saringan ini.</p>
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
  .after {
    margin: 0 var(--space-4) var(--space-2);
  }
  .after p {
    margin: 0;
  }
  .after.pending b {
    color: var(--ink2);
  }
  .after-mark {
    text-align: right;
    font-size: var(--step--1);
  }
  .history button {
    display: grid;
    grid-template-columns: 7.4em 5.2em 1fr auto;
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
