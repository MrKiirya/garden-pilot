# 013 — Review (round 1)

Verdict: CHANGES_REQUESTED

Reviewed: uncommitted working tree on `task/013-watchdog-and-soil-skip` on top of 140f93a (013 spec), stacked on
`task/012-groups-and-lanes`. `tasks/014-switch-to-garden-zones.md` (another task) was ignored.

## Checks run
All in the dev container `gp-dev-012` (podman, this checkout mounted).
- `script/lint` → `esphome config OK: garden-pilot.yaml`, yamllint clean.
- `script/test-cpp` → `24 test cases, 0 failed checks` (`-Wall -Wextra -Werror`).
- `UV_OFFLINE=1 GP_REQUIRE_CXX=1 script/test` → `598 passed, 1 skipped in 311.85s` (the skip is `test_sim_ui`, no
  Xvfb in this container). Safety host scenario and 012 host scenario passed in this run.
- Flake reproduction: 12 parallel runs of the 012 host program
  (`.esphome/gz-groups-host/2026.9.1/.../program`, prefs under `.esphome/review-013/pN`) → 1 of 12 runs logged a
  same-lane overlap (see Required 1).
- `git diff task/012-groups-and-lanes --stat -- garden-pilot.yaml garden-pilot-sim.yaml packages hardware .github script
  tests/configs/garden_zones_sim.yaml tests/configs/garden_zones_groups_sim.yaml tests/configs/garden_zone_entry.yaml`
  → empty.
- `git grep 'GZ-PATCH-BEGIN' -- components` → ids `includes`, `queue-api`, `queue-persist`, `queue-skip-disabled`,
  `manual-run`, `groups`, `lanes`, `zone-skip` (plus the `<id>` placeholder in the file headers), each with a
  `PATCHES.md` section.
- `git grep -i preference -- 'components/garden_zones/watchdog*'` → no hits.

## Acceptance criteria
- [x] `script/test-cpp` builds with `-Wall -Wextra -Werror`, all 24 cases pass — verified in `gp-dev-012`.
- [x] `pytest -m unit` → all pass (part of the full run).
- [x] `GP_REQUIRE_CXX=1 pytest tests/test_garden_zones.py` → all pass, `minimum` rows pass without xfail (full run).
- [x] `script/lint` → clean.
- [x] `script/test` → all pass. However the 012 host scenario is flaky (Required 1), so "all pass" holds only per run.
- [x] Protected-paths diff against the 012 branch → empty.
- [x] GZ-PATCH ids exactly as listed, each documented.
- [x] No `preference` in `watchdog*`.
- [x] README documents keys, defaults, ranges, validation, trip/lockout/reset, pump session, soil scope and policy;
      SPEC §4 and §9 item 7 updated, nothing else. The documented `pump_idle_timeout` rule is wrong though
      (Required 2).
- [ ] CI on the PR green — not verifiable here (no PR / push); still open in the task file, correctly unchecked.
- [x] Implementation notes say nothing ran on a real device and list the scenario results.

## What was checked and is fine
- The watchdog polls the raw `switch->state` in its own `loop()` (never disabled), independent of the sprinkler; the
  limits have no "disable" value (1 s .. 4 h, idle 1 s .. 5 min); one watchdog per group is always generated.
- Forced off = `lane->shutdown(false)` then raw `turn_off()`; lockout re-enforced on every rising edge (also for the
  HA zone switch path); stuck relays retried once per 1000 ms; trip fired once; latches not persisted; `reset()`
  restarts timers of actuators that are still on.
- All timing arithmetic is `uint32_t` wrap-safe subtraction; limits (max 4 h = 14.4e6 ms, `max_age` 24 h) fit.
- `setup()` turns every monitored actuator off at `DATA` priority (after the `HARDWARE` switches restore).
- Restore-mode rule (`ALWAYS_OFF` / `RESTORE_DEFAULT_OFF` only) for valves and the pump.
- Soil: NaN, no value and stale readings are "unavailable"; default `water`; equal value waters; manual runs ignore
  the rule; the queue and cycle hooks run only without a pending request and outside manual runs. The first valve of
  a cycle goes through the same branch (`fsm_transition_from_shutdown_` → `load_next_valve_run_request_`), and the
  scenario's step 8h exercises that path (one-valve lanes in `beds`).
- Host scenario: durations measured from the state log with a 100 ms lower-bound relaxation, plus the trip lines,
  `tripped` condition, queue contents and the turn-off counter of the welded relay; the global "no valve longer than
  limit + 1 s, pump at most 6 s" check is there. The timing proof is adequate; the strict `>` boundary is covered in
  C++.
