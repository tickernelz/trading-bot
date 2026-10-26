<script lang="ts">
  import { lang, setLang, t } from "../lib/i18n";
  import { LANGUAGES } from "../lib/locales/index";
</script>

<div class="lang" role="group" aria-label={t("lang.label")}>
  {#each LANGUAGES as l (l.code)}
    <button class="chip" type="button" lang={l.htmlLang} aria-pressed={lang === l.code} onclick={() => setLang(l.code)}>{l.nativeName}</button>
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
