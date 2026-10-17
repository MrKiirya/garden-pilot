# 026 — Review (round 1)

Verdict: APPROVE

Scope reviewed: Part B only (Schedules page on WATER, `garden_schedule.toggle_slot`, Home NEXT from the schedule hub),
as set by the header of `tasks/026-screens-schedules.md`. Parts A and C (cards, history) are tasks 025 / 027 and their
acceptance items are not judged here.

## Checks run
- `script/lint` -> exit 1, only yamllint `new-lines` on 8 files (`garden-pilot*.yaml`, 4 `examples/*.yaml`,
  `page_home.yaml`, `page_setup.yaml`): CRLF of the Windows working copy; `.gitattributes` has `* text=auto eol=lf`, so
  they are normalized on add. Not blocking. (yamllint stops the script before its `esphome config` step; the config
  rows run inside `script/test`.)
- `script/test` -> `6 failed, 844 passed, 20 skipped in 165.84s`; the 6 failures are exactly the known Windows-only ones
  (`test_ci.py::test_esphome_selector_resolves`, 4 executable-bit checks in `test_devcontainer.py`,
  `test_sim_ui.py::test_start_xvfb_deadline_holds_when_xvfb_hangs`).
- `uv run pytest -n0 -rs tests/test_schedule.py tests/test_screens_schedules.py` -> `21 passed, 1 skipped` (skip:
  no C++ compiler on this host).
- `grep -rnE "garden_zones|gh_zones|gh_bed[0-9]" packages/lvgl/page_schedules.yaml packages/greenhouse/lvgl_schedules.yaml`
  -> no match.
- Not runnable here: `script/test-cpp` (no compiler), ESP32 / host compile, the sim config rows (no `sdl2-config`),
  `sim-ui`. The new glue C++ was read against the pinned ESPHome 2026.9.1 sources instead (below).

## Static compile review (never compiled by the implementer)
- `components/garden_schedule/garden_schedule.h`: all referenced symbols exist with matching types — `Scheduler::master()`,
  `state(i).pending`, `day_runs(int, const SlotConfig*, size_t)` -> `DayRun{slot, start_minute, state}`, `DayRunState::STOPPED`,
  `NextRun{slot, day, start_minute}` via `optional<NextRun> next_run()`, `cfg_[MAX_SLOTS]`, `zone_count_`, `TAG`,
  `SlotEntities::enabled` (`switch_::Switch*`: public `state` and `toggle()`). `ToggleSlotAction` follows the existing
  `ZoneDoneAction` pattern (`TEMPLATABLE_VALUE`, `play(const Ts &...x)`). `Scheduler::today()` reads `prev_.local.day`
  (the same field `day_runs` uses). No name clash for `Today` / `SlotView` / `page_count` in `schedule_core.h` or `gp`.
- `schedule_format.h`: standard C++17 only (`char + std::string`, `std::to_string`); compiled by the implementer with
  `-Wall -Wextra -Werror` (zig), not re-run here.
- `__init__.py`: `register_action(..., synchronous=True)` (keyword present in 2026.9.1 `automation.py:66`, already used by
  the other actions of this file, so the minimum 2026.6.3 is covered by CI history), `cg.size_t` exists
  (`cpp_types.py:25`), `cv.templatable(cv.int_range(0, MAX_SLOTS - 1))`.
- `lvgl_schedules.yaml` lambdas: types line up (`size_t` global * 3 into a `size_t` templatable; `const char* + std::string`;
  `std::string == "done"`); `lvgl.widget.update state: checked: !lambda` and list forms of `lvgl.widget.show/hide` pass
  `esphome config` in `script/test`. The slot enabled switches are `optimistic: true`, so the immediate redraw after
  `toggle_slot` sees the new state.
- Final proof is the CI `compile (pinned)` / `compile (minimum)` and `host` jobs; merge only when they are green.

## Principles
- `gp_*` layer: the page touches no irrigation engine; only `garden_schedule.toggle_slot` and `switch.toggle: gh_schedules_on`
  (checked by `test_schedules_shell_and_rows`, file added to `CALLERS`).
- LVGL only from click handlers and a 1 s `interval` guarded by `gh_schedule->changed_since(...)`; nothing from hub
  triggers or `on_value`. Home NEXT is no longer written by `gp_lvgl_status.yaml`; `gp::fmt::home_next` removed.
- Lambdas one line, texts from pure tested helpers. No actuator, pin or secret changes. `packages:` order: new keys
  documented in CLAUDE.md and placed consistently in both entry files and the 4 examples.
- Tokens: colours / fonts pass `test_page_uses_only_token_colors/fonts`; no new font size; amber use noted in
  `design/README.md`. ASCII texts checked.
- Hygiene: no SSIDs, IPs, entity ids or local paths in the diff.

## Acceptance criteria (Part B subset)
- [x] `uv run pytest -m unit` -> passes (within `script/test`).
- [x] `script/lint` / `script/test` -> green apart from CRLF and the known Windows-only failures.
- [x] `GP_SECRETS=example script/config garden-pilot.yaml` valid (config rows in `script/test`, incl. new `no_schedules_lvgl`).
- [ ] `garden-pilot-sim.yaml` config, `sim_no_schedules` row, `sim-ui` `schedules.png` — not verifiable here; CI.
- [ ] `script/test-cpp` incl. `schedule_texts` / `schedule_pager` / `schedule_view_hash` / `scheduler_today_accessor` —
      implementer's run only; CI.
- [ ] ESP32 compile pinned + minimum, RAM/Flash budget — not run by anyone yet; CI must be green and the summary lines
      recorded in the PR.
- [x] Grep for engine ids in the new schedule files -> no match.
- [x] Docs: SPEC §8 / §9 stage 11, CLAUDE.md layout + package order + gotcha, design/README.md, garden_schedule README.
- [ ] Emulator by hand / hardware — not done; the notes say so explicitly (acceptable: the PR must state "not verified
      on hardware").

## Findings
### Required
None.

### Suggestions
1. `packages/greenhouse/lvgl_schedules.yaml:425,466,507` (and the `"missed"` twins) — the colour of the today word is
   chosen by comparing the formatted string in YAML (`row_today(...) == "done"`), so renaming a word in
   `schedule_format.h` silently loses the colour. A hub accessor returning the colour (or the `Today` enum) keeps the
   word/colour pair in one tested place and halves the nested `if`s.
2. `components/garden_schedule/garden_schedule.h:222` — `RUNNING` = fired today with pending zones; a slot held back
   behind a manual cycle, or with zones left after a restart outside the catch-up window, also reads `running`. Fine for
   a view; consider `queued` vs `running` once gp exposes it, or document the meaning in the README.
3. `components/garden_schedule/garden_schedule.h:217` — `day_runs()` returns nothing while the master switch is off, so
   today's word disappears (a `done` slot shows blank) when the master is switched off. Probably intended; worth one line
   in the README "Data for screens".
4. `components/garden_schedule/garden_schedule.h:187` — `changed_since` builds a vector and the next-run string every
   second; negligible today (<= 8 slots), but a `std::array<SlotView, MAX_SLOTS>` would avoid heap churn.
5. Follow-up (outside scope): `lawn_page` is now unreachable (open question 2 default); track it in task 024 or the Home
   widgets task.
