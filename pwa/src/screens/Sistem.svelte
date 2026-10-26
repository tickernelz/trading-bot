<script lang="ts">
  import Notifications from "../components/Notifications.svelte";
  import { gateway } from "../lib/gateway.svelte";
  import { age, clock, decimal, duration } from "../lib/format";
  import { statusWord } from "../lib/feedText";

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
  const PANEL_LABEL: Record<string, string> = {
    open: "posisi terbuka",
    closed: "trade ditutup",
    equityDay: "jejak hari ini",
    equityWeek: "ekuitas Bot A dan B",
    decisions: "keputusan swarm",
    sysinfo: "beban PC",
    logs: "log bot",
    candles: "kandel",
  };
  const panelFaults = $derived(Object.entries(g.panelFaults));
</script>

<h2 class="sec first">Kesehatan <span class="meta">{g.health ? "dari gateway " + clock(g.lastDataAt ?? g.now, true) : ""}</span></h2>
{#if g.health}
  <dl class="rows" class:stale-value={g.stale}>
    <div><dt>Bot (Freqtrade {g.health.freqtrade.version})</dt><dd class:warn-text={g.health.freqtrade.state !== "running"}>{statusWord(g.health.freqtrade.state)}</dd></div>
    <div><dt>Heartbeat bot</dt><dd class="num" class:warn-text={heartbeat > 180000}>{age(heartbeat)}</dd></div>
    <div><dt>Bot berjalan sejak</dt><dd class="num">{g.health.freqtrade.bot_start ? clock(g.health.freqtrade.bot_start) + " · " + duration(g.now - Date.parse(g.health.freqtrade.bot_start)) : "-"}</dd></div>
    <div><dt>Gateway {g.health.gateway.version}</dt><dd class="num">{g.health.gateway.status === "ok" ? "normal" : g.health.gateway.status} · aktif {duration(g.health.gateway.uptime_s * 1000)}</dd></div>
    <div><dt>Feed WebSocket</dt><dd class="num" class:warn-text={g.link.state !== "open"}>{g.link.state === "open" ? "tersambung · seq " + (g.lastSeq ?? 0) : "terputus"}</dd></div>
    <div><dt>Bursa {g.health.exchange.name}</dt><dd class="num" class:warn-text={!g.health.exchange.reachable}>{g.health.exchange.reachable ? "terjangkau · " + decimal((g.health.exchange.latency_ms ?? 0) / 1000, 1) + " dtk" : "tidak terjangkau"}</dd></div>
    {#if g.sysinfo && cpu !== null}
      <div><dt>Beban PC</dt><dd class="num">CPU {decimal(cpu, 0)}% · RAM {decimal(g.sysinfo.ram_pct, 0)}%</dd></div>
    {/if}
  </dl>
{:else}
  <p class="note">Menunggu data kesehatan dari gateway.</p>
{/if}

{#if panelFaults.length}
  <h2 class="sec">Data yang gagal dimuat</h2>
  <dl class="rows">
    {#each panelFaults as [name, f] (name)}
      <div><dt>{PANEL_LABEL[name] ?? name}</dt><dd class="warn-text">{f!.code} · {clock(f!.at)}</dd></div>
    {/each}
  </dl>
  <p class="note">Bagian lain tetap diperbarui; bagian ini memakai data terakhir yang berhasil dimuat.</p>
{/if}

<h2 class="sec">Provider voter <span class="meta">dari keputusan swarm terakhir</span></h2>
{#if providers.length}
  <dl class="rows">
    {#each providers as [name, p] (name)}
      <div><dt>{name}</dt><dd class="num" class:warn-text={p.status !== "ok"}>{p.status === "ok" ? "menjawab · " + decimal(p.latency, 1) + " dtk" : p.status === "timeout" ? "waktu habis" : "gagal"}</dd></div>
    {/each}
  </dl>
{:else}
  <p class="note">Belum ada keputusan swarm yang mencatat provider.</p>
{/if}

<h2 class="sec">Log bot terakhir</h2>
<ol class="logs">
  {#each g.logs.slice(0, 6) as l, i (i)}
    <li class:warn={l.level === "WARNING" || l.level === "ERROR"}><span class="num muted">{clock(l.ts)}</span> <span class="lvl">{l.level}</span> {l.message}</li>
  {:else}
    <li class="muted">Belum ada log.</li>
  {/each}
</ol>

<Notifications />

<h2 class="sec">Sumber data</h2>
<dl class="rows">
  <div><dt>Gateway</dt><dd>{location.host}</dd></div>
  <div><dt>Data</dt><dd>{g.sampleData ? "contoh data dari gateway tiruan" : "bot sungguhan"}</dd></div>
  <div><dt>Versi PWA</dt><dd>{version}</dd></div>
</dl>
<p class="note">Lingkup sesi: {g.canControl ? "control (dari PC bot)" : "baca (jarak jauh)"}. <a class="tap" href="#kontrol">Kontrol</a> · <a class="tap" href="#provider">Provider dan key</a> · <a class="tap" href="#audit">Audit</a></p>
<p class="note">Grafik memakai TradingView Lightweight Charts™, hak cipta TradingView, Inc. <a class="tap" href="https://www.tradingview.com/" rel="noopener" target="_blank">tradingview.com</a></p>
<div class="actions"><button class="btn secondary" type="button" onclick={() => gateway.logout()}>Keluar dari gateway</button></div>

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
