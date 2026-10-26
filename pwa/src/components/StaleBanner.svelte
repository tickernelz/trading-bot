<script lang="ts">
  import { gateway } from "../lib/gateway.svelte";
  import { age, clock } from "../lib/format";

  const g = gateway;
  const retryIn = $derived(g.link.retryAt === null ? null : Math.max(0, Math.ceil((g.link.retryAt - g.now) / 1000)));
  const fault = $derived(g.upstreamFault ?? g.coreFault);
  const show = $derived(
    g.link.state === "waiting" || g.link.state === "offline" || fault !== null || (g.stale && g.link.state !== "connecting"),
  );
</script>

{#if show}
  <div class="banner" role="status">
    <p>
      {#if g.link.state === "offline"}
        Perangkat sedang offline.
      {:else if g.link.state === "waiting"}
        Sambungan ke gateway putus{g.link.closedAt ? " sejak " + clock(g.link.closedAt) : ""}.
      {:else if g.upstreamFault}
        Gateway tersambung, tetapi bot tidak menjawab sejak {clock(g.upstreamFault.at)}: {g.upstreamFault.message} ({g.upstreamFault.code}).
      {:else if g.coreFault}
        Keadaan bot gagal dimuat pada {clock(g.coreFault.at)}: {g.coreFault.message} ({g.coreFault.code}).
      {:else}
        Tidak ada data baru selama {age(g.dataAge).replace(" lalu", "")}.
      {/if}
      {#if g.lastDataAt}
        Angka di layar ini dari {clock(g.lastDataAt, true)} dan bisa sudah basi.
      {:else}
        Belum ada data dari gateway.
      {/if}
    </p>
    <p class="retry">
      {#if g.link.state === "waiting" && retryIn !== null}
        Mencoba lagi dalam {retryIn} dtk (percobaan ke-{g.link.attempts}).
      {:else if g.link.state === "offline"}
        Menyambung lagi otomatis saat jaringan kembali.
      {/if}
      {#if g.link.state === "waiting"}
        <button class="btn secondary" type="button" onclick={() => gateway.reconnect()}>Coba sekarang</button>
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
