<script lang="ts">
  import { gateway } from "../lib/gateway.svelte";
  import { age, clock, MINUS, percent } from "../lib/format";

  const g = gateway;
  const word = $derived(
    g.safety === "aman" ? "Aman" : g.safety === "ditahan" ? "Ditahan" : g.safety === "berhenti" ? "Berhenti" : g.coreFault ? "Tidak diketahui" : "",
  );
  const sentence = $derived.by(() => {
    const risk = g.risk;
    if (!risk || !g.safety) return "";
    const loss = percent(risk.daily_loss_pct);
    const limit = percent(risk.limits.max_daily_loss_pct, 1);
    if (g.safety === "berhenti") {
      return "Bot tidak memproses entry atau exit. " + g.openTrades.length + " posisi terbuka tetap tercatat; stop loss hanya jalan saat bot berjalan.";
    }
    if (g.safety === "ditahan") {
      if (risk.breaches.includes("total_drawdown")) return "Rugi total " + percent(risk.drawdown_pct) + " menyentuh batas " + percent(risk.limits.max_total_drawdown_pct, 1) + ". Entry baru ditahan sampai batas diubah.";
      return "Rugi hari ini " + MINUS + loss + " menyentuh batas " + limit + ". Entry baru ditahan sampai besok; posisi terbuka tetap dijaga stop loss.";
    }
    if (risk.daily_pnl >= 0) return "Belum ada rugi hari ini. Batas rugi harian " + limit + ". Entry baru boleh dibuka.";
    return "Rugi hari ini " + MINUS + loss + " dari batas " + limit + ". Entry baru boleh dibuka.";
  });
</script>

<section class="board {g.safety ?? (g.coreFault ? 'unknown' : 'loading')}" class:stale={g.stale && g.safety !== null} aria-label="Keadaan bot">
  <p class="sr-only" aria-live="assertive">{word ? "Keadaan bot: " + word : ""}</p>
  {#if g.safety}
    <div class="w" aria-hidden="true">{word}</div>
    <p class="s">{sentence}</p>
    {#if g.stale}
      <p class="basi">Keadaan terakhir yang diketahui, dari {g.lastDataAt ? clock(g.lastDataAt) : "-"} ({age(g.dataAge)}). Bisa sudah berubah.</p>
    {/if}
  {:else if g.coreFault}
    <div class="w">Tidak diketahui</div>
    <p class="s">Keadaan bot belum bisa dimuat dari gateway. Jangan anggap aman sampai papan ini menampilkan keadaan.</p>
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
