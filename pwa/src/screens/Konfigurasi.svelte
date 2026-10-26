<script lang="ts">
  import BotSwitch from "../components/BotSwitch.svelte";
  import Confirm from "../components/Confirm.svelte";
  import NumField from "../components/NumField.svelte";
  import { actionLabel, show } from "../lib/audit";
  import { explain, explainRead, idempotencyKey, restartText, send } from "../lib/control";
  import { clock, dayClock, rupiah } from "../lib/format";
  import { gateway } from "../lib/gateway.svelte";
  import { t } from "../lib/i18n";
  import { Resource } from "../lib/resource.svelte";
  import { anyNeedsConfirmation, diff, direction, EDITABLE, errorsFor, needsConfirmation, nextVoterId, patchBody, rupiahOf, schemaErrors, validate, validateVoter, type FieldError } from "../lib/settings";
  import type { ChangeEntry, Confirmation, Settings, VoterFields, VoterList, VoterView, WriteResult } from "../lib/types";

  const g = gateway;
  let bot = $state(g.bots[0]?.id ?? "A");
  const q = () => "bot=" + encodeURIComponent(bot);
  const doc = new Resource(() => g.api.get<Settings>("/gw/v1/settings?" + q()));
  const voters = new Resource(() => g.api.get<VoterList>("/gw/v1/voters?" + q()));
  const log = new Resource(() => g.api.get<ChangeEntry[]>("/gw/v1/settings/changes?limit=50&" + q()));

  let draft = $state<Settings | null>(null);
  let step = $state<"edit" | "review">("edit");
  let busy = $state(false);
  let key = "";
  let confirmation = $state<Confirmation | null>(null);
  let serverErrors = $state<FieldError[]>([]);
  let message = $state<{ ok: boolean; text: string } | null>(null);
  let newPair = $state("");

  let editing = $state<string | null>(null);
  let voterForm = $state<VoterFields & { id: string }>({ id: "", adapter: "llm_structured", provider: "", model: "", variation: "option_order", timeout_s: 30, weight: 1, enabled: true });
  let voterBusy = $state(false);
  let voterNote = $state<{ ok: boolean; text: string } | null>(null);
  let voterServer = $state<string | null>(null);

  async function reload() {
    await doc.load();
    if (doc.data) draft = $state.snapshot(doc.data) as Settings;
    step = "edit";
    confirmation = null;
    serverErrors = [];
    void voters.load();
    void log.load();
  }

  $effect(() => {
    void bot;
    message = null;
    voterNote = null;
    editing = null;
    void reload();
  });

  const base = $derived(doc.data);
  const changes = $derived(base && draft ? diff(base, draft) : []);
  const enabledVoters = $derived(voters.data?.voters.filter((v) => v.enabled).length ?? draft?.swarm.voters.filter((v) => v.enabled).length ?? 0);
  const errors = $derived([...(draft ? validate(draft, enabledVoters) : []), ...serverErrors]);
  const changed = $derived(new Set(changes.map((c) => c.key)));
  const capital = $derived(draft?.capital.initial_idr ?? 0);
  const providers = $derived(draft?.providers ?? []);
  const voterIds = $derived((voters.data?.voters ?? []).map((v) => v.id));
  const voterErrors = $derived(editing ? validateVoter(voterForm.id, voterForm, providers, editing === "+" ? voterIds : voterIds.filter((id) => id !== editing)) : []);
  const groups = $derived.by(() => {
    const out: { id: number; ts: string; actor: string; action: string; items: ChangeEntry[] }[] = [];
    for (const e of log.data ?? []) {
      const last = out.at(-1);
      if (last && last.id === e.audit_id) last.items.push(e);
      else out.push({ id: e.audit_id, ts: e.ts, actor: e.actor, action: e.action, items: [e] });
    }
    return out;
  });

  const err = (k: string) => errorsFor(errors, k);
  const was = (k: string) => {
    const c = changes.find((x) => x.key === k);
    return c ? show(c.old) : null;
  };

  function addPair() {
    const p = newPair.trim().toUpperCase();
    if (draft && p) draft.exchange.pairs.push(p);
    newPair = "";
  }

  function discard() {
    if (doc.data) draft = $state.snapshot(doc.data) as Settings;
    step = "edit";
    serverErrors = [];
  }

  function failText(e: { code: string; message: string }): string {
    if (e.code !== "invalid_request") return explain(e);
    const parsed = schemaErrors(e.message, EDITABLE);
    serverErrors = parsed.fields;
    return t("cfg.rejected") + (parsed.rest.length ? " " + parsed.rest.join("; ") : "");
  }

  async function save(confirm?: string) {
    if (!confirm) key = idempotencyKey();
    busy = true;
    const outcome = await send<WriteResult>(g.api, { method: "patch", path: "/gw/v1/settings?" + q(), body: { changes: patchBody(changes) } }, key, confirm);
    busy = false;
    if (outcome.kind === "confirm") {
      confirmation = outcome.confirmation;
      return;
    }
    confirmation = null;
    if (outcome.kind === "done") {
      await reload();
      message = { ok: true, text: t("cfg.saved", { n: outcome.result.changes.length }) + (outcome.result.restart_required ? " " + t("cfg.restart_required") : "") };
      return;
    }
    if (outcome.kind === "restart") {
      message = { ok: false, text: restartText(outcome.reason) };
      return;
    }
    message = { ok: false, text: failText(outcome.error) };
    if (serverErrors.length) step = "edit";
  }

  function startVoter(v: VoterView | null) {
    voterNote = null;
    voterServer = null;
    if (v) {
      editing = v.id;
      voterForm = { id: v.id, adapter: v.adapter, provider: v.provider, model: v.model, variation: v.variation, timeout_s: v.timeout_s, weight: v.weight, enabled: v.enabled };
      return;
    }
    const last = voters.data?.voters.at(-1);
    const provider = last?.provider ?? providers[0]?.id ?? "";
    const model = last?.model ?? providers.find((p) => p.id === provider)?.models[0] ?? "";
    editing = "+";
    voterForm = { id: nextVoterId(voterIds), adapter: "llm_structured", provider, model, variation: "option_order", timeout_s: 30, weight: 1, enabled: true };
  }

  async function voterWrite(method: "put" | "del", id: string, body: Record<string, unknown>) {
    voterBusy = true;
    voterServer = null;
    const outcome = await send<WriteResult>(g.api, { method, path: "/gw/v1/voters/" + encodeURIComponent(id) + "?" + q(), body }, idempotencyKey());
    voterBusy = false;
    if (outcome.kind === "done") {
      voterNote = { ok: true, text: (method === "del" ? t("cfg.voter_removed", { id }) : t("cfg.voter_saved", { id })) + (outcome.result.restart_required ? " " + t("cfg.restart_required") : "") };
      editing = null;
      void reload();
      return;
    }
    const text = outcome.kind === "failed" ? (outcome.error.code === "invalid_request" ? outcome.error.message : explain(outcome.error)) : t("common.not_run");
    voterServer = text;
    voterNote = { ok: false, text };
  }

  function saveVoter() {
    const { id, ...fields } = $state.snapshot(voterForm);
    void voterWrite("put", id, fields);
  }

  const DIRECTION_TEXT = { naik: t("cfg.dir_up"), turun: t("cfg.dir_down"), netral: "" } as const;
  const ADAPTERS = ["llm_structured", "systemone", "openrouter_decisions", "openai_decisions"] as const;
  const VARIATIONS = [
    { id: "option_order", label: t("cfg.var_order") },
    { id: "temperature", label: t("cfg.var_temp") },
    { id: "prompt_variant", label: t("cfg.var_prompt") },
  ] as const;
  const actorText = (actor: string) => (actor === "file" ? t("cfg.actor_file") : actor);
