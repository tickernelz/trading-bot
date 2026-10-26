<script lang="ts">
  import { secondsLeft } from "../lib/control";
  import { gateway } from "../lib/gateway.svelte";
  import type { Confirmation } from "../lib/types";

  let {
    confirmation,
    busy = false,
    onconfirm,
    oncancel,
    consequence,
  }: { confirmation: Confirmation; busy?: boolean; onconfirm: () => void; oncancel: () => void; consequence?: string } = $props();

  const left = $derived(secondsLeft(confirmation, gateway.now));
  let panel = $state<HTMLDivElement | null>(null);

  $effect(() => {
    panel?.focus();
  });
</script>

<div class="confirm" role="alertdialog" tabindex="-1" bind:this={panel} aria-labelledby={"cf-" + confirmation.id} aria-describedby={"cf-d-" + confirmation.id}>
  <p class="title" id={"cf-" + confirmation.id}>Langkah 2 dari 2: konfirmasi</p>
  <div id={"cf-d-" + confirmation.id}>
    <p class="summary">{confirmation.summary}</p>
    {#if consequence}<p class="consequence">{consequence}</p>{/if}
    <p class="muted small num" aria-live="off">{left > 0 ? "Berlaku " + left + " detik lagi. Sasaran: " + confirmation.targets.join(", ") : "Konfirmasi kedaluwarsa. Mulai lagi dari langkah 1."}</p>
  </div>
  <div class="row">
    <button class="btn" type="button" disabled={busy || left === 0} aria-busy={busy} onclick={onconfirm}>{busy ? "Menjalankan…" : "Ya, jalankan"}</button>
    <button class="btn secondary" type="button" disabled={busy} onclick={oncancel}>Batal</button>
  </div>
</div>

<style>
  .confirm {
    margin: var(--space-2) var(--space-4) var(--space-3);
    padding: var(--space-3) var(--space-4);
    border-radius: var(--radius);
    box-shadow: inset 0 0 0 2px var(--sig);
    background: var(--bg);
    animation: in var(--t) var(--ease);
  }
  p {
    margin: 0;
  }
  .confirm:focus-visible {
    outline-offset: 3px;
  }
  .title {
    font-weight: 650;
  }
  .summary {
    margin-top: var(--space-1);
  }
  .consequence {
    margin-top: var(--space-2);
    font-size: var(--step-0);
  }
  .small {
    margin-top: var(--space-2);
    font-size: var(--step--1);
  }
  .row {
    display: flex;
    flex-wrap: wrap;
    gap: var(--space-2);
    margin-top: var(--space-3);
  }
  @keyframes in {
    from {
      opacity: 0;
      transform: translateY(-4px);
    }
  }
</style>
