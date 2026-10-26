<script lang="ts">
  import { onMount } from "svelte";
  import { gateway } from "../lib/gateway.svelte";
  import { t } from "../lib/i18n";
  import { currentSubscription, disablePush, enablePush, isIos, PUSH_KINDS, pushSupport } from "../lib/push";

  const support = pushSupport();
  let permission = $state<NotificationPermission | "unknown">("Notification" in window ? Notification.permission : "unknown");
  let active = $state(false);
  let busy = $state(false);
  let message = $state<string | null>(null);

  onMount(async () => {
    if (support === "supported") active = (await currentSubscription()) !== null;
  });

  async function enable() {
    busy = true;
    message = null;
    try {
      await enablePush(gateway.api);
      active = true;
      message = t("notif.enabled");
    } catch (error) {
      const reason = error instanceof Error ? error.message : String(error);
      message =
        reason === "denied"
          ? t("notif.denied")
          : reason === "dismissed"
            ? t("notif.dismissed")
            : t("notif.enable_failed", { reason });
    } finally {
      permission = Notification.permission;
      busy = false;
    }
  }

  async function disable() {
    busy = true;
    try {
      await disablePush(gateway.api);
      active = false;
      message = t("notif.disabled");
    } catch (error) {
      message = t("notif.disable_failed", { reason: error instanceof Error ? error.message : String(error) });
    } finally {
      busy = false;
    }
  }

  async function test() {
    busy = true;
    try {
      const r = await gateway.api.post<{ sent: number; failed: number }>("/gw/v1/push/test", {});
      message = r.sent > 0 ? t("notif.test_sent") : t("notif.no_subscription");
    } catch (error) {
      message = t("notif.test_failed", { reason: error instanceof Error ? error.message : String(error) });
    } finally {
      busy = false;
    }
  }
</script>

<h2 class="sec">{t("notif.title")} <span class="meta">{active ? t("notif.active") : t("notif.inactive")}</span></h2>
{#if support === "ios-needs-home-screen"}
  <p class="note">
    {t("notif.ios_home")}
  </p>
{:else if support === "unsupported"}
  <p class="note">{t("notif.unsupported")}</p>
{:else}
  <ul class="kinds">
    {#each PUSH_KINDS as k (k.kind)}
      <li>{k.label}</li>
    {/each}
  </ul>
  <div class="actions">
    {#if active}
      <button class="btn secondary" type="button" disabled={busy} onclick={test}>{t("notif.send_test")}</button>
      <button class="btn secondary" type="button" disabled={busy} onclick={disable}>{t("notif.turn_off")}</button>
    {:else}
      <button class="btn" type="button" disabled={busy || permission === "denied"} onclick={enable}>{t("notif.turn_on")}</button>
    {/if}
  </div>
  {#if permission === "denied" && !message}
    <p class="note">{t("notif.denied_here")}</p>
  {/if}
  {#if isIos()}
    <p class="note">{t("notif.ios_visible")}</p>
  {/if}
{/if}
{#if message}
  <p class="note msg" role="status">{message}</p>
{/if}

<style>
  .kinds {
    margin: 0;
    padding: 0 var(--space-4) var(--space-2) calc(var(--space-4) + 1.1em);
    font-size: var(--step-0);
  }
  .kinds li {
    padding: 3px 0;
  }
  .actions {
    display: flex;
    flex-wrap: wrap;
    gap: var(--space-2);
    padding: var(--space-2) var(--space-4) var(--space-3);
  }
  .msg {
    color: var(--ink);
  }
</style>
