# 019 — Review (round 1)

Verdict: CHANGES_REQUESTED

Range reviewed: `git diff 8440aea 15ca53e` (7 commits on `task/019-schedules`, stacked on 018).

## Checks run
(in the `gp-dev-014` devcontainer)
- `script/lint` → `esphome config OK: garden-pilot.yaml` (yamllint clean)
- `script/test-cpp` → `63 test cases, 0 failed checks` (all 23 `test_schedule` cases ok)
- `UV_OFFLINE=1 GP_REQUIRE_CXX=1 script/test` → TEST_RESULT_PLACEHOLDER

## Acceptance criteria
- [x] `script/test-cpp` → `test_schedule` all pass — re-run here, 63/63.
- [x] `uv run pytest -m unit` → all pass — part of the full run above.
- [x] `script/lint` → clean; config OK — re-run here.
- [x] `script/test` all pass incl. config rows and the host scenario — re-run here (see above). Wall time before/after
      was **not** recorded (Implementation notes say so) although the box is ticked.
- [ ] `GP_ESPHOME=minimum script/compile` (ESP32) and the sim compile — **not run** (Implementation notes: "Not done:
      `GP_ESPHOME=minimum` ESP32 compile ... sim ESP32/host compile outside the emulator run"), but the box is ticked.
      Pinned ESP32 compile and the minimum `--only-generate` codegen row were done. Left to CI.
- [x] `git grep -e 'garden_zones\.' -e 'sprinkler\.' -- packages/greenhouse/schedule*.yaml components/garden_schedule*`
      → no hits (checked; `test_no_engine_and_no_cron_in_schedules` enforces it).
- [x] `git grep 'on_time:' -- packages` → no cron trigger (checked).
- [x] Emulator checks E1-E4 reported (not re-run by the reviewer; E5 not done, allowed).
- [ ] CI green — not visible to the reviewer.
- [x] Docs (SPEC §4, §8, §9 item 11, §11; CLAUDE.md; READMEs in sync; component README) — checked.
- [x] Implementation notes state what ran on the device (nothing; said explicitly).

## What was verified (strict points from the brief)
- **DST:** spring-forward crosses the gap in one continuous step (`dst_spring_gap`); fall-back repeated hour blocked by
  the day mark (`dst_fall_back_no_double`). A fall-back at midnight (local day going backwards) is also harmless: the
  crossing loop does not run and a "tomorrow" mark is kept (`> today + 1` only is cleared). OK.
- **Invalid clock / first valid tick / sync jumps / midnight / millis wrap:** core logic and tests OK
  (`invalid_clock`, `boot_*`, `sync_jump_*`, `midnight_crossing`, `mono_wraps`; wrapper uses `uint32_t` differences).
- **Multiplier vs bed max and watchdog:** `gp.enqueue_zones` → `enqueue_zone` → `clamp_` to the zone's
  `max_run_seconds` (55 min ≤ `max_on_time` 60 min), WARN when cut. OK.
- **Service mode:** `skip_if: gp.inhibited` → `mark_skipped` clears pending, marked for the day; `gp.enqueue_zones` and
  `gp.start_queue` also refuse while inhibited (defence in depth). OK.
- **Flash writes:** `save_()` + `global_preferences->sync()` only when a persisted field changes: one per fire / miss
  and one per completed zone, i.e. about `slots x (1 + zones)` NVS commits per day (≈ 8/day with 2 slots x 3 zones).
  `ESPPreferenceObject::save` skips unchanged blobs, so repeated catch-up events do not write. Wear is negligible. OK.
- **Principle 2:** `on_run` = `gp.enqueue_zones` + `gp.start_queue` only; hub has no engine symbol. OK.
- **Entities:** 11 per slot (enable, start, 7 days, zones, multiplier; all `entity_category: config`, restored) + 4 per
  group = 26 new HA entities with 2 slots. Matches the human decisions.
- **018 guarantees:** `enqueue_zones` respects inhibit and the clamp; `stop_all` behaviour unchanged (only records
  `stop_ms_`); the adapted 018 tests only exclude the new hook / names, nothing weakened.
- **Host scenario:** three program runs on one prefs dir really prove the per-zone mark (zone 1 never re-runs in phase
  2, nothing in phase 3). Meaningful.

## Findings
### Required
1. `components/garden_schedule/schedule_core.h:390-396` (+ `components/gp/gp.h:223-224`) — **a user STOP (or entering
   service mode) does not cancel the slot: the stopped zones stay `pending` and run again later.** `stop_all` makes
   `completed = false`, so the stopped zone and every zone the STOP removed from the queue keep their pending bits. A
   reboot inside the catch-up window (OTA, restart button, power blip) then re-queues and *starts* them: watering
   resumes unattended after the user explicitly stopped it (or after a valve-test session that ended with a reboot).
   The human decision covers *power cuts mid-slot*, not a deliberate STOP; the README sentence "not when it was
   stopped" makes the re-run sound intended but no test and no human decision backs it. Direction: a STOP / service
   mode entry settles today's pending zones (e.g. a `gp` group `on_stop` hook or a `completed`-independent "settled"
   flag → `garden_schedule.cancel_pending` / `zone_done`), result text "stopped"; keep the power-cut path as is.
   Add a cpp case (`stop_clears_pending`) and a host or gp scenario step (STOP mid-slot → restart → nothing runs).
   If the human prefers the current behaviour, get it written into "Human decisions" and test it explicitly instead.
