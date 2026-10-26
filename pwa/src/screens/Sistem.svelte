<script lang="ts">
  import LangSwitch from "../components/LangSwitch.svelte";
  import Notifications from "../components/Notifications.svelte";
  import { gateway } from "../lib/gateway.svelte";
  import { age, clock, decimal, duration } from "../lib/format";
  import { statusWord } from "../lib/feedText";
  import { t, type Key } from "../lib/i18n";

  const g = gateway;
  const heartbeat = $derived(g.health?.freqtrade.last_process ? g.now - Date.parse(g.health.freqtrade.last_process) : Number.NaN);
  const providers = $derived.by(() => {
    const seen = new Map<string, { status: string; latency: number; ts: string }>();
    for (const d of g.decisions) {
      for (const v of d.voters) {
        if (!seen.has(v.provider)) seen.set(v.provider, { status: v.status, latency: v.latency_s, ts: d.ts });
      }
    }
    return [...seen.entries()];
  });
  const cpu = $derived(g.sysinfo ? g.sysinfo.cpu_pct.reduce((a, b) => a + b, 0) / Math.max(1, g.sysinfo.cpu_pct.length) : null);
  const version = __APP_VERSION__;
  const PANEL_LABEL: Record<string, Key> = {
    open: "panel.open",
    closed: "panel.closed",
    equityDay: "panel.equity_day",
    equityWeek: "panel.equity_week",
    decisions: "panel.decisions",
    sysinfo: "panel.sysinfo",
    logs: "panel.logs",
    candles: "panel.candles",
    news: "panel.news",
    sentiment: "panel.sentiment",
    history: "panel.history",
  };
  const panelFaults = $derived(Object.entries(g.panelFaults));
</script>

