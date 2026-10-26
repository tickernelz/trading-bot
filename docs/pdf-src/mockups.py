from mockup_parts import *


def chips(items, on):
    return '<div class="chips">' + "".join('<span class="' + ("on" if i == on else "") + '">' + i + "</span>" for i in items) + "</div>"


def stp(v):
    return '<span class="stp"><u>' + M + "</u>" + v + "<u>+</u></span>"


def dash_inner(hold):
    if hold:
        board = '<div class="board sig"><div class="w">Held</div><div class="s">Today&#39;s loss of 1.0% has reached the 1.0% limit. New entries are on hold; open positions stay protected by stop loss.</div></div>'
        tr = trace_svg(EQ_HOLD, 272, 84, -1.2, 0.2, -1.0, "daily limit " + M + "1.0%", HOURS)
        profit = row("Profit today", loss(M + "Rp 20,000 (" + M + "1.0%) loss"))
        meters = meter("Daily loss", "1.0%", "1.0%", 100, True) + meter("Total loss", "1.0%", "10.0%", 10)
        pos = row("BTC/IDR &middot; 1h", loss(M + "0.3% loss")) + row("ETH/IDR &middot; 1h", loss(M + "0.5% loss"))
    else:
        board = '<div class="board"><div class="w">Safe</div><div class="s">Today&#39;s loss is 0.3% of the 1.0% limit. New entries may be opened.</div></div>'
        tr = trace_svg(EQ_OK, 272, 84, -1.2, 0.2, -1.0, "daily limit " + M + "1.0%", HOURS)
        profit = row("Profit today", loss(M + "Rp 6,000 (" + M + "0.3%) loss"))
        meters = meter("Daily loss", "0.3%", "1.0%", 30) + meter("Total loss", "0.3%", "10.0%", 3)
        pos = row("BTC/IDR &middot; 1h", gain("+0.4% profit")) + row("ETH/IDR &middot; 1h", loss(M + "0.2% loss"))
    return (
        board + sec("Today", "hourly trace, percent of capital") + '<div style="padding:0 12px">' + tr + "</div>" + profit + meters
        + sec("Open positions", "2 of max 3") + pos + sec("Bot")
        + row("Bot A &middot; rules only", "Dry-run") + row("Bot B &middot; rules + shadow swarm", "Dry-run")
        + row("LLM cost today (informational)", "Rp 410 &middot; 540 k tokens", "sm")
    )


def g1():
    a = phone(dash_inner(False), "Summary")
    b = phone(dash_inner(True), "Summary", dark=True, age="2 sec ago")
    return phones(pc("Screen 1a. Dashboard, light theme, safe state", a), pc("Screen 1b. Dashboard, dark theme (follows system), on-hold state", b))


def g2a():
    inner = (
        chips(["BTC/IDR", "ETH/IDR", "SOL/IDR"], 0)
        + sec("BTC/IDR &middot; 1h", "open position")
        + '<div style="padding:0 12px">' + candles_svg(272, 236) + "</div>"
        + row("Entry 14:00", gain("+0.4% profit"))
        + row("Previous exit 03:00", gain("+0.7% profit"))
        + row("Indicator", "EMA 9 (thick line)", "sm")
        + '<div class="r sm"><span class="k">Swarm markers</span>' + switch(True, "On") + "</div>"
        + '<div class="r sm"><span class="k">News and sentiment (nice-to-have)</span>' + switch(False, "Off") + "</div>"
    )
    return phones(pc("Screen 2a. Live chart (phone)", phone(inner, "Chart")))


def g2b():
    left = (
        chips(["BTC/IDR", "ETH/IDR", "SOL/IDR"], 0)
        + sec("BTC/IDR &middot; 1h", "candles updated via WebSocket, data 3 sec ago")
        + '<div style="padding:0 14px 10px">' + candles_svg(470, 300, 52, 36, 18) + "</div>"
    )
    right = (
        sec("Markers")
        + row("14:00 Entry", gain("+0.4% profit"), "sm")
        + row("03:00 Exit", gain("+0.7% profit"), "sm")
        + sec("Overlay")
        + '<div class="r sm"><span class="k">EMA 9</span>' + switch(True, "On") + "</div>"
        + '<div class="r sm"><span class="k">Swarm markers</span>' + switch(True, "On") + "</div>"
        + '<div class="r sm"><span class="k">News and sentiment (nice-to-have)</span>' + switch(False, "Off") + "</div>"
        + sec("Strategy signal")
        + '<div class="note">The next entry candidate is computed when the 1-hour candle closes. Signal preview on other timeframes: nice-to-have.</div>'
    )
    inner = '<div class="cols"><div style="flex:1.75">' + left + "</div><div>" + right + "</div></div>"
    return '<div class="mkw">' + label("Screen 2b. Live chart (desktop)") + desk(inner, "Chart") + "</div>"


