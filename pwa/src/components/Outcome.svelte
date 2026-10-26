<script lang="ts">
  import { direction, outcomeWord, signedPercent, signedRupiah } from "../lib/format";

  let {
    value,
    unit = "pct",
    word = true,
    digits = 2,
  }: { value: number; unit?: "pct" | "idr"; word?: boolean; digits?: 1 | 2 } = $props();

  const rounded = $derived(unit === "idr" ? Math.round(value) : Number(value.toFixed(digits)));
  const dir = $derived(direction(rounded));
  const text = $derived(unit === "idr" ? signedRupiah(value) : signedPercent(value, digits));
</script>

<span class="outcome {dir} num"><span class="arrow" aria-hidden="true"></span>{text}{#if word}&nbsp;{outcomeWord(rounded)}{/if}</span>

<style>
  .outcome {
    display: inline-flex;
    align-items: baseline;
    gap: 4px;
    font-weight: 600;
  }
  .up {
    color: var(--gain);
  }
  .down {
    color: var(--loss);
  }
  .flat {
    color: var(--ink2);
  }
  .arrow {
    display: inline-block;
    width: 0.55em;
    height: 0.55em;
    background: currentColor;
  }
  .up .arrow {
    clip-path: polygon(50% 0, 100% 100%, 0 100%);
  }
  .down .arrow {
    clip-path: polygon(0 0, 100% 0, 50% 100%);
  }
  .flat .arrow {
    height: 2px;
    align-self: center;
  }
</style>
