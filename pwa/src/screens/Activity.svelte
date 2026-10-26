<script lang="ts">
  import Outcome from "../components/Outcome.svelte";
  import { gateway } from "../lib/gateway.svelte";
  import { clock } from "../lib/format";
  import { FEED_KINDS, type FeedKind } from "../lib/feedText";
  import { t } from "../lib/i18n";

  const g = gateway;
  const FILTERS: ("all" | FeedKind)[] = ["all", "order", "swarm", "risk", "system"];
  let filter = $state<"all" | FeedKind>("all");
  const items = $derived(filter === "all" ? g.feed : g.feed.filter((i) => i.kind === filter));
  const filterLabel = (f: "all" | FeedKind) => (f === "all" ? t("activity.all") : t(FEED_KINDS[f]));
</script>

<div class="chips" role="group" aria-label={t("activity.filter")}>
  {#each FILTERS as f (f)}
    <button class="chip" type="button" aria-pressed={filter === f} onclick={() => (filter = f)}>{filterLabel(f)}</button>
  {/each}
</div>

<h2 class="sec">{t("activity.title")} <span class="meta">{t("activity.meta", { n: g.feed.length })}</span></h2>
<ol class="feed" role="log" aria-label={t("activity.title")}>
  {#each items as item (item.seq)}
    <li class:warn={item.warn}>
      <time class="num" datetime={item.ts}>{clock(item.ts, true)}</time>
      <span class="kind">{item.warn ? t("activity.warning") : t(FEED_KINDS[item.kind])}</span>
      <span class="text">
        {item.text}
        {#if item.outcome !== undefined}<span class="sr-only"><Outcome value={item.outcome} /></span>{/if}
      </span>
    </li>
  {:else}
    <li class="empty">
      {#if g.link.state === "open"}
        {filter === "all" ? t("activity.empty") : t("activity.empty_kind", { kind: filterLabel(filter) })}
      {:else}
        {t("activity.not_connected")}
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
