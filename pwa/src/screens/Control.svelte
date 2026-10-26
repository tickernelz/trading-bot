<script lang="ts">
  import BotSwitch from "../components/BotSwitch.svelte";
  import Confirm from "../components/Confirm.svelte";
  import Outcome from "../components/Outcome.svelte";
  import { explain, explainRead, idempotencyKey, restartText, resultText, send, type Request } from "../lib/control";
  import { clock, dayClock, rupiah, signedPercent } from "../lib/format";
  import { gateway } from "../lib/gateway.svelte";
  import { t } from "../lib/i18n";
  import { Resource } from "../lib/resource.svelte";
  import type { Confirmation, ControlResult, Overview, Pairs, Trade } from "../lib/types";

  const g = gateway;
  let bot = $state(g.bots[0]?.id ?? "A");
  const q = (path: string) => path + (path.includes("?") ? "&" : "?") + "bot=" + encodeURIComponent(bot);

  const overview = new Resource(() => g.api.get<Overview>(q("/gw/v1/overview")));
  const open = new Resource(() => g.api.get<Trade[]>(q("/gw/v1/trades/open")));
  const pairs = new Resource(() => g.api.get<Pairs>(q("/gw/v1/pairs")));

  function reload() {
    void overview.load();
    void open.load();
    void pairs.load();
  }

  $effect(() => {
    void bot;
    void g.stateTick;
    reload();
  });

  interface Active {
    id: string;
    request: Request;
    key: string;
    confirmation: Confirmation | null;
    busy: boolean;
  }
  let active = $state<Active | null>(null);
  let notes = $state<Record<string, { ok: boolean; text: string }>>({});
  let lockPair = $state("");
  let lockHours = $state("4");
  let blackPair = $state("");

  const botState = $derived(overview.data?.state ?? (bot === g.bots[0]?.id && g.health ? (g.health.freqtrade.state as Overview["state"]) : null) ?? null);
  const entriesAllowed = $derived(overview.data?.risk.entries_allowed ?? null);
  const trades = $derived(open.data ?? []);
  const exposure = $derived(trades.reduce((s, t) => s + t.stake_amount, 0));
  const unrealized = $derived(trades.reduce((s, t) => s + t.profit_abs, 0));
  const whitelist = $derived(pairs.data?.whitelist.pairs ?? overview.data?.pairs.whitelist ?? []);
  const blacklist = $derived(pairs.data?.blacklist.pairs ?? []);
  const locks = $derived((pairs.data?.locks.locks ?? []).filter((l) => l.active));
  const perTrade = $derived(g.risk ? (g.risk.equity * g.risk.limits.risk_per_trade_pct) / 100 : null);
  const goneExits = $derived(Object.keys(notes).filter((id) => /^exit-\d+$/.test(id) && !trades.some((t) => "exit-" + t.trade_id === id)));
  const disabled = $derived(!g.canControl || active !== null);
  const dry = $derived(overview.data?.mode !== "live");

  const STATE_TEXT: Record<string, { big: string; small: string }> = {
    running: { big: t("ctl.running"), small: t("ctl.running_note") },
    paused: { big: t("ctl.paused"), small: t("ctl.paused_note") },
    stopped: { big: t("ctl.stopped"), small: t("ctl.stopped_note") },
  };

  function note(id: string, ok: boolean, text: string) {
    notes = { ...notes, [id]: { ok, text } };
  }

  async function handle(id: string, outcome: Awaited<ReturnType<typeof send<ControlResult>>>) {
    if (!active) return;
    if (outcome.kind === "confirm") {
      active = { ...active, confirmation: outcome.confirmation, busy: false };
      return;
    }
    active = null;
    if (outcome.kind === "done") note(id, true, t("ctl.done", { reply: resultText(outcome.result) }));
    else if (outcome.kind === "restart") note(id, false, restartText(outcome.reason));
    else note(id, false, explain(outcome.error));
    g.touchState();
  }

  async function run(id: string, request: Request) {
    const { [id]: _drop, ...rest } = notes;
    notes = rest;
    active = { id, request, key: idempotencyKey(), confirmation: null, busy: true };
    await handle(id, await send<ControlResult>(g.api, request, active.key));
  }

  async function confirm() {
    if (!active?.confirmation) return;
    const { id, request, key, confirmation } = active;
    active = { ...active, busy: true };
    await handle(id, await send<ControlResult>(g.api, request, key, confirmation.id));
  }

  function cancel() {
    if (active) note(active.id, false, t("common.cancelled"));
    active = null;
  }

  function untilIso(hours: number): string {
    return new Date(Date.now() + hours * 3600000).toISOString().replace(/\.\d{3}Z$/, "Z");
  }
