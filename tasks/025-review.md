# 025 — Review (round 1, Part A only)

Verdict: APPROVE

Scope reviewed: Part A (gp data for the cards, bed card template + refresh scripts, Greenhouse page, bed detail page,
transport row). Part B (task 026, PR #35) and Part C (task 027, PR #33, incl. the history `result` byte, skip entries,
`gh_btn_history`) are out of this review by the author's split and are not requested here.

## Checks run
- `script/lint` -> `esphome config OK: garden-pilot.yaml` (exit 0)
- `script/test` -> `6 failed, 854 passed, 19 skipped in 147.61s`; the 6 failures are exactly the known Windows-host ones
  (`test_ci.py::test_esphome_selector_resolves`, 4 exec-bit tests in `test_devcontainer.py`,
  `test_sim_ui.py::test_start_xvfb_deadline_holds_when_xvfb_hangs`)
- `script/test-cpp` (zig c++ via a wrapper script; `CXX` with spaces is not accepted by the script) -> `86 test cases, 0 failed checks`
- Not run here: SDL config rows, host scenarios, sim-ui (no SDL/Xvfb on Windows), ESP32 compile (running separately in Docker).

## Static compile read (gp.h, gp_zone, generated lambdas) against pinned 2026.9.1 sources
- `ESPTime::from_epoch_local(time_t)` exists (`esphome/core/time.h:125`), reached via `real_time_clock.h`; `is_valid()`,
  `day_of_month` etc. exist. `EntityBase::has_state()` (`core/entity_base.h:146`) and public `Sensor::state` exist.
- `<cmath>` added for `std::isnan`; `sensor` added to `AUTO_LOAD` because `gp.h` now always includes `sensor.h`.
- `GpGroup::zone()` / `GroupModel::zone()` return `absent()` past the zone count, so hidden slots 4-6 read safely.
- `refresh` loop over `input_.zone_count` indexes `soil_[MAX_ZONES]` safely: the adapter caps `zone_count` at `MAX_ZONES`.
- The adapter resets every `ZoneInput` on `read()`, so a sensor going NaN clears `has_soil` on the next refresh.
- `globals.set value: ${idx}` is a raw expression (`"0"`..`"5"`); fine.
- No compile error found by reading; actual ESP32 / host compile is still the open item below.

## Acceptance criteria (Part A subset)
- [x] `script/test-cpp` passes incl. new `test_gp_screens.cpp` (run_total/progress, soil in view + revision rounding,
      card state/colour table with token check, card time/last/soil/name, layout geometry, gaps, no overlap)
- [x] `uv run pytest -m unit` — covered by the `script/test` run above (only known Windows failures)
- [x] `script/lint` green; `script/test` green except the known Windows-only failures. CI time not measurable here.
- [x] `GP_SECRETS=example script/config garden-pilot.yaml` valid (lint); new config rows `beds_1_lvgl`, `beds_6_lvgl` pass.
      Sim config not checked here (no SDL).
- [ ] `GP_SECRETS=example script/compile` pinned + minimum, RAM/Flash of master vs branch — **open**: the branch build
      failed to start on the Windows host; the Docker compile must be green and the branch RAM/Flash lines recorded in the
      task notes before merge (budget: flash +96 KB, static RAM +8 KB). Widget estimate: 12 objects per card x 7 = 84
      plus page chrome (~100 objects, roughly 15-20 KB heap) — inside the planned budget.
- [ ] CI compile (pinned/minimum), sim-ui `zones.png` — pending CI.
- [x] `grep -rnE "garden_zones|gh_zones|gh_bed[0-9]" packages/lvgl/card_bed*.yaml` -> no match (also enforced by
      `test_card_template_shape` / `test_card_refresh_uses_card_ids_and_one_line_lambdas`).
- [x] Old history blob: `history.h` / `PersistBlob` untouched in Part A (owned by 027).
- [ ] Emulator by hand / compact screenshot — not done by the reviewer (no SDL); PR must attach or say so.
- [x] Docs: CLAUDE.md layout row + gotcha, design/README.md (Greenhouse, Bed detail, amber use), SPEC §8,
      components/gp/README.md updated for Part A.
- [ ] Hardware — not verified; the task notes say so explicitly (acceptable per task text).

## Principles checked
- gp-only access: cards are parameterised by `group` + zone index; RUN = `gp.run_zone`, +Q = `gp.enqueue_zone`; page
  actions only `gp.stop_all` / `gp.full_cycle` / `gp.start_queue` (test enforced). No bed ids or engine names in the
  card files.
- LVGL writes only from the guarded 1 s poller (`changed_since(gp_gh_seen)`) and from click handlers (compact card ->
  detail page). Every refresh lambda is one line into `gp::fmt::*` / `gp::layout::*` / group glue.
- Safety: STOP (danger) and WATER ALL (`danger: false`, texts as specified) go through the guarded `gp_confirm` pattern.
- Tokens: all colours/fonts/geometry from tokens (`test_page_uses_only_token_colors/fonts` extended to the 3 files;
  `format_screens.h` colours checked against `tokens.json`); no red on cards; amber used for locked/paused only. ASCII
  texts checked.
- Header: only the "Greenhouse" title at x=8; x 232..312 of the header is free for 027's `gh_btn_history`, which is not
  defined here.
- Hygiene: no secrets, IPs, local paths.

## Findings
### Required
None.

### Suggestions
1. `components/gp/gp.h:77-80` — the card's last line ("06:00 5m" for today vs "12 Oct 5m") is recomputed only when the
   model revision changes; after midnight an idle zone keeps showing "06:00" until something else changes. Either mix
   the local day into the revision or refresh the cards once when the date changes.
2. `components/gp/layout.h:33` — a group with more than 6 zones shows zones 1-6 as compact cards and silently omits the
   rest. Document it in the header / gp README (or log once at boot) so a 7-bed user is not surprised.
3. `tests/test_screens_gp.py` — add a check that no Greenhouse page widget occupies the header area x 232..312,
   y 0..22, so the slot reserved for 027's `gh_btn_history` cannot be taken by accident before 027 merges.
4. `tests/test_sim_ui.py` — `EMPTY_PROBE = (200, 40)` lies in the stats strip, so it does not prove that slots past
   the zone count stay hidden (with 3 full cards there is no free slot-4 area). Acceptable given the sim has 3 beds;
   hidden-slot behaviour is covered by `layout_bed_cards` + the `beds_1_lvgl` config row only.
5. `packages/lvgl/card_bed.yaml` — a full card without a soil sensor keeps an empty `_soil` label instead of hiding it
   (task text says "hidden"); visually equivalent, fine to leave.
6. `script/test-cpp` — `CXX` containing spaces (`uvx --from ziglang ...`) fails with "command not found"; a note in
   CLAUDE.md or word-splitting in the script would help Windows contributors (outside this task's scope; follow-up).

### Follow-ups (not blocking, from the task)
- Legacy `on_value` LVGL writes in `sensors_air_dht.yaml` / `sensors_soil.yaml`.
- WATER tab still opens `lawn_page` until task 026 provides `schedules_page`.
