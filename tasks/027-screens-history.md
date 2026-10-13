# Task 027: History page

> Split 2026-10-13 by the author: screens are separate tasks. Scope of THIS task = **Part C only** of the combined spec below (history page reached from a HISTORY header button, paged rows) **plus** the gp history changes it needs: the `result` byte taken from `reserved` (PersistBlob size and magic unchanged) and skip entries. Part A (greenhouse cards, task 025) and Part B (schedules, task 026) are developed in parallel from master: do not implement them. Where the history page needs a header/nav element from Part A, add the minimal version here. Open questions: recommended defaults apply until the author confirms.

---

# 025 — Screens: Greenhouse bed cards, Schedules (WATER tab), History, Home NEXT fix

Status: planned
Roadmap: stage 9 (screens on the design system: Greenhouse, navigation, bed layout variants); stage 11 (WATER tab,
view only; the time editor stays a later task); SPEC §9.1 backlog item "Watering history on screen"
Spec sections: SPEC §8 (Design; "Screens: slots and widgets" and §10.2 from PR #21, branch
`task/017-screens-decision`), §4.1 (`gp_*` layer), §7 (testing without hardware), §6 (pinned / minimum ESPHome)
Hardware check: the three pages must be checked on the author's breadboard display (ESP32-S3 + ILI9341 + XPT2046):
rendering, touch targets of the 20 px in-card buttons, free heap after every page was opened. The implementer cannot
do this; the human does it or the PR says explicitly that it was not done.

Branch: `task/025-screens-greenhouse-schedules-history`. Task 024 (lawn group) runs in parallel: rebase on it if it
merges first; never edit the files it owns (lawn packages, `examples/my-garden.yaml`, `packages/lvgl/page_lawn.yaml`).

## Goal
The device gets its first three design-system screens, in English with the built-in Montserrat sizes only:
1. **Greenhouse page (ZONES tab)**: up to 6 bed cards from one template `card_bed.yaml` (one include per slot,
   slots past the zone count hidden at boot), full cards for 1-3 beds and a compact 3x2 grid for 4-6 beds (tap = bed
   detail page). A card shows name, state, time left with a progress bar, last watering (time, duration, result), soil
   moisture when the zone has a sensor, and RUN / +Q. Page actions STOP, RUN QUEUE and WATER ALL; STOP and WATER ALL ask
   through the confirm dialog. It replaces today's debug text column on the default theme.
