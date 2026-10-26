---
target: PWA stage 1 (5 screens)
total_score: 29
p0_count: 0
p1_count: 0
timestamp: 2026-10-25T18-34-22Z
slug: pwa-src-app-svelte
---
## Impeccable critique: pwa/src/App.svelte (5 screens, phone 390 px and desktop 1440 px, light and dark)

### Design Health Score

| # | Heuristic | Score | Key Issue |
|---|-----------|-------|-----------|
| 1 | Visibility of System Status | 4 | Mode, connected, data age, and big state always on screen; stale turns the board gray with the last data time |
| 2 | Match System / Real World | 3 | Swarm terms (median, quartile spread, quorum) are explained in one sentence, still technical |
| 3 | User Control and Freedom | 3 | Read-only; feed filter, pair selection, chart layers, old decisions can be selected |
| 4 | Consistency and Standards | 3 | One vocabulary of rows, tables, tabs; Swarm highlights the selection with a box, Chart with an underline |
| 5 | Error Prevention | 3 | No risky actions; notification button is disabled when permission is denied |
| 6 | Recognition Rather Than Recall | 3 | Chart legend is written below the chart, not above it |
| 7 | Flexibility and Efficiency | 2 | No keyboard shortcuts on desktop; no direct link to a single trade |
| 8 | Aesthetic and Minimalist Design | 3 | Summary is long on phone (about 2,400 px) because the desktop side column is stacked below |
| 9 | Error Recovery | 3 | Disconnected: reason, time, countdown, Retry now button; REST errors are only stored, not yet shown |
| 10 | Help and Documentation | 2 | iOS hint and per-section notes exist; no glossary |
| **Total** | | **29/40** | **Good** |

### Anti-Patterns Verdict

LLM: does not read as AI. Quick DESIGN.md test: white light theme, a single orange color used only for borders and warnings, dark blue for profit, gray candles with no green or red; from color and shape alone the Summary screen reads as a station board (one big word on an ink field) and a seismograph strip (a single-line trace with a dashed limit line), not a trading dashboard. No hero-metric (the big thing is the state word, not a profit number), no cards, no gradient, eyebrow, or numbering. The candlestick chart on the Chart screen still resembles a generic charting tool; that is reasonable because it is a charting tool, and it is not the center of the app.

Detector: source (`pwa/src`, `index.html`, `public`) 0 findings. Rendered HTML of the 5 screens plus build-output CSS: 2 `side-tab` findings on `border-left: 1px solid var(--rule)` (Summary side column divider) and `border-right: 1px solid var(--rule)` (desktop navigation rail divider). Both are false positives: the skill's prohibition is a colored accent thicker than 1 px on the side of a card; this is a neutral 1 px line separating columns, not a card and not an accent. The previous run also reported `numbered-section-markers` from the clock times in the feed (01, 02, 06); that finding disappeared after the sample data was updated and was in fact clock times, not scaffolding. The Inter font was flagged as `overused-font` and replaced with Atkinson Hyperlegible Next.

### Overall Impression

Calm and readable within two seconds: the word Safe, Held, or Stopped on top, a sentence stating the number and its limit, then today's trace with the limit line. Biggest opportunity: the phone Summary is too long.

### What's Working

- The state board uses an ink field for safe and a signal field for held or stopped, with a sentence stating the limit; when stale the board turns gray with the last data time, so color never claims a state that is unknown.
- Every profit or loss carries a sign (+ or U+2212), a direction triangle, and the word profit, loss, or flat; dark blue and orange are only reinforcement.
- The risk meter states the remainder in percent before entries are held, and turns into "Batas tercapai" when exceeded.

### Priority Issues

- [P2] Phone Summary is long. The desktop side column (swarm decision, health, last action) is stacked at the bottom; at 390 px the page is about 2,400 px. Fix: on phone replace it with one compact line per section linking to its full screen. Command: $impeccable distill.
- [P2] REST errors are invisible. `gateway.error` is filled when a fetch fails but is not displayed; the user only sees the data age growing. Fix: show it in StaleBanner when the error is newer than the last data. Command: $impeccable harden.
- [P2] Empty feed after signing in again. The feed only contains events since connecting; resume does not apply to a new session. Fix: the real gateway sends the last 50 events in `gw.hello`. Command: $impeccable onboard.
- [P3] Price labels on the phone chart axis take up about a quarter of the width (1,463,933,000). Fix: compact format (1,464 M) on the axis, full number at the crosshair. Command: $impeccable adapt.

### Persona Red Flags

- Casey (distracted phone user): from notification to answer takes one tap and one glance; safe. The open position sits below the first fold after the board, trace, and two meters.
- Alex (power user on desktop): no keyboard shortcuts to switch screens or pairs; no URL per pair (`#grafik` always starts from the first pair).
- The owner (midnight, dark theme): the dark theme is designed separately, the signal stays orange, second text contrast 9.14:1; no glaring colors other than the Held board.

### Minor Observations

- On the desktop Swarm, the v6 label can stick to the median line when the values are nearly equal.
- Candles hollow for up and filled for down follow charting convention, explained in the note below the chart.

### Questions to Consider

- Should the phone Summary stop after the open position and move the rest to their own screens? (Options: yes, compact; no, one full scroll.)
- Should the PWA session persist after the app is closed (currently the token is in sessionStorage, signing in again on every open)? (Options: keep as is; store in IndexedDB with a short expiry.)

Questions skipped from the card: full-autonomy mode; decisions were taken as "Autonomous decision" in the closing comment, the owner corrects along the way.
