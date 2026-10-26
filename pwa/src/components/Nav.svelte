<script lang="ts">
  import { t } from "../lib/i18n";
  import { SCREENS, type Screen } from "../lib/route.svelte";

  let { current, labelled = t("nav.main") }: { current: Screen; labelled?: string } = $props();
</script>

<nav aria-label={labelled}>
  {#each SCREENS as s (s.id)}
    <a href={"#" + s.id} aria-current={current === s.id ? "page" : undefined}>{s.label}</a>
  {/each}
</nav>

<style>
  nav {
    display: flex;
  }
  a {
    display: flex;
    align-items: center;
    justify-content: center;
    min-height: 48px;
    color: var(--ink2);
    text-decoration: none;
    font-size: var(--step-0);
    transition: color var(--t) var(--ease), box-shadow var(--t) var(--ease);
  }
  a:hover {
    color: var(--ink);
  }
  a[aria-current="page"] {
    color: var(--ink);
    font-weight: 600;
  }
</style>
