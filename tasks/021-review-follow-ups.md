# 021 — Review follow-ups: main switch through gp, start after STOP, cap and inhibit checks

Status: implemented (CI and review pending)
Roadmap: maintenance (safety/correctness debt from the reviews of 014, 018 and 019; stage 8 gp layer)
Spec sections: SPEC §3 (engine limitations), §4 / §4.1 (gp layer, schedules), §9 (roadmap)
Hardware check: none. No device is available for this task. Everything is verified on the host (cpp, config, host
scenarios). The implementer must state in the notes that nothing ran on a real device.

Stacked on 020 → 019 → 018 (branch `task/021-review-follow-ups`).

## Goal
After this task every start and stop path that Home Assistant can reach goes through `gp`. The "Greenhouse irrigation"
main switch becomes a gp-owned switch with the same name and object id. Turning it ON respects the service-mode
inhibit, and turning it OFF is a full gp STOP: `on_stop` fires, schedules settle, held-back starts are cancelled, and
the queue is cleared when schedules are on. A queue start (or full cycle) issued while the engine is still stopping is
no longer dropped without a trace: gp holds it back and runs it once the lane is idle. A single `gp.enqueue_zone` during
a manual run or cycle is held back the same way as `gp.enqueue_zones`. The minutes cap, the clamp to the zone maximum
and the inhibit on every start action get real checks. The watchdog trip log prints the zone label once, and the
history reload after a reboot is tested.

## Context

### Sources (review follow-ups)
- 018 review round 2: R2-1 (main switch bypasses the inhibit), R2-2 (no checks for the clamp, the 24 h cap or the
  inhibit on enqueue / start queue / full cycle), R2-3 (queue start within ~1 s of a shutdown dropped silently;
  `quick_off` / `delay_off` only check the end state); round 1 S8 (history reload test).
- 019 review round 2: suggestion 2 (`gp.enqueue_zone` not held back), human question **C** (main switch OFF is not a
  STOP). **The author has not answered C yet.** This task implements the reviewer's and planner's recommendation
  (route the switch through gp). If the author decides otherwise, drop items 1a-1d below and keep the rest.
- 014 follow-ups: watchdog trip log repeats the label ("zone 0 ('group 'Greenhouse' zone 0 ('Greenhouse bed 1')')").

### Facts checked in the code (line numbers are approximate; the implementer verifies them)
- `packages/greenhouse/irrigation.yaml` (around l. 37-50): the engine group has `main_switch` (id
  `gh_zones_main_switch`, name "Greenhouse irrigation"). `components/garden_zones/group.h` `set_main_switch` (around
  l. 54-63) wires ON to `start_cycle()` and OFF to `shutdown()`. gp is bypassed, so there is no inhibit, no `on_stop`,
  and the queue is kept.
- Precedent for keeping HA entities stable: `bed.yaml` makes the engine valve switch `internal: true` and adds a gp-owned
  switch with the same name, so the object id stays `greenhouse_bed_N` (018 review "HA entity continuity").
- ESPHome template switch (pinned 2026.9.1, checked in
  `.venv/.../esphome/components/template/switch/template_switch.cpp`; minimum 2026.6.3 checked on GitHub tag `2026.6.3`,
  same logic). `setup()` calls `turn_on()` / `turn_off()` when `get_initial_state_with_restore_mode()` has a value, so
  with the default `ALWAYS_OFF` it **runs `turn_off_action` at boot**. `restore_mode: DISABLED` (valid in
  `esphome/components/switch/__init__.py`) skips this. `loop()` publishes the lambda's value. With `optimistic: false`
  the state comes only from the lambda.
  **Consequence:** a template main switch must use `restore_mode: DISABLED`. Otherwise every boot calls `gp.stop_all`,
  `on_stop` settles the slots, and the 019 power-cut resume breaks.
- Dropped start after a shutdown (R2-3), likely cause: `Sprinkler::shutdown()` → `fsm_transition_to_shutdown_()` puts
  the lane in `STOPPING`. `fsm_kick_()` (around `sprinkler.cpp:1575`) only acts in `IDLE` / `ACTIVE`, so
  `start_from_queue()` sets `queue_enable` and returns without a kick. The `STOPPING → IDLE` transition (around
  l. 1612-1625) only picks up `next_req_`, not the queue. Therefore `run_zone` (which uses `next_req_`) survives, while
  `start_queue` (and probably `start_full_cycle`, which also only kicks) is lost. `Sprinkler::controller_state()` is
  public (`sprinkler.h` around l. 436), so no fork patch is needed to read it.
