<script lang="ts">
  import { percent } from "../lib/format";
  import { t } from "../lib/i18n";

  let { name, value, limit, stale = false }: { name: string; value: number; limit: number; stale?: boolean } = $props();

  const ratio = $derived(limit > 0 ? Math.min(1, Math.max(0, value / limit)) : 0);
  const hot = $derived(ratio >= 0.8);
  const left = $derived(Math.max(0, limit - value));
  const reached = $derived(value >= limit);
</script>

<div class="meter" class:stale>
  <div class="head">
    <span>{name}</span>
    <span class="num"><b class:warn-text={hot && !stale}>{percent(value)}</b> {t("meter.of_limit", { limit: percent(limit, 1) })}</span>
  </div>
  <div
    class="track"
    role="meter"
    aria-label={name}
    aria-valuemin={0}
    aria-valuemax={limit}
    aria-valuenow={value}
    aria-valuetext={percent(value) + " " + t("meter.of_limit", { limit: percent(limit, 1) })}
  >
    <i class:hot style="inline-size:{ratio * 100}%"></i>
  </div>
  <div class="foot num">
    {#if reached}
      {t("meter.reached")}
    {:else}
      {t(hot ? "meter.only_left" : "meter.left", { left: percent(left) })}
    {/if}
  </div>
</div>

<style>
  .meter {
    padding: var(--space-2) var(--space-4) var(--space-3);
  }
  .head {
    display: flex;
    justify-content: space-between;
    gap: var(--space-3);
    font-size: var(--step-0);
  }
  .head > span:first-child {
    color: var(--ink2);
  }
  .track {
    position: relative;
    height: 10px;
    margin-top: 6px;
    background: var(--panel);
    box-shadow: inset 0 0 0 1px var(--rule);
  }
  .track i {
    position: absolute;
    inset-block: 0;
    inset-inline-start: 0;
    background: var(--ink2);
    transition: inline-size var(--t) var(--ease);
  }
  .track i.hot {
    background: var(--sig);
  }
  .stale .track i {
    background: var(--rule-strong);
  }
  .foot {
    margin-top: 4px;
    font-size: var(--step--1);
    color: var(--ink2);
  }
</style>
