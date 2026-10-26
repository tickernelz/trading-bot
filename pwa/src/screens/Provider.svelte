<script lang="ts">
  import { explain, explainRead, idempotencyKey, send } from "../lib/control";
  import { clock, dayClock, decimal } from "../lib/format";
  import { gateway } from "../lib/gateway.svelte";
  import { Resource } from "../lib/resource.svelte";
  import type { ImportCandidate, Provider, ProviderSetting, ProviderTest } from "../lib/types";

  const g = gateway;
  const list = new Resource(() => g.api.get<Provider[]>("/gw/v1/providers"));
  const candidates = new Resource(() => g.api.get<{ source: string; candidates: ImportCandidate[] }>("/gw/v1/providers/import"));

  let busy = $state<Record<string, "test" | "state" | "save" | "import" | undefined>>({});
  let notes = $state<Record<string, { ok: boolean; text: string }>>({});
  let editing = $state<string | null>(null);
  let form = $state({ id: "", type: "openai-completions" as ProviderSetting["type"], base_url: "", models: "", api_key_env: "", api_key: "", api_key_clear: false });
  let picks = $state<Record<string, { take: boolean; key: boolean }>>({});

  $effect(() => {
    void list.load();
  });

  $effect(() => {
    if (g.canControl) void candidates.load();
  });

  const TYPES: ProviderSetting["type"][] = ["openai-completions", "openai-responses", "anthropic-messages"];
  const ERROR_KIND: Record<string, string> = {
    timeout: "waktu habis",
    auth: "key ditolak",
    rate_limited: "dibatasi (429)",
    http_5xx: "server provider galat",
    invalid: "jawaban tidak sah",
    provider_disabled: "provider nonaktif",
  };

  function note(id: string, ok: boolean, text: string) {
    notes = { ...notes, [id]: { ok, text } };
  }

  function testText(t: ProviderTest | null): string {
    if (!t) return "Belum pernah diuji.";
    const when = dayClock(t.at);
    if (t.ok) return "Berhasil " + decimal((t.latency_ms ?? 0) / 1000, 2) + " dtk, model " + (t.model ?? "-") + ", " + when + ".";
    return "Gagal: " + (ERROR_KIND[t.error_kind ?? ""] ?? t.error_kind ?? "tidak diketahui") + ", " + when + ".";
  }

  function usedBy(p: Provider): string {
    const parts: string[] = [];
    if (p.used_by.analyst) parts.push("agen analis");
    if (p.used_by.voters.length > 0) parts.push("voter " + p.used_by.voters.join(", "));
    return parts.length ? parts.join(" dan ") : "tidak dipakai peran mana pun";
  }

  function keyText(p: Provider): string {
    if (!p.api_key_configured) return "Belum ada key";
    if (p.api_key_source === "env") return "Key terpasang lewat variabel " + (p.api_key_env ?? "lingkungan");
    return "Key terpasang di config" + (p.api_key_last4 ? ", berakhiran " + p.api_key_last4 : "");
  }

  async function test(p: Provider) {
    busy = { ...busy, [p.id]: "test" };
    const o = await send<ProviderTest>(g.api, { method: "post", path: "/gw/v1/providers/" + encodeURIComponent(p.id) + "/test", body: {} }, idempotencyKey());
    busy = { ...busy, [p.id]: undefined };
    if (o.kind === "done") {
      note(p.id, o.result.ok, testText(o.result));
      void list.load();
    } else note(p.id, false, o.kind === "failed" ? explain(o.error) : "Uji tidak dijalankan.");
  }

  async function toggle(p: Provider) {
    busy = { ...busy, [p.id]: "state" };
    const o = await send<Provider>(g.api, { method: "post", path: "/gw/v1/providers/" + encodeURIComponent(p.id) + "/state", body: { enabled: !p.enabled } }, idempotencyKey());
    busy = { ...busy, [p.id]: undefined };
    if (o.kind === "done") {
      note(p.id, true, o.result.enabled ? "Diaktifkan." : "Dinonaktifkan. Voter di provider ini tidak dipanggil.");
      void list.load();
    } else note(p.id, false, o.kind === "failed" ? explain(o.error) : "Tidak dijalankan.");
  }

  function startEdit(p: Provider | null) {
    editing = p ? p.id : "+";
    form = p
      ? { id: p.id, type: p.type, base_url: p.base_url, models: p.models.join(", "), api_key_env: p.api_key_env ?? "", api_key: "", api_key_clear: false }
      : { id: "", type: "openai-completions", base_url: "https://", models: "", api_key_env: "", api_key: "", api_key_clear: false };
  }

  const formError = $derived.by(() => {
    if (!/^[a-z0-9][a-z0-9_-]*$/.test(form.id)) return "Id: huruf kecil, angka, - atau _";
    if (!/^(from_import|https?:\/\/\S+)$/.test(form.base_url)) return "Base URL: http(s)://… atau from_import";
    if (form.models.split(",").map((m) => m.trim()).filter(Boolean).length === 0) return "Minimal satu model";
    if (form.api_key_env && !/^[A-Z][A-Z0-9_]*$/.test(form.api_key_env)) return "Nama variabel: huruf besar, angka, _";
    return null;
  });

  async function save() {
    const id = editing === "+" ? form.id : editing!;
    busy = { ...busy, [id]: "save" };
    const body: Record<string, unknown> = {
      id: form.id,
      type: form.type,
      base_url: form.base_url,
      models: form.models.split(",").map((m) => m.trim()).filter(Boolean),
      api_key_env: form.api_key_env || null,
    };
    if (form.api_key) body.api_key = form.api_key;
    if (form.api_key_clear) body.api_key_clear = true;
    form.api_key = "";
    const o = await send<Provider>(g.api, editing === "+" ? { method: "post", path: "/gw/v1/providers", body } : { method: "put", path: "/gw/v1/providers/" + encodeURIComponent(id), body }, idempotencyKey());
    busy = { ...busy, [id]: undefined };
    if (o.kind === "done") {
      note(id, true, "Tersimpan. " + keyText(o.result) + ".");
      editing = null;
      void list.load();
    } else note(id, false, o.kind === "failed" ? explain(o.error) : "Tidak tersimpan.");
  }

  async function importPicked() {
    const items = Object.entries(picks)
      .filter(([, v]) => v.take)
      .map(([id, v]) => ({ id, include_key: v.key }));
    busy = { ...busy, _import: "import" };
    const o = await send<{ imported: Provider[] }>(g.api, { method: "post", path: "/gw/v1/providers/import", body: { items } }, idempotencyKey());
    busy = { ...busy, _import: undefined };
    if (o.kind === "done") {
      note("_import", true, o.result.imported.length + " provider diimpor.");
      picks = {};
      void list.load();
      void candidates.load();
    } else note("_import", false, o.kind === "failed" ? explain(o.error) : "Tidak dijalankan.");
  }
