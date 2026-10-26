<script lang="ts">
  import NewsList from "../components/NewsList.svelte";
  import Outcome from "../components/Outcome.svelte";
  import TimeMachine from "../components/TimeMachine.svelte";
  import { gateway } from "../lib/gateway.svelte";
  import { clock, dayClock, parseTs, price, rupiah } from "../lib/format";
  import { t } from "../lib/i18n";
  import { clampStep, timeline } from "../lib/timeMachine";
  import { fearGreedText } from "../lib/words";

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
  let showNews = $state(false);
  let showSentiment = $state(false);
  let machine = $state(false);
  let step = $state<number | null>(null);

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

  const pairView = $derived(selected && selected !== AB ? selected : null);
  const asset = $derived(pairView?.split("/")[0] ?? "");
  $effect(() => {
    if (showNews && pairView && !g.viewingSaved) void g.loadNews(pairView);
  });
  $effect(() => {
    if (showSentiment && !g.viewingSaved) void g.loadSentiment();
  });
  $effect(() => {
    if (machine && pairView && !g.viewingSaved) void g.loadHistory(pairView);
  });
  const firstMs = $derived(frame?.data.length ? parseTs(String(frame.data[0][0])) : null);
  const tl = $derived(timeline(pairView ? (g.history[pairView] ?? []) : [], firstMs));
  const index = $derived(clampStep(step ?? tl.steps.length - 1, tl.steps.length));
  const focus = $derived(machine && tl.steps.length ? tl.steps[index] : null);
  const pairNews = $derived(pairView ? g.news[pairView] : undefined);
  const latestMood = $derived(g.sentiment?.points.at(-1) ?? null);

  function pick(p: string) {
    view = p;
    step = null;
  }

  function closeMachine() {
    machine = false;
    step = null;
  }
</script>

