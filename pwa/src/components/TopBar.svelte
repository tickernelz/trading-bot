<script lang="ts">
  import { gateway } from "../lib/gateway.svelte";
  import { age } from "../lib/format";

  const g = gateway;
  const linkText = $derived.by(() => {
    switch (g.link.state) {
      case "open":
        return "Tersambung";
      case "connecting":
        return "Menyambung";
      case "waiting":
      case "offline":
        return "Terputus";
      default:
        return "Belum tersambung";
    }
  });
</script>

<header class="bar">
  {#if g.mode === null}
    <span class="mode unknown" aria-label="Mode belum diketahui" title="Mode belum diketahui">Mode ?</span>
  {:else}
    <span class="mode" class:live={g.mode === "live"}>{g.mode === "live" ? "Live, dana nyata" : "Dry-run"}</span>
  {/if}
  {#if g.sampleData}
    <span class="sample">contoh data</span>
  {/if}
  <span class="sp"></span>
  <span class="link" class:down={g.link.state !== "open"}>
    <span class="dot" aria-hidden="true"></span>
    <span>{linkText}</span>
    <span class="age num" class:warn-text={g.stale}>{g.lastDataAt === null ? "" : age(g.dataAge)}</span>
  </span>
</header>

<style>
  .bar {
    position: sticky;
    top: 0;
    z-index: 20;
    display: flex;
    align-items: center;
    gap: var(--space-2);
    min-height: var(--bar-h);
    padding: env(safe-area-inset-top) var(--space-4) 0;
    background: var(--bg);
    border-bottom: 1px solid var(--rule);
    font-size: var(--step--1);
  }
  .mode,
  .sample {
    white-space: nowrap;
  }
  .mode {
    padding: 3px 8px;
    border-radius: 4px;
    background: var(--ink);
    color: var(--onink);
    font-weight: 600;
  }
  .mode.unknown {
    background: transparent;
    color: var(--ink);
    box-shadow: inset 0 0 0 1px var(--ink2);
  }
  .mode.live {
    background: var(--sig);
    color: var(--onsig);
  }
  .sample {
    padding: 2px 7px;
    border-radius: 4px;
    box-shadow: inset 0 0 0 1px var(--ink2);
    color: var(--ink);
  }
  .sp {
    flex: 1;
  }
  .link {
    display: inline-flex;
    align-items: center;
    gap: 6px;
    color: var(--ink2);
  }
  .link > span:nth-child(2) {
    color: var(--ink);
    font-weight: 600;
  }
  .dot {
    width: 9px;
    height: 9px;
    border-radius: 50%;
    background: var(--ink);
  }
  .down .dot {
    background: transparent;
    box-shadow: inset 0 0 0 2px var(--loss);
  }
  .down > span:nth-child(2) {
    color: var(--loss);
  }
</style>
