<script lang="ts">
  import BotSwitch from "../components/BotSwitch.svelte";
  import Outcome from "../components/Outcome.svelte";
  import { explainRead } from "../lib/control";
  import { dayClock, duration, parseTs, price } from "../lib/format";
  import { gateway } from "../lib/gateway.svelte";
  import { Resource } from "../lib/resource.svelte";
  import { faultOf, type Fault } from "../lib/state";
  import type { Performance, ProfitWindow, Stats, Trade } from "../lib/types";

  const g = gateway;
  const PAGE = 50;
  let bot = $state(g.bots[0]?.id ?? "A");
  let period = $state<"daily" | "weekly" | "monthly">("daily");
  let groupBy = $state<"exit" | "tag" | "pair">("exit");
  const b = () => "bot=" + encodeURIComponent(bot);

  const profit = new Resource(() => g.api.get<ProfitWindow>("/gw/v1/profit?window=" + period + "&timescale=" + (period === "daily" ? 14 : period === "weekly" ? 8 : 6) + "&" + b()));
  const stats = new Resource(() => g.api.get<Stats>("/gw/v1/stats?" + b()));
  const perf = new Resource(() => g.api.get<Performance>("/gw/v1/performance?" + b()));

  let trades = $state<Trade[]>([]);
  let tradesLoading = $state(false);
  let tradesFault = $state<Fault | null>(null);
  let more = $state(false);

  async function loadTrades(append: boolean) {
    tradesLoading = true;
    try {
      const page = await g.api.get<Trade[]>("/gw/v1/trades?limit=" + PAGE + "&offset=" + (append ? trades.length : 0) + "&state=closed&" + b());
      trades = append ? [...trades, ...page] : page;
      more = page.length === PAGE;
      tradesFault = null;
    } catch (error) {
      tradesFault = faultOf(error, Date.now());
    } finally {
      tradesLoading = false;
    }
  }

  $effect(() => {
    void bot;
    void stats.load();
    void perf.load();
    void loadTrades(false);
  });

  $effect(() => {
    void bot;
    void period;
    void profit.load();
  });

  const PERIODS = [
    { id: "daily" as const, label: "Harian" },
    { id: "weekly" as const, label: "Mingguan" },
    { id: "monthly" as const, label: "Bulanan" },
  ];
  const GROUPS = [
    { id: "exit" as const, label: "Alasan exit" },
    { id: "tag" as const, label: "Tag entry" },
    { id: "pair" as const, label: "Pair" },
  ];
  const EXIT: Record<string, string> = {
    roi: "target ROI",
    stop_loss: "stop loss",
    stoploss_on_exchange: "stop loss di bursa",
    trailing_stop_loss: "trailing stop",
    exit_signal: "sinyal exit",
    force_exit: "exit paksa",
    emergency_exit: "exit darurat",
  };
  const exitLabel = (r: string | null | undefined) => (r ? (EXIT[r] ?? r) : "-");

  const grouped = $derived.by(() => {
    if (!perf.data) return [];
    if (groupBy === "pair") return perf.data.per_pair.map((r) => ({ name: r.pair, ...r }));
    if (groupBy === "tag") return perf.data.by_enter_tag.map((r) => ({ name: r.enter_tag, ...r }));
    return perf.data.by_exit_reason.map((r) => ({ name: exitLabel(r.exit_reason), ...r }));
  });

  const held = (t: Trade) => (t.close_timestamp ? duration(t.close_timestamp - t.open_timestamp) : "-");
  const minutes = (m: number | null) => (m === null ? "-" : duration(m * 60000));
</script>

<div class="head"><BotSwitch bind:value={bot} label="Riwayat bot" /><span class="muted small">Angka dry-run, uang simulasi.</span></div>

