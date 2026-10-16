# GardenPilot design system

> Snapshot of the live design system kept in claude.ai artifacts (author's account):
> design system <https://claude.ai/artifact/GYaHhiazSZFFokttp417Vg> and the screens canvas
> <https://claude.ai/artifact/7v8AHEhtX6ou1kKJroEwvP> (pages "Screens" and "Drafts" D01–D25).
> Synced: 2026-10-16. The firmware depends on `tokens.json` (colours, font sizes, geometry) and `icons/`;
> when tokens change in the design system, update them here in a PR.
> Mentions of `GardenPilot.<Component>` below refer to the React preview components in the artifact.

GardenPilot is the on-device UI for a greenhouse and lawn irrigation controller: an ESPHome + LVGL firmware on a **320×240 dark display**. This system describes that screen, not a website. Every token and component maps to something an LVGL page in `packages/lvgl/` can draw.

## Ground rules

- Design at **1× display pixels inside `Screen`** (320×240). Place everything with absolute `x`/`y`, the same coordinates an LVGL `widgets:` list uses. Never reflow; never add scrolling.
- There is **one theme**: the device is always dark. `bg` is the only ground; `card` and `status` are the two raised levels.
- A glance must answer three questions: *what is the reading, is water running, what happens next.* Keep each page to that.
- Coordinates and font sizes are starting values. Check legibility on the real panel before trusting them.

## Content

- English UI copy, short. Captions are UPPERCASE nouns (`SOIL MOISTURE`, `STATUS`, `NEXT`). Button labels are UPPERCASE verbs (`RUN`, `STOP`, `RUN QUEUE`, `WATER NOW`), with `+Q` as the queue shorthand.
- Values carry their unit with no space: `24C`, `65%`, `5 min` (duration keeps the space). Times are 24h `18:00`; unknown is `--:--`.
- Status words: `Watering`, `Running: Bed 2`, `Idle`. Mode flags compress to `AA:on  Q:off  Rev:off`.
- No emoji, no exclamation marks.

## Colour

- `text` for values and labels, `text-dim` for captions, inactive navigation and anything with **no live data yet** (the lawn card shows `Idle` in `text-dim` on purpose).
- `green` / `green-fill` mean **active water or the current page**: Watering text, RUN buttons, the running bed, the active nav button, greenhouse soil bar. Text on `green-fill` is `on-green`.
- `blue` / `blue-fill` mean **water-as-resource and the queue**: lawn bar, humidity icon, RUN QUEUE, WATER NOW, a queued bed. Text on `blue-fill` is `on-blue`.
- `heat` / `heat-fill` with `on-heat` are reserved for bed heating; no built screen uses them yet.
- `error-fill` with `on-error` is reserved for **STOP**. Nothing else is red.
- `amber` / `amber-fill` are reserved for warnings and a paused bed; the Schedules page uses `amber` text for a missed slot.
- `amber` / `amber-fill` are reserved for warnings and a paused bed; the bed card uses them for a locked or paused bed (state word in `amber`, top edge `amber-fill`).
- `border` (1px) outlines cards and draws dividers. It is decorative (1.85:1 on `card`). State is always shown with a fill colour plus a word, never by the outline alone.
- Contrast: every text pair above passes 4.5:1 (`on-green` 4.58, `on-blue` 4.57 are the tightest).

## Type

One family, Montserrat (LVGL's built-in bitmap fonts), type scale C: four built-in text sizes, two button sizes and one custom clock size:

- `caption` 10px/600: uppercase captions.
- `label` 12px/600: status text, header clock, titles.
- `value` 14px/700: sensor readings, bed durations.
- `value-lg` 16px/700: the one headline reading of a page, the boot title.
- Buttons keep their own smaller labels (repo-only tokens until the design system has them): `button-md` 10px/700 for transport buttons (STOP, RUN QUEUE, HOME, BACK), `button-sm` 8px/700 for in-card buttons (RUN, +Q, TEST) and nav labels (DASH, ZONES, SCHEDULE, SETUP). On the device they are glyph-limited custom Bold fonts (`gp_font_button_md` / `gp_font_button_sm`, baked from the vendored Montserrat Bold: upper case, digits, a few symbols), because LVGL's built-in Montserrat has one weight.
- `clock` 40px/44px/700: the screensaver clock only, digits, colon and dash only (custom font `gp_font_clock` from the vendored Montserrat Bold TTF, a few KB); don't use it elsewhere.

Don't introduce other sizes (a new one needs the author's approval): each one is an extra font baked into the firmware.

## Layout

- Header band `header-h` 22px: title at x=6 (Home, in `green`) or x=8 (detail pages, in `text`), divider underneath. **The current time is always at the right of every header** (`label`, `<page>_clock_label`, y=4, x=-6 on Home and -8 elsewhere from the right edge, fed by one shared poller); header actions sit left of it. Boot, the confirm dialog and the screensaver have no header clock.
- Home: two zone cards 152/153 wide, `space-1` 3px apart, `space-3` 6px from the edge; bottom `NavBar` at y=201, `nav-h` 39px (`status` band, 1px `border` top line); four buttons at y=204, h 32, x/w 4/76, 84/76, 164/76, 244/72 with a 12px icon, gap 2, then the 8px label: DASH (house), ZONES (leaf), SCHEDULE (drop), SETUP (gear); active = `green-fill` + `on-green`, inactive = `status` + `text-dim`. On the device the icons are the `design/icons/*.svg` rendered once to 12x12 PNG (`packages/lvgl/icons/`) and recoloured per state.
- Detail pages: `space-4` 8px margins; a stats strip (three `Stat`s at x = 8, 111, 214), a divider, the main block (bed cards / headline bar), a divider, then the **transport row** of `btn-h-md` 26px buttons along the bottom.
- In the transport row the main action is the widest button; STOP sits leftmost; HOME is a ghost button at the right.
- In-card buttons are `btn-h-sm` 20px; nothing tappable is smaller.
- Radii are tight: `radius-card` 2px, `radius-control` 3px; only the switch is a pill.

## Iconography

Five stroke icons (house, leaf, drop, gear, thermo) on a 24-unit grid, 2.2 stroke, round caps. Use them through `GardenPilot.Icon` so they take a tone; the SVG files in **Icons** have the `text-dim` ink baked in. Meaning: house = Home/DASH, leaf = zones/soil, drop = water/humidity, gear = setup, thermo = temperature. On the device these map to LVGL symbol images; keep the same five glyphs.

## Pages

- **Home** (`home_page`): built. Greenhouse card + Lawn card + nav.
- **Greenhouse** (`greenhouse_page`): proposal. Stats strip, three `BedCard`s with state edges, status line, STOP / RUN QUEUE / HOME.
- **History** (`gh_history_page`): built (task 027). Sub-page without nav: "History" header, 6 one-line rows (`B2  13 Oct 06:00  5 min  done`, skips `... skipped wet`), "1-6 of 37" caption, PREV / NEXT (`btn-h-sm`), BACK. Reached from the HISTORY ghost button (`gh_btn_history`) in the Greenhouse header. Paged, never scrolled.
- **Greenhouse** (`greenhouse_page`): built (task 025). Stats strip (AIR / HUMIDITY / SOIL), up to six `BedCard`s from one template (`packages/lvgl/card_bed.yaml`; ids `gh_card<N>_*`), transport row STOP (`gh_btn_stop`) / RUN QUEUE (`gh_btn_start_queue`) / WATER ALL (`gh_btn_water_all`), nav with ZONES active (`gh_nav_btn_*`). 1-3 beds: full cards with RUN and +Q; 4-6 beds: compact 97x57 grid, a tap opens the bed detail page. STOP and WATER ALL ask through the confirm dialog.
- **Bed detail** (`gh_bed_detail_page`): built (task 025). The same card, one zone, full size, and BACK (`gh_detail_btn_back`); no nav.
  Card states: Watering green, Queued #N blue, Locked / Paused amber, Off / Skipped / Idle `text-dim`; the 3 px top edge is `green-fill` / `blue-fill` / `amber-fill` / `border`.
- **Boot** (`boot_page`): built (D17). Title, "Connecting to Wi-Fi...", spinner (replaces the draft's progress bar), "Valves closed - offline mode in 30s", ESPHome version.
- **Setup** (`setup_page`): built (D10). 2x3 tile grid (NETWORK, TIME, DISPLAY, SERVICE active; CYCLE, SENSORS "Soon"), nav with SETUP active.
- **Setup - Service - Valves** (`valve_test_page`): built (D18). Title "Setup - Service - Valves", header clock at the right (the amber hint line marks service mode). Beds 1-3 only (no Lawn/Pump, no per-row CLOSE), TEST per bed (10 s max from the tap, ~8 s open), STOP, EXIT SERVICE.
- **Setup - Network** (`network_page`): built (D11). Status line, WI-FI / HOME ASSISTANT / IP / ESPHOME / UPTIME rows, BACK, RESTART.
- **Confirm dialog** (`gp_confirm`, top layer): built (D14). Dim layer (`bg` at 65 %), card, CANCEL ghost + one action button: `error-fill` for stop actions only, `green-fill` for other confirmations. ASCII-only texts.
- **Schedules** (`schedules_page`): built (task 026, WATER tab, view only). Header "Schedules" (PREV / NEXT with "1/3" at the right when more than 3 slots), master row (`GREENHOUSE`, next run, switch pill), 3 slot rows of 43 px (start time `value`, today's word `done` green / `missed` amber, days - zones - multiplier as `caption`, switch pill; the tappable end is 68x41, the pill is only drawn), nav with WATER active. First built use of `amber` (a missed slot). Ids `gh_sched_*`, `sched_*`.
- **Screensaver** (top layer): built (D23). Clock (`clock`), date line in `value` ("Friday - 16 Oct"; the built-in fonts have no middle dot), status line, running-bed dot, "Touch to wake".
- **Lawn** (`lawn_page`): concept. Headline soil bar, status card with AUTO-MODE `Switch`, WATER NOW / HOME. No backing entities exist yet.
- **Lawn** (`lawn_page`): concept. Headline soil bar, status card with AUTO-MODE `Switch`, WATER NOW / HOME. Backing data exists (`gp_lawn`, task 024); not wired yet.

Component notes keep the LVGL ids (`gh_btn_run_bed1`, `home_clock_label`…) so a design change can be traced to the YAML that implements it.

## Using the components

The bundle exposes `window.GardenPilot` (React 18): `Screen`, `Header`, `Text`, `Card`, `StatusCard`, `ProgressBar`, `Button`, `NavBar`, `BedCard`, `Stat`, `Switch`, `Icon`. Load the token variables first (`tokens.css`, compiled from `tokens.json`), then `components/bundle.css` (it also pulls Montserrat from Google Fonts), then `components/bundle.js`. Numeric props (`x`, `y`, `w`, `h`, `value`, `size`) accept numbers or numeric strings. Without `x`/`y` a component sits where its container places it, so on a canvas position each one with its slot.