- Public hygiene: no real names, IPs, secrets or local paths in the diff.

## Findings
### Required
1. **Flake in `test_groups_host_scenario` is a real same-lane overlap in the (stock-derived) sprinkler, reproduced.**
   `components/garden_zones/sprinkler.cpp` `fsm_transition_from_valve_run_()` (around line 1640-1680) +
   `SprinklerValveOperator::loop()` (line 91-107). When a valve's run ends, the controller timer `TIMER_SM`
   (`set_timeout`, fires at `>= run_duration`, started *before* `vo.start()`) runs the transition, which does **not**
   stop the finishing operator (it only does so when the timer is still active) and calls `start_valve_()` for the
   next valve on the second operator. The old valve is switched off only when its operator's `loop()` sees
   `now - start > start_delay + run_duration` (strict, using the loop start time) — i.e. in the next
   `Sprinkler::loop()`. ESPHome runs the scheduler (timeouts and intervals) before component loops, so for up to one
   main-loop iteration **two valves of one lane are on together** (`max_parallel` violated; with a pump, the pump
   feeds two valves). The 200 ms state interval occasionally samples inside that window. Reproduced: 12 parallel
   runs of the 012 host program, run 9 logged `state=0000011` in step 4 (solo, `max_parallel: 1`, valves 6 and 7
   both on → `assert not any(_on(s, 6, 7) ...)` → exactly the reported "assert not True") and `state=0011100` in
   step 5 (lawn zones 0 and 2, same lane). Load makes the window longer, which matches "seen once in a loaded full
   run". This is not a harness/port/prefs interaction: each run uses its own prefs dir and no network port.
   Fix direction: a small GZ-PATCH region (e.g. `lane-handover`) that, when the timer finished, stops/kills the
   finishing operator's valve (raw `valve_off_` / `kill_` without dropping a shared pump that the next valve needs)
   before `start_valve_()` of the next request; add a C++ or host check that never samples two valves of one lane on
   (e.g. a check on every state change from the switches' `on_turn_on` instead of a 200 ms poll). This belongs to
   012's code; the human may prefer fixing it on the 012 branch, but it must be fixed before 014 puts lanes on a
   device, and CI stays intermittently red until then. Note: upstream `sprinkler` (current device) has the same
   millisecond overlap — mention in SPEC §3 limitations if it is not fixed for the stock engine.
2. **`pump_idle_timeout` validation uses the wrong start delay** — `components/garden_zones/groups.py:286-291`,
   `safety_rules.py:64-72`, README "Validation" bullet, test `idle-too-short` and `test_safety_rules_pump`.
   In the fork `set_valve_start_delay` (`pump_start_valve_delay`) sets `start_delay_is_valve_delay_ = true`, and
   `SprinklerValveOperator::start()` then calls `pump_on_()` first: **`pump_start_valve_delay` is the "pump on, no
   valve" phase**, not `pump_start_pump_delay` (which opens the valve first). (The task's Context bullet has the same
   inversion.) So `pump_start_valve_delay: 15s` with the default `pump_idle_timeout: 10s` validates, and every normal
   run trips `pump_idle` and locks the whole group. Fix: `pump_idle_timeout >= max(pump_start_valve_delay,
   pump_stop_pump_delay) + 2 s`; update README/test cases (the `idle-too-short` case must use
   `pump_start_valve_delay`), and add a scenario-free config-error case proving it.
3. **Zone-limit validation misses `pump_stop_valve_delay`** — `groups.py:256-260` (`_validate_safety`). With
   `pump_stop_valve_delay` the operator turns the pump off first and the valve stays open for the stop delay
   (`SprinklerValveOperator::stop()`, `stop_delay_is_valve_delay_`), so the valve's real on-time is
   `run + pump_start_pump_delay + pump_stop_valve_delay`. A config can pass validation and trip `max_on_time` (zone
   lockout) on every normal run. Fix: add `pump_stop_valve_delay` to the delay term (and, strictly, only
   `pump_start_pump_delay` extends the valve's on-time at the start; keeping both start keys is conservative and fine);
   unit + config-error check.
4. **Per-zone `max_on_time` override has no check** (human decision 2026-10-08 explicitly keeps it overridable per
   zone). Nothing asserts that a zone-level `max_on_time` reaches `GroupWatchdog::add_zone()` or the validation (all
   test zones use the group value). Add e.g. a zone with `max_on_time: 5s` to the codegen check (`add_zone(..., 5000)`)
   and a config-error case where only the zone override makes the run too long / the pump limit too short.

### Suggestions
1. `tests/test_garden_zones.py` `_SAFETY_ERRORS`: several expected strings (`max_on_time`, `pump_max_on_time`,
   `pump_idle_timeout`, `nope`, `maybe`) also appear in ESPHome's echo of the failing config, so they pass for any
   validation error. Assert on the rule's own wording (`exceeds max_on_time`, `is below max_on_time of`,
   `must be at least`, `Couldn't find ID 'nope'`, the `one_of` message).