def feed(t, kind, msg, warn=False):
    return '<div class="f ' + ("warn" if warn else "") + '"><time>' + t + '</time><span><span class="kd">' + kind + "</span> " + msg + "</span></div>"


def g3_phone():
    inner = (
        chips(["All", "Order", "Swarm", "Risk", "System"], 0)
        + feed("14:02:11", "Swarm", "BTC/IDR: quorum 6 of 7, median 0.67, spread 0.08, decision allow (shadow: logged only)")
        + feed("14:02:09", "Voter", "v7 lucif: timed out after 30 sec, dropped for this decision", True)
        + feed("14:02:08", "Strategy", "entry candidate BTC/IDR 1h")
        + feed("13:58:40", "Order", "buy ETH/IDR filled (dry-run)")
        + feed("13:30:00", "Risk", "gate passed: daily loss 0.3% of 1.0%, positions 2 of max 3")
        + feed("13:00:00", "System", "heartbeat bot A and bot B normal")
        + feed("12:41:55", "Warning", "nutaraline replied 429; voter v6 dropped for this decision", True)
        + feed("12:40:02", "Order", "exit BTC/IDR (dry-run) " + gain("+0.7% profit"))
        + '<div class="note">Connection lost: the view marks data as stale, then reconnects with backoff.</div>'
    )
    return phone(inner, "Action", h=720)


def vtable(voters):
    rows = ""
    for vid, prov, model, ans, p in voters:
        pv = "discarded" if p is None else ("%.2f" % p).replace(".", ",")
        rows += '<tr><td><b>' + vid + '</b></td><td class="w">' + prov + "<br><span style='color:var(--ink2)'>" + model + "</span></td><td>" + ans + '</td><td class="n">' + pv + "</td></tr>"
    return '<table class="tb"><tr><th></th><th>Provider and model</th><th>Answer</th><th class="n">P(allow)</th></tr>' + rows + "</table>"


def g3_preview():
    inner = (
        chips(["Preview", "Decision"], 0)
        + sec("SOL/IDR &middot; 1h", "entry candidate 15:00, no order yet")
        + sec("Voter A", "decision model")
        + vtable(VOTERS)
        + sec("Voter B", "return forecast")
        + row("Kronos mini", gain("+1.10%"), "sm")
        + row("Time series base model", gain("+0.95%"), "sm")
        + row("FreqAI (LightGBM)", gain("+0.40%"), "sm")
        + row("Median A &middot; interquartile range", "0.67 &middot; 0.08", "sm")
        + row("Quorum", "6 of 7 (min 5) met", "sm")
        + '<div class="note" style="background:var(--panel);margin:6px 12px 0;padding:7px 9px;color:var(--ink)"><b>Preview result: allow.</b> Shadow mode: logged only, no order. Spread threshold not yet set.</div>'
    )
    return phone(inner, "Swarm", h=720)


def g3():
    return phones(pc("Screen 3. Live actions (real-time feed)", g3_phone()), pc("Screen 4. Entry candidate preview with voter answers", g3_preview()))


def g4_swarm():
    q = [v for v in VOTERS]
    inner = (
        chips(["Preview", "Decision"], 1)
        + sec("Latest decisions")
        + row("14:00 BTC/IDR &middot; allow (shadow)", gain("opened +0.4%"), "sm")
        + row("12:00 ETH/IDR &middot; skip: wide spread", "if opened " + loss(M + "0.6%") + "<br>skip was correct", "sm")
        + row("09:00 SOL/IDR &middot; skip: quorum 4 of 7", "if opened " + gain("+0.3%") + "<br>skip missed", "sm")
        + row("06:00 BTC/IDR &middot; reduce", "not yet evaluated", "sm")
        + sec("Decision 14:00 BTC/IDR")
        + '<div style="padding:0 12px">' + dots_svg(272, q, 0.665, 0.625, 0.705) + "</div>"
        + row("Median A &middot; interquartile range", "0.67 &middot; 0.08", "sm")
        + row("Quorum", "6 of 7 (min 5) met", "sm")
        + row("Median B", gain("+0.95%") + " (3 of 3 in agreement)", "sm")
        + row("Decision", "allow (shadow)", "sm")
        + '<div class="note">The outcome afterwards is computed from price: whether the skipped entry turned out to be a loss.</div>'
    )
    return phone(inner, "Swarm", h=770)


