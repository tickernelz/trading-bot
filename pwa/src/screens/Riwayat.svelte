<script lang="ts">
  import BotSwitch from "../components/BotSwitch.svelte";
  import Outcome from "../components/Outcome.svelte";
  import { explainRead } from "../lib/control";
  import { dayClock, duration, parseTs, price } from "../lib/format";
  import { gateway } from "../lib/gateway.svelte";
  import { t } from "../lib/i18n";
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
    { id: "daily" as const, label: t("hist.daily") },
    { id: "weekly" as const, label: t("hist.weekly") },
    { id: "monthly" as const, label: t("hist.monthly") },
  ];
  const GROUPS = [
    { id: "exit" as const, label: t("hist.by_exit") },
    { id: "tag" as const, label: t("hist.by_tag") },
    { id: "pair" as const, label: "Pair" },
  ];
  const EXIT: Record<string, string> = {
    roi: t("exit.roi"),
    stop_loss: t("exit.stop_loss"),
    stoploss_on_exchange: t("exit.stoploss_on_exchange"),
    trailing_stop_loss: t("exit.trailing_stop_loss"),
    exit_signal: t("exit.exit_signal"),
    force_exit: t("exit.force_exit"),
    emergency_exit: t("exit.emergency_exit"),
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

<div class="head"><BotSwitch bind:value={bot} label={t("hist.bot_label")} /><span class="muted small">{t("hist.dry")}</span></div>

<h2 class="sec">{t("hist.per_period")}</h2>
<div class="chips" role="group" aria-label={t("hist.period")}>
  {#each PERIODS as p (p.id)}<button class="chip" type="button" aria-pressed={period === p.id} onclick={() => (period = p.id)}>{p.label}</button>{/each}
</div>
{#if profit.loading && !profit.data}
  <div class="skel-rows" aria-busy="true"><span class="skeleton" style="width: 90%"></span><span class="skeleton" style="width: 85%"></span><span class="skeleton" style="width: 88%"></span></div>
{:else if profit.fault && !profit.data}
  <p class="note warn-text">{t("hist.period_failed", { code: profit.fault.code })} {explainRead(profit.fault)}</p>
{:else if profit.data}
  <div class="scroll"><table class="table" aria-busy={profit.loading}>
    <thead><tr><th>{period === "daily" ? t("hist.col_date") : period === "weekly" ? t("hist.col_week") : t("hist.col_month")}</th><th class="n">Trade</th><th class="n">Profit</th><th class="n">%</th></tr></thead>
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

<h2 class="sec">{t("hist.groups")}</h2>
<div class="chips" role="group" aria-label={t("hist.group_by")}>
  {#each GROUPS as k (k.id)}<button class="chip" type="button" aria-pressed={groupBy === k.id} onclick={() => (groupBy = k.id)}>{k.label}</button>{/each}
</div>
{#if perf.loading && !perf.data}
  <div class="skel-rows" aria-busy="true"><span class="skeleton" style="width: 80%"></span><span class="skeleton" style="width: 70%"></span></div>
{:else if perf.fault && !perf.data}
  <p class="note warn-text">{t("hist.groups_failed", { code: perf.fault.code })} {explainRead(perf.fault)}</p>
{:else if grouped.length === 0}
  <p class="note">{t("hist.none_closed")}</p>
{:else}
  <table class="table">
    <thead><tr><th>{GROUPS.find((k) => k.id === groupBy)?.label}</th><th class="n">Trade</th><th class="n">Profit</th>{#if groupBy === "exit" && stats.data}<th class="n">{t("hist.wld")}</th>{/if}</tr></thead>
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
    <p class="note">{t("hist.wld_note", { w: minutes(stats.data.durations.wins), l: minutes(stats.data.durations.losses), d: minutes(stats.data.durations.draws) })}</p>
  {/if}
{/if}

<h2 class="sec">{t("hist.closed")} <span class="meta num">{t("swarm.loaded", { n: trades.length })}</span></h2>
{#if tradesLoading && trades.length === 0}
  <div class="skel-rows" aria-busy="true"><span class="skeleton" style="width: 90%"></span><span class="skeleton" style="width: 90%"></span><span class="skeleton" style="width: 90%"></span></div>
{:else if tradesFault && trades.length === 0}
  <p class="note warn-text">{t("hist.closed_failed", { code: tradesFault.code })} {explainRead(tradesFault)}</p>
  <div class="inline-actions"><button class="btn quiet" type="button" onclick={() => loadTrades(false)}>{t("common.retry")}</button></div>
{:else if trades.length === 0}
  <p class="note">{t("hist.closed_empty")}</p>
{:else}
  <div class="scroll">
    <table class="table">
      <thead><tr><th>Pair</th><th>{t("hist.col_close")}</th><th class="wide n">{t("hist.col_prices")}</th><th class="n">{t("hist.col_result")}</th></tr></thead>
      <tbody>
        {#each trades as tr (tr.trade_id)}
          <tr>
            <td><b>{tr.pair}</b><br /><span class="muted small">#{tr.trade_id} · {tr.enter_tag ?? "-"}</span></td>
            <td><span class="num">{tr.close_timestamp ? dayClock(tr.close_timestamp) : tr.close_date ? dayClock(parseTs(tr.close_date)) : "-"}</span><br /><span class="muted small">{t("hist.held", { reason: exitLabel(tr.exit_reason), d: held(tr) })}</span></td>
            <td class="wide n num">{price(tr.open_rate)} → {tr.close_rate ? price(tr.close_rate) : "-"}</td>
            <td class="n"><Outcome value={tr.profit_pct ?? 0} word={false} /><br /><span class="small"><Outcome value={tr.profit_abs} unit="idr" word={false} /></span></td>
          </tr>
        {/each}
      </tbody>
    </table>
  </div>
  {#if tradesFault}<p class="note warn-text">{t("common.next_failed", { code: tradesFault.code })}</p>{/if}
  {#if more}
    <div class="inline-actions"><button class="btn quiet" type="button" disabled={tradesLoading} aria-busy={tradesLoading} onclick={() => loadTrades(true)}>{tradesLoading ? t("common.loading") : t("hist.more", { n: PAGE })}</button></div>
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
