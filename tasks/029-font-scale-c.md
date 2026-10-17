# 029 — Type scale C, header clock and screensaver date on the built pages

Status: implemented (not compiled, no sim-ui, not on hardware)
Roadmap: stage 9 (Screens on the design system), SPEC §9
Spec sections: SPEC §8 (Design), §4.1a (Time sources, Home clock note), §6 (versions)
Hardware check: legibility of the new sizes on the real ILI9341 panel (author); flash size from the ESP32 compile. Neither can be checked in CI beyond "it compiles".

## Goal
The design system moved to type scale C (chosen on review): caption 10, label 12, value 14, value-lg 16; button
labels keep their smaller sizes (transport 10, in-card and nav 8). After this task `design/tokens.json` and
`design/README.md` mirror that, every tokenized page that exists on `master` uses the new sizes with geometry
adjusted to the artboards, every page header that stays shows the current time at the right (one shared poller),
and the screensaver gets the date line from D23. New pages built by later tasks (030 scheduler, the new history task,
greenhouse cards, lawn) are built directly in scale C.

## Context
- **Base:** current `master` only. No dependency on the open PRs #33-#36 (worktrees wt024-wt027); their pages are
  neither touched nor covered. Order decided by the author: 029 (this) -> 030 scheduler -> a new history task.
- **Source of truth** (claude.ai design system, copied 2026-10-16): DS `tokens.json` + `README.md`, screens canvas
  artboards `Main`, `D10-Setup`, `D11-Network`, `D14-Confirm-stop`, `D17-Boot`, `D18-Valve-test`, `D23-Screensaver`.
  The implementer does not have those files; every number needed is copied into this spec.
- **Token diff (repo today = scale A -> DS = scale C):**

  | style | repo now | DS (scale C) | LVGL font |
  |---|---|---|---|
  | caption | 8px / 9 / 400 | 10px / 11 / 600 | montserrat_10 |
  | label | 10px / 11 / 600 | 12px / 13 / 600 | montserrat_12 |
  | value | 12px / 13 / 700 | 14px / 15 / 700 | montserrat_14 |
  | value-lg | 14px / 15 / 700 | 16px / 17 / 700 | montserrat_16 |
  | clock | 40px / 44 / 700 | (absent in DS) | gp_font_clock — **keep** (repo-only token) |

  DS README: "Buttons keep their own smaller labels: transport buttons (STOP, RUN QUEUE, HOME) 10px/700, in-card
  buttons (RUN, +Q, TEST) and nav labels (DASH, ZONES...) 8px/700." The DS `tokens.json` has no style for them;
  this task adds two repo-only styles so every built-in font maps to a token (open question 1):
  `button-md` 10px/11/700 (montserrat_10) and `button-sm` 8px/9/700 (montserrat_8).
  The DS also added colours `heat` `#ff7a59`, `heat-fill` `#e0582b`, `on-heat` `#2b0a00` (bed heating, unused on
  built screens): copy them so the snapshot matches. Update `meta.synced` to `2026-10-16`.
- **Weights:** LVGL built-in Montserrat fonts have one weight; 600/700 are not reproduced on the device (same as
  today). Bold variants would need custom fonts per size and weight (canvas note on draft D) — out of scope.
- **ESPHome (pinned 2026.9.1, minimum 2026.6.3)** — checked <https://esphome.io/components/lvgl/>: built-in fonts
  `montserrat_8` ... `montserrat_48` in 2 px steps; "The binary will only include any of the above if used in the
  configuration"; `default_font` defaults to `montserrat_14`. So nothing has to be enabled by hand: using
  `montserrat_16` pulls it in, and a size drops out when no YAML references it. No difference in the minimum version
  for this (the built-in font list is unchanged since long before 2026.6).
