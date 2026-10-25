<script lang="ts">
  import { gateway } from "../lib/gateway.svelte";

  let password = $state("");
  let busy = $state(false);
  let error = $state<string | null>(null);

  async function submit(event: SubmitEvent) {
    event.preventDefault();
    busy = true;
    error = null;
    try {
      await gateway.login(password);
      password = "";
    } catch (e) {
      error = e instanceof Error && e.message ? (e.message === "Sesi berakhir" ? "Kata sandi salah." : e.message) : "Gagal masuk.";
    } finally {
      busy = false;
    }
  }
</script>

<main class="login">
  <h1>Bot Trading</h1>
  <p class="muted">Panel baca-saja. Masuk ke gateway di PC untuk melihat keadaan bot.</p>
  <form onsubmit={submit}>
    <label for="pw">Kata sandi gateway</label>
    <input id="pw" type="password" autocomplete="current-password" bind:value={password} required />
    {#if error}<p class="err" role="alert">{error}</p>{/if}
    <button class="btn" type="submit" disabled={busy || !password}>{busy ? "Masuk..." : "Masuk"}</button>
  </form>
  <p class="muted small">Token sesi hanya disimpan selama tab atau aplikasi ini terbuka.</p>
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
</style>