def g4_conf():
    inner = (
        chips(["Configuration", "Provider", "Controls"], 0)
        + sec("Loss limits", "decrease immediately, increase in two steps")
        + row("Daily", stp("1.0%") + ' <span class="k">Rp 20,000</span>', "sm")
        + row("Total", stp("10.0%") + ' <span class="k">Rp 200,000</span>', "sm")
        + row("Risk per trade", stp("0.5%") + ' <span class="k">Rp 10,000</span>', "sm")
        + sec("Swarm voters", "model, adapter, active")
        + '<div class="r sm"><span class="k"><b>v1</b> modelrouter &middot; jev-1.13<br>systemone</span>' + switch(True, "On") + "</div>"
        + '<div class="r sm"><span class="k"><b>v2</b> experientiallabs &middot; clef<br>systemone</span>' + switch(True, "On") + "</div>"
        + '<div class="r sm"><span class="k"><b>v6</b> nutaraline &middot; deepseek-v4.1<br>llm_structured</span>' + switch(True, "On") + "</div>"
        + '<div class="r sm"><span class="k"><b>v8</b> sub2api-claude &middot; chat model<br>llm_structured</span>' + switch(False, "Off") + "</div>"
        + sec("LLM backend")
        + row("Backend", "deepagents", "sm")
        + row("Analyst agent", "nutaraline:deepseek-v4.1-flash-1017", "sm")
        + sec("Compute")
        + '<div class="r sm"><span class="k">Daily cost limit</span>' + switch(False, "Off (default)") + "</div>"
        + '<div class="r sm"><span class="k">Log cost and tokens</span>' + switch(True, "On") + "</div>"
        + row("Today (information)", "Rp 410 &middot; 540 k tokens", "sm")
        + '<div class="note">Cost is only logged, not a limit meter. If a limit is set and exceeded: skip new entries.</div>'
    )
    return phone(inner, "Settings", h=770)


def g4():
    return phones(pc("Screen 5. Swarm per decision", g4_swarm()), pc("Screen 6. Configuration, cost limit off by default", g4_conf()))


PROV = [
    ("nutaraline", "openai-completions", "nutaraline.co.uk", "23", "Connected 1.8 s", "ok"),
    ("modelrouter", "openai-completions", "modelrouter.id", "23", "Connected 0.9 s", "ok"),
    ("experientiallabs", "openai-completions", "api.experientiallabs.ai", "272", "Not tested", "no"),
    ("tiprouter", "openai-completions", "tiprouter.my.id", "18", "Failed: timeout", "bad"),
    ("xai-hm", "openai-responses", "gateway.example.com", "17", "Not tested", "no"),
    ("lucif", "anthropic-messages", "lucif.ai", "2", "Not tested", "no"),
]


