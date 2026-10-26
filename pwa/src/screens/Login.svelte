<script lang="ts">
  import LangSwitch from "../components/LangSwitch.svelte";
  import { ApiError } from "../lib/api";
  import { gateway } from "../lib/gateway.svelte";
  import { dayClock } from "../lib/format";
  import { t } from "../lib/i18n";

  let password = $state("");
  let busy = $state(false);
  let error = $state<string | null>(null);
  let online = $state(navigator.onLine);

  $effect(() => {
    const up = () => (online = true);
    const down = () => (online = false);
    addEventListener("online", up);
    addEventListener("offline", down);
    return () => {
      removeEventListener("online", up);
      removeEventListener("offline", down);
    };
  });

  async function submit(event: SubmitEvent) {
    event.preventDefault();
    busy = true;
    error = null;
    try {
      await gateway.login(password);
      password = "";
    } catch (e) {
      error = e instanceof ApiError && e.code === "unauthorized" ? t("login.wrong_password") : e instanceof Error && e.message ? e.message : t("login.failed");
    } finally {
      busy = false;
    }
  }
</script>

<main class="login">
  <h1>Bot Trading</h1>
  <p class="muted">{t("login.lead")}</p>
  {#if !online && gateway.savedAt}
    <div class="offline" role="status">
      <p>{t("login.offline")}</p>
      <button class="btn" type="button" onclick={() => gateway.openSaved()}>{t("login.open_saved", { at: dayClock(gateway.savedAt) })}</button>
    </div>
  {/if}
  <form onsubmit={submit}>
    <label for="pw">{t("login.password")}</label>
    <input id="pw" type="password" autocomplete="current-password" bind:value={password} required />
    {#if error}<p class="err" role="alert">{error}</p>{/if}
    <button class="btn" type="submit" disabled={busy || !password}>{busy ? t("login.busy") : t("login.submit")}</button>
  </form>
  <p class="muted small">{t("login.session_note")}</p>
  <LangSwitch />
</main>

<style>
  .login {
    max-width: 420px;
    margin: 0 auto;
    padding: calc(env(safe-area-inset-top) + 15vh) var(--space-4) var(--space-6);
  }
  h1 {
    font-size: var(--step-3);
    font-weight: 650;
    letter-spacing: -0.02em;
    line-height: 1;
  }
  p {
    margin: var(--space-2) 0 var(--space-5);
  }
  form {
    display: grid;
    gap: var(--space-2);
  }
  label {
    font-weight: 600;
  }
  input {
    min-height: 48px;
    padding: 0 var(--space-3);
    border: 0;
    border-radius: var(--radius);
    background: var(--bg);
    box-shadow: inset 0 0 0 1.5px var(--ink2);
    color: var(--ink);
    font: inherit;
  }
  input:focus-visible {
    outline: 2px solid var(--focus);
    outline-offset: 1px;
  }
  .btn {
    margin-top: var(--space-2);
  }
  .err {
    margin: 0;
    color: var(--loss);
    font-weight: 600;
  }
  .small {
    font-size: var(--step--1);
  }
  .offline {
    margin-bottom: var(--space-5);
    padding: var(--space-3) var(--space-4);
    background: var(--panel);
    border-top: 2px solid var(--sig);
  }
  .offline p {
    margin: 0 0 var(--space-3);
  }
</style>