<div class="chips" role="tablist" aria-label={t("grafik.pick")}>
  {#each [...pairs, AB] as p (p)}
    <button class="chip" type="button" role="tab" aria-selected={selected === p} onclick={() => pick(p)}>{p === AB ? t("grafik.ab") : p}</button>
  {/each}
</div>

{#if selected === AB}
  <h2 class="sec">{t("grafik.ab_title")} <span class="meta">{t("grafik.ab_meta")}</span></h2>
  {#if ab}
    {#await charts}
      <div class="pad"><span class="skeleton" style="height:260px"></span></div>
    {:then [, Equity]}
      <Equity.default equity={ab} />
    {:catch}
      <p class="note warn-text">{t("grafik.module_failed")}</p>
    {/await}
    <ul class="legend">
      <li><span class="key dashed" aria-hidden="true"></span>{t("grafik.bot_a")}</li>
      <li><span class="key solid" aria-hidden="true"></span>{t("grafik.bot_b")}</li>
    </ul>
    <table class="table">
      <thead><tr><th>Bot</th><th class="n">{t("grafik.equity")}</th><th class="n">{t("grafik.days7")}</th></tr></thead>
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
      <p class="note">{t("grafik.diff")} <Outcome value={finals[1].end - finals[0].end} unit="idr" word={false} />. {t("grafik.diff_note")}</p>
    {/if}
  {:else if g.panelFaults.equityWeek}
    <p class="note warn-text">{t("grafik.ab_failed", { code: g.panelFaults.equityWeek.code })}</p>
  {:else}
    <div class="pad"><span class="skeleton" style="height:260px"></span></div>
  {/if}
{:else if selected}
  <div class="head">
    <div>
      <h2>{selected}</h2>
      <p class="muted small">{t("grafik.candles_meta", { n: frame?.data.length ?? 0 })}</p>
    </div>
    {#if lastRow}
      <div class="price">
        <span class="num big">{price(Number(lastRow[4]))}</span>
        {#if change !== null}<span class="small"><Outcome value={change} word={false} /> {t("grafik.h24")}</span>{/if}
      </div>
    {/if}
  </div>
  {#if machine}
    {#if g.history[selected]}
      <TimeMachine steps={tl.steps} {index} older={tl.older} onstep={(i) => (step = i)} onclose={closeMachine} />
    {:else if g.panelFaults.history}
      <p class="note warn-text">{t("tm.load_failed", { code: g.panelFaults.history.code })}</p>
    {:else if g.viewingSaved}
      <p class="note">{t("tm.offline")}</p>
    {:else}
      <div class="pad"><span class="skeleton" style="height:120px"></span></div>
    {/if}
  {:else}
    <div class="tm-open">
      <button class="btn secondary" type="button" onclick={() => (machine = true)}>{t("tm.open")}</button>
      <span class="muted small">{t("tm.hint")}</span>
    </div>
  {/if}
  {#if frame}
    {#await charts}
      <div class="pad"><span class="skeleton" style="height:340px"></span></div>
    {:then [Candle]}
      <Candle.default
        {frame}
        trades={pairTrades}
        {showFast}
        {showSlow}
        {showRsi}
        {showMarkers}
        news={pairNews?.items ?? []}
        {showNews}
        sentiment={g.sentiment?.points ?? []}
        {showSentiment}
        {focus}
      />
    {:catch}
      <p class="note warn-text">{t("grafik.module_failed")}</p>
    {/await}
    <p class="note age">
      {t("grafik.last_candle", { at: lastRow ? dayClock(String(lastRow[0])) : "-" })}{frame.last_analyzed ? " · " + t("grafik.analyzed", { at: clock(frame.last_analyzed) }) : ""}. {t("grafik.next_candle")}
    </p>
  {:else if g.panelFaults.candles}
    <p class="note warn-text">{t("grafik.candles_failed", { code: g.panelFaults.candles.code })}</p>
  {:else}
    <div class="pad"><span class="skeleton" style="height:340px"></span></div>
  {/if}
  <h2 class="sec">{t("grafik.layers")}</h2>
  <div class="toggles">
    <label><input type="checkbox" bind:checked={showMarkers} /> {t("grafik.markers")}</label>
    <label><input type="checkbox" bind:checked={showFast} /> {t("grafik.ema_fast")}</label>
    <label><input type="checkbox" bind:checked={showSlow} /> {t("grafik.ema_slow")}</label>
    <label><input type="checkbox" bind:checked={showRsi} /> {t("grafik.rsi")}</label>
    <label><input type="checkbox" bind:checked={showNews} /> {t("layer.news")}</label>
    <label><input type="checkbox" bind:checked={showSentiment} /> {t("layer.sentiment")}</label>
  </div>
  {#if showSentiment}
    <h2 class="sec">{t("fng.title")} <span class="meta">{t("fng.meta")}</span></h2>
    {#if g.sentiment && !g.sentiment.enabled}
      <p class="note">{t("fng.disabled")}</p>
    {:else if g.sentiment}
      {#if latestMood}
        <p class="note mood"><span class="num big">{latestMood.value}</span> {fearGreedText(latestMood.classification)} · {dayClock(latestMood.date + "T00:00:00Z")}</p>
      {/if}
      <p class="note small">
        {t("fng.source", { name: g.sentiment.source.name, provider: g.sentiment.source.provider })}
        <a href={g.sentiment.source.url} target="_blank" rel="noopener noreferrer">{g.sentiment.source.url.replace("https://", "")}</a>{#if g.sentiment.source.ok === false}<span class="warn-text"> ({t("news.source_failed", { error: g.sentiment.source.error ?? "-" })})</span>{/if}. {t("fng.scale")}
      </p>
    {:else if g.panelFaults.sentiment}
      <p class="note warn-text">{t("fng.load_failed", { code: g.panelFaults.sentiment.code })}</p>
    {:else}
      <div class="pad"><span class="skeleton" style="height:48px"></span></div>
    {/if}
  {/if}
  {#if showNews}
    <h2 class="sec">{t("news.title", { asset })} <span class="meta">{t("news.meta")}</span></h2>
    {#if pairNews}
      <NewsList news={pairNews} {asset} />
    {:else if g.panelFaults.news}
      <p class="note warn-text">{t("news.load_failed", { code: g.panelFaults.news.code })}</p>
    {:else if g.viewingSaved}
      <p class="note">{t("news.offline")}</p>
    {:else}
      <div class="pad"><span class="skeleton" style="height:120px"></span></div>
    {/if}
  {/if}
  {#if showNews || showSentiment}
    <p class="note">{t("layer.display_only")}</p>
  {/if}
  <p class="note">{t("grafik.legend")}</p>
{/if}

<style>
  .tm-open {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: var(--space-2) var(--space-3);
    padding: 0 var(--space-4) var(--space-2);
  }
  .mood .big {
    font-size: var(--step-2);
    font-weight: 600;
  }
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
