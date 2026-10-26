<script lang="ts">
  import { clock, dayClock } from "../lib/format";
  import { t } from "../lib/i18n";
  import type { News } from "../lib/types";

  let { news, asset, limit = 8 }: { news: News; asset: string; limit?: number } = $props();

  const names = $derived(Object.fromEntries(news.sources.map((s) => [s.id, s.name])));
  const shown = $derived(news.items.slice(0, limit));
</script>

{#if !news.enabled}
  <p class="note">{t("news.disabled")}</p>
{:else}
  {#if shown.length}
    <ul class="news" aria-label={t("news.list_label", { asset })}>
      {#each shown as item (item.id)}
        <li>
          <span class="num muted">{dayClock(item.published)}</span>
          <span class="src">{names[item.source] ?? item.source}</span>
          <a href={item.url} target="_blank" rel="noopener noreferrer">{item.title}</a>
        </li>
      {/each}
    </ul>
  {:else}
    <p class="note">{t("news.none", { asset })}</p>
  {/if}
  <p class="note small">
    {t("news.source_line")}
    {#each news.sources as s, i (s.id)}{i ? ", " : " "}<a href={s.url} target="_blank" rel="noopener noreferrer">{s.name}</a>{#if s.ok}{s.fetched_at ? " (" + t("news.fetched", { at: clock(s.fetched_at) }) + ")" : ""}{:else}<span class="warn-text"> ({t("news.source_failed", { error: s.error ?? "-" })}{s.fetched_at ? "; " + t("news.kept_from", { at: clock(s.fetched_at) }) : ""})</span>{/if}{/each}.
  </p>
{/if}

<style>
  .news {
    margin: 0;
    padding: 0 var(--space-4);
    list-style: none;
  }
  .news li {
    display: grid;
    grid-template-columns: auto auto 1fr;
    gap: var(--space-1) var(--space-3);
    align-items: baseline;
    padding: var(--space-2) 0;
    border-top: 1px solid var(--rule);
    font-size: var(--step-0);
  }
  .news li:first-child {
    border-top: 0;
  }
  .src {
    font-size: var(--step--1);
    color: var(--ink2);
  }
  .small {
    font-size: var(--step--1);
  }
  @media (max-width: 520px) {
    .news li {
      grid-template-columns: auto 1fr;
    }
    .news a {
      grid-column: 1 / -1;
    }
  }
</style>
