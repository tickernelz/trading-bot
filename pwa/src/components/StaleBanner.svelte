<script lang="ts">
  import { gateway } from "../lib/gateway.svelte";
  import { age, clock, dayClock } from "../lib/format";
  import { t } from "../lib/i18n";

  const g = gateway;
  const retryIn = $derived(g.link.retryAt === null ? null : Math.max(0, Math.ceil((g.link.retryAt - g.now) / 1000)));
  const fault = $derived(g.upstreamFault ?? g.coreFault);
  const savedOnly = $derived(g.viewingSaved && !g.token);
  const show = $derived(
    savedOnly || g.link.state === "waiting" || g.link.state === "offline" || fault !== null || (g.stale && g.link.state !== "connecting"),
  );
</script>

{#if show}
  <div class="banner" role="status">
    <p>
      {#if savedOnly}
        {t("banner.saved_only", { at: dayClock(g.savedAt ?? 0) })}
      {:else if g.link.state === "offline"}
        {t("banner.offline")}
      {:else if g.link.state === "waiting"}
        {g.link.closedAt ? t("banner.link_lost_since", { at: clock(g.link.closedAt) }) : t("banner.link_lost")}
      {:else if g.upstreamFault}
        {t("banner.upstream", { at: clock(g.upstreamFault.at), message: g.upstreamFault.message, code: g.upstreamFault.code })}
      {:else if g.coreFault}
        {t("banner.core", { at: clock(g.coreFault.at), message: g.coreFault.message, code: g.coreFault.code })}
      {:else}
        {t("banner.no_data_for", { span: age(g.dataAge, false) })}
      {/if}
      {#if g.lastDataAt}
        {t("banner.numbers_from", { at: clock(g.lastDataAt, true) })}
      {:else}
        {t("banner.no_data")}
      {/if}
      {#if g.viewingSaved}
        <b>{t("banner.read_only")}</b>
      {/if}
    </p>
    <p class="retry">
      {#if savedOnly}
        <button class="btn secondary" type="button" onclick={() => gateway.closeSaved()}>{t("banner.sign_in")}</button>
      {:else if g.link.state === "waiting" && retryIn !== null}
        {t("banner.retry_in", { s: retryIn, n: g.link.attempts })}
      {:else if g.link.state === "offline"}
        {t("banner.auto_reconnect")}
      {/if}
      {#if g.link.state === "waiting" && !savedOnly}
        <button class="btn secondary" type="button" onclick={() => gateway.reconnect()}>{t("banner.try_now")}</button>
      {/if}
    </p>
  </div>
{/if}

<style>
  .banner {
    padding: var(--space-3) var(--space-4);
    background: var(--panel);
    border-bottom: 2px solid var(--sig);
    font-size: var(--step-0);
  }
  p {
    margin: 0;
  }
  .retry {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: var(--space-2) var(--space-3);
    margin-top: var(--space-2);
    color: var(--ink2);
    font-size: var(--step--1);
  }
</style>