def g5a():
    trs = ""
    for i, (n, t, h, c, st, k) in enumerate(PROV):
        dot = '<span class="dot"></span>' if k == "ok" else '<span class="dot hol"></span>'
        cls = "sel" if i == 0 else ""
        stt = ('<span class="loss">' + st + "</span>") if k == "bad" else st
        trs += '<tr class="' + cls + '"><td><b>' + n + "</b></td><td>" + t + "</td><td>" + h + '</td><td class="n">' + c + '</td><td style="padding-left:14px">' + dot + stt + "</td></tr>"
    table = '<table class="tb"><tr><th>Provider</th><th>API type</th><th>Host</th><th class="n">Models</th><th style="padding-left:14px">Last test</th></tr>' + trs + "</table>"
    top = (
        sec("Provider", "from omp models.yml")
        + table
        + '<div style="padding:6px 14px"><span class="btn sm">Add provider</span> <span class="btn sm sec">Import from models.yml</span></div>'
        + '<div class="note">Import is read locally by the app on the PC: name, API type, base URL, models. Key only if ticked per provider.</div>'
    )
    detail = (
        sec("nutaraline", "edited from the PC (localhost)")
        + '<div class="fld"><div class="l">API type</div><div class="in">openai-completions</div></div>'
        + '<div class="fld"><div class="l">Base URL</div><div class="in">https://nutaraline.co.uk/&hellip;/v1</div></div>'
        + '<div class="fld"><div class="l">Key source</div><div class="rad" style="flex-direction:column;gap:3px"><span>environment variable NUTARALINE_API_KEY</span><span class="on">local config.yaml</span></div></div>'
        + '<div class="fld"><div class="l">Key (write-once; after saving only the last 4 characters are shown)</div><div class="in">&bull;&bull;&bull;&bull;&bull;&bull;&bull;&bull;&bull;&bull;&bull;&bull;abcd <span style="color:var(--ink2)">&middot; saved 2026-10-25</span></div></div>'
        + '<div style="padding:6px 14px"><span class="btn sm sec">Replace key</span> <span class="btn sm sec">Delete key</span> <span class="btn sm">Test connection</span></div>'
        + row("Test result", "Connected &middot; 1.8 s", "sm")
        + '<div class="note">There is no view-key button and no endpoint that returns the full key.</div>'
    )
    roles = (
        sec("Model per role")
        + row("Analyst agent", "nutaraline: deepseek-v4.1-flash-1017", "sm")
        + row("Voter v1", "modelrouter: jev-1.13 &middot; systemone", "sm")
        + row("Voter v2", "experientiallabs: clef &middot; systemone", "sm")
        + row("Voter v6", "nutaraline: deepseek-v4.1-flash-1017 &middot; llm_structured", "sm")
        + '<div class="note">During testing all roles use deepseek-v4.1-flash-1017 on nutaraline.</div>'
    )
    inner = top + '<div class="cols" style="border-top:1px solid var(--rule)"><div style="flex:1.2">' + detail + "</div><div>" + roles + "</div></div>"
    return '<div class="mkw">' + label("Screen 7a. Provider and key (on the PC, localhost)") + desk(inner, "Settings", ("Summary", "Chart", "Actions", "Swarm", "Positions and history", "Settings")) + "</div>"


def g5b():
    items = ""
    for n, t, h, c, st, k in PROV[:4]:
        dot = '<span class="dot"></span>' if k == "ok" else '<span class="dot hol"></span>'
        on = k != "no"
        stt = ('<span class="loss">' + st + "</span>") if k == "bad" else st
        items += '<div class="r sm"><span class="k"><b style="color:var(--ink)">' + n + "</b> &middot; " + t + "<br>" + dot + stt + "</span>" + switch(on, "On" if on else "Off") + "</div>"
    inner = (
        chips(["Configuration", "Provider", "Controls"], 1)
        + sec("Provider", "6 registered")
        + items
        + sec("nutaraline")
        + row("Active model", "deepseek-v4.1-flash-1017", "sm")
        + row("Last test", "Connected &middot; 1.8 s", "sm")
        + '<span class="btn">Test connection</span>'
        + '<div class="note" style="background:var(--panel);margin:4px 12px;padding:7px 9px;color:var(--ink)">There is no key field on the phone. Entering or replacing a key is only possible from the PC; the phone only sees the status, enables or disables, and tests the connection.</div>'
    )
    legend = (
        '<div class="legend"><p><b>PC vs phone differences</b></p>'
        '<p>PC (localhost): write-once key field, only the last 4 characters are shown, no view button; connection test; pick the model per role.</p>'
        '<p>Phone (remote PWA): no key field. Only status, on or off, and connection test, so the key never passes through the tunnel.</p>'
        '<p>Source: plan section 4.5. Provider names from plan section 4.3.</p></div>'
    )
    return '<div class="mkw"><div class="phones">' + pc("Screen 7b. Provider (phone, no key field)", phone(inner, "Settings")) + legend + "</div></div>"


def g6_ctrl():
    inner = (
        chips(["Configuration", "Provider", "Controls"], 2)
        + sec("Reduce risk", "immediate, no confirmation")
        + '<span class="btn sig">Stop new entries</span>'
        + '<div class="note">Open positions stay protected by the stop loss on the bot side.</div>'
        + '<span class="btn sec">Pause bot</span>'
        + sec("Risky actions", "two steps")
        + '<span class="btn sec">Close all positions&hellip;</span>'
        + '<span class="btn sec">Raise loss limit&hellip;</span>'
        + '<span class="btn sec">Switch to live mode&hellip;</span>'
        + sec("Status")
        + row("Mode", "Dry-run", "sm")
        + row("Bot heartbeat", "4 s ago", "sm")
        + row("Gateway", "HTTPS tunnel, Freqtrade API stays local", "sm")
    )
    return phone(inner, "Settings", dark=True)


