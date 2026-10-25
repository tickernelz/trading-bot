<script lang="ts">
  import Outcome from "../components/Outcome.svelte";
  import { gateway } from "../lib/gateway.svelte";
  import { clock, dayClock, price, rupiah } from "../lib/format";

  const g = gateway;
  const charts = Promise.all([import("../components/CandleChart.svelte"), import("../components/EquityChart.svelte")]);
  const AB = "Bot A vs B";
  const pairs = $derived(g.overview?.pairs.whitelist ?? []);
  let view = $state<string | null>(null);
  const selected = $derived(view ?? pairs[0] ?? null);
  let showFast = $state(true);
  let showSlow = $state(true);
  let showRsi = $state(false);
  let showMarkers = $state(true);

  $effect(() => {
    if (selected && selected !== AB) g.watchCandles(selected);
  });

  const frame = $derived(selected && selected !== AB ? g.candles[selected] : undefined);
  const pairTrades = $derived(selected ? [...g.openTrades, ...g.closedTrades].filter((t) => t.pair === selected) : []);
  const lastRow = $derived(frame?.data.at(-1));
  const dayAgo = $derived(frame && frame.data.length > 24 ? frame.data.at(-25) : undefined);
  const change = $derived(lastRow && dayAgo ? ((Number(lastRow[4]) - Number(dayAgo[4])) / Number(dayAgo[4])) * 100 : null);
  const ab = $derived(g.equityWeek);
  const finals = $derived(ab ? ab.series.map((s) => ({ ...s, end: s.points.at(-1)?.[1] ?? ab.start_equity })) : []);
</script>

<div class="chips" role="tablist" aria-label="Pilih grafik">
  {#each [...pairs, AB] as p (p)}
    <button class="chip" type="button" role="tab" aria-selected={selected === p} onclick={() => (view = p)}>{p}</button>
  {/each}
</div>

{#if selected === AB}
  <h2 class="sec">Bot A vs Bot B <span class="meta">ekuitas 7 hari, dry-run</span></h2>
  {#if ab}
    {#await charts}
      <div class="pad"><span class="skeleton" style="height:260px"></span></div>
    {:then [, Equity]}
      <Equity.default equity={ab} />
    {:catch}
      <p class="note warn-text">Modul grafik gagal dimuat. Muat ulang aplikasi.</p>
    {/await}
    <ul class="legend">
      <li><span class="key dashed" aria-hidden="true"></span>Bot A: aturan saja</li>
      <li><span class="key solid" aria-hidden="true"></span>Bot B: aturan + swarm bayangan</li>
    </ul>
    <table class="table">
      <thead><tr><th>Bot</th><th class="n">Ekuitas</th><th class="n">7 hari</th></tr></thead>
      <tbody>
        {#each finals as s (s.bot)}
          <tr>
            <td><b>{s.label}</b><br /><span class="muted small">{s.strategy}</span></td>
            <td class="n num">{rupiah(s.end)}</td>
            <td class="n"><Outcome value={((s.end - ab.start_equity) / ab.start_equity) * 100} /></td>
          </tr>
        {/each}
      </tbody>
    </table>
    {#if finals.length === 2}
      <p class="note">Selisih B terhadap A: <Outcome value={finals[1].end - finals[0].end} unit="idr" word={false} />. Swarm di Bot B hanya mencatat (mode bayangan); selisih ini belum bukti swarm berguna. Syarat adopsi ada di plan bagian 8.</p>
    {/if}
  {:else}
    <div class="pad"><span class="skeleton" style="height:260px"></span></div>
  {/if}
{:else if selected}
  <div class="head">
    <div>
      <h2>{selected}</h2>
      <p class="muted small">1 kandel = 1 jam · {frame?.data.length ?? 0} kandel</p>
    </div>
    {#if lastRow}
      <div class="price">
        <span class="num big">{price(Number(lastRow[4]))}</span>
        {#if change !== null}<span class="small"><Outcome value={change} word={false} /> 24 jam</span>{/if}
      </div>
    {/if}
  </div>
  {#if frame}
    {#await charts}
      <div class="pad"><span class="skeleton" style="height:340px"></span></div>
    {:then [Candle]}
      <Candle.default {frame} trades={pairTrades} {showFast} {showSlow} {showRsi} {showMarkers} />
    {:catch}
      <p class="note warn-text">Modul grafik gagal dimuat. Muat ulang aplikasi.</p>
    {/await}
    <p class="note age">
      Kandel tertutup terakhir {lastRow ? dayClock(String(lastRow[0])) : "-"}{frame.last_analyzed ? " · dianalisis " + clock(frame.last_analyzed) : ""}. Kandel baru tiba saat jam berikutnya tertutup.
    </p>
  {:else}
    <div class="pad"><span class="skeleton" style="height:340px"></span></div>
  {/if}
  <h2 class="sec">Lapisan</h2>
  <div class="toggles">
    <label><input type="checkbox" bind:checked={showMarkers} /> Penanda masuk dan keluar</label>
    <label><input type="checkbox" bind:checked={showFast} /> EMA cepat (garis penuh)</label>
    <label><input type="checkbox" bind:checked={showSlow} /> EMA lambat (garis putus)</label>
    <label><input type="checkbox" bind:checked={showRsi} /> RSI di panel bawah</label>
  </div>
  <p class="note">Kandel berongga: harga naik dalam jam itu; kandel penuh: turun. Garis putus jingga: stop loss posisi terbuka.</p>
{/if}

<style>
  .head {
    display: flex;
    align-items: flex-end;
    justify-content: space-between;
    gap: var(--space-3);
    padding: var(--space-3) var(--space-4) var(--space-2);
  }
  .head h2 {
    font-size: var(--step-2);
  }
  .head p {
    margin: 0;
  }
  .price {
    display: flex;
    flex-direction: column;
    align-items: flex-end;
  }
  .big {
    font-size: var(--step-2);
    font-weight: 600;
  }
  .small {
    font-size: var(--step--1);
  }
  .pad {
    padding: 0 var(--space-4);
  }
  .age {
    padding-top: var(--space-2);
  }
  .toggles {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(240px, 1fr));
    padding: 0 var(--space-4) var(--space-2);
  }
  .toggles label {
    display: flex;
    align-items: center;
    gap: var(--space-2);
    min-height: 44px;
    font-size: var(--step-0);
    cursor: pointer;
  }
  .toggles input {
    width: 20px;
    height: 20px;
    accent-color: var(--ink);
  }
  .legend {
    display: flex;
    flex-wrap: wrap;
    gap: var(--space-2) var(--space-5);
    margin: 0;
    padding: var(--space-2) var(--space-4);
    list-style: none;
    font-size: var(--step-0);
  }
  .legend li {
    display: flex;
    align-items: center;
    gap: var(--space-2);
  }
  .key {
    width: 28px;
    border-top: 2px solid var(--ink);
  }
  .key.dashed {
    border-top: 2px dashed var(--ink2);
  }
</style>
