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
    <h2 class="sec">{t("ringkas.trace")} <span class="meta">{t("ringkas.trace_meta")}</span></h2>
    {#if day && g.risk}
      <div class="pad"><Trace points={day.points} start={g.equityDay!.start_equity} limitPct={g.risk.limits.max_daily_loss_pct} from={g.risk.day_start} stale={g.stale} /></div>
    {:else if g.panelFaults.equityDay}
      <p class="note warn-text">{t("ringkas.trace_failed", { code: g.panelFaults.equityDay.code })}</p>
    {:else}
      <div class="pad"><span class="skeleton" style="height:150px"></span></div>
    {/if}

    {#if g.risk}
      <Meter name={t("ringkas.daily_loss")} value={g.risk.daily_loss_pct} limit={g.risk.limits.max_daily_loss_pct} stale={g.stale} />
      <Meter name={t("ringkas.drawdown")} value={g.risk.drawdown_pct} limit={g.risk.limits.max_total_drawdown_pct} stale={g.stale} />
    {/if}

    <h2 class="sec">{t("ringkas.open")} <span class="meta">{g.overview ? t("ringkas.open_meta", { n: g.overview.open_trades.count, max: g.overview.open_trades.max }) : ""}</span></h2>
    {#if g.openTrades.length}
      <table class="table" class:stale-value={g.stale}>
        <thead>
          <tr><th>Pair</th><th>{t("ringkas.col_entry")}</th><th class="n">{t("ringkas.col_pnl")}</th></tr>
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
      <p class="note">{t("ringkas.no_open")}</p>
    {/if}

    <h2 class="sec">{t("ringkas.pending")} <span class="meta">{t("ringkas.pending_meta")}</span></h2>
    {#if g.pending.length}
      <dl class="rows">
        {#each g.pending as o (o.trade_id)}
          <div><dt>{o.side === "beli" ? t("ringkas.buy") : t("ringkas.sell")} {o.pair} · #{o.trade_id}</dt><dd class="num">{price(o.price)} · {clock(o.ts, true)}</dd></div>
        {/each}
      </dl>
    {:else}
      <p class="note">{t("ringkas.no_pending")}</p>
    {/if}

    {#if g.overview && g.risk}
      <h2 class="sec">{t("ringkas.balance")} <span class="meta">{g.overview.balance.note === "Simulated balances" ? t("ringkas.simulated") : ""}</span></h2>
      <dl class="rows" class:stale-value={g.stale}>
        <div><dt>{t("ringkas.equity")}</dt><dd class="num">{rupiah(g.risk.equity)}</dd></div>
        <div><dt>{t("ringkas.initial")}</dt><dd class="num">{rupiah(g.overview.capital.initial_idr)}</dd></div>
        <div><dt>{t("ringkas.closed_result")}</dt><dd><Outcome value={g.overview.profit.abs} unit="idr" /></dd></div>
        <div><dt>{t("ringkas.closed")}</dt><dd class="num">{t("ringkas.closed_value", { n: g.overview.profit.trades_closed, win: Math.round(g.overview.profit.winrate * 100) })}</dd></div>
      </dl>
    {/if}
  </div>

  <aside class="side" aria-label={t("ringkas.side")}>
    <h2 class="sec">{t("ringkas.last_decision")} <span class="meta">{latest ? latest.pair + " " + clock(latest.ts) : ""}</span></h2>
    {#if latest}
      <dl class="rows">
        <div><dt>{t("ringkas.result")}</dt><dd>{verdictText(latest)}{latest.mode === "shadow" ? " " + t("ringkas.shadow") : ""}</dd></div>
        <div><dt>{t("ringkas.quorum")}</dt><dd class="num">{t("tm.quorum", { answered: latest.answered, total: latest.voters.length, required: latest.required })}</dd></div>
        {#if latest.aggregate?.questions.action}
          <div><dt>{t("ringkas.median_spread")}</dt><dd class="num">{decimal(latest.aggregate.questions.action.median_probabilities?.izinkan ?? 0)} · {decimal(latest.aggregate.questions.action.spread.iqr)}</dd></div>
        {/if}
      </dl>
      <p class="note"><a class="tap" href="#swarm">{t("ringkas.see_voters")}</a></p>
    {/if}

    <h2 class="sec">{t("ringkas.health")}</h2>
    {#if g.health}
      <dl class="rows">
        <div><dt>{t("ringkas.loop")}</dt><dd>{g.health.freqtrade.state === "running" ? t("status.running") : t("status.stopped")}</dd></div>
        <div><dt>Heartbeat</dt><dd class="num">{age(heartbeat)}</dd></div>
        <div><dt>Indodax</dt><dd class="num">{g.health.exchange.reachable ? t("ringkas.reachable", { s: decimal((g.health.exchange.latency_ms ?? 0) / 1000, 1) }) : t("ringkas.unreachable")}</dd></div>
      </dl>
    {/if}

    <h2 class="sec">{t("ringkas.last_actions")} <span class="meta"><a class="tap" href="#aksi">{t("ringkas.all")}</a></span></h2>
    <ul class="mini-feed">
      {#each g.feed.slice(0, 5) as item (item.seq)}
        <li class:warn={item.warn}><time class="num">{clock(item.ts)}</time><span>{item.text}</span></li>
      {:else}
        <li class="muted">{t("ringkas.no_actions")}</li>
      {/each}
    </ul>
    {#if g.closedTrades[0]}
      <p class="note">{t("ringkas.last_closed", { pair: g.closedTrades[0].pair, reason: exitReason(g.closedTrades[0].exit_reason) })}</p>
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
