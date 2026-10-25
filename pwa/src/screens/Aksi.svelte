<script lang="ts">
  import Outcome from "../components/Outcome.svelte";
  import { gateway } from "../lib/gateway.svelte";
  import { clock } from "../lib/format";
  import type { FeedKind } from "../lib/feedText";

  const g = gateway;
  const FILTERS: ("Semua" | FeedKind)[] = ["Semua", "Order", "Swarm", "Risiko", "Sistem"];
  let filter = $state<"Semua" | FeedKind>("Semua");
  const items = $derived(filter === "Semua" ? g.feed : g.feed.filter((i) => i.kind === filter));
</script>

<div class="chips" role="group" aria-label="Saring aksi">
  {#each FILTERS as f (f)}
    <button class="chip" type="button" aria-pressed={filter === f} onclick={() => (filter = f)}>{f}</button>
  {/each}
</div>

<h2 class="sec">Feed aksi <span class="meta">{g.feed.length} kejadian sejak tersambung, terbaru di atas</span></h2>
<ol class="feed" role="log" aria-label="Feed aksi">
  {#each items as item (item.seq)}
    <li class:warn={item.warn}>
      <time class="num" datetime={item.ts}>{clock(item.ts, true)}</time>
      <span class="kind">{item.warn ? "Peringatan" : item.kind}</span>
      <span class="text">
        {item.text}
        {#if item.outcome !== undefined}<span class="sr-only"><Outcome value={item.outcome} /></span>{/if}
      </span>
    </li>
  {:else}
    <li class="empty">
      {#if g.link.state === "open"}
        Belum ada aksi{filter === "Semua" ? "" : " jenis " + filter} sejak tersambung. Order, keputusan swarm, penolakan risiko, dan pesan sistem muncul di sini begitu terjadi.
      {:else}
        Feed kosong karena belum tersambung ke gateway.
      {/if}
    </li>
  {/each}
</ol>

<style>
  .feed {
    margin: 0;
    padding: 0;
    list-style: none;
  }
  .feed li {
    display: grid;
    grid-template-columns: 4.6em 6.2em 1fr;
    gap: var(--space-2);
    padding: 10px var(--space-4);
    border-top: 1px solid var(--rule);
    font-size: var(--step-0);
  }
  .feed li:first-child {
    border-top: 0;
  }
  time {
    color: var(--ink2);
  }
  .kind {
    font-weight: 600;
  }
  .warn .kind,
  .warn .text {
    color: var(--loss);
  }
  .warn .text {
    font-weight: 600;
  }
  .empty {
    display: block !important;
    color: var(--ink2);
  }
  @media (max-width: 420px) {
    .feed li {
      grid-template-columns: 4.6em 1fr;
    }
    .text {
      grid-column: 1 / -1;
    }
  }
</style>
