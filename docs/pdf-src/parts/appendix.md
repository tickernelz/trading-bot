
::: {.pb}
:::

# Appendix: Visual direction and mockups

All figures, balances, position names, and voter results in the mockups are sample data, not real results; every screen carries that label. There are no API keys or secret values in the mockups. Provider and model names come from tables 5.3 and 5.4. During testing all voters use deepseek-v4.1-flash-1017 on nutaraline (chapter 5.4); the diverse voter list in the mockups shows the configuration after the engine passes testing.

## A.1 Visual direction decision (plan section 12; PRODUCT.md and DESIGN.md)

The visual direction is the operator's decision, still open to correction by the owner. The owner delegated the theme to the operator and did not answer the impeccable interview; PRODUCT.md and DESIGN.md in the repo (commit 54ed647) are the source. The mockups use that direction as is and it has not yet been tested by the owner.

| Item | Decision |
|---|---|
| Register and user | product; the owner only, on PC (configuration, analysis) and on phone (quick glance, midnight) |
| Creative North Star | a station information board meets a seismograph paper strip: one big answer (Safe, Held, Stopped) and one trace line about what just happened |
| Physical scene | phone under the tropical sun to check whether the bot is safe; PC in daytime when setting configuration; phone again at midnight in a dark room |
| Theme | light as default (highest contrast under the sun); dark follows the system; both are designed (Screen 1a light, 1b and 8a dark) |
| Color | Restrained strategy: pure neutrals, one warm signal color oklch(0.673 0.217 38.6) (seed-041) only for loss, limits, warnings, and the kill switch; profit in dark blue oklch(0.40 0.15 258); primary button in ink oklch(0.19 0.012 255) |
| Profit and loss | not only red and green: dark blue and orange, always with a plus or minus sign, an arrow, and the word profit or loss |
| Typography | one sans family, tabular numbers mandatory, fixed scale (A.2) |
| Shape | flat, no wide shadows, no nested cards; buttons and fields radius 3 to 6 px |
| Motion | only for state changes, 150 to 250 ms, with a prefers-reduced-motion version (not depicted in the static mockups) |
| Forbidden | Binance or Robinhood style, gamification, hero-metric template, generic AI dashboard, default FreqUI and Nuxt UI look |

## A.2 Font family and tabular number evidence

Chosen family: Inter version 3.019 (installed on the PDF-building computer; what is embedded in this PDF is Inter Regular and Inter SemiBold, checked with pdffonts). The font's OpenType feature table contains tnum; with font-variant-numeric: tabular-nums all digits have equal width.

Evidence in Chrome render (40 px size, text box width):

| Number style | 1111 | 8888 |
|---|---|---|
| proportional | 74.33 px | 98.64 px |
| tabular (tnum) | 103.64 px | 103.64 px |

Proportional digit widths differ; tabular digit widths are equal, so the price, amount, and percent columns align. One family for headings, labels, buttons, and data; fixed scale (11, 12.5, 32 px on phone).

## A.3 Color contrast

Computed from the OKLCH values used in the mockups (WCAG contrast formula). WCAG AA target: text at least 4.5:1.

| Pair | Light theme | Dark theme |
|---|---|---|
| primary text on background | 18.46 | 17.51 |
| secondary text on background | 8.45 | 9.17 |
| secondary text on panel | 7.64 | 8.43 |
| profit blue on background | 9.41 | 9.86 |
| profit blue on panel | 8.51 | 9.07 |
| loss orange (text) on background | 6.53 | 7.19 |
| loss orange (text) on panel | 5.90 | 6.62 |
| ink text on signal color | 5.69 | 6.07 |

All pairs above are over 4.5:1.

## A.4 AI slop and category-reflex test (plan section 12)

| Prohibition or test | How the mockups avoid it |
|---|---|
| Hero-metric template (big number, small label, gradient) | no giant numbers; one state word (Safe, Held, Stopped) before the details; other numbers are normal size in tabular rows |
| Grid of identical cards, nested cards | no cards; sections separated by thin lines and spacing, section titles are plain sentences |
| Glassmorphism, gradient, gradient text | no blur, gradient, or gradient text |
| Small caps eyebrow in every section | no spaced small-caps text; section titles use normal letters |
| Numbering 01, 02, 03 as scaffolding | sequence numbers only in the iOS install steps (1 to 4), which really are sequential; screen numbers are only image labels |
| Border with wide shadow | no shadows with blur; only 1 to 2 px lines |
| Card radius above 16 px | largest radius 16 px (device frame); buttons and fields 3 to 6 px; switches are pill-shaped |
| Sketch SVG illustrations | none; SVG is only data charts and geometric app icons |
| Profit and loss only red and green | dark blue and orange, plus a plus or minus sign, arrow, and the word profit or loss on every number |
| Category-reflex level one (dark, neon green and red, candlestick at the center) | light as default, no neon; candlestick only on Screen 2, small, without green and red |
| Category-reflex level two (terminal-style dark mode) | light typography-based station board; dark only as an optional theme |
| DESIGN.md quick test: instantly guessed to be a trading dashboard from color and shape | the final judgment rests with the owner; this direction is open to correction |

