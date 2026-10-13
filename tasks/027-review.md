# 027 — Review (round 1)

Verdict: APPROVE

Scope reviewed: the task header, i.e. Part C (History page) plus the gp history `result` byte and skip entries. Parts A
and B (cards, schedules, Home NEXT, nav rewrite, soil link, `run_total`) are other tasks and were not expected here.

## Checks run
- `script/lint` -> `esphome config OK: garden-pilot.yaml` (yamllint clean)
- `GP_SECRETS=example GP_ESPHOME=minimum script/config garden-pilot.yaml` -> `esphome config OK: garden-pilot.yaml`
  (so `!extend greenhouse_page` also merges on the minimum version)
- `script/test` -> `6 failed, 841 passed, 19 skipped in 106.14s`. The 6 failures are exactly the known Windows-only ones
  (`test_ci.py::test_esphome_selector_resolves`, 4 executable-bit tests in `test_devcontainer.py`,
  `test_sim_ui.py::test_start_xvfb_deadline_holds_when_xvfb_hangs`). Host scenarios, sim `esphome config` rows and the
  sim-ui scenario skipped (no C++ compiler / `sdl2-config` / Xvfb on this host).
- C++ unit tests, with the `script/test-cpp` flags but zig clang instead of g++:
  `uvx --from ziglang python -m ziglang c++ -std=c++17 -Wall -Wextra -Werror -I components -I tests/cpp tests/cpp/*.cpp`
  -> `85 test cases, 0 failed checks`
- Not run (not part of this review): ESP32 / host firmware compile (Docker, separate), sim-ui screenshots.

## Persistence compatibility (checked by hand against `master`)
- `master` `history.h`: `HistoryEntry {uint32 epoch, uint32 duration, uint8 zone, uint8 source, uint16 reserved}` = 12 B;
  `History<100> {entries[100], uint16 head, uint16 count}` = 1200 + 4 = 1204 B (4-byte aligned); `PersistBlob
  {uint32 magic, History<100>, LastRun[16] (8 B each)}` = 4 + 1204 + 128 = **1336 B**. The new `static_assert`s (12 and
  1336) match. Xtensa/RISC-V ESP32 use the same natural alignment as the host, so the value holds on the device.
- `master` always wrote `reserved = 0` (`HistoryEntry entry{..., 0}` in `gp.h`), so both new bytes read 0 on old
  entries -> `Result::UNKNOWN` -> `-` (a service entry reads `test`). Magic `GP01` unchanged; the preference object is
  sized by `sizeof(PersistBlob)`, unchanged. `result_of()` also maps any out-of-range byte to UNKNOWN. Old blobs load.

## gp.h glue (never compiled here; read for errors)
- `#include "esphome/core/time.h"`; `ESPTime::from_epoch_local(time_t)`, `day_of_month`, `month`, `hour`, `minute`
  (`uint8_t`) and `is_valid()` exist in the pinned 2026.9.1 sources (`esphome/core/time.h`), long-standing API.
- `history_row` / `history_pager` / `history_clamp_page` / `history_changed_since` are const, types line up
  (`size_t` index, `int` page), `fmt::LocalTime{...}` aggregate init is valid C++17, `RunRecord{...}` (aggregate with
  default member initialisers and a member function) is valid C++17. `now_ms` and `STOP_WINDOW_MS` are in scope in
  `refresh`. YAML lambdas return `std::string` / `int` as the actions expect. No obvious compile error found; CI compile
  is still the real proof.
- Skip path: one `push` + one `pref_.save` per refresh batch, `history_pushes_++`, no `on_zone_finished`, no
  `last[]` update — as the task says. Runs: STOPPED inside the stop window, else DONE (watchdog = DONE).

## Acceptance criteria (Part C + history scope)
- [x] `script/test-cpp` checks pass incl. the new history checks — 85 cases, 0 failed (zig clang, same flags).
  (Task names `test_gp_screens.cpp`; the implementer used `test_gp_history.cpp` because Part A owns that name — fine.)
