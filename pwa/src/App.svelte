<script lang="ts">
  import type { Component } from "svelte";
  import Nav from "./components/Nav.svelte";
  import StaleBanner from "./components/StaleBanner.svelte";
  import TopBar from "./components/TopBar.svelte";
  import { gateway } from "./lib/gateway.svelte";
  import { route, SCREENS, type Screen } from "./lib/route.svelte";
  import Activity from "./screens/Activity.svelte";
  import Chart from "./screens/Chart.svelte";
  import More from "./screens/More.svelte";
  import Login from "./screens/Login.svelte";
  import Summary from "./screens/Summary.svelte";
  import { t } from "./lib/i18n";

  const EAGER: Partial<Record<Screen, Component>> = { summary: Summary, chart: Chart, activity: Activity, more: More };
  const LAZY: Partial<Record<Screen, () => Promise<{ default: Component }>>> = {
    swarm: () => import("./screens/Swarm.svelte"),
    system: () => import("./screens/System.svelte"),
    control: () => import("./screens/Control.svelte"),
    config: () => import("./screens/Config.svelte"),
    provider: () => import("./screens/Provider.svelte"),
    history: () => import("./screens/History.svelte"),
    ab: () => import("./screens/AvsB.svelte"),
    audit: () => import("./screens/Audit.svelte"),
  };
  const title = $derived(SCREENS.find((s) => s.id === route.screen)?.label ?? "");
  const eager = $derived(EAGER[route.screen] ?? null);
  const lazy = $derived(LAZY[route.screen]?.() ?? null);

  $effect(() => {
    document.title = title ? t("app.title", { screen: title }) : t("app.name");
  });

  $effect(() => {
    if (gateway.token) import("./lib/push").then((push) => push.syncPushLang(gateway.api)).catch(() => undefined);
  });
</script>

{#if !gateway.token && !gateway.viewingSaved}
  <Login />
{:else}
  <div class="shell">
    <aside class="rail">
      <p class="brand">{t("app.name")}</p>
      <Nav current={route.screen} variant="rail" />
    </aside>
    <div class="body">
      <TopBar />
      <StaleBanner />
      <main id="isi">
        <h1 class="sr-only">{title}</h1>
        {#if eager}
          {@const Screen = eager}
          <Screen />
        {:else if lazy}
          {#await lazy}
            <div class="loading" aria-busy="true" aria-label={t("app.loading_screen")}>
              <span class="skeleton" style="width: 40%"></span>
              <span class="skeleton" style="width: 85%"></span>
              <span class="skeleton" style="width: 70%"></span>
            </div>
          {:then module}
            {@const Screen = module.default}
            <Screen />
          {:catch}
            <p class="note warn-text">{t("app.screen_failed")}</p>
          {/await}
        {/if}
      </main>
    </div>
    <div class="tabs"><Nav current={route.screen} /></div>
  </div>
{/if}

<style>
  .shell {
    min-height: 100dvh;
  }
  .rail {
    display: none;
  }
  main {
    padding-bottom: calc(var(--nav-h) + env(safe-area-inset-bottom) + var(--space-5));
  }
  .tabs {
    position: fixed;
    inset: auto 0 0 0;
    z-index: 30;
    padding-bottom: env(safe-area-inset-bottom);
    background: var(--bg);
    border-top: 1px solid var(--rule);
  }
  .tabs :global(nav) {
    height: var(--nav-h);
  }
  .tabs :global(a) {
    flex: 1;
  }
  .tabs :global(a[aria-current="page"]) {
    box-shadow: inset 0 2px 0 var(--ink);
  }
  .loading {
    display: grid;
    gap: var(--space-3);
    padding: var(--space-5) var(--space-4);
  }
  @media (min-width: 960px) {
    .shell {
      display: grid;
      grid-template-columns: 200px minmax(0, 1fr);
    }
    .rail {
      display: block;
      position: sticky;
      top: 0;
      height: 100dvh;
      background: var(--panel);
      border-right: 1px solid var(--rule);
    }
    .brand {
      margin: 0;
      padding: 0 var(--space-4);
      height: var(--bar-h);
      display: flex;
      align-items: center;
      font-weight: 650;
      border-bottom: 1px solid var(--rule);
    }
    .rail :global(nav) {
      padding: 0 0 var(--space-4);
    }
    .rail :global(a) {
      justify-content: flex-start;
      padding: 0 var(--space-4);
    }
    .rail :global(a[aria-current="page"]) {
      background: var(--bg);
      box-shadow: inset 0 0 0 1px var(--rule);
    }
    .tabs {
      display: none;
    }
    main {
      max-width: 1240px;
      padding-bottom: var(--space-7);
    }
  }
</style>
