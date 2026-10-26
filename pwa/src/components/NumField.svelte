<script lang="ts">
  import { t } from "../lib/i18n";

  let {
    id,
    label,
    value = $bindable(),
    hint = "",
    error = null,
    was = null,
    step = "any",
    unit = "",
    disabled = false,
    optional = false,
  }: {
    id: string;
    label: string;
    value: number | null;
    hint?: string;
    error?: string | null;
    was?: string | null;
    step?: string;
    unit?: string;
    disabled?: boolean;
    optional?: boolean;
  } = $props();
</script>

<div class="field">
  <label for={id}>{label}{#if unit}<span class="muted unit">({unit})</span>{/if}</label>
  <input
    {id}
    class="input"
    type="number"
    inputmode="decimal"
    {step}
    {disabled}
    bind:value
    placeholder={optional ? t("audit.v_empty") : undefined}
    aria-invalid={error ? "true" : undefined}
    aria-describedby={id + "-h"}
  />
  <span id={id + "-h"} class="hint-group">
    {#if error}<span class="err">{error}</span>{/if}
    {#if hint}<span class="hint">{hint}</span>{/if}
    {#if was !== null}<span class="hint was">{t("cfg.was", { v: was })}</span>{/if}
  </span>
</div>

<style>
  .unit {
    margin-left: 0.3em;
    font-weight: 400;
  }
  .hint-group {
    display: grid;
    gap: 2px;
  }
  .was {
    color: var(--ink);
  }
</style>
