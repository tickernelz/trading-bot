<script lang="ts">
  import Board from "../components/Board.svelte";
  import Meter from "../components/Meter.svelte";
  import Outcome from "../components/Outcome.svelte";
  import Trace from "../components/Trace.svelte";
  import { gateway } from "../lib/gateway.svelte";
  import { age, clock, decimal, MINUS, percent, price, rupiah } from "../lib/format";
  import { exitReason } from "../lib/feedText";

  const g = gateway;
  const day = $derived(g.equityDay?.series[0] ?? null);
  const latest = $derived(g.decisions[0] ?? null);
  const heartbeat = $derived(g.health?.freqtrade.last_process ? g.now - Date.parse(g.health.freqtrade.last_process) : Number.NaN);
</script>

<Board />

<div class="cols">
  <div class="main">
    <h2 class="sec">Jejak hari ini <span class="meta">sejak 00.00 WIB</span></h2>
    {#if day && g.risk}
      <div class="pad"><Trace points={day.points} start={g.equityDay!.start_equity} limitPct={g.risk.limits.max_daily_loss_pct} from={g.risk.day_start} stale={g.stale} /></div>
    {:else if g.panelFaults.equityDay}
      <p class="note warn-text">Jejak hari ini gagal dimuat ({g.panelFaults.equityDay.code}).</p>
    {:else}
      <div class="pad"><span class="skeleton" style="height:150px"></span></div>
    {/if}

    {#if g.risk}
      <Meter name="Rugi hari ini" value={g.risk.daily_loss_pct} limit={g.risk.limits.max_daily_loss_pct} stale={g.stale} />
      <Meter name="Turun dari puncak (total)" value={g.risk.drawdown_pct} limit={g.risk.limits.max_total_drawdown_pct} stale={g.stale} />
    {/if}

    <h2 class="sec">Posisi terbuka <span class="meta">{g.overview ? g.overview.open_trades.count + " dari maks " + g.overview.open_trades.max : ""}</span></h2>
    {#if g.openTrades.length}
      <table class="table" class:stale-value={g.stale}>
        <thead>
          <tr><th>Pair</th><th>Masuk</th><th class="n">Untung rugi</th></tr>
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
      <p class="note">Tidak ada posisi terbuka. Bot membuka posisi saat sinyal strategi muncul dan batas risiko mengizinkan.</p>
    {/if}

    <h2 class="sec">Order menunggu terisi <span class="meta">dari feed sejak tersambung</span></h2>
    {#if g.pending.length}
      <dl class="rows">
        {#each g.pending as o (o.trade_id)}
          <div><dt>{o.side === "beli" ? "Beli" : "Jual"} {o.pair} · #{o.trade_id}</dt><dd class="num">{price(o.price)} · {clock(o.ts, true)}</dd></div>
        {/each}
      </dl>
    {:else}
      <p class="note">Tidak ada order yang menunggu. Order limit biasanya terisi dalam hitungan detik.</p>
    {/if}

    {#if g.overview && g.risk}
      <h2 class="sec">Saldo <span class="meta">{g.overview.balance.note === "Simulated balances" ? "saldo simulasi dry-run" : ""}</span></h2>
      <dl class="rows" class:stale-value={g.stale}>
        <div><dt>Ekuitas sekarang</dt><dd class="num">{rupiah(g.risk.equity)}</dd></div>
        <div><dt>Modal awal</dt><dd class="num">{rupiah(g.overview.capital.initial_idr)}</dd></div>
        <div><dt>Hasil trade ditutup</dt><dd><Outcome value={g.overview.profit.abs} unit="idr" /></dd></div>
        <div><dt>Trade ditutup</dt><dd class="num">{g.overview.profit.trades_closed} · menang {Math.round(g.overview.profit.winrate * 100)}%</dd></div>
      </dl>
    {/if}
  </div>

  <aside class="side" aria-label="Ringkasan lain">
    <h2 class="sec">Keputusan swarm terakhir <span class="meta">{latest ? latest.pair + " " + clock(latest.ts) : ""}</span></h2>
    {#if latest}
      <dl class="rows">
        <div><dt>Hasil</dt><dd>{latest.status === "skip" && latest.reason === "quorum_not_met" ? "kuorum gagal, dilewati" : latest.verdict}{latest.mode === "shadow" ? " (bayangan)" : ""}</dd></div>
        <div><dt>Kuorum</dt><dd class="num">{latest.answered} dari {latest.voters.length} (min {latest.required})</dd></div>
        {#if latest.aggregate?.questions.action}
          <div><dt>Median · sebaran</dt><dd class="num">{decimal(latest.aggregate.questions.action.median_probabilities?.izinkan ?? 0)} · {decimal(latest.aggregate.questions.action.spread.iqr)}</dd></div>
        {/if}
      </dl>
      <p class="note"><a class="tap" href="#swarm">Lihat jawaban tiap voter</a></p>
    {/if}

    <h2 class="sec">Kesehatan</h2>
    {#if g.health}
      <dl class="rows">
        <div><dt>Loop bot</dt><dd>{g.health.freqtrade.state === "running" ? "berjalan" : "berhenti"}</dd></div>
        <div><dt>Heartbeat</dt><dd class="num">{age(heartbeat)}</dd></div>
        <div><dt>Indodax</dt><dd class="num">{g.health.exchange.reachable ? "terjangkau · " + decimal((g.health.exchange.latency_ms ?? 0) / 1000, 1) + " dtk" : "tidak terjangkau"}</dd></div>
      </dl>
    {/if}

    <h2 class="sec">Aksi terakhir <span class="meta"><a class="tap" href="#aksi">semua</a></span></h2>
    <ul class="mini-feed">
      {#each g.feed.slice(0, 5) as item (item.seq)}
        <li class:warn={item.warn}><time class="num">{clock(item.ts)}</time><span>{item.text}</span></li>
      {:else}
        <li class="muted">Belum ada aksi sejak tersambung.</li>
      {/each}
    </ul>
    {#if g.closedTrades[0]}
      <p class="note">Trade terakhir ditutup: {g.closedTrades[0].pair}, {exitReason(g.closedTrades[0].exit_reason)}.</p>
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