def g6_raise():
    inner = (
        chips(["Configuration", "Provider", "Controls"], 2)
        + sec("Raise daily loss limit", "step 2 of 2")
        + row("Current limit", "1.0% (Rp 20,000)", "sm")
        + row("New limit", "1.5% (Rp 30,000)", "sm")
        + row("Added risk", loss("Rp 10,000 per day"), "sm")
        + '<div class="note">Raising the limit adds risk. The decision is up to the owner.</div>'
        + '<div class="fld"><div class="l">Type RAISE to continue</div><div class="in">RAI</div></div>'
        + '<span class="btn dis">Apply new limit</span>'
        + '<div class="note">The button becomes active once the word matches.</div>'
        + '<span class="btn sec">Cancel</span>'
        + '<div class="note">The change is logged: who, when, old and new value.</div>'
    )
    return phone(inner, "Settings")


def chk(text, state):
    return '<div class="r sm"><span class="k"><span class="dot hol"></span>' + text + '</span><span class="v">' + state + "</span></div>"


def g6_live():
    inner = (
        chips(["Configuration", "Provider", "Controls"], 2)
        + sec("Switch to live mode", "step 2 of 2")
        + row("Current mode", "Dry-run", "sm")
        + row("New mode", loss("Live, real funds"), "sm")
        + row("Initial portion (stage 3 proposal)", "Rp 500,000", "sm")
        + sec("Before live")
        + chk("Positive expectancy after fees and tax on out-of-sample data", "not yet")
        + chk("PC without sleep and without automatic restart", "not yet")
        + chk("Heartbeat to a monitor outside the PC", "not yet")
        + chk("Explicit approval from the owner", "not yet")
        + '<span class="btn dis">Switch to live</span>'
        + '<div class="note">The button becomes active once all requirements are met and the word LIVE is typed.</div>'
        + '<span class="btn sec">Cancel</span>'
    )
    return phone(inner, "Settings")


def g6a():
    return phones(pc("Screen 8a. Kill switch and controls (dark theme)", g6_ctrl()), pc("Screen 8b. Two-step confirmation: raise loss limit", g6_raise()))


def g6b():
    legend = (
        '<div class="legend"><p><b>Two-step confirmation</b></p>'
        '<p>Reducing risk (stop new entries, lower limits) takes effect immediately. Raising risk limits and switching to live mode require two steps and state the consequence in rupiah.</p>'
        '<p>Cancel is always available and the apply button stays disabled until the conditions are met.</p>'
        '<p>The live conditions list on this screen comes from plan sections 6 and 8: the values are examples, not real status.</p></div>'
    )
    return '<div class="mkw"><div class="phones">' + pc("Screen 8c. Two-step confirmation: switch to live mode", g6_live()) + legend + "</div></div>"


def g7():
    left = (
        '<div class="board" style="display:flex;justify-content:space-between;align-items:flex-end"><div><div class="w">Safe</div><div class="s">Today&#39;s loss 0.3% of the 1.0% limit. New entries may be opened.</div></div>'
        '<div class="s" style="text-align:right">Example balance Rp 1,994,000<br>of capital Rp 2,000,000</div></div>'
    )
    eq = (
        sec("Equity today", "solid line Bot B (shadow swarm), dashed Bot A (rules only)")
        + '<div style="padding:0 14px">' + trace_svg(EQ_B, 450, 130, -1.2, 0.6, -1.0, "daily limit " + M + "1.0%", HOURS, EQ_A) + "</div>"
        + meter("Daily loss", "0.3%", "1.0%", 30) + meter("Total loss", "0.3%", "10.0%", 3)
        + sec("Open positions", "2 of max 3")
        + '<table class="tb"><tr><th>Pair</th><th>Bot</th><th>Entry</th><th class="n">Profit/loss</th></tr>'
        + '<tr><td><b>BTC/IDR</b></td><td>B</td><td>14:00</td><td class="n">' + gain("+0.4% profit") + "</td></tr>"
        + '<tr><td><b>ETH/IDR</b></td><td>A</td><td>13:58</td><td class="n">' + loss(M + "0.2% loss") + "</td></tr></table>"
    )
    right = (
        sec("Latest swarm decision", "BTC/IDR 14:02")
        + '<div style="padding:0 14px">' + dots_svg(270, VOTERS, 0.665, 0.625, 0.705) + "</div>"
        + row("Quorum", "6 of 7 (min 5) met", "sm")
        + row("Decision", "allow (shadow)", "sm")
        + sec("Health")
        + row("Bot loop", "normal", "sm")
        + row("nutaraline", "connected &middot; 1.8 s", "sm")
        + row("modelrouter", "connected &middot; 0.9 s", "sm")
        + row("tiprouter", loss("failed: timed out"), "sm")
        + row("LLM cost today (informational)", "Rp 410 &middot; 540 k tokens", "sm")
        + sec("Latest actions")
        + feed("14:02", "Swarm", "allow (shadow)")
        + feed("13:58", "Order", "buy ETH/IDR (dry-run)")
        + feed("12:41", "Warning", "nutaraline 429", True)
    )
    inner = left + '<div class="cols"><div style="flex:1.45">' + eq + "</div><div>" + right + "</div></div>"
    return '<div class="mkw">' + label("Screen 9. Desktop dashboard (wide)") + desk(inner, "Compact") + "</div>"