<h2 class="sec first">{t("ringkas.health")} <span class="meta">{g.health ? t("sistem.from_gateway", { at: clock(g.lastDataAt ?? g.now, true) }) : ""}</span></h2>
{#if g.health}
  <dl class="rows" class:stale-value={g.stale}>
    <div><dt>Bot (Freqtrade {g.health.freqtrade.version})</dt><dd class:warn-text={g.health.freqtrade.state !== "running"}>{statusWord(g.health.freqtrade.state)}</dd></div>
    <div><dt>{t("sistem.heartbeat")}</dt><dd class="num" class:warn-text={heartbeat > 180000}>{age(heartbeat)}</dd></div>
    <div><dt>{t("sistem.running_since")}</dt><dd class="num">{g.health.freqtrade.bot_start ? clock(g.health.freqtrade.bot_start) + " · " + duration(g.now - Date.parse(g.health.freqtrade.bot_start)) : "-"}</dd></div>
    <div><dt>Gateway {g.health.gateway.version}</dt><dd class="num">{g.health.gateway.status === "ok" ? t("sistem.normal") : g.health.gateway.status} · {t("sistem.up_for", { span: duration(g.health.gateway.uptime_s * 1000) })}</dd></div>
    <div><dt>Feed WebSocket</dt><dd class="num" class:warn-text={g.link.state !== "open"}>{g.link.state === "open" ? t("sistem.ws_open", { seq: g.lastSeq ?? 0 }) : t("sistem.ws_down")}</dd></div>
    <div><dt>{t("sistem.exchange", { name: g.health.exchange.name })}</dt><dd class="num" class:warn-text={!g.health.exchange.reachable}>{g.health.exchange.reachable ? t("ringkas.reachable", { s: decimal((g.health.exchange.latency_ms ?? 0) / 1000, 1) }) : t("ringkas.unreachable")}</dd></div>
    {#if g.sysinfo && cpu !== null}
      <div><dt>{t("sistem.load")}</dt><dd class="num">CPU {decimal(cpu, 0)}% · RAM {decimal(g.sysinfo.ram_pct, 0)}%</dd></div>
    {/if}
  </dl>
{:else}
  <p class="note">{t("sistem.waiting_health")}</p>
{/if}

{#if panelFaults.length}
  <h2 class="sec">{t("sistem.failed_data")}</h2>
  <dl class="rows">
    {#each panelFaults as [name, f] (name)}
      <div><dt>{PANEL_LABEL[name] ? t(PANEL_LABEL[name]) : name}</dt><dd class="warn-text">{f!.code} · {clock(f!.at)}</dd></div>
    {/each}
  </dl>
  <p class="note">{t("sistem.failed_note")}</p>
{/if}

<h2 class="sec">{t("sistem.providers")} <span class="meta">{t("sistem.providers_meta")}</span></h2>
{#if providers.length}
  <dl class="rows">
    {#each providers as [name, p] (name)}
      <div><dt>{name}</dt><dd class="num" class:warn-text={p.status !== "ok"}>{p.status === "ok" ? t("sistem.answered", { s: decimal(p.latency, 1) }) : p.status === "timeout" ? t("voter.timeout") : t("voter.failed")}</dd></div>
    {/each}
  </dl>
{:else}
  <p class="note">{t("sistem.no_providers")}</p>
{/if}

<h2 class="sec">{t("sistem.logs")}</h2>
<ol class="logs">
  {#each g.logs.slice(0, 6) as l, i (i)}
    <li class:warn={l.level === "WARNING" || l.level === "ERROR"}><span class="num muted">{clock(l.ts)}</span> <span class="lvl">{l.level}</span> {l.message}</li>
  {:else}
    <li class="muted">{t("sistem.no_logs")}</li>
  {/each}
</ol>

<Notifications />

<h2 class="sec">{t("lang.label")} <span class="meta">{t("lang.meta")}</span></h2>
<div class="actions"><LangSwitch /></div>

<h2 class="sec">{t("sistem.offline_view")}</h2>
<p class="note">{g.savedAt ? t("sistem.offline_saved", { at: clock(g.savedAt, true) }) : t("sistem.offline_none")}</p>

<h2 class="sec">{t("sistem.sources")}</h2>
<dl class="rows">
  <div><dt>Gateway</dt><dd>{location.host}</dd></div>
  <div><dt>Data</dt><dd>{g.sampleData ? t("sistem.sample") : t("sistem.real")}</dd></div>
  <div><dt>{t("sistem.news")}</dt><dd><a class="tap" href="https://www.coindesk.com/" rel="noopener noreferrer" target="_blank">CoinDesk</a>, <a class="tap" href="https://cointelegraph.com/" rel="noopener noreferrer" target="_blank">Cointelegraph</a> (RSS)</dd></div>
  <div><dt>{t("sistem.sentiment")}</dt><dd><a class="tap" href="https://alternative.me/crypto/fear-and-greed-index/" rel="noopener noreferrer" target="_blank">Fear &amp; Greed Index, alternative.me</a></dd></div>
  <div><dt>{t("sistem.version")}</dt><dd>{version}</dd></div>
</dl>
<p class="note">{g.canControl ? t("sistem.scope_control") : t("sistem.scope_read")} <a class="tap" href="#kontrol">{t("nav.kontrol")}</a> · <a class="tap" href="#provider">{t("nav.provider")}</a> · <a class="tap" href="#audit">{t("nav.audit")}</a></p>
<p class="note">{t("sistem.charts_credit")} <a class="tap" href="https://www.tradingview.com/" rel="noopener" target="_blank">tradingview.com</a></p>
<div class="actions"><button class="btn secondary" type="button" onclick={() => gateway.logout()}>{t("sistem.logout")}</button></div>

<style>
  .logs {
    margin: 0;
    padding: 0 var(--space-4) var(--space-3);
    list-style: none;
    font-size: var(--step--1);
  }
  .logs li {
    padding: 4px 0;
    overflow-wrap: anywhere;
  }
  .logs .lvl {
    font-weight: 600;
  }
  .logs .warn .lvl {
    color: var(--loss);
  }
  .actions {
    padding: 0 var(--space-4) var(--space-6);
  }
  .first {
    border-top: 0;
  }
</style>
