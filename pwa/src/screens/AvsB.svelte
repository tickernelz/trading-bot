<script lang="ts">
  import Outcome from "../components/Outcome.svelte";
  import { explainRead } from "../lib/control";
  import { clock, decimal, rupiah } from "../lib/format";
  import { gateway } from "../lib/gateway.svelte";
  import { Resource } from "../lib/resource.svelte";
  import type { Equity, ProfitTotal } from "../lib/types";

  const g = gateway;
  const chart = import("../components/EquityChart.svelte");
  let window = $state<"7d" | "total">("total");
  const ids = $derived(g.bots.map((b) => b.id).join(","));
  const equity = new Resource(() => g.api.get<Equity>("/gw/v1/equity?window=" + window + "&bots=" + encodeURIComponent(ids)));
  const profits = new Resource(() => Promise.all(g.bots.map((b) => g.api.get<ProfitTotal>("/gw/v1/profit?window=total&bot=" + encodeURIComponent(b.id)).then((p) => ({ bot: b, p })))));

  $effect(() => {
    void window;
    void ids;
    void equity.load();
  });

  $effect(() => {
    void ids;
    void profits.load();
  });

  const finals = $derived(equity.data ? equity.data.series.map((s) => ({ ...s, end: s.points.at(-1)?.[1] ?? equity.data!.start_equity, from: s.points[0]?.[0] ?? null })) : []);
  const WINDOWS = [
    { id: "total" as const, label: "Sejak awal dry-run" },
    { id: "7d" as const, label: "7 hari" },
  ];
</script>

<div class="chips" role="group" aria-label="Rentang waktu">
  {#each WINDOWS as w (w.id)}
    <button class="chip" type="button" aria-pressed={window === w.id} onclick={() => (window = w.id)}>{w.label}</button>
  {/each}
</div>

<h2 class="sec">Kurva ekuitas bertumpuk <span class="meta">dry-run, uang simulasi</span></h2>
{#if equity.data}
  {#await chart}
    <div class="pad"><span class="skeleton" style="height: 260px"></span></div>
  {:then Equity}
    <Equity.default equity={equity.data} label={"Kurva ekuitas " + g.bots.map((b) => b.label).join(" dan ") + ", " + (window === "7d" ? "tujuh hari" : "sejak awal dry-run")} />
  {:catch}
    <p class="note warn-text">Modul grafik gagal dimuat. Muat ulang aplikasi.</p>
  {/await}
  <ul class="legend">
    {#each finals as s, i (s.bot)}
      <li><span class="key" class:dashed={i % 2 === 0} class:solid={i % 2 === 1} aria-hidden="true"></span>{s.label}: {s.strategy}</li>
    {/each}
  </ul>
  <table class="table">
    <thead><tr><th>Bot</th><th class="n">Ekuitas akhir</th><th class="n">Perubahan</th></tr></thead>
    <tbody>
      {#each finals as s (s.bot)}
        <tr>
          <td><b>{s.label}</b><br /><span class="muted small">sejak {s.from ? clock(s.from) + " " + s.from.slice(0, 10) : "-"}</span></td>
          <td class="n num">{rupiah(s.end)}</td>
          <td class="n"><Outcome value={((s.end - equity.data.start_equity) / equity.data.start_equity) * 100} /></td>
        </tr>
      {/each}
    </tbody>
  </table>
{:else if equity.fault}
  <p class="note warn-text">Ekuitas gagal dimuat ({equity.fault.code}). {explainRead(equity.fault)}</p>
  <div class="inline-actions"><button class="btn quiet" type="button" onclick={() => equity.load()}>Coba lagi</button></div>
{:else}
  <div class="pad" aria-busy="true"><span class="skeleton" style="height: 260px"></span></div>
{/if}

<h2 class="sec">Pembanding <span class="meta">trade ditutup sejak awal</span></h2>
{#if profits.data}
  <div class="scroll">
    <table class="table">
      <thead>
        <tr><th></th>{#each profits.data as row (row.bot.id)}<th class="n">{row.bot.label}</th>{/each}</tr>
      </thead>
      <tbody>
        <tr><th scope="row">Trade ditutup</th>{#each profits.data as row (row.bot.id)}<td class="n num">{row.p.closed_trade_count}</td>{/each}</tr>
        <tr><th scope="row">Menang / kalah</th>{#each profits.data as row (row.bot.id)}<td class="n num">{row.p.winning_trades} / {row.p.losing_trades}</td>{/each}</tr>
        <tr><th scope="row">Profit tertutup</th>{#each profits.data as row (row.bot.id)}<td class="n"><Outcome value={row.p.profit_closed_coin} unit="idr" word={false} /></td>{/each}</tr>
        <tr><th scope="row">Profit tertutup (%)</th>{#each profits.data as row (row.bot.id)}<td class="n"><Outcome value={row.p.profit_closed_percent} word={false} /></td>{/each}</tr>
        <tr><th scope="row">Drawdown maksimal</th>{#each profits.data as row (row.bot.id)}<td class="n num">{row.p.max_drawdown === undefined ? "-" : decimal(row.p.max_drawdown * 100) + "%" + (row.p.max_drawdown_abs === undefined ? "" : " · " + rupiah(row.p.max_drawdown_abs))}</td>{/each}</tr>
        <tr><th scope="row">Pair terbaik / terburuk</th>{#each profits.data as row (row.bot.id)}<td class="n">{row.p.best_pair ?? "-"} / {row.p.worst_pair ?? "-"}</td>{/each}</tr>
      </tbody>
    </table>
  </div>
  <p class="note">Bot A aturan saja; Bot B aturan dengan swarm. Selama swarm dalam mode bayangan, selisih kedua bot bukan bukti swarm berguna. Syarat adopsi swarm ada di plan bagian 8 (minimal 4 minggu dan 30 keputusan veto).</p>
{:else if profits.fault}
  <p class="note warn-text">Pembanding gagal dimuat ({profits.fault.code}). {explainRead(profits.fault)}</p>
{:else}
  <div class="skel-rows" aria-busy="true"><span class="skeleton" style="width: 80%"></span><span class="skeleton" style="width: 70%"></span><span class="skeleton" style="width: 75%"></span></div>
{/if}

<style>
  .pad {
    padding: 0 var(--space-4);
  }
  .small {
    font-size: var(--step--1);
  }
  .legend {
    display: flex;
    flex-wrap: wrap;
    gap: var(--space-2) var(--space-4);
    margin: 0;
    padding: var(--space-2) var(--space-4);
    list-style: none;
    font-size: var(--step--1);
    color: var(--ink2);
  }
  .key {
    display: inline-block;
    width: 22px;
    margin-right: 6px;
    vertical-align: middle;
    border-top: 2px solid var(--ink);
  }
  .key.dashed {
    border-top: 2px dashed var(--ink2);
  }
  .scroll {
    overflow-x: auto;
  }
  th[scope="row"] {
    padding-left: var(--space-4);
    color: var(--ink2);
    font-weight: 400;
    border-top: 1px solid var(--rule);
  }
</style>
