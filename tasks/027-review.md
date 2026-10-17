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

---

# 027 — Review, Round: D20 rework

Verdict: CHANGES_REQUESTED

Scope reviewed: the task file section "Rework to design D20 (2026-10-17)" and its implementation notes, i.e. the
uncommitted diff against HEAD (HEAD already contains the schedules merge).

## Checks run
- `script/lint` -> yamllint clean, `esphome config OK: garden-pilot.yaml`
- `GP_SECRETS=example GP_ESPHOME=minimum script/config garden-pilot.yaml` -> `esphome config OK: garden-pilot.yaml`.
  The `!extend schedules_page` `on_load`, the page `on_unload` and `!extend sched_history_open` merge on the minimum
  version too.
- C++ (`script/test-cpp` flags, zig clang): `120 test cases, 0 failed checks`
- `script/test` -> `7 failed, 952 passed, 20 skipped in 131.08s`. Six of these are the known Windows-only failures. The
  seventh, `tests/test_esphome_config.py::test_header_clock_merged`, is caused by this change (see Required 1).
- Not run: ESP32 compile (runs separately in Docker), host scenarios, sim `esphome config` rows, sim-ui scenario (this
  host has no C++ host toolchain, `sdl2-config` or Xvfb), hardware.

## History lifecycle (read `journal.h`, `history.h`, `gp.h`)
- OPEN at start: `ZoneTracker` sets `start_pending_` on the first RUNNING / PAUSED sample, with planned = `time_left`.
  `Journal::process` pushes the OPEN entry before it drains completions. A zone cannot end and restart within one
  sample, so the start and end of a run never mix within one refresh.
- Close in place: `book::close` finds the zone's newest OPEN entry. It keeps that entry's epoch (back-filled as
  `end - seconds` when it was 0) and writes the valve-open seconds and DONE / STOPPED. If the entry was overwritten, a
  closed entry is pushed instead. `last[]` is updated for non-service runs, as before. Covered by `book_*`.
- Boot: `setup()` loads the blob, then `recover_after_boot()` turns every OPEN entry into INTERRUPTED. It saves once,
  and only if something changed. Tested.
- Flash: `process` returns true only on a start, a completion or a skip, and the glue saves once per refresh in that
  case. Nothing is written while a run is open; live seconds come from `ZoneTracker::open_seconds` in RAM.
- Layout: the `static_assert`s (12 B / 1336 B) and `MAGIC` are unchanged. `reserved` is renamed to `detail`. Old entries
  have 0 in both new bytes, so `result` reads UNKNOWN and renders like DONE. `result_of` maps 0..6, anything else to
  UNKNOWN. `old_blob_still_loads` is kept and green.

## Sources and `completed`
- These actions take `source`: `gp.run_zone` (now also `ha` / `schedule`), `gp.enqueue_zone`, `gp.enqueue_zones` (plus a
  templatable `slot` 0..8) and `gp.full_cycle`. Deferred enqueues and a deferred `full_cycle` carry it.
- Callers: `schedule.yaml` passes `source: schedule` and `slot: !lambda "return slot;"` (`slot` is a real `uint8`
  argument of `on_run`). `gp_api.yaml` passes `ha` for run / enqueue / full_cycle, the main switch ON passes `ha`, and
  `GpZoneSwitch` uses `Source::HA`. Screens keep `manual`.
- `completed` is unchanged. Before: `source == QUEUE && !stopped`, where QUEUE meant "no fresh run_zone intent and
  `queue_run_`". Now: `from_queue = !fresh && queue_run` and `completed = from_queue && result != STOPPED`. It is the
  same predicate and does not depend on the stored source, so a SCHEDULE run still marks the slot zone done.
  `completed_flag_kept` covers it.
- `SourcePlan` precedence matches the task: intent (15 s) > queued > cycle > QUEUE > UNKNOWN. The queued source is used
  up when the zone shows RUNNING / PAUSED or is skipped. It is cleared by `stop_all`, `clear_queue`, `dequeue_zone` and
  service mode.

## Live row and poller
- `history_live_` returns seconds only for an OPEN entry whose zone view has `run_elapsed`. That field is set only while
  the tracker's run is open, so a stale OPEN entry renders like DONE with the planned time. `model_.zone()` returns the
  absent view for an out-of-range zone byte, so old entries are safe.
- Poller: runs every 1 s with `history_tick(seen, gh_hist_visible, page)`, which is `history_changed_since` (always
  evaluated) OR (page visible AND an open row on the current page). `gh_hist_visible` is set from the page's `on_load` /
  `on_unload`. The implementer says 2026.9.1 has no `lvgl.page.is_showing` condition; that is plausible, and the config
  validates on both versions.

