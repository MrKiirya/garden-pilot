# 030 — Review (round 1)

Verdict: APPROVE

Approval covers the code, the checks and the docs of the working-tree diff on `task/026-screens-schedules`. The
merge still waits on the criteria that could not be checked on Windows (compile, CI, emulator, hardware, see below).

## Checks run
- `script/lint` -> `esphome config OK: garden-pilot.yaml`, exit 0
- `script/test` -> `6 failed, 911 passed, 20 skipped in 115.05s`. All 6 failures are the known Windows-only ones
  (`test_ci.py::test_esphome_selector_resolves`, 4 executable-bit tests in `test_devcontainer.py`,
  `test_sim_ui.py::test_start_xvfb_deadline_holds_when_xvfb_hangs`). The skipped rows include the `sdl2-config`-dependent
  sim config rows.
- `script/test-cpp` (zig c++, `-Wall -Wextra -Werror`) -> `98 test cases, 0 failed checks`
- I read `garden_schedule.h` against the pinned ESPHome 2026.9.1 sources in `.venv` and found no compile error:
  - `TimeEntity::hour` / `minute` are public const refs and `TimeCall::set_time(h, m, s)` exists (`datetime/time_entity.h`).
  - `TextCall::set_value(std::string)` and `NumberCall::set_value(float)` exist.
  - `Switch` has `turn_on()` / `turn_off()` and no `make_call()`, so using `turn_on()` / `turn_off()` is correct.
  - `text::Text::state` is a `std::string`.
  - The free functions `row_time` / `row_caption` are called fully qualified from the members of the same name.
  - `StatusWord` brace init and the `esphome::optional` uses match patterns that already exist in the file.

## Acceptance criteria
- [x] Merge of `task/029-font-scale-c` before the task commits. Verified: HEAD `134d735` merges 029.
- [x] `script/test-cpp` passes, including the run-mark cases and `test_schedule_ui.cpp`. Verified: re-run, 98 cases.
- [ ] `uv run pytest -m unit`, `script/lint`, `script/test` green. Green apart from the known Windows-only failures;
  CI has to confirm.
- [ ] `script/config` of the entry, the sim entry and each example. Not re-run separately: the `config` rows inside
  `script/test` passed for the entry and the examples. The `garden-pilot-sim.yaml` config was not run (no
  `sdl2-config` on Windows).
- [ ] ESP32 compile, pinned and minimum, with RAM / Flash of master and branch recorded. Open: the compile runs
  separately in Docker. The numbers are not in the task file yet, so the budget (flash +96 KB / static RAM +8 KB)
  is unchecked.
- [ ] CI `compile (pinned)`, `compile (minimum)`, `sim-ui` with `schedules.png` / `schedule_edit.png`. Open.
- [x] `rg -n "toggle_slot|pager_text|page_step" components packages tests` -> only `test_toggle_slot_removed`.
  Verified with grep.
- [x] No `garden_zones|gh_zones|board_relay|sprinkler` in the two YAML files (nor in the 4 new includes). Verified.
- [ ] Emulator by hand (`script/sim`). Open (main session / human).
- [x] Docs updated: component README (run-mark rule, persistence v2), SPEC §8/§9, CLAUDE.md (layout row, Schedule
  screens / Schedules gotchas), design/README.md (pages, 20 px HISTORY, 22 px buttons), README.md + README.ru.md.
  Verified in the diff.
- [ ] Hardware: open. The PR must say "not verified on hardware" unless the human checks it.

## Focus points verified
1. **Run mark.** `handled_()` (`schedule_core.h`) is the single predicate used by crossing, catch-up, `next_run` and
   `day_runs`.
   - `fire_` and the missed path write `last_fired_minute`.
   - A future mark also resets the minute to `ANY_MINUTE`.
   - Pending zones from a run with a different start are dropped only on the resume tick, before the `start_s > now_s`
     check, so a start moved ahead also drops them.
   - Tests cover the cases the task lists: moved later (the same day, the next day once), STOP then moved (full mask,
     `RAN`), the same start re-saved / re-enabled, DST fall-back (the mark minute is asserted), moved to a passed time,
     moved while pending (catch-up / ahead / missed / unchanged start), v1 `ANY_MINUTE` (also the pending resume), and
     `next_run` / `day_runs` after a move.
   - **Persistence.** v2 is 84 bytes and v1 is 68 bytes, under different keys.
     - `esp32/preferences.cpp` `load()` returns false on a size mismatch: the pending-save branch (~l.100) and the
       NVS `actual_len != len` check (~l.117).
     - `host/preferences.h` l.41 checks `vec.size() != len`.
     - On a v2 miss the code migrates from v1 with `ANY_MINUTE`, so an upgrade does not cause an extra run.
2. **Editor draft.**
   - Every click lambda edits only `draft()` (RAM).
   - `save_edit()` writes only the `diff(original_)` fields: per day switch, zones only when non-empty, start via
     `make_call`. The snapshot comes from the entities in `begin_edit`, so a Home Assistant change to a field the
     user did not touch survives.
   - The only `save_edit` caller is `gh_sed_btn_save` (`test_editor_writes_only_on_save`).
3. **Engine reached only via entities / actions.** The hub reads `gp_greenhouse->zone(z).run_duration` (read model,
   bounds-checked in `zone_model.h:309`) through `set_zone_seconds`. Nothing touches `garden_zones`.
4. **LVGL.**
   - LVGL is called only from the guarded 1 s poller (`changed_since(gh_sched_seen)`), click handlers and the
     `gp_header_clock_update` extend.
   - Every colour is in `design/tokens.json` (checked each hex).
   - Fonts are montserrat_10/12/14/16 plus `gp_font_button_sm` (22 px buttons) / `_md` (26 px buttons). There is no
     `montserrat_8`.
   - All texts are ASCII, button-font texts stay within their glyph set, and nothing tappable is under 20 px.

## Findings
### Required
None.

### Suggestions
1. `components/garden_schedule/schedule_ui.h:169` / `garden_schedule.h:207`:
   - Problem: `duration_text` calls `zone_seconds(z)` without checking that the `std::function` is set. On ESP32
     (no exceptions) an empty function aborts.
   - Why it is not a bug today: the provider is set in `on_boot` priority 600 (`lvgl_schedules.yaml:25`), before the
     first poll.
   - Risk: a future config that uses the hub's row texts without that lambda would crash.
   - Fix: return `""` (or treat the duration as 0) when the provider is empty.
2. `garden_schedule.h:298-325`:
   - Problem: after SAVE, `gh_sched_list_refresh` draws from `cfg_`, which is refreshed only on the next 1 s tick,
     so the list shows the old values for up to 1 s. The poller then redraws.
   - Fix: call `this->read_config_()` at the end of `save_edit()`.
3. Run-mark edge, as specified but not tested:
   - Case: moving a slot to a later time while its earlier run is still watering (`pending != 0`) fires the full
     mask again at the new start. The zones may still be queued or running in `gp`.
   - Fix: add a C++ case pinning the intended outcome (the new fire replaces `pending`), and add one line in the
     README saying what `gp` does with the second enqueue.
4. Scope note, not a defect: the examples had 1 slot and now have 4 (slots 2-4 added), which goes beyond "add slots
   3-4". It is consistent with the "4 slots" goal and documented in the notes.
5. Follow-ups already listed in the task: lawn zones in the editor, a HISTORY target >= 20 px. Record the RAM / Flash
   numbers in the task file once the Docker compile finishes.
