<script lang="ts">
  import { ACTION_GROUPS, actionLabel, auditPath, changeLines, isProblem, matches, RESULTS, resultLabel, show } from "../lib/audit";
  import { explainRead } from "../lib/control";
  import { dayClock } from "../lib/format";
  import { gateway } from "../lib/gateway.svelte";
  import { t } from "../lib/i18n";
  import { faultOf, type Fault } from "../lib/state";
  import type { AuditRow } from "../lib/types";

  const g = gateway;
  const PAGE = 50;
  let action = $state("");
  let result = $state("");
  let target = $state("");
  let rows = $state<AuditRow[]>([]);
  let loading = $state(false);
  let fault = $state<Fault | null>(null);
  let more = $state(false);
  let open = $state<number | null>(null);

  async function load(append: boolean) {
    loading = true;
    try {
      const page = await g.api.get<AuditRow[]>(auditPath(action, result, append ? (rows.at(-1)?.id ?? null) : null, PAGE, target));
      rows = append ? [...rows, ...page] : page;
      more = page.length === PAGE;
      fault = null;
    } catch (error) {
      fault = faultOf(error, Date.now());
    } finally {
      loading = false;
    }
  }

  $effect(() => {
    void action;
    void result;
    void target;
    open = null;
    void load(false);
  });

  $effect(() => {
    const fresh = g.auditLive.filter((r) => matches(r, action, result, target) && !rows.some((x) => x.id === r.id) && r.id > (rows[0]?.id ?? 0));
    if (fresh.length > 0) rows = [...fresh, ...rows];
  });

  function summary(row: AuditRow): string {
    const d = row.detail ?? {};
    if (typeof d.summary === "string") return d.summary;
    if (typeof d.message === "string" && d.message) return d.message;
    if (typeof d.error === "string" && d.error) return d.error;
    const n = changeLines(row).length;
    return n > 0 ? t("audit.n_keys", { n }) : "";
  }
</script>

<div class="filters">
  <div class="field">
    <label for="f-action">{t("audit.kind")}</label>
    <select id="f-action" class="input" bind:value={action}>
      {#each ACTION_GROUPS as a (a.id)}<option value={a.id}>{a.label}</option>{/each}
    </select>
  </div>
  <div class="field">
    <label for="f-target">Bot</label>
    <select id="f-target" class="input" bind:value={target}>
      <option value="">{t("audit.g_all")}</option>
      {#each g.bots as bot (bot.id)}<option value={bot.id}>{bot.label}</option>{/each}
    </select>
  </div>
  <div class="field">
    <label for="f-result">{t("audit.result")}</label>
    <select id="f-result" class="input" bind:value={result}>
      {#each RESULTS as r (r.id)}<option value={r.id}>{r.label}</option>{/each}
    </select>
  </div>
</div>
<p class="note">{t("audit.note")}</p>

{#if loading && rows.length === 0}
  <div class="skel-rows" aria-busy="true" aria-label={t("audit.loading")}><span class="skeleton" style="width: 90%"></span><span class="skeleton" style="width: 80%"></span><span class="skeleton" style="width: 85%"></span><span class="skeleton" style="width: 70%"></span></div>
{:else if fault && rows.length === 0}
  <p class="note warn-text">{t("audit.failed", { code: fault.code })} {explainRead(fault)}</p>
  <div class="inline-actions"><button class="btn quiet" type="button" onclick={() => load(false)}>{t("common.retry")}</button></div>
{:else if rows.length === 0}
  <p class="note">{action || result || target ? t("audit.filter_empty") : t("audit.empty")}</p>
{:else}
  <ol class="audit">
    {#each rows as row (row.id)}
      {@const lines = changeLines(row)}
      <li class:problem={isProblem(row)}>
        <button type="button" class="row" aria-expanded={open === row.id} aria-controls={"a-" + row.id} onclick={() => (open = open === row.id ? null : row.id)}>
          <span class="num muted when">{dayClock(row.ts)}</span>
          <span class="what"><b>{actionLabel(row.action)}</b>{#if row.targets.length}<span class="muted tgt">{row.targets.join(", ")}</span>{/if}<br /><span class="muted small">{summary(row)}</span></span>
          <span class="res" class:warn-text={isProblem(row)}>{resultLabel(row.result)}</span>
        </button>
        {#if open === row.id}
          <div class="detail" id={"a-" + row.id}>
            <dl class="rows">
              <div><dt>{t("audit.actor")}</dt><dd>{row.actor === "file" ? t("cfg.actor_file") : row.actor}</dd></div>
              <div><dt>IP</dt><dd class="num">{row.ip ?? "-"}</dd></div>
              <div><dt>{t("audit.action")}</dt><dd><code>{row.action}</code></dd></div>
              {#if row.idempotency_key}<div><dt>{t("audit.idem")}</dt><dd class="num"><code>{row.idempotency_key.slice(0, 8)}…</code></dd></div>{/if}
              {#if row.detail?.params && typeof row.detail.params === "object" && Object.keys(row.detail.params).length > 0}<div><dt>{t("audit.params")}</dt><dd><code>{Object.entries(row.detail.params).map(([k, v]) => k + "=" + show(v)).join(" · ")}</code></dd></div>{/if}
            </dl>
            {#if lines.length > 0}
              <table class="table">
                <thead><tr><th>{t("cfg.col_key")}</th><th>{t("cfg.col_old")}</th><th>{t("cfg.col_new")}</th></tr></thead>
                <tbody>
                  {#each lines as c (c.key)}<tr><td><code>{c.key}</code></td><td class="num">{c.old}</td><td class="num"><b>{c.new}</b></td></tr>{/each}
                </tbody>
              </table>
            {/if}
          </div>
        {/if}
      </li>
    {/each}
  </ol>
  {#if fault}<p class="note warn-text">{t("common.next_failed", { code: fault.code })}</p>{/if}
  {#if more}
    <div class="inline-actions"><button class="btn quiet" type="button" disabled={loading} aria-busy={loading} onclick={() => load(true)}>{loading ? t("common.loading") : t("audit.older")}</button></div>
  {/if}
{/if}

<style>
  .filters {
    display: flex;
    flex-wrap: wrap;
    padding-top: var(--space-2);
  }
  .filters .field {
    flex: 1 1 10rem;
  }
  .audit {
    margin: 0;
    padding: 0 0 var(--space-3);
    list-style: none;
  }
  .audit > li {
    border-top: 1px solid var(--rule);
  }
  .row {
    display: grid;
    grid-template-columns: 7.4em 1fr auto;
    gap: var(--space-2);
    width: 100%;
    min-height: 52px;
    padding: var(--space-2) var(--space-4);
    border: 0;
    background: transparent;
    text-align: left;
    font-size: var(--step-0);
    cursor: pointer;
    transition: background-color var(--t) var(--ease);
  }
  .row:hover,
  .row[aria-expanded="true"] {
    background: var(--panel);
  }
  .row:active {
    background: var(--rule);
  }
  .problem .what b {
    color: var(--loss);
  }
  .small {
    font-size: var(--step--1);
  }
  .tgt {
    margin-left: 0.4em;
  }
  .res {
    font-size: var(--step--1);
    white-space: nowrap;
  }
  .detail {
    padding-bottom: var(--space-2);
    background: var(--panel);
  }
  code {
    font-family: inherit;
    font-size: var(--step--1);
    overflow-wrap: anywhere;
  }
</style>
