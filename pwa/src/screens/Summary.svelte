<script lang="ts">
  import Board from "../components/Board.svelte";
  import Meter from "../components/Meter.svelte";
  import Outcome from "../components/Outcome.svelte";
  import Trace from "../components/Trace.svelte";
  import { gateway } from "../lib/gateway.svelte";
  import { age, clock, decimal, MINUS, percent, price, rupiah } from "../lib/format";
  import { exitReason } from "../lib/feedText";
  import { t } from "../lib/i18n";
  import { verdictText } from "../lib/words";

  const g = gateway;
  const day = $derived(g.equityDay?.series[0] ?? null);
  const latest = $derived(g.decisions[0] ?? null);
  const heartbeat = $derived(g.health?.freqtrade.last_process ? g.now - Date.parse(g.health.freqtrade.last_process) : Number.NaN);
</script>

<Board />

<div class="cols">
  <div class="main">
    <h2 class="sec">{t("summary.trace")} <span class="meta">{t("summary.trace_meta")}</span></h2>
    {#if day && g.risk}
      <div class="pad"><Trace points={day.points} start={g.equityDay!.start_equity} limitPct={g.risk.limits.max_daily_loss_pct} from={g.risk.day_start} stale={g.stale} /></div>
    {:else if g.panelFaults.equityDay}
      <p class="note warn-text">{t("summary.trace_failed", { code: g.panelFaults.equityDay.code })}</p>
    {:else}
      <div class="pad"><span class="skeleton" style="height:150px"></span></div>
    {/if}

    {#if g.risk}
      <Meter name={t("summary.daily_loss")} value={g.risk.daily_loss_pct} limit={g.risk.limits.max_daily_loss_pct} stale={g.stale} />
      <Meter name={t("summary.drawdown")} value={g.risk.drawdown_pct} limit={g.risk.limits.max_total_drawdown_pct} stale={g.stale} />
    {/if}

    <h2 class="sec">{t("summary.open")} <span class="meta">{g.overview ? t("summary.open_meta", { n: g.overview.open_trades.count, max: g.overview.open_trades.max }) : ""}</span></h2>
    {#if g.openTrades.length}
      <table class="table" class:stale-value={g.stale}>
        <thead>
          <tr><th>Pair</th><th>{t("summary.col_entry")}</th><th class="n">{t("summary.col_pnl")}</th></tr>
        </thead>
        <tbody>
          {#each g.openTrades as t (t.trade_id)}
            <tr>
              <td><b>{t.pair}</b><br /><span class="muted small">#{t.trade_id} · {t.enter_tag ?? "-"}</span></td>
              <td class="num">{clock(t.open_timestamp)}<br /><span class="muted small">{price(t.open_rate)}</span></td>
              <td class="n">
                <Outcome value={t.profit_pct_now ?? 0} /><br />
                <span class="small"><Outcome value={t.profit_abs} unit="idr" word={false} /></span><br />
                <span class="muted small">stop {MINUS}{percent(t.stop_loss_pct ?? 0, 1)}</span>
              </td>
            </tr>
          {/each}
        </tbody>
      </table>
    {:else if g.overview}
      <p class="note">{t("summary.no_open")}</p>
    {/if}

    <h2 class="sec">{t("summary.pending")} <span class="meta">{t("summary.pending_meta")}</span></h2>
    {#if g.pending.length}
      <dl class="rows">
        {#each g.pending as o (o.trade_id)}
          <div><dt>{o.side === "buy" ? t("summary.buy") : t("summary.sell")} {o.pair} · #{o.trade_id}</dt><dd class="num">{price(o.price)} · {clock(o.ts, true)}</dd></div>
        {/each}
      </dl>
    {:else}
      <p class="note">{t("summary.no_pending")}</p>
    {/if}

    {#if g.overview && g.risk}
      <h2 class="sec">{t("summary.balance")} <span class="meta">{g.overview.balance.note === "Simulated balances" ? t("summary.simulated") : ""}</span></h2>
      <dl class="rows" class:stale-value={g.stale}>
        <div><dt>{t("summary.equity")}</dt><dd class="num">{rupiah(g.risk.equity)}</dd></div>
        <div><dt>{t("summary.initial")}</dt><dd class="num">{rupiah(g.overview.capital.initial_idr)}</dd></div>
        <div><dt>{t("summary.closed_result")}</dt><dd><Outcome value={g.overview.profit.abs} unit="idr" /></dd></div>
        <div><dt>{t("summary.closed")}</dt><dd class="num">{t("summary.closed_value", { n: g.overview.profit.trades_closed, win: Math.round(g.overview.profit.winrate * 100) })}</dd></div>
      </dl>
    {/if}
  </div>

  <aside class="side" aria-label={t("summary.side")}>
    <h2 class="sec">{t("summary.last_decision")} <span class="meta">{latest ? latest.pair + " " + clock(latest.ts) : ""}</span></h2>
    {#if latest}
      <dl class="rows">
        <div><dt>{t("summary.result")}</dt><dd>{verdictText(latest)}{latest.mode === "shadow" ? " " + t("summary.shadow") : ""}</dd></div>
        <div><dt>{t("summary.quorum")}</dt><dd class="num">{t("tm.quorum", { answered: latest.answered, total: latest.voters.length, required: latest.required })}</dd></div>
        {#if latest.aggregate?.questions.action}
          <div><dt>{t("summary.median_spread")}</dt><dd class="num">{decimal(latest.aggregate.questions.action.median_probabilities?.allow ?? 0)} · {decimal(latest.aggregate.questions.action.spread.iqr)}</dd></div>
        {/if}
      </dl>
      <p class="note"><a class="tap" href="#swarm">{t("summary.see_voters")}</a></p>
    {/if}

    <h2 class="sec">{t("summary.health")}</h2>
    {#if g.health}
      <dl class="rows">
        <div><dt>{t("summary.loop")}</dt><dd>{g.health.freqtrade.state === "running" ? t("status.running") : t("status.stopped")}</dd></div>
        <div><dt>Heartbeat</dt><dd class="num">{age(heartbeat)}</dd></div>
        <div><dt>Indodax</dt><dd class="num">{g.health.exchange.reachable ? t("summary.reachable", { s: decimal((g.health.exchange.latency_ms ?? 0) / 1000, 1) }) : t("summary.unreachable")}</dd></div>
      </dl>
    {/if}

    <h2 class="sec">{t("summary.last_actions")} <span class="meta"><a class="tap" href="#activity">{t("summary.all")}</a></span></h2>
    <ul class="mini-feed">
      {#each g.feed.slice(0, 5) as item (item.seq)}
        <li class:warn={item.warn}><time class="num">{clock(item.ts)}</time><span>{item.text}</span></li>
      {:else}
        <li class="muted">{t("summary.no_actions")}</li>
      {/each}
    </ul>
    {#if g.closedTrades[0]}
      <p class="note">{t("summary.last_closed", { pair: g.closedTrades[0].pair, reason: exitReason(g.closedTrades[0].exit_reason) })}</p>
    {/if}
  </aside>
</div>

<style>
  .pad {
    padding: 0 var(--space-4) var(--space-2);
  }
  .small {
    font-size: var(--step--1);
  }
  .mini-feed {
    margin: 0;
    padding: 0 var(--space-4) var(--space-2);
    list-style: none;
    font-size: var(--step-0);
  }
  .mini-feed li {
    display: flex;
    gap: var(--space-3);
    padding: 6px 0;
  }
  .mini-feed li + li {
    border-top: 1px solid var(--rule);
  }
  .mini-feed time {
    flex: none;
    width: 3.2em;
    color: var(--ink2);
  }
  .mini-feed .warn span {
    color: var(--loss);
    font-weight: 600;
  }
  @media (min-width: 960px) {
    .cols {
      display: grid;
      grid-template-columns: minmax(0, 1.45fr) minmax(0, 1fr);
    }
    .side {
      border-left: 1px solid var(--rule);
    }
    .side > :global(.sec:first-child) {
      border-top: 0;
    }
  }
</style>