The skill's built-in pattern detector (detect.mjs, local) was run on the HTML of the 11 mockup images: 7 findings, none severe. Six overused-font warnings point to Inter. reference/product.md allows Inter for the product register and DESIGN.md only requires tabular numbers (proven in A.2), so Inter is kept and can still be replaced if the owner chooses another family. One numbered-section-markers suggestion (the series 02, 03, 04, 06, 08, 09) was judged a false positive: the mockups have no numbered section markers, and that series seems to come from hour labels on the chart axis and feed (assumption, not traced per number).

## A.5 Screen 1: Dashboard (phone)

@@MOCKg1@@

- One big state first (Safe or Held), then the per-hour trace against the daily limit, profit with sign and word, daily and total loss meters, open positions, status of bot A and bot B (dry-run), LLM cost as information.
- The mode marker (Dry-run) and data age are in the top bar of all screens; the Stop button is always within reach.
- Feature source: plan section 13 (live positions and orders, risk meter, bot A vs bot B).

## A.6 Screen 2: Live chart (phone and desktop)

@@MOCKg2a@@

@@MOCKg2b@@

- Candles per pair with entry and exit markers, indicator (EMA), stop loss line, percent axis from the entry price; empty candles go up and filled candles go down, without green and red.
- Basis: /pair_candles, WebSocket analyzed_df, /plot_config (plan section 13). News and sentiment layer: nice-to-have, off.

## A.7 Screens 3 and 4: Live actions and Entry candidate preview

@@MOCKg3@@

- Live actions: fills, voter answers, median, spread, quorum, risk gate, warnings, heartbeat, in real time; a dropped connection is marked as stale data.
- Preview: entry candidates along with voter answers before the order is sent; in shadow mode it shows what would happen (plan section 13).

## A.8 Screens 5 and 6: Swarm per decision and Configuration

@@MOCKg4@@

- Swarm: spread of voter answers on a single line, median, interquartile range, quorum, decision, and the outcome afterwards (whether a skipped entry turned out to be a loss).
- Configuration: loss limit (lowering takes effect immediately, raising takes two steps), voters (model, adapter, active), LLM backend, and daily cost limit as a kill switch that is off by default; cost and tokens are informational only, not a limit meter (plan revision 5).

## A.9 Screen 7: Providers and keys

@@MOCKg5a@@

@@MOCKg5b@@

- On PC: write-once key field (only the last 4 characters are shown, no view button), connection test, choose model per role. On phone: no key field; only status, active or inactive, and connection test (plan section 4.5).

## A.10 Screen 8: Kill switch and two-step confirmation

@@MOCKg6a@@

@@MOCKg6b@@

- The kill switch runs stop_new_entries without confirmation; open positions remain protected by the stop loss on the bot side. Raising the limit, closing all positions, and switching to live require two steps with the consequence shown in rupiah.

## A.11 Screen 9: Desktop dashboard (wide)

@@MOCKg7@@

- One large state, equity of bot A and bot B together with the daily limit, meters, positions, the latest swarm decision, provider health, and the latest action. The gateway CPU load and fill delay to the PWA have not been measured (stage 1).

## A.12 Screen 10: Install the PWA on iOS

@@MOCKg8@@

- iOS 16.4 or later; must be added to the Home Screen; notification permission is requested via a button tap; notifications must be visible (Safari does not support silent push). WebSocket is only alive while the app is open in the foreground; in the background updates arrive via Web Push (plan section 13).

## A.13 Mockup list

| No | Screen | Device | Theme |
|---|---|---|---|
| 1 | Dashboard | phone | light (safe) and dark (held) |
| 2 | Live chart | phone and desktop | light |
| 3 | Live actions (real-time feed) | phone | light |
| 4 | Entry candidate preview with voter answers | phone | light |
| 5 | Swarm per decision | phone | light |
| 6 | Configuration, cost limit kill switch off by default | phone | light |
| 7 | Providers and keys | desktop (PC) and phone | light |
| 8 | Kill switch and two-step confirmation | phone (three screens) | dark and light |
| 9 | Wide desktop dashboard | desktop | light |
| 10 | iOS PWA install steps | phone (four steps) | light |