- `GpGroup` (`components/gp/gp.h`):
  - `enqueue_zone` (around l. 96) has no hold-back.
  - `enqueue_zones` / `start_queue` use `run_blocks_queue_()` + `DeferredStart` (`deferred_start.h`, grace 5 s).
  - `clamp_` (around l. 344) cuts to `Engine::max_run_seconds`.
  - `packages/core/gp_api.yaml` has the 24 h cap as a lambda: `minutes > 1440 ? 86400 : (minutes > 0 ? minutes * 60 : 0)`.
- Watchdog label: `groups.py::_zone_label()` returns `group '<name>' zone <n> ('<switch name>')` and is passed to
  `watchdog.add_zone()`. `watchdog.h` then formats `group '%s' zone %d ('%s')` around it, so the text is nested twice
  (trip ERROR, LOCKED_OUT WARN, STILL_ON ERROR, `never` WARN in `dump_config`).
- Host scenarios read only `GZTEST` lines (`tests/test_garden_zones.py::_run_program`). The schedule scenario
  (`tests/configs/schedule_sim.yaml`) already runs 5 boots on one preferences dir with `core_gp` + `gh_gp`.

### CI time constraint
`checks` takes ~25 min, mostly host scenarios. Task 022 will speed it up. This task adds **no new host build and no new
host program run**:
- Pure logic goes into cpp tests (`script/test-cpp`, seconds).
- Behaviour on the real packages goes into steps added to the **existing** scenarios: gp layer (about +45 s), schedule
  (about +0 s; asserts only on existing boots and one swapped action), and greenhouse 014 (0 s; only an id changes).
- Config-level assertions reuse existing `--only-generate` fixtures.

Expected `checks` delta: **≤ +1 min**. The implementer records the before/after wall time of the three host scenarios
(each test alone is enough).

## Decisions made by the planner (author to confirm)
1. **Main switch = YAML template switch in `packages/greenhouse/gp.yaml`, not new C++** (principle 1: ready-made
   component; principle 2: its actions are `gp.*` only).
   - Name "Greenhouse irrigation", `icon: mdi:water-pump`, `restore_mode: DISABLED`, `optimistic: false`.
   - `lambda: return id(gp_greenhouse)->summary().running;`
   - `turn_on_action: gp.full_cycle: gp_greenhouse`, `turn_off_action: gp.stop_all: gp_greenhouse`.
   - The engine `main_switch:` block is **removed** from `irrigation.yaml` (the key is optional). It is not kept as
     internal: nothing needs it, and the removal also closes the principle-2 hole.
   - New id `gp_greenhouse_main_switch` (in line with `gp_greenhouse_status`). The name is unchanged, so the HA object
     id `switch.<node>_greenhouse_irrigation` and the entity stay the same. The `gh_zones_main` ON/OFF log lines move
     along (tag `gp`).
2. **OFF always means STOP**, even when nothing runs. Reason: it must also cancel a held-back start. This matches the
   Home STOP button. Side effect: with schedules on, an HA OFF while idle settles today's pending zones and clears the
   manual queue (same as STOP today, 019 human question B).
3. **ON while inhibited / watchdog-locked:** `gp.full_cycle` refuses with a WARN. The lambda keeps the switch OFF, so HA
   shows OFF again within ~1 s. During the ~2 s switching delay after ON, HA can briefly show OFF (no optimistic window,
   unlike `GpZoneSwitch`). Accepted as cosmetic; listed as a follow-up.
4. **Dropped start after STOP (R2-3): defer, don't just WARN.**
   - New `Engine::stopping()` (virtual, default `false`). The garden_zones adapter implements it from a new read
     accessor `GardenZonesGroup::any_lane_stopping()` in `group.h` (a new GPL file of the repo, not a stock-code patch,
     so no `GZ-PATCH` / `PATCHES.md` entry).
   - `start_must_wait()` gets a `stopping` input. `gp.start_queue` and `gp.full_cycle` issued while stopping are held
     back (INFO log "deferred: the group is still stopping") and run when the existing `DeferredStart` fires.
   - `full_cycle` needs a held-back flag like `deferred_start_`.
   - A later `stop_all` / inhibit / `clear_queue` cancels them as today.
   - The implementer first pins the drop in the scenario (red), then confirms or corrects the cause above. If the cause
     differs, keep the same observable contract (no silent drop; the start happens or a WARN is logged) and record it.