2. `components/garden_schedule/schedule_core.h:378-402` — **pending zones are re-fired on every discontinuous tick, not
   only after a restart.** A clock jump > 5 s while the device stays up (HA/SNTP resync after a long Wi-Fi outage, a
   loop stall, host suspend) with `last_fired_day == today && pending != 0` and `late <= window` emits a second `Fire`
   ("ran (catch-up)" published again, `gp.start_queue` called again). Only `gp.enqueue_zones`' "already queued or
   running" check prevents a double run; zones that are pending but not queued (engine-skipped for wet soil /
   disabled / locked, or stopped — see 1.) are queued and started again. Same spot with `late > window`: a run that
   is **still in progress** is reported as `missed (N min late)` (WARN, `last_result`, `day_runs` = MISSED) and its
   pending cleared. Neither the task's Decision 3 ("not fired today" slots only) nor the human decision (restart after
   a power cut) asks for this. Direction: resume pending zones only on the first valid tick after boot (a `booted_`
   / "resume done" flag in the core); later discontinuities treat a fired slot as handled. Add cpp cases:
   fire → `jump` +20 min with pending → no fire, no missed; fire → `jump` +90 min with pending → no missed, pending
   kept.
3. `tests/` — **the 018 hook's `completed` semantics are untested.** `on_zone_finished(zone, completed)` decides
   what is "done"; only the `true` path is exercised (host scenario zone 1). Nothing checks that `stop_all` within
   the 3 s window gives `false`, that a manual / service run gives `false`, or what a watchdog trip gives (today: a
   watchdog-ended queue run is `completed = true`, i.e. done — fine, but undocumented). Direction: extend
   `tests/configs/gp_layer_sim.yaml` (or a small new scenario) to log `zone/completed` from `on_zone_finished` for:
   normal queue completion, `stop_all` mid-run, manual `run_zone`; document the watchdog case in
   `components/gp/README.md` and the schedule README.
4. `tasks/019-schedules.md` acceptance criteria — the boxes for the minimum ESP32 / sim compile and for the
   `script/test` wall-time record are ticked but the Implementation notes say they were not done. Untick them (left to
   CI) or run them and record the results.

### Suggestions
1. `components/garden_zones/sprinkler.cpp:740` via `gp.start_queue` — a slot that fires while a **manual full cycle**
   runs calls `start_from_queue()`, which disables auto-advance: the rest of the cycle is dropped silently and the
   scheduled zones run instead. Listed as a follow-up already; please surface it to the human (it is a "silent skip")
   and at least log a WARN in `gp.start_queue` when it converts a running cycle. The manual single-zone case
   (`manual_run_active_ = false`) should be stated in the notes too (D2 was "to verify").
2. `components/garden_schedule/garden_schedule.h:86` / `__init__.py:138` — marks are persisted by registration
   **index**, not by slot number. Removing or reordering a slot include moves today's mark / pending zones to another
   slot. Index the blob by `slot number - 1` (already unique, 1..8).
3. `components/garden_schedule/__init__.py:125` — the default `zone_count` counts **all** `gp_zone` entries; with a
   second group (lawn) the greenhouse zone list would accept numbers of the other group. Count per group, or set
   `zone_count` explicitly in `schedule.yaml`.
4. `packages/greenhouse/schedule.yaml:27` — no explicit `time_id: ha_time` (the task's shape-test row asked for it); the
   hub takes the first `time:` entry. Set it explicitly so a future SNTP / RTC entry order cannot change the clock.
5. Catch-up of a slot that was enabled or moved to an earlier start *after* its time passed: no fire while running,
   but a reboot within 60 min fires it (Decision 3 allows it). Worth one README line ("enabling a slot whose time
   passed today does not run it, unless the device restarts within the window").
6. `components/gp/gp.h:223` — the stop detection is a 3 s time window on `millis()`; a `stop_ms_` from 49.7 days ago
   matches again for 3 s after the wrap (negligible). If finding 1 adds an explicit stop signal, use a per-zone flag
   instead of the time window.
7. "Greenhouse next run text" and "Greenhouse last schedule" are screen/diagnostic data; consider `entity_category:
   diagnostic` (26 new entities is noisy in HA).
8. Engine-skipped zones (wet soil, disabled, locked) stay pending and "last schedule" says `ran`; already a
   follow-up — after finding 2 they would only matter on a restart.

Not blocking (legacy / out of scope): none.
