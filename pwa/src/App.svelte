<script lang="ts">
  import Nav from "./components/Nav.svelte";
  import StaleBanner from "./components/StaleBanner.svelte";
  import TopBar from "./components/TopBar.svelte";
  import { gateway } from "./lib/gateway.svelte";
  import { route } from "./lib/route.svelte";
  import Aksi from "./screens/Aksi.svelte";
  import Grafik from "./screens/Grafik.svelte";
  import Login from "./screens/Login.svelte";
  import Ringkas from "./screens/Ringkas.svelte";
  import Sistem from "./screens/Sistem.svelte";
  import Swarm from "./screens/Swarm.svelte";
  import { t } from "./lib/i18n";
  import { SCREENS } from "./lib/route.svelte";

  const title = $derived(SCREENS.find((s) => s.id === route.screen)?.label ?? "");

  $effect(() => {
    document.title = title + " · Bot Trading";
  });
</script>

{#if !gateway.token && !gateway.viewingSaved}
  <Login />
{:else}
  <div class="shell">
    <aside class="rail">
      <p class="brand">Bot Trading</p>
      <Nav current={route.screen} labelled={t("nav.side")} />
    </aside>
    <div class="body">
      <TopBar />
      <StaleBanner />
      <main id="isi">
        <h1 class="sr-only">{title}</h1>
        {#if route.screen === "ringkas"}
          <Ringkas />
        {:else if route.screen === "grafik"}
          <Grafik />
        {:else if route.screen === "aksi"}
          <Aksi />
        {:else if route.screen === "swarm"}
          <Swarm />
        {:else}
          <Sistem />
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
      flex-direction: column;
      padding: var(--space-2) 0;
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