5. **`gp.enqueue_zone` follows the same hold-back rule as `gp.enqueue_zones`** (`run_blocks_queue_()`). The deferred
   list stores either a mask + pct or a single zone + seconds, in arrival order. Consequence: a zone enqueued (by "+Q"
   on the greenhouse page or HA `gp_enqueue_zone`) during a manual run or cycle is **not shown as queued** until 5 s
   after that run ends. INFO is logged. See Open question 2.
6. **24 h cap and clamp as pure helpers** in a new MIT header `components/gp/limits.h`:
   - `api_seconds(int minutes)`: ≤ 0 → 0 (= the configured duration), > 1440 → 86400, else × 60.
   - `clamp_run(optional<uint32_t> seconds, uint32_t max)`: max 0 = unknown, no cut.
   - The `gp_api.yaml` lambdas become one line: `return gp::api_seconds(minutes);`. `GpGroup::clamp_` uses `clamp_run`
     and keeps its WARN.
7. **Watchdog label:** `watchdog.add_zone()` gets the short label (valve switch name, else its id) from a new helper
   `groups.py::_watchdog_label(zone)`. `_zone_label()` stays as it is for config errors. Result:
   `group 'Greenhouse' zone 0 ('Greenhouse bed 1') on for ...`.
8. **History reload is tested on the schedule scenario's existing reboots, not by a second gp program run.** A full
   ring of 100 entries is tested as a cpp blob round trip (byte copy = what the preference layer stores). Filling 100
   entries on the host would take too long.
9. **Schedule scenario phase 4** presses STOP via `switch.turn_off: gp_greenhouse_main_switch` instead of
   `gp.stop_all`. The OFF action is `gp.stop_all` (pinned by a unit shape test), so one existing step covers both
   "main OFF settles the slot" and the STOP chain.

## Files
(About 20 files, above the usual ≤ 10, because this bundles several small follow-ups. Most changes are a few lines.
If it does not fit, cut in the order given under "Cut order" below.)
- modify: `packages/greenhouse/irrigation.yaml` — remove `main_switch:`; update the header comment (the main switch is
  in `gp.yaml`).
- modify: `packages/greenhouse/gp.yaml` — template switch `gp_greenhouse_main_switch` (Decision 1); header comment lists
  the entity.
- modify: `packages/core/gp_api.yaml` — lambdas `return gp::api_seconds(minutes);`.
- modify: `packages/greenhouse/lvgl_valve_test.yaml` — header comment (around l. 18-19): drop the "Exception: the main
  switch" wording; every HA start path now goes through gp.
- create: `components/gp/limits.h` — `api_seconds`, `clamp_run` (pure, MIT, no ESPHome includes).
- modify: `components/gp/deferred_start.h` — `start_must_wait(busy, stopping, cycle_run, queue_run)`.
- modify: `components/gp/engine.h` — `virtual bool stopping() const { return false; }`.
- modify: `components/gp/gp.h` — hold back `enqueue_zone`; defer `start_queue` / `full_cycle` while stopping; use
  `limits.h`.
- modify: `components/garden_zones/group.h` — `any_lane_stopping()` (reads `controller_state() == STOPPING` on every
  lane).
- modify: `components/garden_zones/gp_engine.h` — implements `stopping()`.
- modify: `components/garden_zones/groups.py` — `_watchdog_label()`, used for `watchdog.add_zone`.
- modify: `tests/cpp/test_gp_deferred_start.cpp`, `tests/cpp/test_gp_model.cpp`; create `tests/cpp/test_gp_limits.cpp`
  (if `script/test-cpp` needs registration, add it there).
- modify: `tests/configs/gp_layer_sim.yaml`, `tests/test_gp_layer.py`.
- modify: `tests/configs/schedule_sim.yaml`, `tests/test_schedule.py`.
- modify: `tests/configs/greenhouse_zones_sim.yaml` (`gh_zones_main_switch` → `gp_greenhouse_main_switch`, 4 places),
  `tests/test_greenhouse_zones.py` (`test_irrigation_shape`: no `main_switch`; new gp.yaml shape assertions).