</script>

{#snippet outcomeNote(id: string)}
  {#if notes[id]}
    <p class="result" class:warn-text={!notes[id].ok} class:done-text={notes[id].ok} role="status">{notes[id].text}</p>
  {/if}
{/snippet}

{#snippet confirmFor(id: string, text: string)}
  {#if active?.id === id && active.confirmation}
    <Confirm confirmation={active.confirmation} busy={active.busy} onconfirm={confirm} oncancel={cancel} consequence={text} />
  {/if}
{/snippet}

<div class="head">
  <BotSwitch bind:value={bot} label={t("ctl.bot_label")} />
  <span class="muted small">{g.bots.find((b) => b.id === bot)?.strategy ?? ""}</span>
</div>

<section class="verdict" aria-live="polite" aria-busy={overview.loading && !overview.data}>
  {#if overview.data && botState}
    <p class="big" class:warn-text={botState !== "running"}>{STATE_TEXT[botState]?.big ?? botState}</p>
    <p class="small">{STATE_TEXT[botState]?.small ?? ""}</p>
    <p class="small">
      {dry ? t("ctl.dry") : t("ctl.live")}
      {#if entriesAllowed === false}<span class="warn-text"> {t("ctl.risk_hold")}</span>{/if}
    </p>
  {:else if overview.fault}
    <p class="big warn-text">{t("ctl.unreadable")}</p>
    <p class="small">{explainRead(overview.fault)} ({overview.fault.code})</p>
    <button class="btn quiet" type="button" onclick={reload}>{t("common.retry")}</button>
  {:else}
    <span class="skeleton" style="width: 45%; height: 1.6em"></span>
    <span class="skeleton" style="width: 80%; margin-top: 8px"></span>
  {/if}
</section>

{#if g.token && !g.canControl}
  <p class="note scope">{t("ctl.remote_read")}</p>
{/if}

<h2 class="sec">Entry <span class="meta">{t("ctl.entry_meta")}</span></h2>
<div class="inline-actions">
  {#if botState === "running" || botState === null}
    <button class="btn kill" type="button" disabled={disabled || !botState} aria-busy={active?.id === "stop-entry" && active.busy} onclick={() => run("stop-entry", { method: "post", path: q("/gw/v1/control/stop-entry"), body: {} })}>
      {active?.id === "stop-entry" && active.busy ? t("common.sending") : t("ctl.stop_entry")}
    </button>
  {:else}
    <button class="btn" type="button" disabled={disabled} aria-busy={active?.id === "resume" && active.busy} onclick={() => run("resume", { method: "post", path: q("/gw/v1/control/resume"), body: {} })}>
      {active?.id === "resume" && active.busy ? t("common.sending") : botState === "stopped" ? t("ctl.start_bot") : t("ctl.resume")}
    </button>
  {/if}
  <button class="btn quiet" type="button" {disabled} onclick={() => run("reload", { method: "post", path: q("/gw/v1/control/reload-config"), body: {} })}>{t("ctl.reload")}</button>
</div>
<p class="note">{t("ctl.kill_note")}</p>
{@render confirmFor("stop-entry", "")}
{@render confirmFor("resume", perTrade === null ? "" : t("ctl.resume_risk", { idr: rupiah(perTrade) }))}
{@render outcomeNote("stop-entry")}
{@render outcomeNote("resume")}
{@render outcomeNote("reload")}

<h2 class="sec">{t("ctl.open")} <span class="meta num">{t("ctl.open_meta", { n: trades.length, idr: rupiah(exposure) })}</span></h2>
{#each goneExits as id (id)}{@render outcomeNote(id)}{/each}
{#if open.loading && !open.data}
  <div class="skel-rows"><span class="skeleton" style="width: 90%"></span><span class="skeleton" style="width: 75%"></span></div>
{:else if open.fault && !open.data}
  <p class="note warn-text">{t("ctl.open_failed", { code: open.fault.code })} {explainRead(open.fault)}</p>
{:else if trades.length === 0}
  <p class="note">{t("ctl.open_empty")}</p>
{:else}
  <ul class="list">
    {#each trades as tr (tr.trade_id)}
      <li>
        <div class="line">
          <span><b>{tr.pair}</b> <span class="muted small">#{tr.trade_id} · {dayClock(tr.open_timestamp)}</span></span>
          <span class="num"><Outcome value={tr.profit_pct_now ?? 0} /> <span class="small"><Outcome value={tr.profit_abs} unit="idr" word={false} /></span></span>
        </div>
        <button class="btn quiet" type="button" {disabled} onclick={() => run("exit-" + tr.trade_id, { method: "post", path: q("/gw/v1/trades/" + tr.trade_id + "/exit"), body: {} })}>{t("ctl.force_exit")}</button>
        {@render confirmFor("exit-" + tr.trade_id, t(tr.profit_abs < 0 ? "ctl.exit_loss" : "ctl.exit_gain", { stake: rupiah(tr.stake_amount), idr: rupiah(Math.abs(tr.profit_abs)), pct: signedPercent(tr.profit_pct_now ?? 0) }) + (dry ? " " + t("ctl.dry_mark") : ""))}
        {@render outcomeNote("exit-" + tr.trade_id)}
      </li>
    {/each}
  </ul>
  {#if trades.length > 1}
    <div class="inline-actions">
      <button class="btn quiet" type="button" {disabled} onclick={() => run("exit-all", { method: "post", path: q("/gw/v1/trades/exit-all"), body: {} })}>{t("ctl.exit_all")}</button>
    </div>
    {@render confirmFor("exit-all", t(unrealized < 0 ? "ctl.exit_all_loss" : "ctl.exit_all_gain", { n: trades.length, stake: rupiah(exposure), idr: rupiah(Math.abs(unrealized)) }))}
    {@render outcomeNote("exit-all")}
  {/if}
{/if}

<h2 class="sec">{t("ctl.locks")} <span class="meta">{t("ctl.locks_meta")}</span></h2>
{#if locks.length > 0}
  <ul class="list">
    {#each locks as l (l.id)}
      <li>
        <div class="line">
          <span><b>{l.pair}</b> <span class="muted small">{t("ctl.lock_until", { at: l.lock_end_time.slice(5, 16), reason: l.reason ?? t("ctl.no_reason") })}</span></span>
          <button class="btn quiet" type="button" {disabled} onclick={() => run("unlock-" + l.id, { method: "del", path: q("/gw/v1/locks/" + l.id), body: {} })}>{t("ctl.unlock")}</button>
        </div>
        {@render confirmFor("unlock-" + l.id, perTrade === null ? t("ctl.reenter", { pair: l.pair }) : t("ctl.reenter_risk", { pair: l.pair, idr: rupiah(perTrade) }))}
        {@render outcomeNote("unlock-" + l.id)}
      </li>
    {/each}
  </ul>
{:else if pairs.data}
  <p class="note">{t("ctl.locks_empty")}</p>
{/if}
<form class="inline-actions" onsubmit={(e) => { e.preventDefault(); if (lockPair) void run("lock", { method: "post", path: q("/gw/v1/locks"), body: { pair: lockPair, until: untilIso(Number(lockHours)), side: "*", reason: "manual PWA" } }); }}>
  <label class="sr-only" for="lock-pair">{t("ctl.lock_pair")}</label>
  <select id="lock-pair" class="input narrow" bind:value={lockPair} disabled={disabled}>
    <option value="">{t("ctl.pick_pair")}</option>
    {#each whitelist as p (p)}<option value={p}>{p}</option>{/each}
  </select>
  <label class="sr-only" for="lock-hours">{t("ctl.lock_for")}</label>
  <select id="lock-hours" class="input narrow" bind:value={lockHours} disabled={disabled}>
    <option value="1">{t("ctl.hours", { n: 1 })}</option>
    <option value="4">{t("ctl.hours", { n: 4 })}</option>
    <option value="24">{t("ctl.hours", { n: 24 })}</option>
  </select>
  <button class="btn quiet" type="submit" disabled={disabled || !lockPair}>{t("ctl.lock")}</button>
</form>
{@render confirmFor("lock", "")}
{@render outcomeNote("lock")}

<h2 class="sec">Blacklist <span class="meta num">{t("ctl.n_pairs", { n: blacklist.length })}</span></h2>
{#if blacklist.length > 0}
  <ul class="list">
    {#each blacklist as p (p)}
      <li>
        <div class="line">
          <b>{p}</b>
          <button class="btn quiet" type="button" {disabled} onclick={() => run("unblack-" + p, { method: "del", path: q("/gw/v1/blacklist?pairs=" + encodeURIComponent(p)), body: {} })}>{t("common.remove")}</button>
        </div>
        {@render confirmFor("unblack-" + p, perTrade === null ? t("ctl.reenter", { pair: p }) : t("ctl.reenter_risk", { pair: p, idr: rupiah(perTrade) }))}
        {@render outcomeNote("unblack-" + p)}
      </li>
    {/each}
  </ul>
{:else if pairs.data}
  <p class="note">{t("ctl.black_empty")}</p>
{/if}
<form class="inline-actions" onsubmit={(e) => { e.preventDefault(); if (blackPair) void run("black", { method: "post", path: q("/gw/v1/blacklist"), body: { pairs: [blackPair] } }); }}>
  <label class="sr-only" for="black-pair">{t("ctl.black_pair")}</label>
  <select id="black-pair" class="input narrow" bind:value={blackPair} disabled={disabled}>
    <option value="">{t("ctl.pick_pair")}</option>
    {#each whitelist.filter((p) => !blacklist.includes(p)) as p (p)}<option value={p}>{p}</option>{/each}
  </select>
  <button class="btn quiet" type="submit" disabled={disabled || !blackPair}>{t("ctl.black_add")}</button>
</form>
{@render outcomeNote("black")}

<h2 class="sec">{t("ctl.stop_bot")}</h2>
<p class="note">{t("ctl.stop_note")}</p>
<div class="inline-actions">
  <button class="btn quiet" type="button" disabled={disabled || botState === "stopped"} onclick={() => run("stop", { method: "post", path: q("/gw/v1/control/stop"), body: {} })}>{t("ctl.stop_bot")}</button>
</div>
{@render confirmFor("stop", trades.length > 0 ? t("ctl.stop_consequence", { n: trades.length, idr: rupiah(exposure) }) : t("ctl.stop_none"))}
{@render outcomeNote("stop")}
{#if overview.loadedAt}<p class="note num">{t("common.read_at", { at: clock(overview.loadedAt, true) })}</p>{/if}

<style>
  .head {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: var(--space-3);
    padding: var(--space-3) var(--space-4);
  }
  .verdict {
    display: grid;
    gap: 2px;
    padding: var(--space-4);
    background: var(--panel);
    border-top: 1px solid var(--rule);
    border-bottom: 1px solid var(--rule);
  }
  .verdict p {
    margin: 0;
  }
  .verdict .big {
    font-size: var(--step-2);
    font-weight: 650;
  }
  .small {
    font-size: var(--step--1);
    color: var(--ink2);
  }
  .scope {
    padding-top: var(--space-3);
  }
  .list {
    margin: 0;
    padding: 0;
    list-style: none;
  }
  .list > li {
    display: grid;
    gap: var(--space-2);
    padding: var(--space-2) var(--space-4);
    border-top: 1px solid var(--rule);
  }
  .list > li :global(.confirm) {
    margin-inline: 0;
  }
  .list > li > .btn {
    justify-self: start;
  }
  .line {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    justify-content: space-between;
    gap: var(--space-2);
  }
  .result {
    margin: 0;
    padding: 0 var(--space-4) var(--space-2);
    font-size: var(--step-0);
  }
  .list .result {
    padding: 0;
  }
  .narrow {
    width: auto;
    min-width: 9rem;
  }
</style>