def icon():
    return (
        '<svg viewBox="0 0 40 40" width="40" height="40" style="vertical-align:top;margin:0 6px 6px 0"><rect width="40" height="40" rx="10" fill="var(--ink)"/>'
        '<polyline points="6.26 12.26 15.13 19.30 23.19 26.24 34.24" fill="none" stroke="var(--onink)" stroke-width="2.2" stroke-linejoin="round"/></svg>'
    )


def step(n, text, screen):
    return '<div class="step ui">' + screen + '<div><span class="n">' + n + ".</span> " + text + "</div></div>"


def g8():
    s1 = (
        '<div class="mini"><div class="sb"><span>09:41</span><span>Safari</span></div><div class="u">example-tunnel-address</div>'
        '<div class="board" style="margin:6px"><div class="w" style="font-size:22px">Safe</div><div class="s" style="font-size:10px">Dry-run</div></div>'
        '<div style="position:absolute;left:0;right:0;bottom:0;display:flex;justify-content:space-around;padding:8px 4px 10px;border-top:1px solid var(--rule);color:var(--ink2)"><span>Back</span><span class="hl" style="padding:0 6px;color:var(--ink);font-weight:600">Share</span><span>Tabs</span></div></div>'
    )
    s2 = (
        '<div class="mini"><div class="sb"><span>09:41</span><span>Safari</span></div><div class="u">example-tunnel-address</div>'
        '<div class="sheet"><div>Copy</div><div class="hl" style="font-weight:600">Add to Home Screen</div><div>Print</div></div></div>'
    )
    s3 = (
        '<div class="mini"><div class="sb"><span>09:41</span><span></span></div><div style="padding:14px 10px">'
        + icon() + '<span class="ico o"></span><span class="ico o"></span><span class="ico o"></span>'
        + '<div class="hl" style="display:inline-block;padding:2px 4px;font-weight:600">Bot Trading</div></div>'
        '<div class="note">Open from this icon, not from Safari.</div></div>'
    )
    s4 = (
        '<div class="mini"><div class="sb"><span>09:41</span><span>PWA</span></div><div class="top"><span class="mode">Dry-run</span></div>'
        '<div style="padding:8px 4px"><span class="btn hl">Enable notifications</span><div class="note">Permission is requested after this tap.</div></div>'
        '<div class="dlg"><div><b>&ldquo;Bot Trading&rdquo; would like to send notifications</b></div><div class="bt"><span>Don&#39;t Allow</span><span class="p">Allow</span></div></div></div>'
    )
    row_ = (
        step("1", "Open the PWA address in Safari, then tap Share.", s1)
        + step("2", "Choose Add to Home Screen.", s2)
        + step("3", "Open from the icon on the Home Screen.", s3)
        + step("4", "Tap the Enable notifications button, then Allow on the iOS dialog.", s4)
    )
    return '<div class="mkw">' + label("Screen 10. Install the PWA on iOS 16.4 or later") + '<div class="steps">' + row_ + "</div></div>"


SCREENS = {
    "g1": g1,
    "g2a": g2a,
    "g2b": g2b,
    "g3": g3,
    "g4": g4,
    "g5a": g5a,
    "g5b": g5b,
    "g6a": g6a,
    "g6b": g6b,
    "g7": g7,
    "g8": g8,
}
