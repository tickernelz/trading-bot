<script lang="ts">
  import { lang, LANGS, setLang, t, type Lang } from "../lib/i18n";

  const NAMES: Record<Lang, string> = { id: "Bahasa Indonesia", en: "English" };
</script>

<div class="lang" role="group" aria-label={t("lang.label")}>
  {#each LANGS as code (code)}
    <button class="chip" type="button" lang={code} aria-pressed={lang === code} onclick={() => setLang(code)}>{NAMES[code]}</button>
  {/each}
</div>

<style>
  .lang {
    display: flex;
    flex-wrap: wrap;
    gap: var(--space-2);
  }
  .chip[aria-pressed="true"] {
    background: var(--ink);
    color: var(--onink);
    box-shadow: none;
  }
</style>
