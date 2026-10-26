<!-- SEED: re-run $impeccable document once there's code to capture the actual tokens and components. -->
---
name: trading-bot
description: A calm, honest, glanceable control panel for an autonomous trading bot; risk comes before profit.
---

## Overview

Creative North Star: a station information board meets a seismograph paper strip. One big answer readable from a distance, and one trace line showing what just happened.

Physical scene: the owner holds a phone under bright tropical sun to check whether the bot is safe, or stares at a PC in the daytime while adjusting configuration, then glances at the phone again at midnight in a dark room. For that reason the light theme is the default (highest contrast under sunlight), and the dark theme follows the system setting for night. Both are designed, not one merely inverted from the other.

**The Quiet Win Rule.** Profit appears calm; losses and limits appear firm. The signal color is reserved for risk, not for buttons or decoration.

References (the operator's choice, open to correction): the departure board and timetable typography of SBB; the helicorder paper strip of a seismograph; the calm density of Linear. Anti-reference: a dark Binance-style trading dashboard with neon green and red (mentioned in PRODUCT.md).

Motion: restrained. Only to convey state changes (fill, limit reached, connection lost), 150 to 250 ms, no choreography on load, and a prefers-reduced-motion version is mandatory.

## Colors

Strategy: Restrained. Pure neutrals or with a very faint tint, one signal color covering no more than ten percent of the surface.

**The Risk Signal Rule.** One warm signal color (anchor: coral or burnt orange, oklch(0.673 0.217 38.6), seed seed-041 from palette.mjs for the trading-bot key) only for losses, risk limits, warnings, and the kill switch. Not for primary buttons, links, or decoration.

**The Not-Red-Not-Green Rule.** Profit uses deep blue, loss uses the warm signal color; both always accompanied by a plus or minus sign and a direction. The blue and orange pair was chosen because it remains distinguishable for red-green color blindness. The primary button uses ink (near black), not the signal color.

Values (tokens in `pwa/src/app.css`, light / dark): background `oklch(1 0 0)` / `oklch(0.15 0 0)`; panel `oklch(0.965 0.006 255)` / `oklch(0.2 0.006 255)`; ink `oklch(0.19 0.012 255)` / `oklch(0.96 0 0)`; secondary ink `oklch(0.42 0.015 255)` / `oklch(0.76 0.01 255)`; profit `oklch(0.4 0.15 258)` / `oklch(0.78 0.12 250)`; loss (text) `oklch(0.5 0.19 38.6)` / `oklch(0.72 0.19 38.6)`; signal (fill) `oklch(0.673 0.217 38.6)`. Contrast measured in Chromium: secondary ink on background 8.41:1 / 9.14:1, loss 6.55:1 / 7.2:1, profit 9.46:1 / 9.88:1, ink on signal 5.71:1. Strong line (`--rule-strong`, input field borders, quiet buttons, bot selector) `oklch(0.6 0.01 255)` / `oklch(0.5 0.01 255)`: stage 2 lowered it from 0.7 in the light theme because input field borders need 3:1 against the background (WCAG 1.4.11); placeholder uses secondary ink (the Chromium default in the dark theme is only 4.27:1). Light surfaces use pure white; dark surfaces are near black without tint; the second neutral layer for panels is slightly cooler. Avoid cream, sand, and paper bands.

## Typography

Direction: one technical, easy-to-read sans family, with mandatory tabular numerals (price, quantity, and percent columns aligned). Font family: Atkinson Hyperlegible Next (variable, `@fontsource-variable/atkinson-hyperlegible-next`), made for low-vision legibility, suited to phone screens under sunlight. Tabular numerals proven in Chromium rendering: with `tnum` ten digits 1 and ten digits 0 have equal width (632 px at 100 px), without `tnum` they differ (407 and 648 px); the minus glyph U+2212 exists. Inter was rejected because the impeccable detector flags it as an overly generic typeface. Fixed scale, not fluid. Headings do not use a display typeface; labels and buttons use the same family.

## Elevation

Flat by default. Layers are distinguished by surface tone, not shadows. No wide shadows and no nested cards.

## Do's and Don'ts

Do:
- Show one big state (safe, held, stopped) before any detail.
- Always show the dry-run or live mode marker and the age of the latest data.
- Give every profit and loss figure a plus or minus sign, a direction, and text.

Don't:
- A Binance- or Robinhood-style trading dashboard: dark, neon green and red, candlesticks as the center of everything.
- A gamified broker app: confetti, win streaks, big celebrated profit figures.
- A SaaS hero-metric template: giant number, small label, gradient, repeated identical stat cards.
- A generic AI dashboard: purple gradient, glass cards, colored round icons.
- The default look of FreqUI and Nuxt UI.
- Signal color for buttons or decoration; red and green as the only distinction between profit and loss.

Quick test: if someone looks at the screen and immediately guesses "trading dashboard" from color and shape alone, the visual direction has failed.