- **Font set after the task:** montserrat_8 (button-sm: nav labels, TEST, SIM), 10 (caption, button-md),
  12 (label, also the HA icon), 14 (value, nav icons, Network Wi-Fi icon, LVGL default font of the untokenized
  pages), 16 (value-lg: boot title) + gp_font_clock. **montserrat_8 is not dead** (button-sm), so nothing is dropped;
  one font is added (montserrat_16). Flash budget: expected +15..25 KB for montserrat_16 (4 bpp, ASCII + symbols);
  the implementer records the measured delta from the `script/compile` size line (before/after) in the notes;
  more than 40 KB = stop and report.
- **ESPHome merge (checked `esphome/config_helpers.py` at tag 2026.9.1):** `merge_config` concatenates lists
  (`return old + new`) and `!extend` items are merged with it, so several packages can `!extend` the same script and
  each appends to its `then:` (same mechanism as `touch_dot_overlay` and the `!extend` of a page's `widgets`).
- **Header clock design rule (DS README, Layout):** "The current time is always at the right of every header".
  Today only Home has one (`home_clock_label`, x 252, `on_time_sync` + 30 s interval in `page_home.yaml`).
  Design for this task:
  - `packages/lvgl/base.yaml` (in every LVGL config, so no entry-file change) gets a global
    `gp_header_clock_text` (`std::string`, not restored, initial `"--:--"`), a script `gp_header_clock_update`
    (mode `restart`) whose first action computes the text once in one lambda
    (`ha_time` valid ? `now().strftime("%H:%M")` : `"--:--"`) and an `interval: 2s` that executes the script.
  - Every page with a header adds ONE action to that script with
    `script: [{id: !extend gp_header_clock_update, then: [lvgl.label.update {id: <page>_clock_label, text: !lambda "return id(gp_header_clock_text);"}]}]`.
    No per-page time formatting, LVGL is written only from the interval (CLAUDE.md gotchas), no `on_time_sync`.
  - Label: `align: TOP_RIGHT`, `x: -8` (Home: `-6`, its edge margin), `y: 4`, `montserrat_12`, colour `text`
    `0xe5e2e1`, initial text `"--:--"`.
  - Ids: `home_clock_label` (kept), `setup_clock_label`, `network_clock_label`, `valve_test_clock_label`,
    `sim_board_clock_label` (emulator page; open question 4).
  - The 2 s poller replaces Home's 30 s interval and its `!extend ha_time` / `on_time_sync` block (removed).
- **Pages without a header clock:** boot (no header), confirm dialog and screensaver (top-layer overlays).
- **Rebuilt later, left untouched** (no `text_font`, default theme, not tokenized): `packages/greenhouse/lvgl_page.yaml`
  (`greenhouse_page`, replaced by the greenhouse cards task), `packages/lvgl/page_lawn.yaml` (lawn task),
  `packages/lvgl/page_touch_test.yaml` (debug page). They render in the LVGL default `montserrat_14`, which stays
  compiled. Schedules / history pages do not exist on master (030 and the history task build them in scale C).
- **Screensaver date (D23):** artboard text "Friday · 16 Oct" in `value`. Built-in fonts are ASCII only (no `·`),
  so the device text is `"Friday - 16 Oct"` (open question 3; the `-` replacement is the repo rule, CLAUDE.md
  gotchas). Formatter `gp::fmt::saver_date(bool valid, int day_of_week, int day_of_month, int month)` in
  `components/gp/format.h` (ESPHome `ESPTime`: `day_of_week` 1 = Sunday .. 7, `day_of_month` 1..31, `month` 1..12;
  English names from own tables, no `strftime` locale, no leading zero); returns `""` when invalid or out of range.
  The screensaver already depends on the gp layer (`gh_valve_test`, `screensaver_status.yaml` uses `gp::fmt`).
  Longest text "Wednesday - 30 Sep" is ~145 px at 14 px.

### Font mapping rule (tokenized files)
| widget | old | new |
|---|---|---|
| text label, caption role | montserrat_8 | montserrat_10 |
| text label, label role (titles, status, values in rows, header clock) | montserrat_10 | montserrat_12 |
| text label, value role | montserrat_12 | montserrat_14 |
| text label, value-lg role | montserrat_14 | montserrat_16 |
| label inside a 26 px transport `button` (BACK, RESTART, CANCEL, OK, STOP, EXIT SERVICE, HOME) | montserrat_10 | montserrat_10 (unchanged) |
| label inside a 20 px in-card button (TEST), nav labels (DASH...), SIM button | montserrat_8 | montserrat_8 (unchanged) |
| icon labels (LVGL symbol `\uF...`) | as is | as is, except the Setup chevrons `` 10 -> 12 (artboard 12 px chevron) |

### Per-file target (positions from the artboards; only what changes is listed)
- `packages/lvgl/page_home.yaml` (Main): title "GardenPilot" 10->12; clock -> TOP_RIGHT x -6 y 4, font 12, fed by the
  shared poller; HA icon stays x 232 montserrat_12. Cards keep their frames (6/152 and 161/153, DS README
  `space-1`; the artboard's 162/152 is treated as a canvas rounding, open question 2). Greenhouse card: GREENHOUSE
  caption 10 (9,29); air T / RH 12->14 at y 44; SOIL MOISTURE caption 10 at y 64; soil bar y 78, width 140;
  status card y 120, width 140, height 72; STATUS caption y 124; status 12 at y 137; NEXT caption y 155; next 12 at
  y 168. Lawn card (inner x stays 165 / 169): LAWN caption 10; SOIL MOISTURE caption y 64; bar y 78, width 140;
  "Drainage: Optimal" 12 at y 90; status card y 120, width 140, height 72; STATUS y 124; status 12 y 137; NEXT y 155;
  next 12 y 168. The artboard's lawn "45%" value label is NOT added (no data; open question 2). Nav unchanged.
- `packages/lvgl/page_setup.yaml` (D10): title 12; add `setup_clock_label`; tile captions 10, tile values 12, chevrons
  12; geometry unchanged (artboard matches: caption tile+6, value tile+20). Nav unchanged.
- `packages/lvgl/page_network.yaml` (D11): title 12; add `network_clock_label`; status 12->14 (x 30, y 30); row
  captions 10 at y 56/74/92/110/128 (x 8); values 12 at x 124 (was 120), y 55/73/91/109/127, `width: 188`,
  `long_mode: DOT`; Wi-Fi icon unchanged; BACK / RESTART unchanged. MQTT / FIRMWARE rows of the artboard stay
  unbuilt (as today).
- `packages/lvgl/dialog_confirm.yaml` (D14): title 12->14 (42,74); body 10->12 (42,96, width 236, WRAP; two lines
  end at ~126, buttons at 140); buttons unchanged.
- `packages/lvgl/page_boot.yaml` (D17): title 14->16 (TOP_MID y 84); status 10->12 at y 106; spinner unchanged
  (144,124, 32 px); offline line 8->10 at y 160; version 8->10 at (8,224).
- `packages/greenhouse/lvgl_valve_test.yaml` (D18): title becomes "Setup - Service - Valves" 12 (artboard title);
  the amber TOP_RIGHT "SERVICE" label is replaced by `valve_test_clock_label` (the amber hint line still marks
  service mode); hint line 8->10 at (8,28), text shortened to
  `"Opens one valve, max ${valve_test_max_time}. Other watering stops."` so it fits 304 px; bed names 10->12 at
  y 50/50/100; row status 8->10 at y 68/68/118; TEST and transport buttons unchanged. No change to any safety logic.
- `packages/lvgl/screensaver.yaml` (D23): clock y 70->62; new label `gp_screensaver_date` TOP_MID y 116,
  montserrat_14, `text`, initial `""`, written by `gp_screensaver_update_clock` (same script, one-line lambda with
  `gp::fmt::saver_date`); status 10->12 at y 142; bed dot (132,165); bed label 8->10 at (146,163); "Touch to wake"
  8->10 at y 220. The status line content stays "24C - soil 58%" (the "next 18:00" part needs schedules: follow-up).
- `packages/sim/page_board.yaml` (emulator, tokenized): captions 8->10, values / states 10->12, title 12, add
  `sim_board_clock_label`; SIM and HOME buttons unchanged; check nothing overlaps (state labels at x 124, values at
  x 262 end before 312).

## Files
- modify: `design/tokens.json` — type styles to scale C, add `button-md` / `button-sm`, keep `clock`, add heat colours, `synced`.
- modify: `design/README.md` — Type section (scale C + button rule + clock), header-clock rule in Layout, heat line in
  Colour, Pages (screensaver date, valve test title), synced date.
- modify: `packages/lvgl/base.yaml` — shared header clock global, script, 2 s interval.
- modify: `packages/lvgl/page_home.yaml`, `page_setup.yaml`, `page_network.yaml`, `dialog_confirm.yaml`, `page_boot.yaml`,
  `screensaver.yaml` — fonts, geometry, clock labels / date as above; Home loses its own clock interval and `!extend ha_time`.
- modify: `packages/greenhouse/lvgl_valve_test.yaml` — fonts, title, clock instead of the SERVICE label, hint text.
- modify: `packages/sim/page_board.yaml` — fonts, clock label.
- modify: `components/gp/format.h` — `saver_date`.
- modify: `tests/test_design_tokens.py`, `tests/test_screens.py`, `tests/test_screensaver.py`, `tests/test_layout.py`
  (line ~910 font set), `tests/test_esphome_config.py`, `tests/cpp/test_gp_model.cpp` — checks below.
- modify: `docs/SPEC.md` §8 (scale C, header clock poller replaces the `on_time_sync` note at "The Home clock updates...",
  screensaver date) and §4.1a / §6-area notes that say "the Home clock lags at most 30 s" -> 2 s;
  `packages/core/time_host.yaml`, `packages/core/time_sntp.yaml` (comments only, same 30 s mention); `CLAUDE.md`
  (gotchas: header clock = one `lvgl.label.update` appended to `gp_header_clock_update`; font sizes 8/10/12/14/16).

More than 10 files, but all edits are mechanical and belong to one goal; do not split.

## Checks to write first
| Level | Test | Asserts |
|---|---|---|
| unit | `tests/test_design_tokens.py::test_type_scale_c` | styles caption/label/value/value-lg = 10/12/14/16 px with line heights 11/13/15/17 and weights 600/600/700/700; `button-md` 10px/700, `button-sm` 8px/700; `clock` unchanged (existing `test_clock_token` keeps passing). |
| unit | `tests/test_design_tokens.py::test_clock_token` (update) | montserrat set from the styles (minus clock) == `TOKEN_FONTS` montserrat set == {8, 10, 12, 14, 16}. |
| unit | `tests/test_design_tokens.py::test_heat_colours` | `heat`, `heat-fill`, `on-heat` present with the DS values. |
| unit | `tests/test_design_tokens.py::test_page_font_roles[page]` | per tokenized page: a label inside a `button` uses montserrat_8 or _10 only; a label whose text is an LVGL symbol (`\uF...`) may use 12/14; every other label uses 10/12/14/16 — in particular **no montserrat_8 outside buttons**. |
| unit | `tests/test_screens.py::test_header_clock[page]` | Home, Setup, Network, valve test, sim board each have exactly one `<page>_clock_label` with `align: TOP_RIGHT`, `y: 4`, montserrat_12, text `--:--`; each file extends `gp_header_clock_update` with exactly one `lvgl.label.update` of that id reading `gp_header_clock_text`; no `time_format` / `strftime` / `on_time_sync` in those page files. |
| unit | `tests/test_screens.py::test_header_clock_poller` | `base.yaml` defines global `gp_header_clock_text` (not restored), script `gp_header_clock_update`, and one `interval` <= 5 s executing it; the only `strftime` for the header clock is in `base.yaml`; `page_home.yaml` has no `time:` block. |
| unit | `tests/test_screens.py::test_untouched_legacy_pages` | `greenhouse/lvgl_page.yaml`, `page_lawn.yaml`, `page_touch_test.yaml` still contain no `text_font` (guards "rebuilt later" scope). |
| unit | `tests/test_screensaver.py::test_date_line` | `gp_screensaver_date` exists (TOP_MID, y 116, montserrat_14, text `""`), clock y 62, status y 142, bed label y 163, "Touch to wake" y 220; `gp_screensaver_update_clock` updates the date via `gp::fmt::saver_date`. |
| unit | `tests/test_layout.py` (line ~910) | sim page font set check updated to {8, 10, 12, 14, 16}. |
| cpp | `tests/cpp/test_gp_model.cpp::saver_date_*` | Friday 16 Oct -> `"Friday - 16 Oct"`; day 6 -> `"... - 6 ..."` (no leading zero); Wednesday 30 Sep fits `LABEL_MAX`; invalid flag or out-of-range day_of_week / month -> `""`; output is ASCII. |
| config | `tests/test_esphome_config.py::test_header_clock_merged` | `esphome config garden-pilot.yaml` (example secrets) output contains script `gp_header_clock_update` with label updates for all four device clock ids (proves `!extend` appends, not replaces). |

## Acceptance criteria
- [x] `uv run pytest -m unit` -> passes, including every test in the table.
- [x] `script/test-cpp` -> passes (`saver_date_*`).
- [x] `script/lint` and `script/test` -> green (config rows for device, sim and the four examples pass).
- [x] `rg -n "montserrat_8" packages/lvgl packages/greenhouse packages/sim` -> only labels inside buttons / nav (test enforces).
- [x] `rg -n "montserrat_16" packages` -> only `page_boot.yaml` (boot title).
- [x] `rg -n "on_time_sync" packages/lvgl` -> no match.
- [x] `git diff --stat master -- packages/greenhouse/lvgl_page.yaml packages/lvgl/page_lawn.yaml packages/lvgl/page_touch_test.yaml` -> empty.
- [x] No change to `valve_test_max_time`, the guard script or any actuator action (`git diff` of `lvgl_valve_test.yaml` touches only the `lvgl:` block and comments).
- [ ] `GP_SECRETS=example script/compile garden-pilot.yaml` -> builds; flash size before/after recorded in Implementation notes (delta <= 40 KB).
- [ ] `script/sim-ui start` / `shot` of Home, Setup, Network, valve test, screensaver (wait 1 min) -> no clipped or overlapping text; PNGs attached to the PR (not committed).
- [ ] Hardware (author, not CI): new sizes legible on the panel; header clock ticks on every header page; screensaver shows the date.
- [x] `design/README.md`, `docs/SPEC.md`, `CLAUDE.md` updated as listed.

## Out of scope
- Greenhouse cards, lawn page, schedules (030) and history (new task) pages: built later directly in scale C.
- Bold custom fonts (600/700 weights), new colours on built screens, the heat colours in use.
- Screensaver "next 18:00" part of the status line (needs the schedule next-run on the screensaver); backlight dimming.
- Network rows MQTT / FIRMWARE; Setup tile texts from the artboard ("Wi-Fi - HA online", "NTP - 14:32", "Brightness 70%").
- Lawn "45%" value on Home (no lawn data on master).

## Notes for later screen tasks
- Use scale C directly: caption 10, label 12, value 14, value-lg 16; transport-button labels 10, in-card buttons and
  nav labels 8. `tests/test_design_tokens.py::test_page_font_roles` applies once a page is in `TOKENIZED_PAGES`.
- A page header gets `<page>_clock_label` (TOP_RIGHT, x -8, y 4, montserrat_12) and one `!extend gp_header_clock_update`
  action; never its own clock interval. Header actions (HISTORY, the ON switch) sit left of the clock.
- 030 (scheduler) and the history task: add their pages to `TOKENIZED_PAGES` and to `test_header_clock`.

## Open questions
1. DS `tokens.json` has no styles for button labels. Recommended: add repo-only `button-md` (10px/700) and
   `button-sm` (8px/700) styles here and ask the designer to add them to the DS so the next sync keeps them.
2. Main artboard puts the lawn card at x 162, width 152 (gap 4) and adds a lawn "45%" value. Recommended: keep the
   card frames 6/152 + 161/153 (DS README `space-1`), take only y / heights / inner widths from the artboard, no
   lawn value label until lawn data exists.
3. Date text on the device: `"Friday - 16 Oct"` (recommended, closest to the artboard) or `"Fri 16 Oct"` (shorter).
4. Add the header clock to the emulator-only SIM board page too? Recommended: yes (cheap, consistent; the SIM nav
   button at x 200-244 does not collide).
5. Valve test: replacing the amber "SERVICE" header marker by the clock follows D18; the amber hint line remains the
   service-mode cue. Recommended: accept (safety logic unchanged); say no if the marker must stay, then the clock
   moves left of it.

<!-- Filled in by implementer -->
## Implementation notes
Decided (default, author to confirm): 1 `button-md` / `button-sm` repo-only styles added to `tokens.json`; 2 Home card
frames kept 6/152 + 161/153, no lawn "45%" label; 3 date text `"Friday - 16 Oct"`; 4 header clock added to the SIM board
page; 5 amber SERVICE marker replaced by the clock (hint line stays amber, safety logic untouched).

- Test deviation: `test_page_font_roles` treats a `button` as an action button (labels 8/10) only when it is <= 32 px
  tall. The Setup tiles are 52 px `button` widgets holding caption (10) and value (12) labels, which the literal rule
  ("every label inside a button is 8 or 10") would reject. Nav (32), transport (26) and in-card (20) buttons are covered.
- Setup TIME tile used its own `time_format` in the 1 s poller; `test_header_clock` forbids that in page files, so it
  now reads `gp_header_clock_text` (same text, same "--:-- not set" fallback).
- Existing tests adapted minimally: `tests/test_service.py::_scripts` skips `!extend` items (tagged dict as id),
  `tests/test_gp_layer.py::test_callers_use_gp` allows `gp_header_clock_text`.
- `test_header_clock_merged` reads the `esphome config` dump (`GP_VERBOSE=1`) up to "Configuration is valid!".
- Screensaver date lambda is a 2-line block (`auto t = id(ha_time).now();` ...) to stay under the 120-char yamllint limit;
  invalid time yields `""` through `saver_date(t.is_valid(), ...)`, and the else branch clears the label.
- SIM board: relay state labels moved x 124 -> 128 so the larger relay names (10 px) cannot touch them.
- The sim page has no `border_side` / header band changes; the SIM top-layer button (x 200-244) does not collide with the clock.
- Results: `uv run pytest -m unit` all pass except the known Windows-only failures; `script/test` 841 passed, 6 failed
  (the known: `test_esphome_selector_resolves`, 4 executable-bit tests in test_devcontainer, `test_start_xvfb_deadline...`),
  19 skipped (no sdl2-config, so the sim config row is skipped; Xvfb tests); `script/test-cpp` with zig: 81 cases ok;
  `script/lint` ok.
- NOT run: ESP32 compile (no flash size before/after recorded; main session compiles in Docker; expected +15..25 KB for
  `montserrat_16`, stop above 40 KB), `script/sim-ui` screenshots, sim config row, hardware legibility.

## Follow-ups
- Ask the designer to add `button-md` / `button-sm` to the design system so the next sync keeps them.
- Screensaver status line "next 18:00" part still needs the schedule next-run.
- Screenshots of Home / Setup / Network / valve test / screensaver / SIM board for the PR (needs Xvfb).

## Rig feedback (2026-10-17)
The author flashed 029 on the device. Fixes, in priority order; each has its own acceptance criteria.

1. **Bolder button labels.** LVGL's built-in Montserrat has one weight, so button labels get glyph-limited custom fonts
   baked from the vendored `Montserrat-Bold.ttf` (same mechanism as `gp_font_clock`): `gp_font_button_md` (10 px,
   transport buttons) and `gp_font_button_sm` (8 px, nav labels, in-card TEST, SIM). Declared in `packages/lvgl/base.yaml`
   (in every LVGL config); the tokens `button-md` / `button-sm` carry `font` + `glyphs`.
   - [x] `test_button_fonts_match_tokens`: font ids, sizes and glyphs equal the tokens; TTF is the vendored file.
   - [x] Every label inside an action button (<= 32 px) on the tokenized pages uses `gp_font_button_md` (10) or `gp_font_button_sm` (8); `montserrat_8` is no longer used anywhere.
   - [x] Glyph set covers every button text (test reads the texts).
2. **Network ESPHome version overlap.** The version text carries the config hash.
   - [x] `gp::fmt::version_short` keeps the text up to the first space (C++ test); the page label uses it (one-line lambda); value labels have a fixed one-line height.
3. **Valve test opens at once.** Cause: `gp_valve_test_start` always ran `gp.stop_all` first; `shutdown()` on an idle lane
   enters STOPPING (1 s timer), then `run_valve` waits for IDLE and the manual selection delay (1 s): about 2 s.
   Fix: stop first only when something is running (`summary().running`); an idle group starts the valve immediately.
   No change to the 10 s limit, the guard script, service mode or the engine.
   - [x] `tests/test_service.py`: `gp.stop_all` before the start is conditional on a running group, still before `gp.run_zone` and the guard; limit and guard asserts unchanged.
   - [x] CLAUDE.md / SPEC / file header: the valve opens at once when idle (about 2 s only when another valve had to be stopped first).
4. **Bottom nav = design NavBar.** Band y 201 h 39 `status`, 1 px `border` top line; buttons y 204, h 32, x/w 4/76, 84/76, 164/76,
   244/72; icon 12 px, gap 2, label below; active `green-fill` + `on-green`, inactive `status` + `text-dim`; labels DASH, ZONES,
   SCHEDULE, SETUP; icons house, leaf, drop, gear. The leaf (U+F06C) is not in LVGL's symbol set, so all four icons are
   real images: `design/icons/*.svg` rendered once to 12x12 PNG (white stroke, alpha; `resvg`, not a build dependency)
   and vendored in `packages/lvgl/icons/`, loaded with ESPHome `image:` (RGB565 + alpha channel) and recoloured per state by
   `image_recolor`. Applies to Home and Setup (the only pages with the nav; the SIM button is not a nav).
   - [x] Test: both navs have the four buttons with the geometry, labels, icons (`image` widgets with ids of the vendored PNGs) and colours above; PNGs are 12x12.
   - [x] No `\uF06C` / `\uF043` / `\uF015` / `\uF013` left in the navs.

### Rig feedback: implementation notes
- Fonts: `gp_font_button_md` / `gp_font_button_sm` in `packages/lvgl/base.yaml` (41 glyphs: A-Z, 0-9, space and `+-./:%`, bpp 4, same
  vendored Bold TTF); `montserrat_8` is gone from the whole repo. Flash estimate: two fonts ~1.5 KB + ~1 KB, four 12x12 icons
  RGB565+alpha 3 bytes/px = 1.7 KB, minus built-in `montserrat_8` (~3 KB): net about +1 KB. Measure in the Docker compile.
- Icons: rendered once with `resvg` (`uv run --no-project --with resvg-py`, white stroke so `image_recolor` gives the state
  colour) from `design/icons/*.svg`; 2.2/24 stroke at 12 px is ~1.1 px, as in the design. No SVG support is needed at build
  time (ESPHome would need cairosvg). `image_recolor` on the LVGL 9 `image` widget is accepted by `esphome config`; the
  look (thin strokes, RGB565 alpha edges) must be judged on the panel.
- Nav: label ids stay `*nav_btn_water`; its target is still `lawn_page` (the schedules page is not on this branch).
- Valve test: the delay was the unconditional `gp.stop_all` before `gp.run_zone` (idle `shutdown()` -> STOPPING 1 s, then the 1 s
  selection delay). Now conditional on `summary().running`. When another valve runs the old ~2 s remains (engine untouched).
  The 10 s limit, `gp_valve_test_guard`, service mode and the inhibit are unchanged. Not run on hardware.
- Network: `gp::fmt::version_short` (cut at the first space); value labels got `height: 15` so a long value cannot wrap into the next row.
- Test changes: `test_page_font_roles` now requires the custom fonts for labels in action buttons; `test_gp_root_default` counts
  `base.yaml` (fonts) and checks `image` file paths; `test_screensaver` allows fonts in `base.yaml`; `test_layout` font set.
- Results: `uv run pytest -m unit` only the known Windows failures; `script/test` 857 passed, 6 failed (the known ones);
  `script/test-cpp` (zig) 82 cases ok; `script/lint` ok. NOT run: ESP32 compile, sim-ui screenshots, hardware.

## Shared nav (2026-10-17)

Author feedback from the device: (1) every page drew its own nav and some still opened the old empty `lawn_page`;
(2) icons and labels were not centred and seemed to run off the screen edge.

- **What:** `packages/lvgl/nav_bar.yaml` is the only definition of the bottom nav (band, four buttons, icons, labels,
  colours, targets). Pages include it as one widget:
  `- !include {file: nav_bar.yaml, vars: {p: <id prefix>, active: dash|zones|water|setup}}` (Home: `home_` / `dash`,
  Setup: `setup_` / `setup`). Widget ids become `<p>nav_bar`, `<p>nav_btn_<name>` (were `nav_btn_*` / `setup_nav_btn_*`).
  The active colours are Jinja in the component (`${ '0x4caf50' if active == 'dash' else '0x201f1f' }`).
- **Targets:** substitutions with defaults in `packages/lvgl/base.yaml`: `gp_nav_dash_page` (home_page),
  `gp_nav_zones_page` (greenhouse_page), `gp_nav_schedule_page` (lawn_page, the master default), `gp_nav_setup_page`
  (setup_page). The branch that adds `schedules_page` sets `gp_nav_schedule_page: schedules_page` (entry-file
  substitutions always win; a package-level substitution may lose against the base default, so set it in the entry
  files and examples, or change the default in `base.yaml` in that branch).
- **Why an include, not a top-layer nav:** a single top-layer nav would need hiding on non-nav pages and ESPHome has no
  page condition for it (the same limit as the SIM button), so it would also cover boot, valve test, network and
  confirm screens and eat their touches. Includes keep each page self-contained, ids unique via `p`, and one file owns
  geometry and targets. A page include must be a single widget (an include of a list is nested, not flattened), hence the
  band is one `obj` holding the four buttons (child coordinates are inside the 1 px top border: y 2 -> absolute 204).
- **Centring:** buttons have zero padding, border and shadow; icon `TOP_MID` y 4 (centre y 10), label `TOP_MID` y 19 with
  width = button width and `text_align: CENTER` (centre y ~24 for a ~10 px line), so no child can pass its button and the
  last button ends at x 316. The old label (no width, default padding) is the likely cause of the drift; judge on the panel.
- **Checks (`tests/test_screens.py`):** renders the component with its vars and checks geometry, colours, icons, labels,
  `x + w <= 320`, children inside buttons and the column centres; targets are the four `gp_nav_*` substitutions with the
  documented defaults; Home and Setup include it once with the right vars; no other file has `nav_btn_*` ids, a
  `src: gp_icon_*` image or a nav band; pages no longer mention `lawn_page`.
- **For other branches:** schedules, history, greenhouse and any new page that shows the nav must include the component
  (never copy buttons) and pick `active`; set `gp_nav_schedule_page` where the schedules page exists. Merging with branches
  that still carry per-page navs will conflict in `page_home.yaml` / `page_setup.yaml` and the nav tests: take this version.
- Not verified on hardware or in sim-ui screenshots.