</script>

<div class="head">
  <BotSwitch bind:value={bot} label={t("cfg.bot_label")} />
  <span class="muted small">{t("cfg.per_bot")}</span>
</div>

{#if !g.canControl}
  <p class="note scope">{t("cfg.remote_read")}</p>
{/if}

{#if message}
  <p class="result" class:warn-text={!message.ok} class:done-text={message.ok} role="status">{message.text}</p>
{/if}

{#if doc.loading && !draft}
  <div class="skel-rows" aria-busy="true" aria-label={t("cfg.loading")}>
    <span class="skeleton" style="width: 30%"></span><span class="skeleton" style="width: 60%"></span><span class="skeleton" style="width: 55%"></span><span class="skeleton" style="width: 62%"></span>
  </div>
{:else if doc.fault && !draft}
  <p class="note warn-text">{t("cfg.load_failed", { code: doc.fault.code })} {explainRead(doc.fault)}</p>
  <div class="inline-actions"><button class="btn quiet" type="button" onclick={reload}>{t("common.retry")}</button></div>
{:else if draft && step === "edit"}
  <form onsubmit={(e) => { e.preventDefault(); message = null; step = "review"; }}>
    <fieldset disabled={busy || !g.canControl}>
      <legend class="sec">{t("cfg.risk")} <span class="meta">{t("cfg.mode", { mode: draft.mode === "dry_run" ? "dry-run" : draft.mode })}</span></legend>
      <NumField id="r-daily" label={t("cfg.daily")} unit="%" step="0.1" bind:value={draft.risk.max_daily_loss_pct} error={err("risk.max_daily_loss_pct")} was={was("risk.max_daily_loss_pct")} hint={t("cfg.daily_hint", { idr: rupiah(rupiahOf(capital, draft.risk.max_daily_loss_pct)), capital: rupiah(capital) })} />
      <NumField id="r-total" label={t("cfg.total")} unit="%" step="0.5" bind:value={draft.risk.max_total_drawdown_pct} error={err("risk.max_total_drawdown_pct")} was={was("risk.max_total_drawdown_pct")} hint={t("cfg.total_hint", { idr: rupiah(rupiahOf(capital, draft.risk.max_total_drawdown_pct)) })} />
      <NumField id="r-trade" label={t("cfg.per_trade")} unit="%" step="0.1" bind:value={draft.risk.risk_per_trade_pct} error={err("risk.risk_per_trade_pct")} was={was("risk.risk_per_trade_pct")} hint={t("cfg.per_trade_hint", { idr: rupiah(rupiahOf(capital, draft.risk.risk_per_trade_pct)) })} />
      <NumField id="r-open" label={t("cfg.open_trades")} step="1" bind:value={draft.risk.max_open_trades} error={err("risk.max_open_trades")} was={was("risk.max_open_trades")} />
      <p class="note">{t("cfg.fixed_note", { tz: draft.risk.daily_reset_timezone })}</p>
    </fieldset>

    <fieldset disabled={busy || !g.canControl}>
      <legend class="sec">{t("cfg.capital")}</legend>
      <NumField id="c-cap" label={t("cfg.capital_initial")} unit="Rp" step="10000" bind:value={draft.capital.initial_idr} error={err("capital.initial_idr")} was={was("capital.initial_idr")} hint={t("cfg.capital_hint")} />
      <label class="check"><input type="checkbox" bind:checked={draft.capital.compounding} /> {t("cfg.compounding")}{#if changed.has("capital.compounding")}<span class="muted small">{t("cfg.changed_mark")}</span>{/if}</label>
    </fieldset>

    <fieldset disabled={busy || !g.canControl}>
      <legend class="sec">{t("cfg.exchange")} <span class="meta">{draft.exchange.name} · {draft.exchange.timeframe}</span></legend>
      <div class="field">
        <span class="label" id="pairs-l">{t("cfg.pairs")}</span>
        <ul class="pairs" aria-labelledby="pairs-l">
          {#each draft.exchange.pairs as p, i (p + i)}
            <li><span class="num">{p}</span> <button type="button" class="x" aria-label={t("cfg.pair_remove_label", { pair: p })} onclick={() => draft?.exchange.pairs.splice(i, 1)}>{t("common.remove")}</button></li>
          {/each}
        </ul>
        <div class="add">
          <label class="sr-only" for="pair-new">{t("cfg.pair_new")}</label>
          <input id="pair-new" class="input narrow" placeholder="ADA/IDR" bind:value={newPair} onkeydown={(e) => { if (e.key === "Enter") { e.preventDefault(); addPair(); } }} />
          <button class="btn quiet" type="button" disabled={!newPair.trim()} onclick={addPair}>{t("cfg.pair_add")}</button>
        </div>
        {#if err("exchange.pairs")}<span class="err">{err("exchange.pairs")}</span>{/if}
      </div>
      <NumField id="x-fee" label={t("cfg.fee")} unit="%" step="0.01" bind:value={draft.exchange.fee_pct} error={err("exchange.fee_pct")} was={was("exchange.fee_pct")} />
    </fieldset>

    <fieldset disabled={busy || !g.canControl}>
      <legend class="sec">Swarm</legend>
      <label class="check"><input type="checkbox" bind:checked={draft.swarm.enabled} /> {t("cfg.swarm_on")}</label>
      <div class="field">
        <span class="label" id="mode-l">{t("cfg.swarm_mode")}</span>
        <div class="radios" role="radiogroup" aria-labelledby="mode-l">
          <label class="check"><input type="radio" value="shadow" bind:group={draft.swarm.mode} /> {t("cfg.mode_shadow")}</label>
          <label class="check"><input type="radio" value="veto" bind:group={draft.swarm.mode} /> {t("cfg.mode_veto")}</label>
        </div>
        <span class="hint">{t("cfg.mode_hint")}</span>
        {#if was("swarm.mode") !== null}<span class="hint was">{t("cfg.was", { v: was("swarm.mode") ?? "" })}</span>{/if}
      </div>
      <label class="check"><input type="checkbox" bind:checked={draft.swarm.shuffle_options} /> {t("cfg.shuffle")}</label>
      <NumField id="s-quorum" label={t("cfg.quorum")} step="1" bind:value={draft.swarm.min_voters_answered} error={err("swarm.min_voters_answered")} was={was("swarm.min_voters_answered")} hint={t("cfg.quorum_hint", { n: enabledVoters })} />
      <NumField id="s-spread" label={t("cfg.spread")} step="0.01" optional bind:value={draft.swarm.max_spread} error={err("swarm.max_spread")} was={was("swarm.max_spread")} hint={t("cfg.spread_hint")} />
    </fieldset>

    <fieldset disabled={busy || !g.canControl}>
      <legend class="sec">{t("cfg.compute")} <span class="meta">{t("cfg.compute_meta")}</span></legend>
      <label class="check"><input type="checkbox" checked={draft.compute.max_cost_idr_per_day !== false} onchange={(e) => { if (draft) draft.compute.max_cost_idr_per_day = e.currentTarget.checked ? 50000 : false; }} /> {t("cfg.cost_cap")}</label>
      {#if draft.compute.max_cost_idr_per_day !== false}
        <NumField id="cost" label={t("cfg.cost_max")} unit="Rp" step="1000" bind:value={() => (draft?.compute.max_cost_idr_per_day === false ? null : (draft?.compute.max_cost_idr_per_day ?? null)), (v) => { if (draft) draft.compute.max_cost_idr_per_day = v ?? 0; }} error={err("compute.max_cost_idr_per_day")} was={was("compute.max_cost_idr_per_day")} hint={t("cfg.cost_hint")} />
      {/if}
      <label class="check"><input type="checkbox" bind:checked={draft.compute.log_cost} /> {t("cfg.log_cost")}</label>
    </fieldset>

    <fieldset disabled={busy || !g.canControl}>
      <legend class="sec">{t("cfg.data")}</legend>
      <label class="check"><input type="checkbox" bind:checked={draft.data.fear_greed} /> Fear and Greed Index</label>
      <label class="check"><input type="checkbox" bind:checked={draft.data.social} /> {t("cfg.social")}</label>
      <p class="note">{t("cfg.rss", { list: draft.data.news_rss.join(", ") || "-" })}</p>
      <label class="check"><input type="checkbox" bind:checked={draft.notify.web_push} /> Web Push</label>
    </fieldset>

    <div class="bar" aria-live="polite">
      <span class="num">{changes.length === 0 ? t("cfg.no_changes") : t("cfg.n_changes", { n: changes.length })}{#if errors.length > 0} · <span class="warn-text">{t("cfg.n_errors", { n: errors.length })}</span>{/if}</span>
      <span class="actions">
        <button class="btn secondary" type="button" disabled={changes.length === 0} onclick={discard}>{t("cfg.discard")}</button>
        <button class="btn" type="submit" disabled={!g.canControl || changes.length === 0 || errors.length > 0}>{t("cfg.review")}</button>
      </span>
    </div>
  </form>
{:else if draft && step === "review"}
  <h2 class="sec">{t("cfg.review")} <span class="meta">Bot {bot}</span></h2>
  <table class="table">
    <thead><tr><th>{t("cfg.col_key")}</th><th>{t("cfg.col_old")}</th><th>{t("cfg.col_new")}</th></tr></thead>
    <tbody>
      {#each changes as c (c.key)}
        {@const d = direction(c)}
        <tr>
          <td><code>{c.key}</code>{#if d !== "netral"}<br /><span class="small" class:warn-text={d === "naik"}>{DIRECTION_TEXT[d]}</span>{/if}</td>
          <td class="num">{show(c.old)}</td>
          <td class="num"><b>{show(c.new)}</b></td>
        </tr>
      {/each}
    </tbody>
  </table>
  {#if anyNeedsConfirmation(changes)}<p class="note warn-text">{t("cfg.needs_confirm", { keys: changes.filter(needsConfirmation).map((c) => c.key).join(", ") })}</p>{/if}
  <p class="note">{t("cfg.restart_note")}</p>
  {#if confirmation}
    <Confirm {confirmation} {busy} onconfirm={() => save(confirmation?.id)} oncancel={() => { confirmation = null; message = { ok: false, text: t("common.cancelled") }; }} consequence={t("cfg.confirm_consequence", { bot })} />
  {:else}
    <div class="inline-actions">
      <button class="btn" type="button" disabled={busy || !g.canControl} aria-busy={busy} onclick={() => save()}>{busy ? t("common.saving") : t("common.save")}</button>
      <button class="btn secondary" type="button" disabled={busy} onclick={() => (step = "edit")}>{t("cfg.back")}</button>
    </div>
  {/if}
{/if}

<h2 class="sec">{t("cfg.voters")} <span class="meta num">{voters.data ? t("cfg.voters_meta", { n: voters.data.voters.length, active: voters.data.swarm.enabled_voters, quorum: voters.data.swarm.min_voters_answered }) : ""}</span></h2>
{#if voterNote}<p class="result" class:warn-text={!voterNote.ok} class:done-text={voterNote.ok} role="status">{voterNote.text}</p>{/if}
{#if voters.loading && !voters.data}
  <div class="skel-rows" aria-busy="true"><span class="skeleton" style="width: 70%"></span><span class="skeleton" style="width: 60%"></span></div>
{:else if voters.fault && !voters.data}
  <p class="note warn-text">{t("cfg.voters_failed", { code: voters.fault.code })} {explainRead(voters.fault)}</p>
{:else if voters.data}
  <ul class="voters">
    {#each voters.data.voters as v (v.id)}
      <li class:off={!v.enabled}>
        <div class="vhead">
          <span><b>{v.id}</b> <span class="muted">{v.enabled ? t("cfg.voter_on") : t("cfg.voter_off")}</span><br /><span class="small">{v.provider} · {v.model} · {VARIATIONS.find((x) => x.id === v.variation)?.label ?? v.variation} · {t("cfg.voter_timeout", { s: v.timeout_s })} · {t("cfg.voter_weight", { w: v.weight })}</span></span>
          {#if g.canControl && editing !== v.id}<button type="button" class="btn quiet" disabled={voterBusy || editing !== null} onclick={() => startVoter(v)}>{t("common.edit")}</button>{/if}
        </div>
        {#if editing === v.id}{@render voterEditor()}{/if}
      </li>
    {:else}
      <li><p class="note">{t("cfg.voters_empty")}</p></li>
    {/each}
  </ul>
  {#if g.canControl}
    {#if editing === "+"}
      {@render voterEditor()}
    {:else}
      <div class="inline-actions"><button class="btn quiet" type="button" disabled={editing !== null} onclick={() => startVoter(null)}>{t("cfg.voter_add")}</button></div>
    {/if}
  {/if}
  <p class="note">{t("cfg.voters_note")}</p>
{/if}

{#snippet voterEditor()}
  {@const models = providers.find((p) => p.id === voterForm.provider)?.models ?? []}
  <form class="editor" onsubmit={(e) => { e.preventDefault(); if (voterErrors.length === 0) saveVoter(); }}>
    <p class="title">{editing === "+" ? t("cfg.voter_new") : t("cfg.voter_edit", { id: editing ?? "" })}</p>
    <div class="vgrid">
      <div class="field">
        <label for="vf-id">Id</label>
        <input id="vf-id" class="input" bind:value={voterForm.id} disabled={editing !== "+"} autocomplete="off" spellcheck="false" aria-invalid={errorsFor(voterErrors, "id") ? "true" : undefined} />
        {#if errorsFor(voterErrors, "id")}<span class="err">{errorsFor(voterErrors, "id")}</span>{/if}
      </div>
      <div class="field">
        <label for="vf-p">Provider</label>
        <select id="vf-p" class="input" bind:value={voterForm.provider} onchange={() => (voterForm.model = models[0] ?? providers.find((p) => p.id === voterForm.provider)?.models[0] ?? "")}>
          {#each providers as p (p.id)}<option value={p.id}>{p.id}</option>{/each}
        </select>
        {#if errorsFor(voterErrors, "provider")}<span class="err">{errorsFor(voterErrors, "provider")}</span>{/if}
      </div>
      <div class="field">
        <label for="vf-m">{t("cfg.model")}</label>
        <select id="vf-m" class="input" bind:value={voterForm.model} aria-invalid={errorsFor(voterErrors, "model") ? "true" : undefined}>
          {#each models as m (m)}<option value={m}>{m}</option>{/each}
          {#if !models.includes(voterForm.model)}<option value={voterForm.model}>{t("cfg.model_unlisted", { m: voterForm.model })}</option>{/if}
        </select>
        {#if errorsFor(voterErrors, "model")}<span class="err">{errorsFor(voterErrors, "model")}</span>{/if}
      </div>
      <div class="field">
        <label for="vf-a">Adapter</label>
        <select id="vf-a" class="input" bind:value={voterForm.adapter}>{#each ADAPTERS as a (a)}<option value={a}>{a}</option>{/each}</select>
      </div>
      <div class="field">
        <label for="vf-v">{t("cfg.variation")}</label>
        <select id="vf-v" class="input" bind:value={voterForm.variation}>{#each VARIATIONS as v (v.id)}<option value={v.id}>{v.label}</option>{/each}</select>
      </div>
      <NumField id="vf-t" label={t("cfg.timeout")} unit={t("dur.unit_s")} step="1" bind:value={voterForm.timeout_s} error={errorsFor(voterErrors, "timeout_s")} />
      <NumField id="vf-w" label={t("cfg.weight")} step="0.1" bind:value={voterForm.weight} error={errorsFor(voterErrors, "weight")} />
    </div>
    <label class="check"><input type="checkbox" bind:checked={voterForm.enabled} /> {t("cfg.voter_enabled")}</label>
    {#if voterServer}<p class="note warn-text">{voterServer}</p>{/if}
    <div class="inline-actions">
      <button class="btn" type="submit" disabled={voterBusy || voterErrors.length > 0} aria-busy={voterBusy}>{voterBusy ? t("common.saving") : t("cfg.voter_save")}</button>
      {#if editing !== "+"}<button class="btn quiet" type="button" disabled={voterBusy} onclick={() => voterWrite("del", voterForm.id, {})}>{t("cfg.voter_delete")}</button>{/if}
      <button class="btn secondary" type="button" disabled={voterBusy} onclick={() => { editing = null; voterServer = null; }}>{t("common.cancel")}</button>
    </div>
  </form>
{/snippet}

<h2 class="sec">{t("cfg.log")} <span class="meta">{t("cfg.log_meta")}</span></h2>
{#if log.loading && !log.data}
  <div class="skel-rows"><span class="skeleton" style="width: 70%"></span><span class="skeleton" style="width: 50%"></span></div>
{:else if log.fault && !log.data}
  <p class="note warn-text">{t("cfg.log_failed", { code: log.fault.code })} {explainRead(log.fault)}</p>
{:else if groups.length === 0}
  <p class="note">{t("cfg.log_empty")}</p>
{:else}
  <ol class="log">
    {#each groups as row (row.id)}
      <li>
        <p><span class="num muted">{dayClock(row.ts)}</span> <b>{actionLabel(row.action)}</b> <span class="muted">{t("cfg.by", { actor: actorText(row.actor) })}</span></p>
        {#each row.items as c (c.key)}
          <p class="small"><code>{c.key}</code> {show(c.old)} → <b>{show(c.new)}</b></p>
        {/each}
      </li>
    {/each}
  </ol>
{/if}
{#if doc.loadedAt}<p class="note num">{t("common.read_at", { at: clock(doc.loadedAt, true) })}</p>{/if}

<style>
  .head {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: var(--space-3);
    padding: var(--space-3) var(--space-4);
  }
  .small {
    font-size: var(--step--1);
    color: var(--ink2);
  }
  .scope {
    padding-top: var(--space-1);
  }
  .editor {
    margin: var(--space-2) var(--space-4) var(--space-3);
    padding: var(--space-2) 0;
    border-radius: var(--radius);
    box-shadow: inset 0 0 0 1px var(--rule-strong);
  }
  .editor .title {
    margin: 0;
    padding: var(--space-2) var(--space-4) 0;
    font-weight: 650;
  }
  .result {
    margin: 0;
    padding: var(--space-2) var(--space-4);
  }
  fieldset {
    margin: 0;
    padding: 0 0 var(--space-3);
    border: 0;
    min-width: 0;
  }
  legend.sec {
    width: 100%;
    font-weight: 600;
  }
  .pairs {
    display: flex;
    flex-wrap: wrap;
    gap: var(--space-2);
    margin: 0;
    padding: 0;
    list-style: none;
  }
  .pairs li {
    display: inline-flex;
    align-items: center;
    gap: var(--space-1);
    padding-left: var(--space-3);
    border-radius: var(--radius);
    box-shadow: inset 0 0 0 1px var(--rule-strong);
  }
  .add {
    display: flex;
    flex-wrap: wrap;
    gap: var(--space-2);
  }
  .narrow {
    width: auto;
    max-width: 12rem;
  }
  .x {
    min-height: 44px;
    padding: 0 var(--space-3);
    border: 0;
    background: transparent;
    color: var(--ink2);
    text-decoration: underline;
    cursor: pointer;
  }
  .x:hover {
    color: var(--loss);
  }
  .radios .check {
    padding-left: 0;
  }
  .voters {
    margin: 0;
    padding: 0;
    list-style: none;
  }
  .voters > li {
    padding: var(--space-2) 0;
    border-top: 1px solid var(--rule);
  }
  .voters > li.off .vhead {
    color: var(--ink2);
  }
  .vhead {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: var(--space-2);
    padding: 0 var(--space-4);
  }
  .vgrid {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
    transition: opacity var(--t) var(--ease);
  }
  .bar {
    position: sticky;
    bottom: calc(var(--nav-h) + env(safe-area-inset-bottom));
    z-index: 10;
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    justify-content: space-between;
    gap: var(--space-2);
    padding: var(--space-3) var(--space-4);
    background: var(--bg);
    border-top: 1px solid var(--rule-strong);
    font-size: var(--step-0);
  }
  .actions {
    display: flex;
    gap: var(--space-2);
  }
  code {
    font-family: inherit;
    font-size: var(--step--1);
    overflow-wrap: anywhere;
  }
  .log {
    margin: 0;
    padding: 0 0 var(--space-3);
    list-style: none;
  }
  .log li {
    padding: var(--space-2) var(--space-4);
    border-top: 1px solid var(--rule);
  }
  .log p {
    margin: 0;
    font-size: var(--step-0);
    overflow-wrap: anywhere;
  }
  @media (min-width: 960px) {
    .bar {
      bottom: 0;
    }
  }
</style>
