<script lang="ts">
  import { t } from "../lib/i18n";
  import { GROUPS, inGroup, SCREENS, tabFor, type Screen } from "../lib/route.svelte";

  let { current, variant = "tabs" }: { current: Screen; variant?: "tabs" | "rail" } = $props();
  const tabs = SCREENS.filter((s) => s.tab);
</script>

{#if variant === "tabs"}
  <nav aria-label={t("nav.main")} class="tabs">
    {#each tabs as s (s.id)}
      <a href={"#" + s.id} aria-current={tabFor(current) === s.id ? "page" : undefined}>{s.label}</a>
    {/each}
  </nav>
{:else}
  <nav aria-label={t("nav.side")} class="rail">
    {#each GROUPS as group (group.id)}
      <p class="group" id={"nav-" + group.id}>{group.label}</p>
      <ul aria-labelledby={"nav-" + group.id}>
        {#each inGroup(group.id) as s (s.id)}
          <li><a href={"#" + s.id} aria-current={current === s.id ? "page" : undefined}>{s.label}</a></li>
        {/each}
      </ul>
    {/each}
  </nav>
{/if}

<style>
  nav.tabs {
    display: flex;
  }
  ul {
    margin: 0;
    padding: 0;
    list-style: none;
  }
  a {
    display: flex;
    align-items: center;
    justify-content: center;
    min-height: 48px;
    color: var(--ink2);
    text-decoration: none;
    font-size: var(--step-0);
    transition: color var(--t) var(--ease), box-shadow var(--t) var(--ease), background-color var(--t) var(--ease);
  }
  a:hover {
    color: var(--ink);
  }
  a:active {
    background: var(--panel);
  }
  a[aria-current="page"] {
    color: var(--ink);
    font-weight: 600;
  }
  .rail a {
    min-height: 44px;
  }
  .group {
    margin: var(--space-3) 0 0;
    padding: 0 var(--space-4);
    font-size: var(--step--1);
    color: var(--ink2);
  }
</style>