</script>

{#snippet result(id: string)}
  {#if notes[id]}<p class="result" class:warn-text={!notes[id].ok} class:done-text={notes[id].ok} role="status">{notes[id].text}</p>{/if}
{/snippet}

{#if !g.canControl}
  <p class="note scope">Dari jarak jauh hanya tampil status, aktif atau nonaktif, dan uji koneksi. Key, tambah provider, dan impor dari models.yml hanya di PC bot (localhost).</p>
{/if}

{#if list.loading && !list.data}
  <div class="skel-rows" aria-busy="true" aria-label="Memuat provider"><span class="skeleton" style="width: 40%"></span><span class="skeleton" style="width: 85%"></span><span class="skeleton" style="width: 70%"></span></div>
{:else if list.fault && !list.data}
  <p class="note warn-text">Daftar provider gagal dimuat ({list.fault.code}). {explainRead(list.fault)}</p>
  <div class="inline-actions"><button class="btn quiet" type="button" onclick={() => list.load()}>Coba lagi</button></div>
{:else if list.data && list.data.length === 0}
  <p class="note">Belum ada provider. {g.canControl ? "Tambah satu atau impor dari models.yml di bawah." : "Tambahkan dari PC bot."}</p>
{:else if list.data}
  <ul class="providers">
    {#each list.data as p (p.id)}
      <li class:off={!p.enabled}>
        <h2 class="name">{p.id} <span class="state" class:warn-text={!p.enabled}>{p.enabled ? "aktif" : "nonaktif"}</span></h2>
        <dl class="rows">
          <div><dt>Tipe dan host</dt><dd>{p.type} · {p.host ?? (p.base_url === "from_import" ? "dari impor" : p.base_url)}</dd></div>
          <div><dt>Model</dt><dd>{p.models.join(", ")}</dd></div>
          <div><dt>Dipakai oleh</dt><dd>{usedBy(p)}</dd></div>
          <div><dt>Key</dt><dd class:warn-text={!p.api_key_configured}>{keyText(p)}</dd></div>
          <div><dt>Uji terakhir</dt><dd class:warn-text={p.last_test !== null && !p.last_test.ok}>{testText(p.last_test)}</dd></div>
          <div><dt>20 keputusan terakhir</dt><dd>{p.health ? p.health.ok + " dari " + p.health.calls + " menjawab · p50 " + (p.health.latency_p50_s === null ? "-" : decimal(p.health.latency_p50_s, 1) + " dtk") + " · maks " + (p.health.latency_max_s === null ? "-" : decimal(p.health.latency_max_s, 1) + " dtk") : "belum ada panggilan"}</dd></div>
        </dl>
        <div class="inline-actions">
          <button class="btn quiet" type="button" disabled={busy[p.id] !== undefined} aria-busy={busy[p.id] === "test"} onclick={() => test(p)}>{busy[p.id] === "test" ? "Menguji…" : "Uji koneksi"}</button>
          <button class="btn quiet" type="button" disabled={busy[p.id] !== undefined} aria-busy={busy[p.id] === "state"} onclick={() => toggle(p)}>{p.enabled ? "Nonaktifkan" : "Aktifkan"}</button>
          {#if g.canControl}<button class="btn quiet" type="button" disabled={busy[p.id] !== undefined} onclick={() => startEdit(p)}>Ubah</button>{/if}
        </div>
        {#if p.enabled && p.used_by.voters.length > 0}<p class="note">Menonaktifkan berarti {p.used_by.voters.length} voter tidak dipanggil; kuorum bisa gagal dan entry dilewati.</p>{/if}
        {@render result(p.id)}
        {#if editing === p.id}{@render editor()}{/if}
      </li>
    {/each}
  </ul>
{/if}

{#snippet editor()}
  <form class="editor" onsubmit={(e) => { e.preventDefault(); if (!formError) void save(); }}>
    <p class="title">{editing === "+" ? "Provider baru" : "Ubah " + editing}</p>
    <div class="field"><label for="pf-id">Id</label><input id="pf-id" class="input" bind:value={form.id} disabled={editing !== "+"} autocomplete="off" spellcheck="false" /></div>
    <div class="field">
      <label for="pf-type">Tipe API</label>
      <select id="pf-type" class="input" bind:value={form.type}>{#each TYPES as t (t)}<option value={t}>{t}</option>{/each}</select>
    </div>
    <div class="field"><label for="pf-url">Base URL</label><input id="pf-url" class="input wide" bind:value={form.base_url} autocomplete="off" spellcheck="false" /><span class="hint">Berakhiran /v1 untuk tipe OpenAI.</span></div>
    <div class="field"><label for="pf-models">Model</label><input id="pf-models" class="input wide" bind:value={form.models} autocomplete="off" spellcheck="false" /><span class="hint">Pisahkan dengan koma.</span></div>
    <div class="field"><label for="pf-env">Nama variabel key</label><input id="pf-env" class="input" bind:value={form.api_key_env} placeholder="NUTARALINE_API_KEY" autocomplete="off" spellcheck="false" /><span class="hint">Key dibaca dari .env bila diisi. Disarankan.</span></div>
    <div class="field">
      <label for="pf-key">Key langsung di config</label>
      <input id="pf-key" class="input wide" type="password" bind:value={form.api_key} autocomplete="new-password" spellcheck="false" placeholder={editing === "+" ? "kosong" : "kosong berarti tidak berubah"} />
      <span class="hint">Tersimpan sebagai teks biasa di config/config.yaml lokal (tidak di-commit). Setelah disimpan hanya 4 karakter terakhir yang tampil.</span>
    </div>
    {#if editing !== "+"}<label class="check"><input type="checkbox" bind:checked={form.api_key_clear} /> Hapus key yang tersimpan di config</label>{/if}
    {#if formError}<p class="note warn-text">{formError}</p>{/if}
    <div class="inline-actions">
      <button class="btn" type="submit" disabled={formError !== null || Boolean(busy[editing === "+" ? form.id : (editing ?? "")])}>Simpan provider</button>
      <button class="btn secondary" type="button" onclick={() => { editing = null; form.api_key = ""; }}>Batal</button>
    </div>
  </form>
{/snippet}

{#if g.canControl}
  <h2 class="sec">Tambah provider</h2>
  {#if editing === "+"}
    {@render editor()}
  {:else}
    <div class="inline-actions"><button class="btn quiet" type="button" onclick={() => startEdit(null)}>Tambah provider</button></div>
  {/if}

  <h2 class="sec">Impor dari models.yml <span class="meta">dibaca lokal di PC ini</span></h2>
  {#if candidates.loading && !candidates.data}
    <div class="skel-rows"><span class="skeleton" style="width: 60%"></span><span class="skeleton" style="width: 50%"></span></div>
  {:else if candidates.fault && !candidates.data}
    <p class="note warn-text">Daftar impor gagal dimuat ({candidates.fault.code}). {explainRead(candidates.fault)}</p>
  {:else if candidates.data}
    <p class="note">Sumber {candidates.data.source}. Key hanya ikut bila dicentang per provider.</p>
    <table class="table">
      <thead><tr><th>Provider</th><th>Impor</th><th>Sertakan key</th></tr></thead>
      <tbody>
        {#each candidates.data.candidates as c (c.id)}
          <tr>
            <td><b>{c.id}</b>{#if c.exists}<span class="muted"> · sudah ada, akan diperbarui</span>{/if}<br /><span class="muted small">{c.type} · {c.models.length} model</span></td>
            <td><label class="tick"><input type="checkbox" checked={picks[c.id]?.take ?? false} onchange={(e) => (picks = { ...picks, [c.id]: { take: e.currentTarget.checked, key: picks[c.id]?.key ?? false } })} /><span class="sr-only">Impor {c.id}</span></label></td>
            <td><label class="tick"><input type="checkbox" disabled={!c.has_key || !(picks[c.id]?.take ?? false)} checked={picks[c.id]?.key ?? false} onchange={(e) => (picks = { ...picks, [c.id]: { take: picks[c.id]?.take ?? false, key: e.currentTarget.checked } })} /><span class="sr-only">Sertakan key {c.id}</span>{#if !c.has_key}<span class="muted small">tidak ada</span>{/if}</label></td>
          </tr>
        {/each}
      </tbody>
    </table>
    <div class="inline-actions">
      <button class="btn" type="button" disabled={!Object.values(picks).some((v) => v.take) || busy._import !== undefined} aria-busy={busy._import !== undefined} onclick={importPicked}>{busy._import ? "Mengimpor…" : "Impor terpilih"}</button>
    </div>
    {@render result("_import")}
  {/if}
{/if}
{#if list.loadedAt}<p class="note num">Dibaca {clock(list.loadedAt, true)}.</p>{/if}

<style>
  .scope {
    padding-top: var(--space-3);
  }
  .providers {
    margin: 0;
    padding: 0;
    list-style: none;
  }
  .providers > li {
    padding-top: var(--space-3);
    border-top: 1px solid var(--rule);
  }
  .providers > li:first-child {
    border-top: 0;
  }
  .name {
    display: flex;
    align-items: baseline;
    gap: var(--space-2);
    padding: 0 var(--space-4);
    font-size: var(--step-2);
  }
  .state {
    font-size: var(--step--1);
    font-weight: 400;
    color: var(--ink2);
  }
  .off .rows {
    color: var(--ink2);
  }
  .result {
    margin: 0;
    padding: 0 var(--space-4) var(--space-2);
  }
  .editor {
    margin: var(--space-2) var(--space-4) var(--space-4);
    padding: var(--space-2) 0;
    border-radius: var(--radius);
    box-shadow: inset 0 0 0 1px var(--rule-strong);
  }
  .editor .title {
    margin: 0;
    padding: var(--space-2) var(--space-4) 0;
    font-weight: 650;
  }
  .wide {
    max-width: 36rem;
  }
  .small {
    font-size: var(--step--1);
  }
  .tick {
    display: inline-flex;
    align-items: center;
    gap: var(--space-2);
    min-height: 44px;
    min-width: 44px;
    cursor: pointer;
  }
  .tick input {
    width: 20px;
    height: 20px;
    accent-color: var(--ink);
  }
</style>
