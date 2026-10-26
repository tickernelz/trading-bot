<script lang="ts">
  import BotSwitch from "../components/BotSwitch.svelte";
  import { explain, explainRead, idempotencyKey, send } from "../lib/control";
  import { clock, dayClock, decimal } from "../lib/format";
  import { gateway } from "../lib/gateway.svelte";
  import { t } from "../lib/i18n";
  import { Resource } from "../lib/resource.svelte";
  import type { ImportCandidate, ImportResult, Provider, ProviderList, ProviderTest, ProviderType, Roles, WriteResult } from "../lib/types";

  const g = gateway;
  let bot = $state(g.bots[0]?.id ?? "A");
  const q = () => "bot=" + encodeURIComponent(bot);
  const list = new Resource(() => g.api.get<ProviderList>("/gw/v1/providers?" + q()));
  const roles = new Resource(() => g.api.get<Roles>("/gw/v1/roles?" + q()));
  const candidates = new Resource(() => g.api.get<{ bot: string; providers: ImportCandidate[] }>("/gw/v1/providers/import?" + q()));

  let busy = $state<Record<string, string | undefined>>({});
  let notes = $state<Record<string, { ok: boolean; text: string }>>({});
  let editing = $state<string | null>(null);
  let form = $state({ id: "", type: "openai-completions" as ProviderType, base_url: "https://", models: "" });
  let keyFor = $state<string | null>(null);
  let keyMode = $state<"env" | "literal">("env");
  let keyEnv = $state("");
  let keyValue = $state("");
  let picks = $state<Record<string, { take: boolean; key: boolean; replace: boolean }>>({});
  let importResults = $state<ImportResult[]>([]);
  let analyst = $state("");

  $effect(() => {
    void bot;
    editing = null;
    keyFor = null;
    notes = {};
    importResults = [];
    void list.load();
    void roles.load();
    if (g.canControl) void candidates.load();
  });

  $effect(() => {
    if (roles.data) analyst = roles.data.analyst.provider + ":" + roles.data.analyst.model;
  });

  const TYPES: ProviderType[] = ["openai-completions", "openai-responses", "anthropic-messages"];
  const ERROR: Record<string, string> = {
    unauthorized: t("prov.err_unauthorized"),
    not_found: t("prov.err_not_found"),
    rate_limited: t("prov.err_rate_limited"),
    rejected: t("prov.err_rejected"),
    upstream_error: t("prov.err_upstream"),
    timeout: t("prov.err_timeout"),
    connect_error: t("prov.err_connect"),
    invalid_response: t("prov.err_invalid"),
    no_key: t("prov.err_no_key"),
    base_url_unresolved: t("prov.err_base_url"),
  };
  const options = $derived((list.data?.providers ?? []).flatMap((p) => p.models.map((m) => p.id + ":" + m)));

  function note(id: string, ok: boolean, text: string) {
    notes = { ...notes, [id]: { ok, text } };
  }

  function testText(r: ProviderTest | null): string {
    if (!r) return t("prov.never_tested");
    const when = dayClock(r.tested_at);
    if (r.ok) return t("prov.test_ok", { s: decimal((r.latency_ms ?? 0) / 1000, 2), model: r.model ?? "-", at: when });
    const kind = ERROR[r.error ?? ""] ?? r.error ?? t("prov.err_unknown");
    return t("prov.test_failed", { kind: kind + (r.status ? " (HTTP " + r.status + ")" : ""), at: when }) + (r.detail ? " " + r.detail : "");
  }

  function keyText(p: Provider): string {
    if (p.key.source === "config") return p.key.last4 ? t("prov.key_config_last4", { last4: p.key.last4 }) : t("prov.key_config");
    if (p.key.source === "env") return p.key.env_set ? t("prov.key_env_set", { name: p.key.env_name ?? "" }) : t("prov.key_env_empty", { name: p.key.env_name ?? "" });
    return t("prov.key_none");
  }

  async function write<T>(id: string, label: string, method: "post" | "put" | "del", path: string, body: Record<string, unknown>): Promise<T | null> {
    busy = { ...busy, [id]: label };
    const o = await send<T>(g.api, { method, path: path + (path.includes("?") ? "&" : "?") + q(), body }, idempotencyKey());
    busy = { ...busy, [id]: undefined };
    if (o.kind === "done") return o.result;
    note(id, false, o.kind === "failed" ? (o.error.code === "invalid_request" ? t("prov.rejected", { msg: o.error.message }) : explain(o.error)) : t("common.not_run"));
    return null;
  }

  async function test(p: Provider) {
    const model = p.active_models[0] ?? p.models[0];
    const r = await write<ProviderTest>(p.id, "test", "post", "/gw/v1/providers/" + encodeURIComponent(p.id) + "/test", model ? { model } : {});
    if (!r) return;
    note(p.id, r.ok, testText(r));
    void list.load();
  }

  function startEdit(p: Provider | null) {
    keyFor = null;
    editing = p ? p.id : "+";
    form = p ? { id: p.id, type: p.type as ProviderType, base_url: p.base_url, models: p.models.join(", ") } : { id: "", type: "openai-completions", base_url: "https://", models: "" };
  }

  const formError = $derived.by(() => {
    if (!/^[a-z0-9][a-z0-9_-]*$/.test(form.id) || form.id === "import") return t("prov.err_form_id");
    if (!/^https?:\/\/\S+$/.test(form.base_url)) return t("prov.err_form_url");
    if (/^https?:\/\/[^/]*@/.test(form.base_url)) return t("prov.err_form_userinfo");
    if (form.models.split(",").map((m) => m.trim()).filter(Boolean).length === 0) return t("prov.err_form_models");
    return null;
  });

  async function saveProvider() {
    const id = form.id;
    const models = form.models.split(",").map((m) => m.trim()).filter(Boolean);
    const r = await write<WriteResult>(id, "save", "put", "/gw/v1/providers/" + encodeURIComponent(id), { type: form.type, base_url: form.base_url, models });
    if (!r) return;
    note(id, true, r.changes.length === 0 ? t("prov.no_change") : t("prov.saved") + (r.restart_required ? " " + t("cfg.restart_required") : ""));
    editing = null;
    void list.load();
  }

  async function removeProvider(p: Provider) {
    const r = await write<WriteResult>(p.id, "remove", "del", "/gw/v1/providers/" + encodeURIComponent(p.id), {});
    if (!r) return;
    note(p.id, true, t("prov.removed", { id: p.id }));
    void list.load();
  }

  function startKey(p: Provider) {
    editing = null;
    keyFor = p.id;
    keyMode = p.key.source === "config" ? "literal" : "env";
    keyEnv = p.key.env_name ?? p.id.toUpperCase().replace(/-/g, "_") + "_API_KEY";
    keyValue = "";
  }

  const keyError = $derived(keyMode === "env" ? (/^[A-Z][A-Z0-9_]*$/.test(keyEnv) ? null : t("prov.err_env")) : /^\S{8,1024}$/.test(keyValue) ? null : t("prov.err_key"));

  async function saveKey(id: string) {
    const body = keyMode === "env" ? { api_key_env: keyEnv } : { api_key: keyValue };
    keyValue = "";
    const r = await write<WriteResult & { provider?: Provider }>(id, "key", "put", "/gw/v1/providers/" + encodeURIComponent(id) + "/key", body);
    if (!r) return;
    note(id, true, t("prov.key_saved", { state: r.provider ? keyText(r.provider) : "" }) + (r.restart_required ? " " + t("cfg.restart_required") : ""));
    keyFor = null;
    void list.load();
  }

  async function clearKey(id: string) {
    const r = await write<WriteResult>(id, "key", "del", "/gw/v1/providers/" + encodeURIComponent(id) + "/key", {});
    if (!r) return;
    note(id, true, t("prov.key_cleared"));
    keyFor = null;
    void list.load();
  }

  async function saveAnalyst() {
    const [provider, ...rest] = analyst.split(":");
    const r = await write<WriteResult>("_roles", "roles", "put", "/gw/v1/roles", { analyst: { provider, model: rest.join(":") } });
    if (!r) return;
    note("_roles", true, r.changes.length === 0 ? t("prov.no_change") : t("prov.roles_saved") + (r.restart_required ? " " + t("cfg.restart_required") : ""));
    void roles.load();
    void list.load();
  }

  const keyable = (c: ImportCandidate) => c.key_source === "literal" || c.key_source === "env";
  const pick = (name: string) => picks[name] ?? { take: false, key: false, replace: false };

  async function importPicked() {
    const providers = Object.entries(picks)
      .filter(([, v]) => v.take)
      .map(([name, v]) => ({ name, with_key: v.key, models: null, replace: v.replace }));
    const r = await write<{ results: ImportResult[] }>("_import", "import", "post", "/gw/v1/providers/import", { providers });
    if (!r) return;
    importResults = r.results;
    picks = {};
    void list.load();
    void candidates.load();
  }

  const RESULT: Record<string, string> = { created: t("prov.imp_created"), updated: t("prov.imp_updated"), skipped: t("prov.imp_skipped") };
