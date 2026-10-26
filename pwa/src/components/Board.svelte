<script lang="ts">
  import { gateway } from "../lib/gateway.svelte";
  import { age, clock, MINUS, percent } from "../lib/format";
  import { t } from "../lib/i18n";

  const g = gateway;
  const word = $derived(
    g.safety === "aman"
      ? t("board.safe")
      : g.safety === "ditahan"
        ? t("board.held")
        : g.safety === "berhenti"
          ? t("board.stopped")
          : g.coreFault
            ? t("board.unknown")
            : "",
  );
  const sentence = $derived.by(() => {
    const risk = g.risk;
    if (!risk || !g.safety) return "";
    const loss = percent(risk.daily_loss_pct);
    const limit = percent(risk.limits.max_daily_loss_pct, 1);
    if (g.safety === "berhenti") {
      return t("board.s_stopped", { n: g.openTrades.length });
    }
    if (g.safety === "ditahan") {
      if (risk.breaches.includes("total_drawdown"))
        return t("board.s_drawdown", { loss: percent(risk.drawdown_pct), limit: percent(risk.limits.max_total_drawdown_pct, 1) });
      return t("board.s_daily_hit", { loss: MINUS + loss, limit });
    }
    if (risk.daily_pnl >= 0) return t("board.s_no_loss", { limit });
    return t("board.s_loss", { loss: MINUS + loss, limit });
  });
</script>

<section class="board {g.safety ?? (g.coreFault ? 'unknown' : 'loading')}" class:stale={g.stale && g.safety !== null} aria-label={t("board.label")}>
  <p class="sr-only" aria-live="assertive">{word ? t("board.live", { word }) : ""}</p>
  {#if g.safety}
    <div class="w" aria-hidden="true">{word}</div>
    <p class="s">{sentence}</p>
    {#if g.stale}
      <p class="basi">{t("board.stale", { at: g.lastDataAt ? clock(g.lastDataAt) : "-", age: age(g.dataAge) })}</p>
    {/if}
  {:else if g.coreFault}
    <div class="w">{t("board.unknown")}</div>
    <p class="s">{t("board.s_unknown")}</p>
  {:else}
    <span class="skeleton" style="width:40%;height:2.5rem"></span>
    <span class="skeleton" style="width:85%;margin-top:12px"></span>
  {/if}
</section>

<style>
  .board {
    padding: var(--space-4) var(--space-4) var(--space-4);
    background: var(--ink);
    color: var(--onink);
    transition: background-color var(--t) var(--ease), color var(--t) var(--ease);
  }
  .board.ditahan,
  .board.berhenti {
    background: var(--sig);
    color: var(--onsig);
  }
  .board.unknown {
    background: var(--panel);
    color: var(--ink);
    box-shadow: inset 0 0 0 2px var(--sig);
  }
  .board.loading {
    background: var(--panel);
  }
  .board.stale {
    background: var(--panel);
    color: var(--ink);
    box-shadow: inset 0 0 0 2px var(--rule-strong);
  }
  .w {
    font-size: var(--step-3);
    font-weight: 650;
    line-height: 1;
    letter-spacing: -0.02em;
  }
  .s {
    margin: var(--space-2) 0 0;
    max-width: 60ch;
    font-size: var(--step-0);
    line-height: 1.4;
  }
  .basi {
    margin: var(--space-2) 0 0;
    font-size: var(--step--1);
    font-weight: 600;
  }
</style>