- modify: `tests/test_garden_zones.py` — label unit test + codegen assertion.
- modify: `tests/test_service.py` only if its comment / string checks on the valve-test header need it.
- docs:
  - `components/gp/README.md`: main switch row; `enqueue_zone` hold-back; deferral while stopping;
    `on_zone_finished` table (main OFF is now `completed=0`).
  - `components/garden_schedule/README.md`: main switch OFF is a STOP; remove the "HA main switch is not a STOP" rule.
  - `CLAUDE.md`: the `garden_zones` convention line naming "Greenhouse irrigation" as an engine entity; layout row for
    `packages/greenhouse/*.yaml`.
  - `docs/SPEC.md` §4 if it describes the main switch.

## Checks to write first
| Level | Test | Asserts |
|---|---|---|
| cpp | `test_gp_limits.cpp::api_seconds_caps` | -5 → 0, 0 → 0, 1 → 60, 1440 → 86400, 1441 → 86400, `INT_MAX` → 86400 (no overflow) |
| cpp | `test_gp_limits.cpp::clamp_run_cuts_to_max` | none → none; 100 with max 3300 → 100; 5000 with max 3300 → 3300; 5000 with max 0 → 5000 |
| cpp | `test_gp_deferred_start.cpp::stopping_holds_back_a_start` | `start_must_wait(false, true, false, false)` is true; `(false, false, false, false)` false; existing cases unchanged |
| cpp | `test_gp_model.cpp::persist_blob_full_ring_round_trip` | push 130 entries into `PersistBlob::history` and set `last[]`; byte-copy into a second blob (memcpy, as flash stores it); `valid()`, `size()==100`, `at(0)` = newest, `at(99)` = entry 31, `last[]` equal |
| unit | `tests/test_greenhouse_zones.py::test_irrigation_shape` (changed) | the group has no `main_switch` key |
| unit | `tests/test_gp_layer.py::test_main_switch_through_gp` (new) | `packages/greenhouse/gp.yaml` has one template switch named "Greenhouse irrigation", id `gp_greenhouse_main_switch`, `restore_mode: DISABLED`, `optimistic` absent/false, `turn_on_action` = only `gp.full_cycle`, `turn_off_action` = only `gp.stop_all`, the lambda reads `gp_greenhouse` |
| unit | `tests/test_gp_layer.py::test_api_minutes_use_helper` (new) | both duration lambdas in `gp_api.yaml` equal `return gp::api_seconds(minutes);` |
| unit | `tests/test_garden_zones.py::test_watchdog_label_is_short` (new) | `_watchdog_label` gives the switch name for a dict valve switch and the id otherwise; it never contains `group '` |
| config | `tests/test_garden_zones.py::test_safety_codegen` (extended) | `add_zone(` arguments contain no nested `group '`; a fixed `run_duration: 2s` zone has `set_zone_max_run(<n>, 2)` |
| config | `tests/test_gp_layer.py::test_gp_codegen` (extended, pinned + minimum) | `gh_zones->set_zone_max_run(0, 120)` (scenario substitutions, 2 min) or 3300 for the 55-min default (whichever config the fixture builds); no engine main switch in `main.cpp` |
| config | `tests/test_greenhouse_zones.py::test_entity_names_kept` (unchanged) | still passes: "Greenhouse irrigation" exists exactly once among the names |
| host | gp scenario step 8 (extended), `tests/configs/gp_layer_sim.yaml` | while inhibited: `gp.enqueue_zone`, `gp.enqueue_zones`, `gp.start_queue`, `gp.full_cycle` and the main switch ON open no relay; `queue_length == 0`; the main switch is back OFF within 2 s (`inhibit_all_refused=1`). `quick_off` / `delay_off` also assert that relay 3 **never** turned on in the window (a 50 ms latch global), not just the end state |
| host | gp scenario step 9d (changed) | main switch OFF of a queue run → `fin zone=0 completed=0` and the extended `gp_gh_stopped` hook logs `stop_hook` |
| host | gp scenario step 10 (new, ~25 s) | (a) `gp.run_zone` 600 s on zone 0 (max 120 s) → `time_left <= 120` and the WARN path taken (`clamp_ok=1`); (b) run zone 0, `gp.stop_all`, after 300 ms `gp.enqueue_zone` zone 2 + `gp.start_queue` → relay 3 rises within 15 s (`start_after_stop=1`); written first and seen red before the fix; (c) the main switch OFF then ON after 300 ms → relay 1 rises within 15 s; (d) during a manual `gp.run_zone` on zone 1, `gp.enqueue_zone` zone 2 → `deferred_enqueues()==1`, queue 0, and zone 2 is queued after the run ends |
| host | gp scenario boot (new line) | no `stop_hook` before mark `s1_a` (the main switch does not stop at boot) |
| host | schedule scenario phase 4 (changed) | the STOP is `switch.turn_off: gp_greenhouse_main_switch`; the existing asserts (`stopped_idle=1 queue=0`, `#2 stopped`, phase 5 quiet) still hold |
| host | schedule scenario phases 2 and 3 (new log lines at boot) | `hist=<n> last1=<s>`: phase 2 `n >= 1` and `last1` > 0 (zone 1 completed in phase 1 is restored from flash); phase 3 `n` ≥ phase 2's end count |