2. `components/garden_zones/watchdog.h:74-87` / `watchdog_core.h:63-66`: three heap allocations per group per main
   loop iteration (`zones_on`, `rising`, the returned `commands`). Reuse member buffers to avoid heap churn on the
   ESP32 at loop rate.
3. `groups.py:247-252` `_restore_mode()` returns `None` when the switch is not found under `switch:` and the rule is
   then skipped silently (fail-open). Raise an error (or at least warn) when the resolved mode cannot be found.
4. Soil staleness is based on the last state callback: sensors that publish only on change (`homeassistant`
   platform, `delta` / `throttle` filters) look stale after `max_age` while the soil is stable, which with
   `when_unavailable: skip` stops watering. Add a README note (use `heartbeat` or a larger `max_age`). The bed ADC
   sensors publish every 25 s, so 014 is not affected.
5. `soil_skip.h:243` / `watchdog.h` log rate limit: 32-bit ages wrap after ~49.7 days, so a soil sensor dead for
   exactly ~49.7 days looks fresh again for `max_age`. Very unlikely; `millis_64()` (if available in both versions) or
   a "seen within the last wrap" flag would close it. Not blocking.
6. `skip_reason()` logs the `RUN_UNAVAILABLE` WARN on every check (noted by the implementer); rate-limit it per zone.

### Follow-ups (not blocking, outside scope)
- Clean up `.esphome/review-013/` (reproduction prefs and logs from this review; build-cache dir, git-ignored).

---

# 013 — Review (round 2)

Verdict: CHANGES_REQUESTED

Reviewed: uncommitted working tree on top of 140f93a (round-1 fixes included), `tasks/014-*` ignored.

## Checks run (round 2, `gp-dev-012`)
- `script/lint` → `esphome config OK: garden-pilot.yaml`, yamllint clean.
- `script/test-cpp` → `24 test cases, 0 failed checks`.
- `UV_OFFLINE=1 GP_REQUIRE_CXX=1 script/test` → `607 passed, 1 skipped in 342.89s` (the skip is `test_sim_ui`, no Xvfb).
- Read through `valve-handover` against the stock paths: interrupted run, manual run, `fsm_request_` from the
  `STARTING` branch, `valve_open_delay` (switching delay) branch, `valve_overlap`, shutdown, pause/resume, pump stop
  delays, and the pump start delays (see Required R2-1).

## Round-1 items
- Required 1 (same-lane overlap): fixed for configs **without pump start delays** (`valve-handover`). The overlap
  checks are deterministic and do fail without the patch: the counters run in the valves' own `on_state`, and in
  the stock code the next valve's `turn_on()` (and its callback) runs in `fsm_transition_from_valve_run_` while the
  finished valve is still on (it goes off only in the next `Sprinkler::loop()`). So `plain ... overlaps=0` and
  `handover starts=4 overlaps=0` would read 3 without the patch. `ovl` (`valve_overlap: 1s`) asserts `overlaps >= 3`,
  so the deliberate overlap stays (human decision respected: handover gated on `!valve_overlap_`). A regression
  with pump start delays is in R2-1.
- Required 2 (`pump_idle_timeout` uses `pump_start_valve_delay`): fixed in `groups.py:291-296`, `safety_rules.py`,
  README, the `idle-too-short` case and the task Context.
- Required 3 (`pump_stop_valve_delay` in the zone limit): fixed (`groups.py:262-268`, case `stop-valve-delay`).
- Required 4 (per-zone `max_on_time`): fixed. `pair` zone 2 `max_on_time: 5s`, codegen asserts
  `pair_watchdog->add_zone(..., 5000)` (`tests/test_garden_zones.py:1119`), plus `zone-override-too-short` and
  `pump-below-zone-override`.
- Suggestions 1-6: all addressed. Error strings are now the rules' own wording. `watchdog_core.h` / `watchdog.h`
  reuse member buffers. `_restore_mode()` raises instead of failing open. README covers soil staleness and
  `heartbeat`. Stale readings are dropped in `loop()`. The unavailable WARN is limited to once per 60 s per zone.
