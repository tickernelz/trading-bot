<script lang="ts">
  import BotSwitch from "../components/BotSwitch.svelte";
  import Confirm from "../components/Confirm.svelte";
  import Outcome from "../components/Outcome.svelte";
  import { explain, explainRead, idempotencyKey, restartText, resultText, send, type Request } from "../lib/control";
  import { clock, dayClock, rupiah, signedPercent } from "../lib/format";
  import { gateway } from "../lib/gateway.svelte";
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
    running: { big: "Berjalan", small: "Bot memproses entry baru dan menjaga posisi terbuka." },
    paused: { big: "Entry dihentikan", small: "Tidak ada entry baru. Posisi terbuka tetap dijaga stop loss bot." },
    stopped: { big: "Bot berhenti", small: "Tidak ada entry baru dan posisi terbuka tidak dikelola bot." },
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
    if (outcome.kind === "done") note(id, true, "Selesai. Jawaban bot: " + resultText(outcome.result));
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
    if (active) note(active.id, false, "Dibatalkan. Tidak ada yang dijalankan.");
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
  <BotSwitch bind:value={bot} label="Bot yang dikendalikan" />
  <span class="muted small">{g.bots.find((b) => b.id === bot)?.strategy ?? ""}</span>
</div>

<section class="verdict" aria-live="polite" aria-busy={overview.loading && !overview.data}>
  {#if overview.data && botState}
    <p class="big" class:warn-text={botState !== "running"}>{STATE_TEXT[botState]?.big ?? botState}</p>
    <p class="small">{STATE_TEXT[botState]?.small ?? ""}</p>
    <p class="small">
      {dry ? "Dry-run, uang simulasi." : "Live, dana nyata."}
      {#if entriesAllowed === false}<span class="warn-text"> Lapisan risiko menahan entry baru (batas rugi terlewati); tombol di bawah tidak membukanya.</span>{/if}
    </p>
  {:else if overview.fault}
    <p class="big warn-text">Keadaan bot tidak terbaca</p>
    <p class="small">{explainRead(overview.fault)} ({overview.fault.code})</p>
    <button class="btn quiet" type="button" onclick={reload}>Coba lagi</button>
  {:else}
    <span class="skeleton" style="width: 45%; height: 1.6em"></span>
    <span class="skeleton" style="width: 80%; margin-top: 8px"></span>
  {/if}
</section>

{#if g.token && !g.canControl}
  <p class="note scope">Sesi jarak jauh hanya baca. Kontrol hanya dari PWA di PC bot (localhost); gateway menolak kontrol lewat tunnel atau jaringan.</p>
{/if}

<h2 class="sec">Entry <span class="meta">aksi yang menurunkan risiko langsung jalan</span></h2>
<div class="inline-actions">
  {#if botState === "running" || botState === null}
    <button class="btn kill" type="button" disabled={disabled || !botState} aria-busy={active?.id === "stop-entry" && active.busy} onclick={() => run("stop-entry", { method: "post", path: q("/gw/v1/control/stop-entry"), body: {} })}>
      {active?.id === "stop-entry" && active.busy ? "Mengirim…" : "Hentikan entry baru"}
    </button>
  {:else}
    <button class="btn" type="button" disabled={disabled} aria-busy={active?.id === "resume" && active.busy} onclick={() => run("resume", { method: "post", path: q("/gw/v1/control/resume"), body: {} })}>
      {active?.id === "resume" && active.busy ? "Mengirim…" : botState === "stopped" ? "Jalankan bot" : "Lanjutkan entry"}
    </button>
  {/if}
  <button class="btn quiet" type="button" {disabled} onclick={() => run("reload", { method: "post", path: q("/gw/v1/control/reload-config"), body: {} })}>Muat ulang config</button>
</div>
<p class="note">Hentikan entry adalah kill switch: posisi terbuka tetap dijaga stop loss bot. Gateway mengingatnya dan memasangnya lagi bila bot restart, sampai Lanjutkan entry ditekan.</p>
{@render confirmFor("stop-entry", "")}
{@render confirmFor("resume", perTrade === null ? "" : "Entry berikutnya memakai risiko sampai " + rupiah(perTrade) + " per trade.")}
{@render outcomeNote("stop-entry")}
{@render outcomeNote("resume")}
{@render outcomeNote("reload")}

<h2 class="sec">Posisi terbuka <span class="meta num">{trades.length} posisi · {rupiah(exposure)}</span></h2>
{#each goneExits as id (id)}{@render outcomeNote(id)}{/each}
{#if open.loading && !open.data}
  <div class="skel-rows"><span class="skeleton" style="width: 90%"></span><span class="skeleton" style="width: 75%"></span></div>
{:else if open.fault && !open.data}
  <p class="note warn-text">Posisi terbuka gagal dimuat ({open.fault.code}).</p>
{:else if trades.length === 0}
  <p class="note">Tidak ada posisi terbuka. Exit paksa muncul di sini saat bot memegang posisi.</p>
{:else}
  <ul class="list">
    {#each trades as t (t.trade_id)}
      <li>
        <div class="line">
          <span><b>{t.pair}</b> <span class="muted small">#{t.trade_id} · {dayClock(t.open_timestamp)}</span></span>
          <span class="num"><Outcome value={t.profit_pct_now ?? 0} /> <span class="small"><Outcome value={t.profit_abs} unit="idr" word={false} /></span></span>
        </div>
        <button class="btn quiet" type="button" {disabled} onclick={() => run("exit-" + t.trade_id, { method: "post", path: q("/gw/v1/trades/" + t.trade_id + "/exit"), body: {} })}>Exit paksa</button>
        {@render confirmFor("exit-" + t.trade_id, "Posisi " + rupiah(t.stake_amount) + ", saat ini " + (t.profit_abs < 0 ? "rugi " : "untung ") + rupiah(Math.abs(t.profit_abs)) + " (" + signedPercent(t.profit_pct_now ?? 0) + "). Exit di harga pasar menetapkan hasil itu" + (dry ? " (dry-run)." : "."))}
        {@render outcomeNote("exit-" + t.trade_id)}
      </li>
    {/each}
  </ul>
  {#if trades.length > 1}
    <div class="inline-actions">
      <button class="btn quiet" type="button" {disabled} onclick={() => run("exit-all", { method: "post", path: q("/gw/v1/trades/exit-all"), body: {} })}>Exit semua posisi</button>
    </div>
    {@render confirmFor("exit-all", trades.length + " posisi senilai " + rupiah(exposure) + ", saat ini " + (unrealized < 0 ? "rugi " : "untung ") + rupiah(Math.abs(unrealized)) + ". Semua ditutup di harga pasar.")}
    {@render outcomeNote("exit-all")}
  {/if}
{/if}

<h2 class="sec">Kunci pair <span class="meta">pair terkunci tidak dimasuki</span></h2>
{#if locks.length > 0}
  <ul class="list">
    {#each locks as l (l.id)}
      <li>
        <div class="line">
          <span><b>{l.pair}</b> <span class="muted small">sampai {l.lock_end_time.slice(5, 16)} · {l.reason ?? "tanpa alasan"}</span></span>
          <button class="btn quiet" type="button" {disabled} onclick={() => run("unlock-" + l.id, { method: "del", path: q("/gw/v1/locks/" + l.id), body: {} })}>Buka</button>
        </div>
        {@render confirmFor("unlock-" + l.id, l.pair + " bisa dimasuki lagi pada sinyal berikutnya" + (perTrade === null ? "." : ", sampai " + rupiah(perTrade) + " risiko per trade."))}
        {@render outcomeNote("unlock-" + l.id)}
      </li>
    {/each}
  </ul>
{:else if pairs.data}
  <p class="note">Tidak ada pair terkunci. Freqtrade juga mengunci pair satu kandel setelah exit; itu normal.</p>
{/if}
<form class="inline-actions" onsubmit={(e) => { e.preventDefault(); if (lockPair) void run("lock", { method: "post", path: q("/gw/v1/locks"), body: { pair: lockPair, until: untilIso(Number(lockHours)), side: "*", reason: "manual dari PWA" } }); }}>
  <label class="sr-only" for="lock-pair">Pair yang dikunci</label>
  <select id="lock-pair" class="input narrow" bind:value={lockPair} disabled={disabled}>
    <option value="">Pilih pair</option>
    {#each whitelist as p (p)}<option value={p}>{p}</option>{/each}
  </select>
  <label class="sr-only" for="lock-hours">Lama kunci</label>
  <select id="lock-hours" class="input narrow" bind:value={lockHours} disabled={disabled}>
    <option value="1">1 jam</option>
    <option value="4">4 jam</option>
    <option value="24">24 jam</option>
  </select>
  <button class="btn quiet" type="submit" disabled={disabled || !lockPair}>Kunci</button>
</form>
{@render confirmFor("lock", "")}
{@render outcomeNote("lock")}

<h2 class="sec">Blacklist <span class="meta num">{blacklist.length} pair</span></h2>
{#if blacklist.length > 0}
  <ul class="list">
    {#each blacklist as p (p)}
      <li>
        <div class="line">
          <b>{p}</b>
          <button class="btn quiet" type="button" {disabled} onclick={() => run("unblack-" + p, { method: "del", path: q("/gw/v1/blacklist?pairs=" + encodeURIComponent(p)), body: {} })}>Hapus</button>
        </div>
        {@render confirmFor("unblack-" + p, p + " kembali bisa dimasuki" + (perTrade === null ? "." : ", sampai " + rupiah(perTrade) + " risiko per trade."))}
        {@render outcomeNote("unblack-" + p)}
      </li>
    {/each}
  </ul>
{:else if pairs.data}
  <p class="note">Blacklist kosong. Pair di blacklist tidak dimasuki sampai dihapus.</p>
{/if}
<form class="inline-actions" onsubmit={(e) => { e.preventDefault(); if (blackPair) void run("black", { method: "post", path: q("/gw/v1/blacklist"), body: { pairs: [blackPair] } }); }}>
  <label class="sr-only" for="black-pair">Pair untuk blacklist</label>
  <select id="black-pair" class="input narrow" bind:value={blackPair} disabled={disabled}>
    <option value="">Pilih pair</option>
    {#each whitelist.filter((p) => !blacklist.includes(p)) as p (p)}<option value={p}>{p}</option>{/each}
  </select>
  <button class="btn quiet" type="submit" disabled={disabled || !blackPair}>Tambah ke blacklist</button>
</form>
{@render outcomeNote("black")}

<h2 class="sec">Hentikan bot</h2>
<p class="note">Bot berhenti total: tidak ada entry baru dan posisi terbuka tidak dikelola, termasuk stop loss di sisi bot. Untuk berhenti aman, pakai Hentikan entry baru.</p>
<div class="inline-actions">
  <button class="btn quiet" type="button" disabled={disabled || botState === "stopped"} onclick={() => run("stop", { method: "post", path: q("/gw/v1/control/stop"), body: {} })}>Hentikan bot</button>
</div>
{@render confirmFor("stop", trades.length > 0 ? trades.length + " posisi senilai " + rupiah(exposure) + " tidak dijaga stop loss bot sampai bot dijalankan lagi." : "Tidak ada posisi terbuka saat ini.")}
{@render outcomeNote("stop")}
{#if overview.loadedAt}<p class="note num">Keadaan dibaca {clock(overview.loadedAt, true)}.</p>{/if}

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