- [x] `uv run pytest -m unit` passes — covered by the `script/test` run above (only known Windows failures).
- [x] `script/lint` green; `script/test` green apart from the known Windows-only failures. CI time not measurable here.
- [x] `script/config garden-pilot.yaml` valid (pinned and minimum). Sim entry not checkable here (no `sdl2-config`).
- [ ] Compile pinned / minimum + RAM/Flash numbers — pending (Docker run, outside this review).
- [ ] CI `compile`, `sim-ui` with `history.png` — pending CI.
- [x] `grep -rnE "garden_zones|gh_zones|gh_bed[0-9]" packages/greenhouse/lvgl_history.yaml` -> no match.
- [x] Old history blob loads — confirmed by the layout check above (size 1336 and magic unchanged, zero byte -> `-`)
  and by `old_blob_still_loads`.
- [ ] Emulator by hand (history lists runs newest first and pages) — not done (no display here); PR must say so or attach.
- [x] Docs: `components/gp/README.md` (result, skips, glue), SPEC §8 built list and §9.1, `design/README.md` (History
  page), `CLAUDE.md` layout row and package order.
- [ ] Hardware — not verified; the implementation notes say so explicitly (acceptable per the criterion).

Principles: LVGL is written only from the page `on_load` script, the PREV / NEXT buttons and one 1 s `interval` guarded
by `history_changed_since` (no gp trigger, no `on_value`); all lambdas one line; formatters pure (`format_history.h`, no
ESPHome include) and unit tested; colours `bg`, `border`, `text`, `text-dim` and fonts 8 / 10 only (token check
extended); texts ASCII (check extended); 6 row labels, about 14 objects in total (no 100 widgets); geometry: header 22,
`btn-h-sm` 20 PREV / NEXT, BACK 92x26 at y=210 identical to `network_btn_back`; no secrets, no personal data, no
actuator change. Package order: `gh_lvgl_history` right after `gh_lvgl_page` in both entry files and the 4 examples, with
a test.

## Findings
### Required
None.

### Suggestions
1. `packages/greenhouse/lvgl_history.yaml:211` — the HISTORY ghost button (transparent fill, `text-dim` #becab9 outline
   and text) is placed on today's `greenhouse_page`, which still uses the default LVGL theme (no `bg_color` there or in
   `packages/lvgl/base.yaml`). If that theme renders a light background, the button has very low contrast until Part A
   rewrites the page. Check it in the emulator / on the display; if it is hard to read, give it a token fill (e.g.
   `card`) for the interim, or accept it as temporary and note it in the PR.
2. `components/gp/gp.h:309-320` — the STOPPED vs DONE decision lives only in the glue and has no check (the pure tests
   stop at "the glue turns it into STOPPED"). Consider a step in the `tests/test_gp_layer.py` host scenario (STOP during
   a run -> newest entry's result byte = STOPPED; a normal end -> DONE) when the host build is available, or move the
   window decision into a small pure helper so the C++ suite covers it.
3. `components/garden_zones/gp_engine.h:50` — `skip_wet` depends on the engine's reason text prefix `"soil moisture"`
   from `group.h:232`. It is documented, but a text change in the engine would silently turn wet skips into plain
   `skipped`. A one-line unit check (or a shared constant for the prefix) would pin it.
4. Coordination note for Part A (already in the implementation notes): Part A's rewritten `lvgl_page.yaml` defines its
   own `gh_btn_history`, so the `!extend greenhouse_page` block here must be dropped on merge (a duplicate id fails
   `esphome config` loudly, so it cannot slip through). Likewise the `isinstance(p["id"], str)` tweaks in
   `tests/test_screens.py` will meet Part B's `!extend schedules_page`.
5. The implementation notes say the checks were written together with the code (no separate red run). The checks are
   meaningful (they would fail without the change: missing enum / formatter / skip record), so this is not blocking.