- Pause/resume, shutdown, manual run (interrupt path: `timer_was_active` → no handover), `valve_open_delay` (else
  branch, untouched), `valve_overlap` and the pump *stop* delays: no regression found. Old operators still reach
  `stop()` / `kill_()` normally, and `pump_off_()` still goes through `set_pump_state()`'s in-use check, so a shared
  pump stays on for the next valve. Side effect: when the 1 s manual-selection timer from the `STARTING` branch ends
  the transition, the current valve is now switched off before the new one opens. In stock both stay open, so this
  is an improvement.

## Findings
### Required
1. **`valve-handover` breaks lanes that use a pump start delay** (`components/garden_zones/sprinkler.cpp:1692-1697`
   with `SprinklerValveOperator::handover()` at `:193-203`). The run timer `TIMER_SM` is set to `run_duration` only
   (`:1686-1690`, `:1641-1645`). The operator, however, stays `ACTIVE` until `start_delay_ + run_duration_`
   (`loop()`, `:101-105`). In stock this works because the old valve closes when the next operator leaves
   `STARTING` and opens its valve, `start_delay` later. Both groups-form keys are exposed (`groups.py:156-165`), and
   with either of them `handover()` now closes the finished valve at the timer, `start_delay` early:
   - `pump_start_valve_delay: D`: every zone except the last waters `run - D` instead of `run` (zero when `D >= run`),
     and the shared pump runs `D` with no valve open at every handover.
   - `pump_start_pump_delay: D`: the next operator sees the shared pump already on, so it waits `D` before
     `valve_on_()`. The pump runs `D` with no valve open, which is exactly the dead-head / water-hammer situation the
     human wants to avoid. `pump_idle_timeout` validation does not include `pump_start_pump_delay`, so e.g.
     `pump_start_pump_delay: 15s` with the default 10 s idle timeout validates and then trips `pump_idle` on the
     first handover, locking the group.
   No test config uses any pump delay (`git grep pump_start tests/configs` → empty), so nothing catches this.
   Fix direction: apply `handover()` only when the next operator starts its valve immediately, i.e.
   `start_delay_ == 0` or there is no pump. In the pump-start-delay case, keep stock timing and close the old valve
   in the same step where the new operator calls `run_()`, for example from the `STARTING` → `ACTIVE` edge of the
   new operator, or by having `Sprinkler::loop()` stop the old operator before the new one runs. Add a host scenario
   (a pair lane with a pump and `pump_start_pump_delay` / `pump_start_valve_delay`) that asserts: each valve is open
   at least `run - 100 ms`; no two valves are on together (state-callback counter); and the pump is never on with
   no valve open longer than about one loop between zones.

### Suggestions
1. `handover()` returns early when `stop_delay_is_valve_delay_` (`pump_stop_valve_delay`) and a pump is set, so that
   config keeps the stock one-iteration overlap. In stock `stop()` the valve closes at once whenever the pump is
   still in use (`:183-186`), and with a shared pump the next valve keeps it in use, so the handover could also close
   it in that case. Otherwise list this residual case in PATCHES.md / SPEC §3.
2. PATCHES.md `valve-handover` "Re-port notes" should say why the gate is `!timer_was_active` (interrupt path stops
   operators itself) and that the TIMER_SM duration excludes `start_delay` (the reason for R2-1).

### Follow-ups (not blocking)
- Clean up `.esphome/review-013/` (reproduction prefs/logs from round 1 and `r2-test.log` from this round; git-ignored
  build cache).
- This is the last review round: R2-1 goes to the human per the workflow (fix in 013, or restrict `valve-handover`
  to `start_delay_ == 0` now and track the pump-start-delay handover as a follow-up before 014 uses pump delays).

# 013 — Review (round 3, verification)

Verdict: APPROVE

Reviewed: `git diff 140f93a 7ad3c0a` (round 3 started on the uncommitted tree; the main session then committed it without
code changes, verified: `sprinkler.h` / `.cpp` diff against `task/012-groups-and-lanes` is the same at `7ad3c0a`).
Checked against the task's "Review round 2 fixes" and "Human decision 2026-10-10" sections.

