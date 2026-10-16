# 030 — Schedule list (D08), schedule editor (D09), start-time keyed run mark

Status: planned
Roadmap: stage 11 (WATER tab: schedules on the device, with the editor); stage 9 (screens on the design system)
Spec sections: SPEC §8 (design, screens), §4.1 (`gp_*` layer), §6 (pinned / minimum ESPHome), §7 (testing without
hardware), §9 (roadmap); `components/garden_schedule/README.md` (all rules); `design/README.md` (after task 029)
Hardware check: on the author's breadboard display (ESP32-S3 + ILI9341 + XPT2046): both pages render, every button
(22 px day / zone buttons, the header ON area, rows) hits on the first tap, free internal heap after opening both pages
>= 40 KB. The implementer cannot do this; the human does it or the PR says "not verified on hardware".

**Branch: `task/026-screens-schedules` (PR #35), reworked; no new branch.** Step 1 of the implementer: merge
`task/029-font-scale-c` into it (merge commit, no rebase of the pushed branch). Expected conflicts: `page_home.yaml` /
`page_setup.yaml` (take 029's nav: icons, label `SCHEDULE`, `gp_font_button_sm`; re-apply 026's target
`schedules_page`), `tests/test_screens.py`, `tests/test_design_tokens.py` (union of both lists), entry files. Then this
task replaces 026's LVGL schedules page. `tasks/026-screens-schedules.md` gets one line under its notes: "continued and
superseded by task 030". PR #35 title/description are updated by the main session.

## Goal
SCHEDULE on the bottom nav opens the **Schedule** list (D08): one row per greenhouse slot (start time, group + zones,
days + duration, a coloured status word, chevron). Tapping a row opens the **Schedule N** editor (D09): ON switch, hour
and minute with -/+, seven day buttons, zone buttons (configured beds only), RUN TIME factor with -/+, CANCEL / SAVE.
Edits live in a RAM draft; SAVE writes only the changed slot entities (the same ones Home Assistant edits), so there is
no flash write per tap. The scheduler's "already ran today" mark becomes **(local day, start minute)**: moving a slot to
a later time today runs it again, also after a STOP. Entry files get **4 slots**. Scale C fonts, existing colours only.

## Context

### Decisions already made (author)
- 2026-10-16: scheduler "proper, as in the design" — D08 + D09 + DS README rules (4 fixed slots, no add/delete; unused
  slot = OFF with `--:--`; small header actions left of the clock; no scrolling; nothing tappable < 20 px).
- 2026-10-17: rework PR #35 instead of starting over: keep 026's C++ and tests, replace its page, add the editor; base =
  026 + 029 merged.
- 2026-10-17, new scheduler rule (below, "Run mark").
- Defaults kept (not overruled): 4 slots in entry files; D09 REPEAT row = multiplier, caption `RUN TIME`, `x0.1`..`x2.0`;
  slots 5-8 Home Assistant only (screen shows the first 4 in include order, documented, no paging); minute step 5;
  HISTORY header button present but `hidden: true` until the history task; lawn zones in the editor = follow-up; nav label
  `SCHEDULE` (already done by 029); status word empty for an enabled slot that is neither next nor run today;
  disabled row = `--:--`, `Slot N`, `Not set - tap to set up`, `OFF`.

### What 026 has (wt026) and what happens to it
- Keep: `schedule_format.h` (`days_text`, `zones_text`, `today_word`, `next_short`, `view_hash`, `SlotView`, `Today`),
  hub accessors in `garden_schedule.h` (`slot_count`, `master_on`, `slot_view`, `row_*`, `next_run_short`,
  `changed_since`), `Scheduler::today()`, Home NEXT written by `lvgl_schedules.yaml` from the hub (`gh_home_next_label`,
  removed from `gp_lvgl_status.yaml`, `gp::fmt::home_next` gone), the generic shell + `!extend schedules_page` pattern,
  config rows `no_schedules_lvgl` / `sim_no_schedules`, `tests/test_examples.py::_rank` entry, page-id helpers that skip
  `!extend` ids. Texts may change to the D08 wording; adapt the existing `schedule_texts` / `schedule_view_hash` checks.
- Drop: the pager (`page_count`, `step_page`, `pager_text`, hub `page_*`, check `schedule_pager`), the master row and the
  3 paged rows, and `garden_schedule.toggle_slot` (D08 has no toggle; enabling is the editor's ON + SAVE; HA has the
  switch) with `ToggleSlotAction`, its `__init__.py` registration and `test_toggle_slot_action_is_registered_and_documented`.

### Run mark: (local day, start minute) — new rule
Today `SlotState.last_fired_day` blocks a slot for the whole local day, so `tests/cpp/test_schedule.cpp::edit_after_fire`
asserts that moving 06:00 -> 08:00 after a fire does NOT fire. New rule (README + core):
- A slot counts as handled today iff `last_fired_day == day && last_fired_minute == cfg.start_minute`. Crossing,
  catch-up, `next_run` and `day_runs` all use this one predicate (`handled_(i, cfg, day)`).
- Changing the start (editor SAVE or HA) to a time later than now today -> the new start is crossed -> fires again,
  also after a STOP settled the earlier run. A new fire replaces the mark and the pending mask.
- Re-saving or re-enabling never clears a mark by itself: same day + same start stays blocked (DST repeated hour: the
  local clock crosses 01:30 twice, the mark blocks the second). Moving to a time already passed today does not fire (no
  crossing; catch-up only on a discontinuous tick, see next point).
- Catch-up after power loss unchanged and per zone: pending zones resume on the first valid tick only when the mark's
  minute equals the current start; if the start was changed meanwhile, the old pending zones are dropped (logged INFO)
  and the new start is evaluated like an unfired slot (catch-up window / missed).
- Persistence: `PersistBlob` gains `uint16_t last_fired_minute[MAX_SLOTS]`, `version 2`, new preference key
  (`"garden_schedule2:" + key`). On a miss, load the v1 blob from the old key and migrate with
  `last_fired_minute = ANY_MINUTE` (0xFFFF, matches any start), so the upgrade day behaves exactly as before (no extra
  run after the OTA). Implementer: confirm in `esphome/components/esp32/preferences.cpp` (and `host`) that a blob of a
  different size fails `load()` rather than reading garbage; cite the line.

### ESPHome behaviour (pinned 2026.9.1; minimum per SPEC §6 is 2026.6.3)
Checked in the installed package source while planning the previous version of this file:
`datetime/time_entity.h` `TimeCall::set_time(h, m, s)` + `perform()`; `template/datetime/template_time.cpp` saves via
`pref_.save()` with `restore_value` (batched by `preferences: flash_write_interval`, default 60 s); `lvgl/widgets/label.py`
`long_mode` incl. `DOT`; `lvgl/widgets/__init__.py` `state: checked:` accepts `!lambda` (also verified in 026's notes);
`esphome/config.py` `resolve_extend_remove` extends pages by id. **Implementer verifies on the minimum** (cite file and
line in the notes): `!extend` of an LVGL page, `state: checked:` lambda, `lvgl.widget.hide/show` with a list, `long_mode:
DOT`; fall back (lambda `bg_color`) where missing. 026 never compiled for ESP32 or host: the compile criteria below are
the first proof of its glue.

### Structure (recommended; the implementer may adjust and must say why)

**Pure C++ (tests first)**
- `schedule_core.h`: `last_fired_minute`, `ANY_MINUTE`, `handled_()`, `restore(slot, day, minute, pending)`.
- new `components/garden_schedule/schedule_ui.h` (MIT, no ESPHome includes; uses `schedule_core.h` /
  `schedule_format.h`):
  - `ScheduleDraft {index, enabled, hour, minute, days_mask, zone_mask, pct}`: `hour_up/down` (wrap 23 <-> 0),
    `minute_up/down` (step 5, wrap 55 <-> 0; a non-multiple of 5 from HA snaps to the next / previous multiple),
    `toggle_day(d)`, `toggle_zone(z, zone_count)` (z >= zone_count ignored; bits >= 6 kept), `pct_up/down` (step 10,
    clamp 10..200), `toggle_enabled()`, `can_save()` (false when enabled with no day or no zone), `zones_text(zone_count)`
    (`all` or `1 3`, always matches the text entity pattern `^(all|[1-9][0-9]?( [1-9][0-9]?)*)$`), `factor_text()`
    (`x1.0`), `hour_text()`, `minute_text()`, `Diff diff(const ScheduleDraft &original)` (enabled / start / each day /
    zones / pct).
  - D08 row texts: `row_time` (`06:00`, disabled `--:--`), `zones_label(group, noun, mask, count)` (`Greenhouse - all
    beds`, `- bed 2`, `- beds 1 3`, > 3 of not-all -> `- 4 beds`), `duration_text` (`5 min each`, `5 min`, `12 min
    total`, `45 s`; zone seconds x pct / 100), `row_caption` (days ` - ` duration; days -> `N days` past `CAPTION_MAX`;
    disabled -> `Not set - tap to set up`), using 026's `days_text` (adjust wording to `Every day` / `Mon-Fri`).
  - `status_word(enabled, master_on, today_state, pending, is_next)` -> `{text, tone}`: disabled or master off `OFF`
    dim; FIRED, nothing pending `DONE` dim; FIRED with pending `ACTIVE` green; SKIPPED / MISSED / STOPPED `SKIP` amber;
    next run `NEXT` green; else empty. Tone colours mirrored from `design/tokens.json` (`text`, `text-dim`, `green`,
    `amber`); all output ASCII, `LABEL_MAX` / `CAPTION_MAX` constants.
- Hub glue in `garden_schedule.h` (one-line callers): `zone_count()`, `set_zone_seconds(std::function<uint32_t(size_t)>)`
  (set once from YAML so the hub never depends on `gp`), `row_time/label/caption/status/color(i)`, `changed_since` also
  hashes zone seconds; editor `begin_edit(i)` (snapshot from the entities, not `cfg_`), `draft()`, `edit_title()`
  (`Schedule 2`), `save_edit()` (writes only `diff()` fields via `make_call()` on switch / time / text / number, one INFO
  log, false + no write when `!can_save()` or no edit open; HA changes made while open survive unless the user changed the
  same field), `cancel_edit()`. Index out of range = WARN, no-op.

**YAML**
- `packages/lvgl/page_schedules.yaml` (rewrite of 026's shell, generic, no `gh_*` / `garden_schedule`): header title
  `Schedule` (`montserrat_12`, x 8), `sched_clock_label` (029 rule: TOP_RIGHT x -8 y 4, montserrat_12, one `!extend
  gp_header_clock_update`), HISTORY ghost button `sched_btn_history` left of the clock, `hidden: true`; empty state
  `sched_empty_label`; nav copied from 029's Home nav (`sched_nav_btn_dash/zones/water/setup`, icons, `SCHEDULE`
  active).
- `packages/greenhouse/lvgl_schedules.yaml` (rewrite):
  - `!extend schedules_page`: rows `gh_sched_row1..4` (clickable card `obj` x 8, y 26 + 40*(n-1), 304x36, `card`,
    `border`, radius 2) with `_time` (montserrat_14), `_label` (montserrat_12, w 180, `long_mode: DOT`), `_caption`
    (montserrat_10, `text-dim`, w 180, DOT), `_status` (montserrat_10, tone colour), `_chev` (`LV_SYMBOL_RIGHT`,
    montserrat_12, `text-dim`; symbol labels may use 12 per 029's font-role test). Rows >= `slot_count()` hidden on the
    first poll; tap -> `begin_edit(n-1)` -> `gh_sed_refresh` -> show `gh_sched_edit_page`. Hides `sched_empty_label`.
  - Poller `interval: 1s` guarded by `changed_since(gh_sched_seen)` -> `gh_sched_list_refresh` (+ Home NEXT as in 026);
    duration provider set once: `id(gh_schedule)->set_zone_seconds([](size_t z) { return
    id(gp_greenhouse)->zone(z).run_duration; });` (read model only).
  - Page `gh_sched_edit_page` (no nav): `gh_sed_title`, `gh_sed_clock_label`, `gh_sed_on_label` (`ON`/`OFF`,
    montserrat_10) + pill `gh_sed_switch` (28x14, not clickable) inside transparent `gh_sed_btn_enable` (x 196..252,
    y 0..22); captions `START - HOUR`, `MINUTE`, `DAYS`, `ZONES`, `RUN TIME` (montserrat_10, dim); `gh_sed_btn_hour_dec/
    inc` (36x26, x 8 / 112, y 40), `gh_sed_hour_label` (montserrat_16), `gh_sed_btn_min_dec/inc` (x 172 / 276),
    `gh_sed_min_label`; `gh_sed_btn_day1..7` (40x22, x 8+44*i, y 86, `M T W T F S S`); `gh_sed_btn_zone1..6` (56x22,
    y 126, x 8+62*i for 1..5, zone 6 at x 8 y 152, `BED n`, hidden for n > zone count); `gh_sed_btn_pct_dec/inc` (36x22,
    x 168 / 276, y 179), `gh_sed_pct_label` (montserrat_14, `x1.0`); `gh_sed_btn_cancel` (ghost) / `gh_sed_btn_save`
    (`green-fill` / `on-green`), 150x26 at x 8 / 162, y 210. Button labels: `gp_font_button_sm` in 22 px buttons,
    `gp_font_button_md` in 26 px buttons (029 bold fonts; all texts within their glyph set `A-Z 0-9 +-./:%`). Selected
    toggle = `green-fill` + `on-green`, unselected = ghost.
  - Every editor click = one-line draft lambda + `script.execute: gh_sed_refresh`. CANCEL -> `cancel_edit()` -> list.
    SAVE -> `if can_save()` -> `save_edit()` -> `gh_sched_list_refresh` -> list; `!can_save()` draws SAVE dim, click no-op.
- `page_home.yaml` / `page_setup.yaml`: WATER (`SCHEDULE`) -> `schedules_page` (kept from 026 through the merge).
- Entry files + 4 examples: `gh_schedule_slot_3` (`18:00:00`), `gh_schedule_slot_4` (`19:00:00`) after slot 2 (1-2 keep
  06:00 / 07:00; all default OFF); `lvgl_page_schedules` after `lvgl_page_lawn`, `gh_lvgl_schedules` after the last slot.

### Tokens used (no new colour, no new font size)
Colours: bg, card, border, text, text-dim, green, green-fill, on-green, amber (first built use -> `design/README.md`).
Fonts: montserrat_10/12/14/16 (caption/label/value/value-lg), `gp_font_button_sm` / `_md`. Geometry: header-h 22,
nav-h 39 at y 201, btn-h-md 26, radius-card 2, radius-control 3, radius-pill 7. **Deviations to record in
`design/README.md`:** D09 toggle buttons are 22 px (design value, >= 20, not a token); D08 HISTORY is 18 px in the
artboard — hidden here, the history task must make it >= 20 px.

### Budget
~25 objects on the list, ~60 on the editor -> ~12-18 KB heap; flash +30-60 KB; +20 entities for slots 3-4. Record
`GP_SECRETS=example script/compile` RAM / Flash of `master` and of the branch. Flash growth > 96 KB or static RAM > 8 KB
needs the human's OK. CI `checks` <= 15 min: no new host build; screenshots ride the existing `sim-ui` session.

## Files
- modify: `components/garden_schedule/schedule_core.h` — minute-keyed mark, `handled_()`, `restore` with minute
- modify: `components/garden_schedule/schedule_format.h` — drop pager, D08 wording
- create: `components/garden_schedule/schedule_ui.h` — draft, row texts, status words
- modify: `components/garden_schedule/garden_schedule.h` — blob v2 + v1 migration, editor API, row accessors, duration
  provider; remove `toggle_slot` / `ToggleSlotAction`
- modify: `components/garden_schedule/__init__.py` — remove the `toggle_slot` action
- modify: `components/garden_schedule/README.md` — run-mark rule, persistence v2, "Data for screens", editor
- modify: `tests/cpp/test_schedule.cpp` — run-mark cases, flipped `edit_after_fire`, pager check removed
- create: `tests/cpp/test_schedule_ui.cpp` — draft / texts / status checks
- rewrite: `packages/lvgl/page_schedules.yaml`, `packages/greenhouse/lvgl_schedules.yaml`
- rewrite: `tests/test_screens_schedules.py`
- modify: `garden-pilot.yaml`, `garden-pilot-sim.yaml`, `examples/*.yaml` — slots 3-4
- modify (list edits): `tests/test_schedule.py` (4 slots, 4 `add_slot(`), `tests/test_design_tokens.py`,
  `tests/test_screens.py` (header-clock page list += both pages), `tests/test_gp_layer.py`, `tests/test_sim_ui.py`
- modify docs: `docs/SPEC.md` §8 / §9; `CLAUDE.md` (layout rows of the two YAML files, Schedules gotchas: run mark keyed
  by start, editor draft until SAVE, 4 rows / slots 5-8 HA only, no `toggle_slot`); `design/README.md` (Pages: list +
  editor ids, amber, 22 px buttons, HISTORY hidden); `README.md` + `README.ru.md` (4 slots, edit on device or in HA)

Above 10 files, but most are list edits; the work is one pure header, the core rule change and two YAML files.

## Checks to write first
| Level | Test | Asserts |
|---|---|---|
| cpp | `test_schedule.cpp: moved_later_after_run_fires` | slot 06:00 fires at 06:00; start set to 18:00; crossing 18:00 the same day -> 1 fire; next day 18:00 -> 1 fire (not 2) |
| cpp | `stop_then_moved_fires` | fire 06:00, `stop_pending()`, start set to now + 5 min -> 1 fire at that minute with the full zone mask |
| cpp | `unchanged_time_no_second_run` | fire 06:00; re-enable (enabled false -> true) and re-set the same start; ticks through the day -> no fire |
| cpp | `dst_fall_back_one_run` (extend `dst_fall_back_no_double`) | the repeated hour crosses a 01:30 slot twice -> exactly 1 fire |
| cpp | `edit_after_fire` (changed) | 06:00 -> 08:00 after a fire now fires at 08:00 the same day |
| cpp | `moved_while_pending_drops_old_zones` | fired with zones {1,2}, zone 1 done, restart after the start moved to a later passed time inside the window -> old pending dropped, new start caught up with the full mask |
| cpp | `v1_mark_matches_any_minute` | `restore(slot, today, ANY_MINUTE, 0)` blocks the slot today at any start; next day fires |
| cpp | `next_run_and_day_runs` (extended) | after moving a fired slot later today, `next_run` returns it today and `day_runs` shows it PENDING |
| cpp | `test_schedule_ui.cpp: draft_time_wrap` | hour 23 up -> 0, 0 down -> 23; minute 55 up -> 0, 0 down -> 55; 07 up -> 10, 07 down -> 05 |
| cpp | `draft_days_zones_pct` | day bits (bit0 = Mon); zone z >= count ignored, bits >= 6 kept; pct clamps 10/200, step 10; `x1.0` / `x0.5` / `x2.0` |
| cpp | `draft_zones_text` | all -> `all`; `{0,2}` -> `1 3`; every output matches the entity pattern (hand-written matcher); round trip through `parse_zones` |
| cpp | `draft_can_save_and_diff` | enabled without day or zone -> false; disabled without zone -> true; `diff` reports exactly the changed fields, nothing for an untouched draft |
| cpp | `list_texts` | `row_time`, `zones_label`, `duration_text` (each / single / total / `45 s`), disabled caption; ASCII and within limits for worst cases (8 zones, 5 scattered days, 3 h) |
| cpp | `status_words` | every case of the table -> text + tone; tones are mirrored token values |
| unit | `test_screens_schedules.py::test_shell_is_generic` | no `gh_`, `garden_schedule`, `gp.` in the shell; `sched_btn_history` hidden; nav targets home / greenhouse / schedules / setup, SCHEDULE active; `sched_clock_label` per 029 |
| unit | `test_rows_and_editor_shape` | extends `schedules_page`; 4 rows; editor ids above; 7 day + 6 zone buttons; every clickable >= 20 px tall; no `roller`, `spinbox`, `textarea`, `keyboard`, `dropdown`; no `gp.` / engine actions; no `switch.turn_*`, `datetime.*`, `text.set`, `number.set`, `garden_schedule.toggle_slot` |
| unit | `test_editor_writes_only_on_save` | only `gh_sed_btn_save`'s `on_click` calls `save_edit`; no `make_call` / `publish_state` in the YAML |
| unit | `test_pollers_guarded` (kept), `test_home_next_from_schedule` (kept), `test_nav_bars_target_the_right_pages` (kept, SCHEDULE label) | pass on the new files |
| unit | `test_schedule_ui_colours_are_tokens` | every `0x......` in `schedule_ui.h` is a colour in `design/tokens.json` |
| unit | `test_schedule.py::test_entry_includes_schedule` (changed) | slots 1..4 in order, then `gh_lvgl_schedules`; `lvgl_page_schedules` after `lvgl_page_lawn` |
| unit | `test_toggle_slot_removed` | no `toggle_slot` in `components/garden_schedule/` or `packages/` |
| unit | existing token / font-role / header-clock / ASCII / callers / small-lambda checks | extended to both files, pass |
| unit | `test_sim_ui.py::test_schedule_tap_targets_match_yaml` | tap points inside `setup_nav_btn_water`, `gh_sched_row1`, `gh_sed_btn_cancel` |
| config | `no_schedules_lvgl`, `sim_no_schedules` (from 026) | pass `esphome config` |
| host | `test_sim_ui.py::test_sim_headless_shot_and_tap` (extended) | tap SCHEDULE -> `schedules.png` differs, pixels in rows 1 and 4 are `card` (+-8); tap row 1 -> `schedule_edit.png` differs, SAVE pixel `green-fill`; CANCEL -> back on the list |

## Acceptance criteria
- [ ] Branch contains a merge of `task/029-font-scale-c` before the task commits (`git log --merges`)
- [ ] `script/test-cpp` -> passes, including the run-mark cases and `test_schedule_ui.cpp`
- [ ] `uv run pytest -m unit`, `script/lint`, `script/test` -> green
- [ ] `GP_SECRETS=example script/config garden-pilot.yaml`, `... garden-pilot-sim.yaml`, `script/config examples/<each>.yaml` -> valid
- [ ] `GP_SECRETS=example script/compile` and `GP_SECRETS=example GP_ESPHOME=minimum script/compile` -> build; RAM /
      Flash of master and branch recorded; within budget or approved
- [ ] CI `compile (pinned)`, `compile (minimum)` green; `sim-ui` green with `schedules.png`, `schedule_edit.png`
- [ ] `rg -n "toggle_slot|pager_text|page_step" components packages tests` -> only the absence test
- [ ] `rg -nE "garden_zones|gh_zones|board_relay|sprinkler" packages/lvgl/page_schedules.yaml packages/greenhouse/lvgl_schedules.yaml` -> no match
- [ ] Emulator by hand (`script/sim`): 4 rows (OFF, `--:--`); edit slot 1 (ON, 06:05, Mon Wed Fri, beds 1 3, x1.5),
      SAVE -> `script/sim-ctl get` shows the slot entities changed (Tue off, zones `1 3`, multiplier 150); CANCEL changes
      nothing; an HA start change (`script/sim-ctl time ...`) shows within 2 s; after a run, moving the slot to now + 2 min
      runs it again (sim log); screenshots in the PR
- [ ] README of `garden_schedule`, SPEC, CLAUDE.md, design/README.md, README.md + README.ru.md updated
- [ ] **Hardware (not in CI):** pages render, buttons and the ON area hit first tap, heap >= 40 KB — or "not verified on hardware"

## Out of scope
- History page and the HISTORY button target (new history task).
- Lawn zones in the editor (D09 LAWN 1..4): needs a hub per gp group or a multi-group hub. Follow-up.
- True repeats / cycle-and-soak (`REPEAT xN`). Follow-up.
- Paging for slots 5-8; master switch `gh_schedules_on` on the screen (HA only).
- Greenhouse cards (task 025 redo); any new colour or font size; Russian UI.

## Open questions
1. **Run mark on the upgrade day.** Recommended: v1 marks migrate as "any minute" (behaves as before for that one day,
   no surprise run after the OTA). Alternative: drop v1 marks (simpler, but a slot that ran within the last catch-up
   window before the OTA would run again).
2. **Moving a slot to an earlier, already passed time today** does not run it (no crossing), even if it never ran with
   that time today. Recommended as is; the author's rule only names later times.

<!-- Filled in by implementer -->
## Implementation notes
## Follow-ups