</script>

{#snippet result(id: string)}
  {#if notes[id]}<p class="result" class:warn-text={!notes[id].ok} class:done-text={notes[id].ok} role="status">{notes[id].text}</p>{/if}
{/snippet}

<div class="head">
  <BotSwitch bind:value={bot} label={t("prov.bot_label")} />
  <span class="muted small">{t("cfg.per_bot")}</span>
</div>

{#if !g.canControl}
  <p class="note scope">{t("prov.remote_read")}</p>
{/if}

{#if list.loading && !list.data}
  <div class="skel-rows" aria-busy="true" aria-label={t("prov.loading")}><span class="skeleton" style="width: 40%"></span><span class="skeleton" style="width: 85%"></span><span class="skeleton" style="width: 70%"></span></div>
{:else if list.fault && !list.data}
  <p class="note warn-text">{t("prov.load_failed", { code: list.fault.code })} {explainRead(list.fault)}</p>
  <div class="inline-actions"><button class="btn quiet" type="button" onclick={() => list.load()}>{t("common.retry")}</button></div>
{:else if list.data && list.data.providers.length === 0}
  <p class="note">{g.canControl ? t("prov.empty_local") : t("prov.empty_remote")}</p>
{:else if list.data}
  <ul class="providers">
    {#each list.data.providers as p (p.id)}
      <li>
        <h2 class="name">{p.id} <span class="state">{p.active_models.length ? t("prov.in_use") : t("prov.unused")}</span></h2>
        <dl class="rows">
          <div><dt>{t("prov.type_host")}</dt><dd>{p.type} · {p.host ?? (p.base_url === "from_import" ? t("prov.from_import") : p.base_url)}</dd></div>
          <div><dt>{t("prov.models")}</dt><dd>{p.models.join(", ")}</dd></div>
          <div><dt>{t("prov.active_models")}</dt><dd>{p.active_models.join(", ") || "-"}</dd></div>
          <div><dt>Key</dt><dd class:warn-text={!p.key.configured}>{keyText(p)}</dd></div>
          <div><dt>{t("prov.last_test")}</dt><dd class:warn-text={p.last_test !== null && !p.last_test.ok}>{testText(p.last_test)}</dd></div>
        </dl>
        <div class="inline-actions">
          <button class="btn quiet" type="button" disabled={busy[p.id] !== undefined} aria-busy={busy[p.id] === "test"} onclick={() => test(p)}>{busy[p.id] === "test" ? t("prov.testing") : t("prov.test")}</button>
          {#if g.canControl}
            <button class="btn quiet" type="button" disabled={busy[p.id] !== undefined} onclick={() => startEdit(p)}>{t("common.edit")}</button>
            <button class="btn quiet" type="button" disabled={busy[p.id] !== undefined} onclick={() => startKey(p)}>{t("prov.key_set")}</button>
            <button class="btn quiet" type="button" disabled={busy[p.id] !== undefined || p.active_models.length > 0} title={p.active_models.length > 0 ? t("prov.remove_blocked") : undefined} onclick={() => removeProvider(p)}>{t("common.remove")}</button>
          {/if}
        </div>
        {@render result(p.id)}
        {#if editing === p.id}{@render editor()}{/if}
        {#if keyFor === p.id}{@render keyEditor(p)}{/if}
      </li>
    {/each}
  </ul>
  <p class="note">{t("prov.toggle_note")}</p>
{/if}

{#snippet editor()}
  <form class="editor" onsubmit={(e) => { e.preventDefault(); if (!formError) void saveProvider(); }}>
    <p class="title">{editing === "+" ? t("prov.new") : t("prov.edit", { id: editing ?? "" })}</p>
    <div class="field"><label for="pf-id">Id</label><input id="pf-id" class="input" bind:value={form.id} disabled={editing !== "+"} autocomplete="off" spellcheck="false" /></div>
    <div class="field">
      <label for="pf-type">{t("prov.type")}</label>
      <select id="pf-type" class="input" bind:value={form.type}>{#each TYPES as ty (ty)}<option value={ty}>{ty}</option>{/each}</select>
    </div>
    <div class="field"><label for="pf-url">Base URL</label><input id="pf-url" class="input wide" bind:value={form.base_url} autocomplete="off" spellcheck="false" /><span class="hint">{t("prov.url_hint")}</span></div>
    <div class="field"><label for="pf-models">{t("prov.models")}</label><input id="pf-models" class="input wide" bind:value={form.models} autocomplete="off" spellcheck="false" /><span class="hint">{t("prov.models_hint")}</span></div>
    {#if editing === "+"}<p class="note">{t("prov.new_key_hint", { name: (form.id || "id").toUpperCase().replace(/-/g, "_") + "_API_KEY" })}</p>{/if}
    {#if formError}<p class="note warn-text">{formError}</p>{/if}
    <div class="inline-actions">
      <button class="btn" type="submit" disabled={formError !== null || busy[form.id] !== undefined} aria-busy={busy[form.id] === "save"}>{busy[form.id] === "save" ? t("common.saving") : t("prov.save")}</button>
      <button class="btn secondary" type="button" onclick={() => (editing = null)}>{t("common.cancel")}</button>
    </div>
  </form>
{/snippet}

{#snippet keyEditor(p: Provider)}
  <form class="editor" onsubmit={(e) => { e.preventDefault(); if (!keyError) void saveKey(p.id); }}>
    <p class="title">{t("prov.key_title", { id: p.id })}</p>
    <div class="radios" role="radiogroup" aria-label={t("prov.key_source")}>
      <label class="check"><input type="radio" value="env" bind:group={keyMode} /> {t("prov.key_mode_env")}</label>
      <label class="check"><input type="radio" value="literal" bind:group={keyMode} /> {t("prov.key_mode_literal")}</label>
    </div>
    {#if keyMode === "env"}
      <div class="field"><label for="pk-env">{t("prov.env_name")}</label><input id="pk-env" class="input" bind:value={keyEnv} autocomplete="off" spellcheck="false" /><span class="hint">{t("prov.env_hint")}</span></div>
    {:else}
      <div class="field">
        <label for="pk-key">Key</label>
        <input id="pk-key" class="input wide" type="password" bind:value={keyValue} autocomplete="new-password" spellcheck="false" />
        <span class="hint">{t("prov.key_hint")}</span>
      </div>
    {/if}
    {#if keyError && (keyMode === "env" || keyValue)}<p class="note warn-text">{keyError}</p>{/if}
    <div class="inline-actions">
      <button class="btn" type="submit" disabled={keyError !== null || busy[p.id] !== undefined} aria-busy={busy[p.id] === "key"}>{busy[p.id] === "key" ? t("common.saving") : t("prov.key_save")}</button>
      {#if p.key.source !== "none"}<button class="btn quiet" type="button" disabled={busy[p.id] !== undefined} onclick={() => clearKey(p.id)}>{t("prov.key_clear")}</button>{/if}
      <button class="btn secondary" type="button" onclick={() => { keyFor = null; keyValue = ""; }}>{t("common.cancel")}</button>
    </div>
  </form>
{/snippet}

<h2 class="sec">{t("prov.roles")} <span class="meta">{t("prov.roles_meta")}</span></h2>
{#if roles.loading && !roles.data}
  <div class="skel-rows"><span class="skeleton" style="width: 60%"></span></div>
{:else if roles.fault && !roles.data}
  <p class="note warn-text">{t("prov.roles_failed", { code: roles.fault.code })} {explainRead(roles.fault)}</p>
{:else if roles.data}
  <form class="field" onsubmit={(e) => { e.preventDefault(); void saveAnalyst(); }}>
    <label for="role-analyst">{t("prov.analyst")}</label>
    <select id="role-analyst" class="input wide" bind:value={analyst} disabled={!g.canControl || busy._roles !== undefined}>
      {#each options as o (o)}<option value={o}>{o}</option>{/each}
      {#if !options.includes(analyst)}<option value={analyst}>{t("cfg.model_unlisted", { m: analyst })}</option>{/if}
    </select>
    <span class="hint">{t("prov.voters_role_hint", { list: roles.data.voters.map((v) => v.id + " " + v.provider + ":" + v.model).join(" · ") })}</span>
    {#if g.canControl}
      <div class="row"><button class="btn quiet" type="submit" disabled={busy._roles !== undefined || analyst === roles.data.analyst.provider + ":" + roles.data.analyst.model} aria-busy={busy._roles !== undefined}>{t("prov.roles_save")}</button></div>
    {/if}
  </form>
  {@render result("_roles")}
{/if}

{#if g.canControl}
  <h2 class="sec">{t("prov.add")}</h2>
  {#if editing === "+"}
    {@render editor()}
  {:else}
    <div class="inline-actions"><button class="btn quiet" type="button" onclick={() => startEdit(null)}>{t("prov.add")}</button></div>
  {/if}
  {@render result(form.id)}

  <h2 class="sec">{t("prov.import")} <span class="meta">{t("prov.import_meta")}</span></h2>
  {#if candidates.loading && !candidates.data}
    <div class="skel-rows"><span class="skeleton" style="width: 60%"></span><span class="skeleton" style="width: 50%"></span></div>
  {:else if candidates.fault && !candidates.data}
    <p class="note warn-text">{t("prov.import_failed", { code: candidates.fault.code })} {explainRead(candidates.fault)}</p>
  {:else if candidates.data}
    <p class="note">{t("prov.import_note")}</p>
    <div class="scroll">
      <table class="table">
        <thead><tr><th>Provider</th><th>{t("prov.imp_take")}</th><th>{t("prov.imp_key")}</th><th>{t("prov.imp_replace")}</th></tr></thead>
        <tbody>
          {#each candidates.data.providers as c (c.name)}
            <tr>
              <td><b>{c.name}</b>{#if c.exists}<span class="muted">{t("prov.imp_exists")}</span>{/if}<br /><span class="muted small">{c.type ?? "-"} · {c.host ?? "-"} · {t("prov.imp_models", { n: c.models.length })} · key {c.key_source}</span>{#if c.blocker}<br /><span class="small warn-text">{c.blocker}</span>{/if}</td>
              <td><label class="tick"><input type="checkbox" disabled={c.blocker !== null} checked={pick(c.name).take} onchange={(e) => (picks = { ...picks, [c.name]: { ...pick(c.name), take: e.currentTarget.checked } })} /><span class="sr-only">{t("prov.imp_take_label", { name: c.name })}</span></label></td>
              <td><label class="tick"><input type="checkbox" disabled={!keyable(c) || !pick(c.name).take} checked={pick(c.name).key} onchange={(e) => (picks = { ...picks, [c.name]: { ...pick(c.name), key: e.currentTarget.checked } })} /><span class="sr-only">{t("prov.imp_key_label", { name: c.name })}</span>{#if !keyable(c)}<span class="muted small">-</span>{/if}</label></td>
              <td><label class="tick"><input type="checkbox" disabled={!c.exists || !pick(c.name).take} checked={pick(c.name).replace} onchange={(e) => (picks = { ...picks, [c.name]: { ...pick(c.name), replace: e.currentTarget.checked } })} /><span class="sr-only">{t("prov.imp_replace_label", { name: c.name })}</span></label></td>
            </tr>
          {/each}
        </tbody>
      </table>
    </div>
    <div class="inline-actions">
      <button class="btn" type="button" disabled={!Object.values(picks).some((v) => v.take) || busy._import !== undefined} aria-busy={busy._import !== undefined} onclick={importPicked}>{busy._import ? t("prov.importing") : t("prov.import_go")}</button>
    </div>
    {@render result("_import")}
    {#if importResults.length}
      <ul class="results">
        {#each importResults as r (r.name)}<li><b>{r.name}</b> {RESULT[r.result] ?? r.result}{r.with_key ? t("prov.imp_with_key") : ""}{r.reason ? " · " + r.reason : ""}</li>{/each}
      </ul>
    {/if}
  {/if}
{/if}
{#if list.loadedAt}<p class="note num">{t("common.read_at", { at: clock(list.loadedAt, true) })}</p>{/if}

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
  .head {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: var(--space-3);
    padding: var(--space-3) var(--space-4);
  }
  .radios {
    padding: 0 var(--space-4);
  }
  .radios .check {
    padding-left: 0;
  }
  .row {
    padding-top: var(--space-2);
  }
  .scroll {
    overflow-x: auto;
  }
  .results {
    margin: 0;
    padding: 0 var(--space-4) var(--space-3);
    list-style: none;
    font-size: var(--step-0);
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