2. **Schedules page (WATER tab)**: view-only list of the `garden_schedule` slots (start, days, zones, multiplier,
   today's state, on/off toggle), the master "schedules" switch and the next run. No time editor.
3. **History page** (from a HISTORY button in the Greenhouse header, BACK returns): the gp history (100 entries in
   flash) as a paged list of 6 rows: zone, start date and time, duration, result.

The Home "NEXT" label shows the next scheduled run instead of the queue time (known defect, SPEC §8). Everything reads
irrigation data by group + zone index through `gp_*` (and schedule data through the schedule hub), so task 024's lawn
group can reuse the card and the history page later.

## Context

### Decisions already made
- PR #21 (SPEC §8 "Screens: slots and widgets", §10.2, decided 2026-10-10): one card template, up to 6 slots, slots
  past the group's zone count hidden at boot; data by zone index through `gp_*`, never bed ids; 1-3 beds = full cards
  with RUN and +Q, 4-6 beds = compact grid, **tap opens the bed page**. Home widgets, weather, heating: later tasks.
- Author, 2026-10-13: scope = the three screens above + the Home NEXT fix; UI language English (built-in fonts,
  ASCII only, no new font unless a token needs one); Home widgets, weather, heating and the lawn page are out of scope.
- **Compact cards open a detail page** (`gh_bed_detail_page`). Reason: a 97x57 px card cannot hold two 20 px buttons
  plus the state and time without going below `btn-h-sm` or overlapping text, and the detail page is the same card
  template included once more with a run-time zone index (no second card design, no second set of formatters). This
  is also what PR #21 decided.
- **Navigation**: the four tabs stay (DASH, ZONES, WATER, SETUP). WATER now opens `schedules_page` (it opened the
  placeholder `lawn_page`). ZONES and WATER pages get the bottom nav (y=201, same as Home/Setup) with their own tab
  active. History and the bed detail page are sub-pages without nav, with a BACK ghost button (like the Network page).
- **No scrolling** (design/README "Never reflow; never add scrolling"): History and Schedules render a fixed window of
  rows and page with PREV / NEXT buttons (`btn-h-sm`). History never creates 100 widgets.

### Current state (read for this plan)
- `packages/greenhouse/lvgl_page.yaml`: default-theme labels (`gh_greenhouse_*`) + buttons for beds 1-3 hard-wired.
  `packages/greenhouse/sensors_air_dht.yaml`, `sensors_soil.yaml` and `packages/sim/sensors_lvgl.yaml` write
  `gh_greenhouse_t_label`, `gh_greenhouse_rh_label`, `gh_greenhouse_soil_hint` ("Air: 22.5 C", "RH: 60 %",
  "Soil: 58 %"). Keep these three ids on the new page (stats strip) so those packages keep compiling.
- `packages/greenhouse/gp_lvgl_status.yaml`: 1 s poller guarded by `changed_since(gp_gh_seen)`; writes the six debug
  labels, `gh_home_irr_status` and `gh_home_next_label` (from `gp::fmt::home_next`, = queue time with hours dropped:
  the defect).
- `components/gp`: `ZoneView` has `state`, `time_left`, `run_duration`, `queue_position`, `last_*`, and a reserved
  `soil` that is always empty. `HistoryEntry {epoch, duration, zone, source, uint16 reserved}`; history = completed
  runs only (no skips, no result). `PersistBlob` (magic "GP01") is stored with the ESPHome preferences: **its size
  and layout must not change** or every device loses its history on upgrade.
- The stop / completed decision exists in `GpGroup::refresh` (`stop_ms_` within `STOP_WINDOW_MS`).
- Engine skips: `garden_zones` records only soil skips (`"soil moisture X > Y"` or `"soil sensor unavailable"`);
  the adapter `components/garden_zones/gp_engine.h` passes stamp + text in `ZoneInput`.
- `components/garden_schedule/garden_schedule.h`: `next_run()`, `day_runs(offset)`, `next_run_text()`,
  `slot_number(i)`; slot config lives in `cfg_[]` (enabled, start_minute, days_mask, pct, zone_mask), no accessor,
  no revision counter, no action to switch a slot by index.
- `bed_soil.yaml` (device) and `packages/sim/bed_soil.yaml` define `gh_bed${bed}_soil_moisture`; nothing links it to
  the zone.
- Both board profiles have exactly `board_relay_1..3` (enforced by `tests/test_layout.py`); a 6-bed config cannot be
  built from the real profiles without a hardware change (the human's call).
- `script/test-cpp` compiles every `tests/cpp/*.cpp` into one binary: a new test file is picked up automatically.

### ESPHome behaviour checked (pinned 2026.9.1)
- `esphome/config_helpers.py` `merge_config`: lists from packages are **concatenated**, never matched by id.
- `esphome/config.py` `resolve_extend_remove`: `!extend` / `!remove` match list items by their `id` and recurse into
  nested lists, so `gp_zone: [{id: !extend gh_bed1_switch, soil_sensor_id: ...}]` and
  `lvgl: pages: [{id: !extend schedules_page, widgets: [...]}]` work (an item whose id is nested one level, such as
  `- obj: {id: ...}` inside `widgets:`, is **not** matched: extend pages, not widgets inside pages).
- esphome.io LVGL widgets: "Hidden objects are ignored in layout calculations"; the `ignore_layout` flag exists;
  widget update actions take a list of ids.
- **Implementer must verify** on 2026.9.1 and on the minimum 2026.6.3 (cite the source lines in the notes):
  `!include {file, vars}` as an item of a `widgets:` list and of a `script:` list; which `lvgl.widget.update`
  properties accept lambdas (x, y, width, height); `lvgl.widget.hide/show` with a list of ids. If geometry cannot be
  set from a lambda, fall back to a flex container (`layout: flex`, `flex_flow: ROW_WRAP`) and per-mode widths via
  hidden/shown variants; record the choice.

### Structure (recommended; the implementer may adjust and must say why)
- **Card template** `packages/lvgl/card_bed.yaml`: one widget (root `obj`), vars `p` (id prefix, `gh`), `group`
  (gp group id, `gp_greenhouse`), `slot` (`1`..`6` or `d` for the detail page), `zone` (a C++ expression: `0`..`5`, or
  `id(gh_detail_zone)`). Ids `${p}_card${slot}` (root), `_edge` (3 px top state edge), `_name`, `_state`, `_time`,
  `_bar`, `_last`, `_soil`, `_run`, `_queue`. Root `hidden: true`. RUN = `gp.run_zone {id: ${group}, zone: ${zone}}`,
  +Q = `gp.enqueue_zone`, a compact card's click sets `gh_detail_zone` and shows `gh_bed_detail_page`. It is generic
  (no `gh_bed`, no engine name), so a lawn page can include it with `p: lw, group: gp_lawn`.
- **Card refresh**: one script per slot from a fragment `packages/lvgl/card_bed_refresh.yaml` (same vars) holding the
  label/bar/colour/visibility updates of that card, each a one-line lambda into `gp::fmt::*` / `gp::layout::*`. The
  greenhouse poller (`gp_lvgl_status.yaml`) calls the 7 scripts when `changed_since` is true. Geometry and slot
  visibility are applied on the first refresh (the zone count does not change at run time).
- **Geometry** (pure `gp::layout::bed_card(count, slot)`), cards area x 8..312, y 48..168 (between the stats strip
  and the transport row), gap `space-3` 6 px: 1 bed 304x120, 2 beds 149x120, 3 beds 97x120 (full); 4-6 beds 97x57 in
  3 columns x 2 rows (compact: name, state, time or soil; last line, soil and buttons hidden). Slots >= count hidden.
- **Greenhouse page** `packages/greenhouse/lvgl_page.yaml` (rewritten): header "Greenhouse" at x=8 + HISTORY ghost
  button (`gh_btn_history`, 20 px) at the right; stats strip AIR / HUMIDITY / SOIL (captions + the three kept ids);
  divider; the 6 card includes; divider; transport row (`btn-h-md` 26 px) STOP (`gh_btn_stop`, `error-fill`,
  leftmost), RUN QUEUE (`gh_btn_start_queue`, `blue-fill`), WATER ALL (`gh_btn_water_all`, `blue-fill`, widest);
  nav with ZONES active (`gh_nav_btn_*`). Second page `gh_bed_detail_page` in the same file: header with the zone
  name, the card include with `slot: d`, BACK (`gh_detail_btn_back`) to `greenhouse_page`.
- **Schedules shell** `packages/lvgl/page_schedules.yaml` (`schedules_page`, generic, always included with LVGL):
  header "Schedules", empty-state label `sched_empty_label` ("No schedules configured"), nav with WATER active
  (`sched_nav_btn_*`). It must compile without any schedule package.
- **Greenhouse schedule rows** `packages/greenhouse/lvgl_schedules.yaml` (needs `gh_schedule` and the slots):
  `lvgl: pages: [{id: !extend schedules_page, widgets: [...]}]` with a master row (caption "GREENHOUSE", switch-like
  toggle bound to `gh_schedules_on` via `switch.toggle`, "Next: Tue 06:00"), 3 slot rows per page
  (`gh_sched_row{1..3}_*`: text line, today word, toggle), PREV / NEXT + "1/3" when there are more than 3 slots;
  a 1 s poller guarded by the hub's `changed_since` (and a page-change flag) that also writes `gh_home_next_label`.
  A row toggle calls `garden_schedule.toggle_slot {id: gh_schedule, index: <page*3 + row>}` (new action: toggles that
  slot's enabled switch entity, so Home Assistant sees it). The design `Switch` track is 14 px: the tappable object is
  the whole row end (>= 20 px tall), the pill is only drawn.
- **History page** `packages/greenhouse/lvgl_history.yaml` (`gh_history_page`): header "History", 6 row labels
  `gh_hist_row{1..6}` (label 10 px, one line each), "1-6 of 37" / "No watering yet" label, PREV / NEXT
  (`gh_hist_btn_prev/next`, `btn-h-sm`), BACK (`gh_history_btn_back`) to `greenhouse_page`; a 1 s poller guarded by
  `history_changed_since` + page flag. Global `gh_hist_page` (restore false).

### gp / schedule data changes (all pure parts tested first)
- `history.h`: `enum class Result : uint8_t {UNKNOWN=0, DONE, STOPPED, SKIPPED_WET, SKIPPED}`; `HistoryEntry` keeps
  its size: `uint16_t reserved` becomes `uint8_t result; uint8_t reserved;` (old entries read as UNKNOWN, magic
  unchanged). `result_word()`: done / stopped / skipped wet / skipped / `-`; a SERVICE entry shows `test`.
  `History::last_for_zone(zone)` = newest non-service entry of that zone.
- `gp.h` writes `result` when it pushes a run (STOPPED inside the stop window, else DONE; a watchdog-ended run counts as
  DONE, like `completed` today) and pushes **skip entries** (duration 0, `SKIPPED_WET` / `SKIPPED`) when the tracker
  sees a new engine skip stamp. `ZoneInput` gets `skip_wet`; the adapter `gp_engine.h` sets it (engine-side knowledge of
  its own texts, documented there). Skips are persisted like runs (one write per entry).
- `zone_model.h`: `ZoneView::run_total` (time left at the first RUNNING sample of a run, RAM only) for the progress bar,
  so a run longer than `run_duration` (multiplier, manual duration) still goes 0 -> 100 %; `ZoneView::soil` filled from
  `ZoneInput::{has_soil, soil}`; the revision hash includes the soil rounded to whole percent.
- `gp_zone:` gets optional `soil_sensor_id` (`sensor`); codegen `group->set_zone_soil(position - 1, sensor)`; `gp.h`
  copies the sensor state (NaN / no state = empty) on refresh. `bed_soil.yaml` (device) and `packages/sim/bed_soil.yaml`
  add `gp_zone: [{id: !extend gh_bed${bed}_switch, soil_sensor_id: gh_bed${bed}_soil_moisture}]`.
- `GpGroup`: `history_changed_since(uint32_t &seen)` (a RAM push counter, not in the blob); glue one-liners for the
  pollers, e.g. `history_row(index)` and `card_last(zone)` that convert the epoch to local time
  (`ESPTime::from_epoch_local`) and call the pure formatters.
- `garden_schedule`: pure helpers next to `schedule_core.h` (formatters for the schedule's own data stay in the schedule
  component so `gp` never depends on it, and vice versa): days text, zones text, row text, today word, short next run,
  a view hash. Hub accessors `slot_count()`, `slot_view(i)`, `changed_since(uint32_t &seen)`, `next_run_short()`;
  action `garden_schedule.toggle_slot {id, index}` (0-based index in include order; out of range = WARN, no-op).
- `gp::fmt::home_next` is removed (its two checks in `tests/cpp/test_gp_model.cpp` go with it). Debug formatters that
  are no longer referenced (`modes_line`, `durations_line`, `zone_left_line`, `total_left_line`, `queue_line`,
  `status_line`) are removed with their checks unless still used; `ha_status`, `home_status`, `valve_test_*`,
  `saver_bed` stay.

### Texts (ASCII, design/README "Content")
- Card state word + colour token: RUNNING `Watering` green; QUEUED `Queued #2` blue (queue position + 1); DISABLED
  `Off` text-dim; LOCKED `Locked` amber; PAUSED `Paused` amber; SKIPPED `Skipped` text-dim; IDLE `Idle` text-dim. Top
  edge fill: green-fill running, blue-fill queued, amber-fill locked/paused, `border` otherwise. No red (error-fill is
  STOP only). This is the first built use of `amber` / `amber-fill` (tokens exist, reserved for warnings and a paused
  bed): update `design/README.md`.
- Card time: running `04:59` (`1:02:05` from one hour), otherwise the run duration `5 min`; progress 0-100.
- Card last: today `06:00 5 min done`, earlier `13 Oct 5 min stopped`, clock never valid `--:-- 5 min done`, none `-`;
  fits the label width of a 97 px card at its font (checked by a length limit in the test).
- Soil `Soil 58%`; no sensor = label hidden.
- History row `B2  13 Oct 06:00  5 min  done`, `45 s` below one minute, `--:--` when the epoch is 0.
- Schedule row `06:00  Mon-Fri  B1 B3  150%`; days `Daily`, `Mon-Fri`, `Sat Sun`, `Mon Wed Fri`, `Never`; zones `All`
  or `B1 B3`; today word `done` / `missed` / `skipped` / empty; Home NEXT `06:00` (today), `Tue 06:00`, `--:--`.
- Stats strip values follow the design ("22.5C", "60%", "58%"): change only the format strings of the three
  greenhouse-page labels in `sensors_air_dht.yaml`, `sensors_soil.yaml`, `packages/sim/sensors_lvgl.yaml` (no other
  change in those files; their `on_value` LVGL updates are legacy, see Follow-ups).
- Confirm texts: STOP as today (danger); WATER ALL: title "Water all beds?", body "Every enabled bed runs in turn.",
  action "WATER ALL", `danger: false` (green-fill primary button).

### Tokens used (no new colour, no new font size)
Colours: bg, card, status, border, track, text, text-dim, green, green-fill, on-green, blue, blue-fill, on-blue, amber,
amber-fill, error-fill, on-error. Fonts: caption 8 (captions, card last/soil, nav labels), label 10 (titles, state,
buttons, rows), value 12 (card time), value-lg 14 (nav icons, as today). Geometry: header-h 22, nav-h 39 at y=201,
space-3 6 / space-4 8, bar-h 5, btn-h-sm 20, btn-h-md 26, radius-card 2, radius-control 3, radius-pill 7.

### Budget
- Expected: about 210 new LVGL objects (7 cards x ~13, schedules ~35, history ~12, two nav bars x 9, headers) at
  ~120-200 B each = **~30-40 KB heap** at boot (ESPHome creates every page at boot); flash **+40-90 KB** (actions,
  lambdas, formatters). The board is an ESP32-S3 N16R8 (16 MB flash).
- Required: `GP_SECRETS=example script/compile` on `master` and on the branch; record the "RAM:" / "Flash:" summary
  lines of both in the notes. Flash growth > 96 KB or static RAM growth > 8 KB needs the human's OK before merge.
- CI `checks` stays <= 15 min: at most 3 new `esphome config` rows; all new tests are unit / cpp except the extended
  screen scenario, which runs in the separate non-required `sim-ui` job.

## Files
Part A — gp data + Greenhouse cards
- create: `packages/lvgl/card_bed.yaml` — card template (one widget, vars `p`, `group`, `slot`, `zone`)
- create: `packages/lvgl/card_bed_refresh.yaml` — one refresh script per card (same vars)
- create: `tests/cpp/test_gp_screens.cpp` — history result/layout, skip entries, run_total, soil, card/history
  formatters, card layout
- create: `tests/test_screens_gp.py` — YAML shape checks of the new pages (below)
- modify: `components/gp/history.h`, `zone_model.h`, `format.h` (or a new `format_screens.h` included by it),
  new `layout.h` — pure parts
- modify: `components/gp/gp.h` — result, skip entries, soil, history counter, poller glue
- modify: `components/gp_zone/__init__.py` — `soil_sensor_id`
- modify: `components/garden_zones/gp_engine.h` — `skip_wet` (adapter only; no engine change)
- modify: `packages/greenhouse/lvgl_page.yaml` — rewritten page + `gh_bed_detail_page`
- modify: `packages/greenhouse/gp_lvgl_status.yaml` — card scripts, drop the old labels and `gh_home_next_label`
- modify: `packages/greenhouse/bed_soil.yaml`, `packages/sim/bed_soil.yaml` — `gp_zone` soil `!extend`
- modify: `packages/greenhouse/sensors_air_dht.yaml`, `sensors_soil.yaml`, `packages/sim/sensors_lvgl.yaml` — format
  strings of the three greenhouse-page labels only
- modify: `packages/lvgl/page_home.yaml`, `page_setup.yaml` — WATER -> `schedules_page`

Part B — Schedules + Home NEXT
- create: `packages/lvgl/page_schedules.yaml` — page shell, empty state, nav
- create: `packages/greenhouse/lvgl_schedules.yaml` — greenhouse rows, master row, poller, Home NEXT
- modify: `components/garden_schedule/schedule_core.h` (or new pure `schedule_format.h`), `garden_schedule.h`,
  `__init__.py` — helpers, accessors, `toggle_slot`
- modify: `tests/cpp/test_schedule.cpp` — new pure helpers

Part C — History
- create: `packages/greenhouse/lvgl_history.yaml` — page + poller

All parts
- modify: `garden-pilot.yaml`, `garden-pilot-sim.yaml` — `lvgl_page_schedules` (after `lvgl_page_lawn`),
  `gh_lvgl_history` (right after `gh_lvgl_page`), `gh_lvgl_schedules` (after the last `gh_schedule_slot_N`)
- modify: `tests/test_design_tokens.py` (`TOKENIZED_PAGES` += the 6 new/rewritten LVGL files),
  `tests/test_screens.py` (`TOKENIZED_TEXT_FILES`, confirm-text list), `tests/test_gp_layer.py` (`CALLERS` += new
  callers, allowed `id(gp_*)` reads), `tests/cpp/test_gp_model.cpp` (removed formatters), `tests/test_layout.py`
  (package order), `tests/test_config_matrix.py` (rows), `tests/test_sim_ui.py` (screens scenario)
- modify docs: `docs/SPEC.md` §8 (built-today list: greenhouse, schedules, history, detail pages on tokens; nav WATER;
  remove the NEXT defect; compact = detail page), §9 stages 9 and 11, §9.1 history item; `CLAUDE.md` (layout table
  rows for `card_bed*.yaml`, `page_schedules.yaml`, `lvgl_schedules.yaml`, `lvgl_history.yaml`; `packages:` order;
  gotchas: `!extend` of pages/gp_zone, paged lists instead of scrolling); `design/README.md` (Pages: Greenhouse built,
  Schedules, History, Bed detail; nav WATER; amber use; LVGL ids); `components/gp/README.md` (soil, `run_total`,
  history result + skip entries, `history_changed_since`, layout helper, removed formatters);
  `components/garden_schedule/README.md` ("Data for screens": accessors, `toggle_slot`)

This is about 3x the usual task size (see Open questions 1); the parts are ordered so each can be reviewed alone.

## Checks to write first
| Level | Test | Asserts |
|---|---|---|
| cpp | `test_gp_screens.cpp: history_layout_unchanged` | `sizeof(HistoryEntry) == 12`; `sizeof(PersistBlob)` equals the value measured on `master` **before** the change (write this check first, see it pass on old code); magic unchanged; a zero result byte reads as `Result::UNKNOWN` |
| cpp | `history_result_words` | done / stopped / skipped wet / skipped / `-`; SERVICE source -> `test` |
| cpp | `history_last_for_zone` | newest non-service entry of the zone; skips count; none -> empty |
| cpp | `tracker_records_skip_once` | a new skip stamp with `skip_wet` yields one record (zone, duration 0, SKIPPED_WET); the same stamp again yields none; a new stamp yields a second; `skip_wet` false -> SKIPPED |
| cpp | `run_total_and_progress` | first RUNNING sample sets `run_total`; progress 0 / 50 / 100 at left = total / half / 0; a run with `time_left > run_duration` still starts at 0; the end of the run clears it |
| cpp | `zone_soil_in_view` | `has_soil` 57.6 -> `soil == 57.6`; no sensor -> empty; revision bumps on 57 -> 58, not on 57.6 -> 57.8 |
| cpp | `fmt_card_state_and_colour` | every `ZoneState` -> word and colour of the table above; every colour is a token value (list mirrored from `design/tokens.json`) |
| cpp | `fmt_card_time` | `04:59`, `1:02:05`, idle `5 min`, nothing `--` |
| cpp | `fmt_card_last` | today / earlier / no clock / none cases; every output ASCII and <= 20 chars |
| cpp | `fmt_soil` | `Soil 58%`; empty for no value; rounding |
| cpp | `fmt_history_row_and_pager` | row text, `45 s`, `--:--`, < `LABEL_MAX`, ASCII; pager `1-6 of 37`, last page `37-37 of 37`, empty `No watering yet` |
| cpp | `layout_bed_cards` | for count 1..6 and slot 0..5: full for <= 3, compact for 4..6, the geometry above; slots >= count invisible; every visible rect inside the cards area, no overlap, 6 px gaps; full cards tall enough for two 20 px buttons |
| cpp | `test_schedule.cpp: schedule_texts` | days / zones / row text / today word / short next run cases above; ASCII; < `LABEL_MAX` |
| cpp | `test_schedule.cpp: schedule_view_hash` | the hash changes when enabled, start, days, zones, pct, today state, master or next run changes, and only then |
| unit | `tests/test_screens_gp.py::test_card_template_shape` | one root widget, `hidden: true`; all ids `${p}_card${slot}*`; no `gh_bed`, `gh_zones`, `garden_zones`, `board_relay`, `sprinkler`; RUN -> `gp.run_zone {id: ${group}, zone: ...}`, +Q -> `gp.enqueue_zone`; button heights >= 20 |
| unit | `test_greenhouse_page_cards` | `lvgl_page.yaml` includes `card_bed.yaml` exactly 6 times with slots 1..6 / zones 0..5, plus once with slot `d` on `gh_bed_detail_page`; ids `gh_greenhouse_t_label`, `gh_greenhouse_rh_label`, `gh_greenhouse_soil_hint` kept |
| unit | `test_greenhouse_page_actions` | STOP: guarded confirm (`_assert_guarded_confirm`), danger true -> `gp.stop_all: gp_greenhouse`; WATER ALL: guarded confirm, danger false -> `gp.full_cycle: gp_greenhouse`; RUN QUEUE -> `gp.start_queue`; only `gp.*` actions |
| unit | `test_nav_bars_consistent` | home, setup, greenhouse and schedules pages each have the 4 nav buttons with targets `home_page`, `greenhouse_page`, `schedules_page`, `setup_page`, and exactly their own tab in `0x4caf50` |
| unit | `test_subpages_back` | `gh_btn_history` -> `gh_history_page`; history and detail pages have no nav and a BACK to `greenhouse_page`; history has <= 8 row labels |
| unit | `test_schedules_shell_and_rows` | `page_schedules.yaml` has no reference to `gh_*` / `garden_schedule`; `lvgl_schedules.yaml` uses `id: !extend schedules_page`, toggles only through `garden_schedule.toggle_slot` / `switch.toggle: gh_schedules_on`, no `gp.` or engine action, no editor widget (`roller`, `spinbox`, `textarea`, `keyboard`, `dropdown`) |
| unit | `test_home_next_from_schedule` | `gp_lvgl_status.yaml` no longer writes `gh_home_next_label`; `lvgl_schedules.yaml` does, from `gh_schedule`; `home_next` gone from `components/gp` |
| unit | `test_pollers_guarded` | every `interval` in the new / changed pollers starts with an `if` whose condition calls a `changed_since`-style method or a page-change flag; no `lvgl.*` under `on_value` / triggers (existing `test_lvgl_only_from_pollers` covers the new files) |
| unit | `test_soil_link` | both `bed_soil.yaml` files extend `gh_bed${bed}_switch` with `soil_sensor_id: gh_bed${bed}_soil_moisture` |
| unit | existing `test_page_uses_only_token_colors/fonts`, `test_screen_text_is_ascii`, `test_callers_use_gp`, `test_lambdas_are_small` | extended to the new files (list edits) and pass |
| unit | `tests/test_sim_ui.py::test_tap_targets_match_yaml` | the scenario's tap coordinates equal the YAML geometry of `setup_nav_btn_zones`, `gh_btn_history`, `gh_history_btn_back`, `gh_nav_btn_water` |
| config | `test_config_matrix.py` rows `beds_1_lvgl` (full device, only `gh_bed_1`), `no_schedules_lvgl` (full device without `gh_schedule*` and `gh_lvgl_schedules`), `sim_beds_6` (sim entry with `gh_bed_4..6` added by `edits` on relays 1..3; sim only, layout coverage; SDL row) | all pass `esphome config` |
| host | `tests/test_sim_ui.py::test_sim_headless_shot_and_tap` (extended, same session, no second build) | after SETUP: tap ZONES -> `zones.png` not blank, differs from setup, pixel inside card 1 is `card` #1c1b1b (+-8 per channel), pixel in the slot-4 area is `bg` (3 beds); tap HISTORY -> `history.png` differs; tap BACK -> back on zones; tap WATER -> `schedules.png` differs from zones and shows the 2 slot rows (pixel check on row 2 background) |

## Acceptance criteria
- [ ] `script/test-cpp` -> all checks pass, including the new `test_gp_screens.cpp` and schedule checks
- [ ] `uv run pytest -m unit` -> passes
- [ ] `script/lint` and `script/test` -> green; `checks` in CI <= 15 min (state the measured time)
- [ ] `GP_SECRETS=example script/config garden-pilot.yaml` and `GP_SECRETS=example script/config garden-pilot-sim.yaml`
      -> valid
- [ ] `GP_SECRETS=example script/compile` (pinned) and `GP_SECRETS=example GP_ESPHOME=minimum script/compile` -> build;
      RAM / Flash summary of `master` and branch recorded in the notes; growth within the budget or approved
- [ ] CI `compile (pinned)`, `compile (minimum)` green; `sim-ui` green with `zones.png`, `history.png`,
      `schedules.png` in the artifact
- [ ] `grep -rnE "garden_zones|gh_zones|gh_bed[0-9]" packages/lvgl/card_bed*.yaml packages/lvgl/page_schedules.yaml
      packages/greenhouse/lvgl_history.yaml packages/greenhouse/lvgl_schedules.yaml` -> no match
- [ ] An old history blob loads after the upgrade: the host scenario of `tests/test_gp_layer.py` (or a new step) shows
      entries written by the previous code read back with result `-` (or the reviewer confirms by the layout check that
      size and magic are unchanged)
- [ ] Emulator by hand (`script/sim`): 3 cards with soil; RUN on bed 2 shows `Watering`, countdown and progress, then
      `Today`-style last line `... done`; +Q shows `Queued #1`; STOP and WATER ALL ask first; History lists the runs
      newest first and pages; Schedules shows slots 1-2, the toggle flips "Greenhouse schedule 1" (check with
      `script/sim-ctl get`), Home NEXT shows the next slot time once a slot is on; screenshots attached to the PR
- [ ] Compact layout seen once in the emulator with the `sim_beds_6` variant (screenshot in the PR; not in CI)
- [ ] Docs updated: SPEC §8/§9/§9.1, CLAUDE.md layout table + package order + gotchas, design/README.md,
      components/gp/README.md, components/garden_schedule/README.md
- [ ] **Hardware (cannot be checked in CI):** on the author's breadboard display the three pages and the bed detail
      page render, RUN / +Q / toggles / PREV / NEXT hit on the first tap, and free internal heap after opening every
      page is >= 40 KB (temporary `debug:` component, not committed) — or the PR states "not verified on hardware"

## Out of scope
- Home widgets (zones + alert strip, now/next + timeline), weather, climate, bed heating: next stage 9 tasks.
- Lawn page and lawn group (task 024); `packages/lvgl/page_lawn.yaml` is not edited (it loses its nav entry, see Open
  questions 2); lawn packages and `examples/my-garden.yaml` are not touched.
- Schedule time / day / zone editor on the device (WATER tab editor, later stage 11 task).
- "Missed" schedule slots as history entries (needs a schedule -> gp history note; follow-up). The Schedules page shows
  `missed` in the slot's today word.
- Russian UI, any new font or colour token, reference-image comparison of screenshots (stage 12).
- Per-card STOP / dequeue, renaming beds on the device, backlight dimming.
- Moving the legacy `on_value` LVGL updates of `sensors_air_dht.yaml` / `sensors_soil.yaml` to pollers.
- A 4th-6th relay in the board profiles (hardware decision).

## Open questions
1. **Task size.** About 30 files, three times the usual limit. Recommended default: keep the author's scope in one
   task and branch, in parts A -> B -> C with separate commits; if one implementer run cannot finish, Part C (History)
   moves to a task 026 with the same text.
2. **Lawn page reachability.** WATER now opens Schedules, so `lawn_page` has no entry point. Default: leave it
   included and unreachable until task 024 or the Home widgets task gives the lawn an entry (Home lawn card tap or a
   group switch on ZONES); do not edit `page_lawn.yaml` here.
3. **Locked / paused colour.** Default: amber text and amber-fill top edge (first built use of the reserved amber
   tokens); red stays STOP-only.
4. **WATER ALL confirmation.** Default: yes, green primary button, texts above (a full cycle opens every enabled valve
   in turn).
5. **Date format** in history rows and the card's last line. Default: `13 Oct 06:00` (English month abbreviations),
   `06:00` alone for today on the card.
6. **Compact cards.** Default: tap opens `gh_bed_detail_page` (PR #21); no RUN / +Q on compact cards.
7. **Soil link.** Default: `soil_sensor_id` on `gp_zone`, added by `!extend` from the bed's soil include; alternative:
   a `soil:` list on the gp group.
8. **Budget limits.** Default: flash growth <= 96 KB, static RAM <= 8 KB, free internal heap >= 40 KB on the device
   after every page was opened; above that the human decides.
9. **Rows per page.** Default: Schedules 3 slot rows + paging (2 slots by default, so no paging shown), History 6.
10. **6-bed screenshot in CI.** Default: no (a second host build costs minutes); the `sim_beds_6` config row and the
    `layout_bed_cards` check cover it, plus one manual screenshot in the PR.
11. **Old debug formatters.** Default: delete the ones no screen uses any more, with their checks.

<!-- Filled in by implementer -->
## Implementation notes
Scope: Part C only (see the header) plus the gp history `result` byte and skip entries. Parts A / B were not touched.

**Decided (default, author to confirm):**
- Date format `13 Oct 06:00` (open question 5); History rows: 6 per page (9); no scrolling, PREV / NEXT clamp at the ends.
- A skip row has no duration: `B2  13 Oct 06:00  skipped wet`. A valve-test run reads `test`. Old entries (zero byte) read `-`.
- A watchdog-ended run counts as `done` (like `completed` today); `stopped` = ended inside the 3 s window after `stop_all`.
- `skip_wet` is decided in the adapter (`gp_engine.h`) from the engine's reason text prefix `soil moisture`; the
  other engine skip (`soil sensor unavailable`) is a plain `skipped`.

**Deviations / choices:**
- Test file is `tests/cpp/test_gp_history.cpp` (not `test_gp_screens.cpp`, which Part A owns) and the Python checks are in
  `tests/test_history_page.py`. Formatters are in a new `components/gp/format_history.h` (included from `gp.h`), so
  `format.h` is unchanged and `fmt::home_next` etc. stay for Part A/B.
- The HISTORY header button (`gh_btn_history`, 72x20 at x=240 y=1) is added to the existing `greenhouse_page` with
  `lvgl: pages: [{id: !extend greenhouse_page, widgets: [...]}]` from `lvgl_history.yaml`, so `lvgl_page.yaml` is not
  edited. Verified: `esphome config` (pinned) merges it, and `on_load` of a page triggers `gh_hist_open` (page reset to 0).
  Part A, which rewrites `lvgl_page.yaml` with its own `gh_btn_history`, must drop the `!extend` block from
  `lvgl_history.yaml` when merging (a duplicate id fails `esphome config` loudly).
- `gh_lvgl_history` is optional (without it there is no button and no page) and sits right after `gh_lvgl_page` in both
  entry files and the 4 examples (one line each; `examples/my-garden.yaml` is not touched).
- Existing tests edited only by list additions, plus `test_screens.py` (`_page_ids`, `test_page_ids_unique`): an
  `!extend` page id loads as a dict, so ids that are not strings are skipped there. Parts A/B will hit the same lines.
- `HistoryEntry{.., result, reserved}` needed a 6th initialiser at `History::at` and in one line of
  `test_gp_model.cpp` (`-Wmissing-field-initializers` with `-Werror`); no check weakened.
- `static_assert(sizeof(PersistBlob) == 1336)` and `sizeof(HistoryEntry) == 12` in `history.h`: 4 + (100*12 + 2 + 2) + 16*8,
  computed from the old layout (no compiler on this host to measure on `master`; the host layout is the same 4-byte-aligned
  struct on ESP32). `old_blob_still_loads` copies old-layout entries into a `PersistBlob` and reads them back as `-`.
- The poller (`history_changed_since`) only; opening the page and PREV / NEXT render through the script
  `gh_hist_render`, so no separate page-change flag is needed.
- Checks were written together with the code in one pass (no separate red run); the C++ suite was compiled and run with
  `zig c++` (clang, `-Wall -Wextra -Werror`, 85 test cases pass) because the host has no g++.
- `docs`: `components/gp/README.md` (result byte, skips, history glue), SPEC §8 built list and §9.1 history item,
  `design/README.md` (History page), `CLAUDE.md` (layout row + package order).

**Not run here:** ESP32 / host firmware compile (the `gp.h` glue was only reviewed, CI compiles it), `esphome config`
of `garden-pilot-sim.yaml` (needs `sdl2-config`), the `sim-ui` screenshot scenario (Xvfb; `test_sim_ui.py` was extended:
ZONES -> HISTORY -> BACK with pixel probes), `tests/test_gp_layer.py` host scenario, `script/test-cpp` itself (no g++).
Not verified on hardware: the HISTORY button hit area (72x20) and the page rendering on the ILI9341.

## Follow-ups
- Schedule -> gp "missed" history entries; time editor on the WATER tab; lawn card/history reuse (`p: lw`,
  `group: gp_lawn`).
- Move `sensors_air_dht.yaml` / `sensors_soil.yaml` LVGL updates from `on_value` to pollers.
