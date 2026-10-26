<script lang="ts">
  import { t, type Key } from "../lib/i18n";
  import { GROUPS, inGroup } from "../lib/route.svelte";

  const ABOUT: Record<string, Key> = {
    summary: "more.summary",
    chart: "more.chart",
    activity: "more.activity",
    swarm: "more.swarm",
    control: "more.control",
    config: "more.config",
    provider: "more.provider",
    history: "more.history",
    ab: "more.ab",
    audit: "more.audit",
    system: "more.system",
  };
</script>

{#each GROUPS as group (group.id)}
  <h2 class="sec">{group.label}</h2>
  <ul class="links">
    {#each inGroup(group.id) as s (s.id)}
      <li>
        <a href={"#" + s.id}>
          <span class="name">{s.label}</span>
          <span class="about">{t(ABOUT[s.id])}</span>
        </a>
      </li>
    {/each}
  </ul>
{/each}

<style>
  .links {
    margin: 0;
    padding: 0 0 var(--space-2);
    list-style: none;
  }
  a {
    display: grid;
    gap: 2px;
    min-height: 56px;
    padding: var(--space-2) var(--space-4);
    text-decoration: none;
    transition: background-color var(--t) var(--ease);
  }
  li + li a {
    border-top: 1px solid var(--rule);
  }
  a:hover,
  a:active {
    background: var(--panel);
  }
  .name {
    font-weight: 600;
  }
  .about {
    font-size: var(--step--1);
    color: var(--ink2);
  }
  h2:first-child {
    border-top: 0;
  }
</style>