## Checks run (round 3, `gp-dev-012`)
- `script/lint` → `esphome config OK: garden-pilot.yaml`, yamllint clean.
- `script/test-cpp` → `26 test cases, 0 failed checks`.
- `UV_OFFLINE=1 GP_REQUIRE_CXX=1 script/test` → `4 failed, 613 passed, 1 skipped in 353.64s`. All 4 failures are
  `test_public_hygiene` (`test_no_private_ip_addresses`, `test_no_local_absolute_paths`) on `tasks/018-gp-layer.md` and
  `tasks/019-schedules.md`, untracked files of other tasks that were in the working tree during the run and are not part
  of 013 (no longer in the checkout). Every 013 and 012 check passed, including all host scenarios; the skip is
  `test_sim_ui` (no Xvfb).

## Round-2 items and human decisions
- **R2-1 (handover with pump start delays): resolved by removal.** `sprinkler.h` / `.cpp` against
  `task/012-groups-and-lanes` now differ only by the documented `zone-skip` region (`skip_cycle_valves_`, the
  skip-check hook, the queue-pop lambda inside the existing `queue-skip-disabled` region, `<functional>` in `includes`).
  No `handover()` or `valve-handover` remains in code, PATCHES.md, README or SPEC; the README and SPEC §3 describe the
  accepted stock overlap (decision (a)).
- **Pump scenario** (`tests/configs/garden_zones_pump_sim.yaml`, `test_pump_start_delays_host_scenario`): groups `pa`
  (`pump_start_pump_delay: 1s`) and `vb` (`pump_start_valve_delay: 1s`), events timestamped in the switches' own
  `on_state`. It asserts each valve is open 2.9-4.5 s (full 3 s run), one pump session, no gap between v1 off and v2
  on above 100 ms, pump at most 1.3 s before the first valve and 0.3 s after the last. The round-1 handover would fail
  it twice (valve open `run - D` = 2 s, and a 1 s pump-without-valve gap), so it proves the point.
- **Overlap bounds:** `plain` < 100 ms and `pair` `max_ms < 100` measured in callbacks; `ovl` (`valve_overlap: 1s`)
  900-1300 ms, so the deliberate overlap still exists.
- **`never` (decision (b)):** `_limit` accepts only the literal string `never` (case-insensitive); anything else goes
  through `positive_time_period_milliseconds` + `Range(1 s, 30 days)`, so `0s` is rejected (`max-on-time-zero`) and
  `31d` too (`max-on-time-over-30-days`). Defaults remain 60 min / 2 h / 10 s. Each disabled limit logs a
  `watchdog disabled by config` WARN in `watchdog.h` `dump_config`. Lockout and the other limits stay active (C++ case
  `a disabled zone limit (never) does not trip, other zones still do`). CLAUDE.md principle 4 and the gotcha line are
  reworded.
- **30-day maximum:** sound. 30 d = 2,592,000,000 ms. That is below the uint32 wrap (4,294,967,295 ms, about 49.7 d), so
  `now - since` in `OnTimer::on_for` trips before it can wrap. It is also below the `DISABLED = UINT32_MAX` sentinel,
  so a real limit can never collide with it. It is documented in `safety_rules.py` (comment), the README table and
  notes, and the task file.
- **012 assertion change:** only steps 3-5 of `test_groups_host_scenario` changed (`not any(both on)` →
  `_brief_overlap_only`). `garden_zones_groups_sim.yaml` is untouched. See suggestion 1.

## Findings
### Required
None.

### Suggestions
1. `_brief_overlap_only` (`tests/test_garden_zones.py:901`) limits the number of consecutive both-on entries, not how
   long they last. The 012 state log is a 200 ms poll that logs only on change, so a long overlap with no other valve
   change in between would still be a single entry and pass. The duration bound is covered in the 013 scenarios
   (`pair max_ms < 100`, overlap `plain` < 100 ms, pump-scenario gap check), so this does not block. Optional fix:
   log `millis()` with each 012 state line and bound the both-on entry to under about 250 ms, or say in the docstring
   that the duration is checked by the 013 scenarios.
2. The pump scenario merges a pump off/on within 50 ms into one session (the stock handover can toggle a shared pump
   within one loop pass). That is stock behaviour and harmless for a relay that cannot react that fast, but it is worth
   one line in README "Accepted by design" so whoever wires a contactor or VFD knows about it.

### Follow-ups (not blocking)
- `tasks/018-gp-layer.md` / `tasks/019-schedules.md` (other tasks) failed `test_public_hygiene` (private IP pattern,
  local absolute path) while they were in the working tree. Fix them before they are committed.
- Clean up `.esphome/review-013/` (git-ignored; now also holds `r3-test.log`).
- Nothing was verified on a real device (host scenarios only).
