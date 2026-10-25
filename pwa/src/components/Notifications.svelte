<script lang="ts">
  import { onMount } from "svelte";
  import { gateway } from "../lib/gateway.svelte";
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
      message = "Notifikasi aktif untuk perangkat ini.";
    } catch (error) {
      const reason = error instanceof Error ? error.message : String(error);
      message =
        reason === "denied"
          ? "Izin ditolak. Buka pengaturan situs di browser untuk mengizinkan notifikasi lagi."
          : reason === "dismissed"
            ? "Dialog izin ditutup tanpa jawaban. Ketuk tombol lagi bila ingin mengaktifkan."
            : "Gagal mengaktifkan: " + reason;
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
      message = "Notifikasi dimatikan untuk perangkat ini.";
    } catch (error) {
      message = "Gagal mematikan: " + (error instanceof Error ? error.message : String(error));
    } finally {
      busy = false;
    }
  }

  async function test() {
    busy = true;
    try {
      const r = await gateway.api.post<{ sent: number; failed: number }>("/gw/v1/push/test", {});
      message = r.sent > 0 ? "Notifikasi uji dikirim. Bila tidak muncul dalam satu menit, periksa izin notifikasi sistem." : "Gateway belum punya langganan yang bisa dikirimi.";
    } catch (error) {
      message = "Gagal mengirim uji: " + (error instanceof Error ? error.message : String(error));
    } finally {
      busy = false;
    }
  }
</script>

<h2 class="sec">Notifikasi <span class="meta">{active ? "aktif di perangkat ini" : "belum aktif"}</span></h2>
{#if support === "ios-needs-home-screen"}
  <p class="note">
    Di iPhone dan iPad, notifikasi hanya jalan dari aplikasi di Layar Utama (iOS 16.4 atau lebih baru). Ketuk Bagikan di Safari, pilih Tambah ke Layar
    Utama, lalu buka Bot Trading dari ikonnya dan kembali ke layar ini.
  </p>
{:else if support === "unsupported"}
  <p class="note">Browser ini tidak mendukung Web Push. Pakai Chrome atau Edge di Android dan desktop, atau Safari dari Layar Utama di iOS.</p>
{:else}
  <ul class="kinds">
    {#each PUSH_KINDS as k (k.kind)}
      <li>{k.label}</li>
    {/each}
  </ul>
  <div class="actions">
    {#if active}
      <button class="btn secondary" type="button" disabled={busy} onclick={test}>Kirim notifikasi uji</button>
      <button class="btn secondary" type="button" disabled={busy} onclick={disable}>Matikan di perangkat ini</button>
    {:else}
      <button class="btn" type="button" disabled={busy || permission === "denied"} onclick={enable}>Aktifkan notifikasi</button>
    {/if}
  </div>
  {#if permission === "denied" && !message}
    <p class="note">Izin notifikasi ditolak di browser ini. Buka pengaturan situs untuk mengizinkan lagi.</p>
  {/if}
  {#if isIos()}
    <p class="note">iOS menampilkan setiap push sebagai notifikasi yang terlihat; tidak ada pembaruan diam-diam di latar belakang.</p>
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