## Acceptance criteria
- [ ] `script/test-cpp` → all pass, including the 4 new cases.
- [ ] `uv run pytest -m unit` → all pass.
- [ ] `script/lint` → clean; `esphome config` OK for `garden-pilot.yaml` (and `GP_SECRETS=example script/config
      garden-pilot-sim.yaml` where `sdl2-config` exists).
- [ ] `UV_OFFLINE=1 GP_REQUIRE_CXX=1 script/test` → all pass, no skips. The wall time of `test_gp_layer_host_scenario`,
      `test_schedule_host_scenario` and `test_greenhouse_zones_host_scenario` is recorded before and after (delta
      ≤ +1 min expected).
- [ ] The R2-3 step was red before the fix (stated in the notes with the observed log).
- [ ] `git grep -n 'main_switch' -- packages` → no hit. `git grep -n gh_zones_main_switch -- . ':!tasks'` → no hit.
- [ ] `git grep -n -e 'garden_zones\.' -e 'gh_zones' -- packages garden-pilot.yaml garden-pilot-sim.yaml` → only the
      files allowed by `test_no_engine_outside_adapter` (unchanged allow-list).
- [ ] `GP_SECRETS=example script/compile` (pinned, ESP32) OK, with the flash/RAM delta recorded. Minimum ESP32 and sim
      host compiles may be left to CI (say so; leave the box open until CI is green).
- [ ] Docs updated (gp README, schedule README, CLAUDE.md, SPEC if affected). README.md / README.ru.md only if they
      mention the main switch (keep them in sync).
- [ ] CI green.
- [ ] Notes say: not verified on a real device. Hardware check for later (breadboard): HA "Greenhouse irrigation" ON
      runs a cycle, OFF stops it and settles a running slot, the entity id is unchanged after OTA, and the switch is
      refused while SETUP > SERVICE is open.

## Cut order (if the task runs long)
1. Item 5 (watchdog label) → its own light-path PR.
2. Decision 5 (`enqueue_zone` hold-back) → follow-up.
3. Step 10(c) / full-cycle deferral (keep the queue deferral).

Never cut the main switch (Decision 1), the R2-3 pin, or the boot-safety assertion.

## Out of scope
- Soil reading in the gp model, soil-sensor alert, SKIPPED-by-soil scenario (018 cut 1); air-sensor alerts.
- Legacy `on_value` LVGL updates in `sensors_air_dht.yaml` / `sensors_soil.yaml` → pollers.
- Showing held-back (deferred) zones as QUEUED in the model / greenhouse page (see Open question 2).
- An optimistic ON window for the main switch (C++ `GpGroupSwitch`), if the brief OFF flicker in HA bothers.
- 019 human question B (STOP clears the manual queue too) and 019 suggestions 1, 3-5 (`set_inhibit`-only scenario step,
  paused cycle treated as busy, ...).
- Automated number-clamp check across a reboot and the restored auto-advance push (014 follow-up; needs a lower
  `gh_bed_run_max` on a second boot).
- Engine-side fix of the STOPPING drop (`GZ-PATCH` in `sprinkler.cpp`) for direct engine callers; only gp callers
  exist outside tests.
- `valve_test_color` tokens in C++, the HA-icon poller in a core package (018 S6/S7).
- CI speed-up (task 022).

## Open questions
1. **[human]** 019 question C: confirm that "Greenhouse irrigation" OFF should be a full STOP (settles today's slots,
   clears the queue when schedules are on). The planner implemented it; the alternative is to drop Decision 1 and only
   document the gap.