## Screen vs the D20 artboard
- Matches `D20-History.dc.html`:
  - captions x 8/48/92/158/226, y 28; divider x 8, y 38, 304x1; rows at y 44 + 18n
  - buttons x 8/104/208, y 210, w 92/100/104, h 26 (`gap: 4` = `pad_column: 4`)
  - title `History - 1/13` (ASCII for `·`), `4 min...` for `4 min…`
  - the header line at y 22 and the 1 px page frame match the artboard's 22 px `GardenPilot.Header` and outer border
- Colours are tokens. The tests check the YAML, and the `TONE_*` constants in `gp.h` equal `text` / `text-dim` /
  `green` / `amber` from `tokens.json`.
- Fonts: montserrat_10 / _12 and `gp_font_button_md`, no montserrat_8. The shared clock is updated through one
  `!extend gp_header_clock_update`. Texts are ASCII.
- Entry / exit:
  - `gh_btn_history` is gone.
  - `sched_btn_history` (20 px) calls the no-op `sched_history_open` in the generic page, which `lvgl_history.yaml`
    extends. The button is shown from the extended `on_load`.
  - BACK goes to `schedules_page`, and `page_schedules.yaml` names no `gh_*` ids.

## Never-compiled glue (read against the pinned ESPHome sources)
No compile errors found:
- `optional` is `std::optional` in 2026.9.1 (`esphome/core/optional.h`), so `std::optional<uint32_t>(*live)` and
  `has_value()` compile (they would with a custom optional class too).
- `Journal journal_{blob_}` is declared after `blob_`, so the initialisation order is correct.
- `TEMPLATABLE_VALUE(uint8_t, slot)` matches `cg.templatable(..., cg.uint8)`.
- The Python `Source` enum resolves `HA` / `SCHEDULE` through `getattr`, and the C++ enum defines both.
- `gp::parse_skip_limit` and `DETAIL_UNKNOWN` are visible in `gp_engine.h` through `zone_model.h` -> `history.h`.
- `ZoneInput` is reset on every `read()`, so `skip_limit` is never stale.

## Acceptance criteria
- [x] `script/test-cpp`: all 120 pass (zig)
- [ ] `script/test` green: no, `test_header_clock_merged` fails (Required 1). The unit-level checks pass apart from the
  known Windows-only failures.
- [~] Config valid: the device entry is checked on pinned and minimum, and the example config rows in `script/test`
  pass. The sim entry was not checked here (no `sdl2-config`).
- [ ] CI compiles / sim-ui: cannot be checked here
- [x] `gh_btn_history` is absent from `packages`; `page_schedules.yaml` and `history_row.yaml` contain no `gh_` /
  `garden_schedule`
- [x] Both `static_assert`s and `MAGIC = 0x47503031` are unchanged
- [ ] Emulator by hand / hardware: not done (the PR must say "not verified on hardware")

## Findings
### Required
1. `tests/test_esphome_config.py:96-99`: `test_header_clock_merged` fails. The merged `gp_header_clock_update` now also
   updates `history_clock_label` (added by `packages/greenhouse/lvgl_history.yaml`), but the expected list was not
   updated. This turns `script/test` and the CI `checks` job red. Fix: add `"history_clock_label"` to the sorted
   expected list.

### Suggestions
1. `components/gp/zone_model.h` `SourcePlan` and `gp.h` `refresh()`: a queued source is cleared only by gp's own stop /
   clear / dequeue / service mode, a start or a skip. If the engine drops a queued zone by itself (a watchdog trip
   shutting the group down, or a direct engine action), the stale `queued_` beats a later `full_cycle` or queue run of
   that zone. The history then shows the wrong source, e.g. `schedule` with an old slot. This is cosmetic, not a safety
   issue. Fix direction: clear a zone's plan when it has been neither queued nor running in the engine input for more
   than one refresh (the first refresh after `queue_now_` may not show it queued yet), or clear all plans on a watchdog
   trip.
2. The same consume-while-running rule drops the source of a zone that `gp.enqueue_zone` queues again while it is still
   running; the re-queued run then falls back to cycle / QUEUE. This is rare. Either document it in the gp README or
   consume only on the RUNNING edge.
3. `components/gp/gp.h:107`: `history_row_present` is unused. The task says rows past the data are hidden, but they get
   empty texts instead. Empty labels draw nothing, so the screen looks right. Either drop the helper or use it to hide
   the row strip `${p}_hist_r${n}`.
4. `components/gp/gp.h` `TONE_*` copies four token values into C++. A small unit check against `design/tokens.json`
   would catch drift.
5. The chevron PNGs were rendered with Pillow instead of the `resvg` path used for 029's nav icons. Re-render them with
   resvg when convenient (the implementer already noted this).