<h2 class="sec">Per periode</h2>
<div class="chips" role="group" aria-label="Periode">
  {#each PERIODS as p (p.id)}<button class="chip" type="button" aria-pressed={period === p.id} onclick={() => (period = p.id)}>{p.label}</button>{/each}
</div>
{#if profit.loading && !profit.data}
  <div class="skel-rows" aria-busy="true"><span class="skeleton" style="width: 90%"></span><span class="skeleton" style="width: 85%"></span><span class="skeleton" style="width: 88%"></span></div>
{:else if profit.fault && !profit.data}
  <p class="note warn-text">Profit per periode gagal dimuat ({profit.fault.code}). {explainRead(profit.fault)}</p>
{:else if profit.data}
  <div class="scroll"><table class="table" aria-busy={profit.loading}>
    <thead><tr><th>{period === "daily" ? "Tanggal" : period === "weekly" ? "Minggu mulai" : "Bulan"}</th><th class="n">Trade</th><th class="n">Profit</th><th class="n">%</th></tr></thead>
    <tbody>
      {#each [...profit.data.data].reverse() as row (row.date)}
        <tr class:quiet={row.trade_count === 0}>
          <td class="num">{row.date}</td>
          <td class="n num">{row.trade_count}</td>
          <td class="n">{#if row.trade_count === 0}<span class="muted">-</span>{:else}<Outcome value={row.abs_profit} unit="idr" word={false} />{/if}</td>
          <td class="n">{#if row.trade_count === 0}<span class="muted">-</span>{:else}<Outcome value={row.rel_profit * 100} word={false} />{/if}</td>
        </tr>
      {/each}
    </tbody>
  </table></div>
{/if}

<h2 class="sec">Kelompok</h2>
<div class="chips" role="group" aria-label="Kelompokkan menurut">
  {#each GROUPS as k (k.id)}<button class="chip" type="button" aria-pressed={groupBy === k.id} onclick={() => (groupBy = k.id)}>{k.label}</button>{/each}
</div>
{#if perf.loading && !perf.data}
  <div class="skel-rows" aria-busy="true"><span class="skeleton" style="width: 80%"></span><span class="skeleton" style="width: 70%"></span></div>
{:else if perf.fault && !perf.data}
  <p class="note warn-text">Performa per kelompok gagal dimuat ({perf.fault.code}). {explainRead(perf.fault)}</p>
{:else if grouped.length === 0}
  <p class="note">Belum ada trade ditutup.</p>
{:else}
  <table class="table">
    <thead><tr><th>{GROUPS.find((k) => k.id === groupBy)?.label}</th><th class="n">Trade</th><th class="n">Profit</th>{#if groupBy === "exit" && stats.data}<th class="n">M / K / I</th>{/if}</tr></thead>
    <tbody>
      {#each grouped as r (r.name)}
        {@const wl = groupBy === "exit" ? stats.data?.exit_reasons[perf.data?.by_exit_reason.find((x) => exitLabel(x.exit_reason) === r.name)?.exit_reason ?? ""] : undefined}
        <tr>
          <td>{r.name}</td>
          <td class="n num">{r.count}</td>
          <td class="n"><Outcome value={r.profit_abs} unit="idr" word={false} /><br /><span class="small"><Outcome value={r.profit_pct} word={false} /></span></td>
          {#if groupBy === "exit" && stats.data}<td class="n num">{wl ? wl.wins + " / " + wl.losses + " / " + wl.draws : "-"}</td>{/if}
        </tr>
      {/each}
    </tbody>
  </table>
  {#if groupBy === "exit" && stats.data}
    <p class="note">M / K / I: menang, kalah, impas. Rata-rata lama posisi: menang {minutes(stats.data.durations.wins)}, kalah {minutes(stats.data.durations.losses)}, impas {minutes(stats.data.durations.draws)}.</p>
  {/if}
{/if}

<h2 class="sec">Trade ditutup <span class="meta num">{trades.length} dimuat</span></h2>
{#if tradesLoading && trades.length === 0}
  <div class="skel-rows" aria-busy="true"><span class="skeleton" style="width: 90%"></span><span class="skeleton" style="width: 90%"></span><span class="skeleton" style="width: 90%"></span></div>
{:else if tradesFault && trades.length === 0}
  <p class="note warn-text">Trade ditutup gagal dimuat ({tradesFault.code}). {explainRead(tradesFault)}</p>
  <div class="inline-actions"><button class="btn quiet" type="button" onclick={() => loadTrades(false)}>Coba lagi</button></div>
{:else if trades.length === 0}
  <p class="note">Belum ada trade ditutup untuk bot ini. Trade muncul di sini setelah exit terisi.</p>
{:else}
  <div class="scroll">
    <table class="table">
      <thead><tr><th>Pair</th><th>Tutup dan alasan</th><th class="wide n">Harga buka → tutup</th><th class="n">Hasil</th></tr></thead>
      <tbody>
        {#each trades as t (t.trade_id)}
          <tr>
            <td><b>{t.pair}</b><br /><span class="muted small">#{t.trade_id} · {t.enter_tag ?? "-"}</span></td>
            <td><span class="num">{t.close_timestamp ? dayClock(t.close_timestamp) : t.close_date ? dayClock(parseTs(t.close_date)) : "-"}</span><br /><span class="muted small">{exitLabel(t.exit_reason)} · ditahan {held(t)}</span></td>
            <td class="wide n num">{price(t.open_rate)} → {t.close_rate ? price(t.close_rate) : "-"}</td>
            <td class="n"><Outcome value={t.profit_pct ?? 0} word={false} /><br /><span class="small"><Outcome value={t.profit_abs} unit="idr" word={false} /></span></td>
          </tr>
        {/each}
      </tbody>
    </table>
  </div>
  {#if tradesFault}<p class="note warn-text">Halaman berikutnya gagal dimuat ({tradesFault.code}).</p>{/if}
  {#if more}
    <div class="inline-actions"><button class="btn quiet" type="button" disabled={tradesLoading} aria-busy={tradesLoading} onclick={() => loadTrades(true)}>{tradesLoading ? "Memuat…" : "Muat " + PAGE + " trade lagi"}</button></div>
  {/if}
{/if}

<style>
  .head {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: var(--space-3);
    padding: var(--space-3) var(--space-4);
  }
  .small {
    font-size: var(--step--1);
  }
  .quiet td {
    color: var(--ink2);
  }
  .scroll {
    overflow-x: auto;
  }
  .wide {
    display: none;
  }
  @media (min-width: 720px) {
    .wide {
      display: table-cell;
    }
  }
</style>