2. **[human / designer]** Is it acceptable that a zone added with "+Q" during a manual run or cycle does not appear in
   the queue line until that run ends (Decision 5)? If not, a follow-up should make the model show held-back zones as
   QUEUED.
3. **[human]** OFF while idle also settles pending slots and clears the manual queue (Decision 2). Acceptable, or should
   OFF act only when something runs or waits (like the zone switch)?
4. The R2-3 cause is inferred from reading `sprinkler.cpp`. If the step shows that `full_cycle` after a stop is not
   dropped, Decision 4 only needs the queue deferral.

<!-- Filled in by implementer -->
## Implementation notes
Nothing was run on a real device (host cpp, config, host scenarios and an ESP32 compile only). Hardware check for later
(breadboard): HA "Greenhouse irrigation" ON runs a cycle, OFF stops it and settles a running slot, the entity id is
unchanged after OTA, the switch is refused while SETUP > SERVICE is open.

Done (all items, nothing cut): main switch through gp (template switch `gp_greenhouse_main_switch`, `restore_mode:
DISABLED`, engine `main_switch:` removed); `Engine::stopping()` + `GardenZonesGroup::any_lane_stopping()`; start_queue /
full_cycle deferred while stopping (`deferred_cycle_` flag); `enqueue_zone` held back like `enqueue_zones`;
`components/gp/limits.h` (`api_seconds`, `clamp_run`) used by `gp_api.yaml` and `clamp_`; watchdog label
(`_watchdog_label`); docs (gp README, schedule README, CLAUDE.md, SPEC line on STOP).

Checks: cpp 78 cases (4 new: limits x2, stopping, full-ring blob round trip; the oldest kept entry of 130 pushes is
epoch 1030, "entry 31" in the spec is 1-based). Unit tests incl. new shape tests. Gp scenario: boot has no `stop_hook`;
step 8 inhibit (enqueue_zone, enqueue_zones, start_queue, full_cycle, main switch ON all refused, `inhibit_all_refused=1`);
9d main OFF -> `completed=0` + `stop_hook`; new step 10 a-d. Schedule phase 4 STOP via the main switch.

R2-3 was red before the fix (run with `stopping()` forced to false): after `gp.stop_all` + 300 ms, `enqueue_zone` +
`start_queue` left `B3:QUEUED(0) q=1` and `start_after_stop=0`; the main OFF then ON 300 ms later gave
`cycle_after_stop=0`. Cause confirmed (STOPPING lane loses queue / cycle starts). With the fix all of 10a-d are green.

Deviations:
- `delay_off` keeps its end-state check only: from idle the engine opens the valve ~0.1 s after ON (observed in the
  log), so "never opened" is false by design there. The never-opened latch is on `quick_off` (ON right after a stop,
  inside the switching delay) and on the inhibit step.
- History reload on the host is NOT tested: ESPHome's host preferences store the blob length in one byte, so the ~1.4 KB
  gp blob cannot round-trip through the host prefs file (it would also garble neighbouring entries). Only the cpp blob
  round trip covers it. The schedule phase 2/3 `hist=` lines were removed again.
- The `set_zone_max_run` assertion in `test_gp_codegen` uses 3300 (device config, 55 min), the safety fixture asserts
  the fixed `run_duration: 1s` (the fixture's value, not 2s).
- No gp.h reorder of the history save (a schedule mark syncs before gp saves the entry; a power cut loses at most the
  60 s batch): follow-up.

Measured: ESP32 pinned compile OK (`GP_SECRETS=example`), flash 1251675 bytes (68.2 %), RAM 126515 bytes (37.0 %); no
baseline was taken before the change, so no delta. Host scenario times (full run): gp layer 280 s, greenhouse 014 247 s,
schedule 56 s; before-times were not recorded separately. Minimum-ESPHome ESP32 and sim host compiles are left to CI.

## Follow-ups
- Main switch shows OFF briefly (~2 s) after ON in HA (no optimistic window); a C++ switch could fix it.
- Host preferences truncate blobs over 255 bytes (ESPHome `host`): split or shrink the gp blob if a host reload test is wanted.
- gp history is saved after the done-mark callbacks, so the schedule's `sync()` does not flush it (up to 60 s lost on a power cut).
- Open questions 1-4 of the spec still stand (author to confirm); implemented as recommended.
