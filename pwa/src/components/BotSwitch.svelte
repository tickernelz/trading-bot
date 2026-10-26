<script lang="ts">
  import { gateway } from "../lib/gateway.svelte";

  let { value = $bindable(), label = "Bot" }: { value: string; label?: string } = $props();
</script>

<div class="seg" role="radiogroup" aria-label={label}>
  {#each gateway.bots as bot (bot.id)}
    <button type="button" role="radio" aria-checked={value === bot.id} onclick={() => (value = bot.id)}>
      {bot.label}{#if bot.strategy}<span class="sr-only">, {bot.strategy}</span>{/if}
    </button>
  {/each}
</div>

<style>
  .seg {
    display: inline-flex;
    padding: 2px;
    border-radius: var(--radius);
    box-shadow: inset 0 0 0 1px var(--rule-strong);
  }
  button {
    min-height: 44px;
    min-width: 72px;
    padding: 0 var(--space-3);
    border: 0;
    border-radius: 4px;
    background: transparent;
    color: var(--ink2);
    cursor: pointer;
    transition: background-color var(--t) var(--ease), color var(--t) var(--ease);
  }
  button:hover {
    color: var(--ink);
  }
  button:active {
    background: var(--panel);
  }
  button[aria-checked="true"] {
    background: var(--ink);
    color: var(--onink);
    font-weight: 600;
  }
</style>
