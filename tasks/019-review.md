# 019 — Review (rounds 1 and 2)

Verdict (round 2): APPROVE — round 1 verdict was CHANGES_REQUESTED; see "Round 2" at the end.

Range reviewed: `git diff 8440aea 15ca53e` (7 commits on `task/019-schedules`, stacked on 018). The partial draft of an
earlier attempt was re-verified point by point; this file replaces it.

## Checks run
(in the `gp-dev-014` devcontainer)
- `script/lint` → `esphome config OK: garden-pilot.yaml` (yamllint clean)
- `script/test-cpp` → `63 test cases, 0 failed checks` (all 23 `test_schedule` cases ok)
- `UV_OFFLINE=1 GP_REQUIRE_CXX=1 script/test` → `744 passed in 978.18s (0:16:18)`, exit 0 (no skips)
- `git diff 8440aea 15ca53e | grep` for IPs, local paths, SSIDs, passwords → only `127.0.0.1:6053` (emulator API, fine).

## Acceptance criteria
- [x] `script/test-cpp` → `test_schedule` all pass — re-run here, 63/63.
- [x] `uv run pytest -m unit` → all pass — part of the full run above.
- [x] `script/lint` → clean; config OK — re-run here.
- [ ] `script/test` all pass incl. config rows and host scenario — the run passes (see above), but "wall time before/after
      recorded" is ticked while the Implementation notes say it was not done (only "17:05" after). Required item 6.
- [ ] `GP_ESPHOME=minimum script/compile` (ESP32) and the `garden-pilot-sim.yaml` compiles — **not run** (Implementation
      notes: "Not done: `GP_ESPHOME=minimum` ESP32 compile ... sim ESP32/host compile"), but the box is ticked. Pinned
      ESP32 compile (+20 kB flash, +2.9 kB RAM) and the minimum `--only-generate` codegen row were done. Required item 6.
- [x] `git grep -e 'garden_zones\.' -e 'sprinkler\.' -- packages/greenhouse/schedule*.yaml components/garden_schedule*`
      → no hits (checked; `test_no_engine_and_no_cron_in_schedules` enforces it).
- [x] `git grep 'on_time:' -- packages` → no cron trigger for watering (checked).
- [x] Emulator checks E1-E4 reported (not re-run by the reviewer; E5 not done, allowed).
- [ ] CI green — not visible to the reviewer.
- [ ] Docs — SPEC §4/§8/§9/§11, CLAUDE.md, both READMEs (in sync) and the component README are updated, but the `gp`
      contract README is not (required item 4).
- [x] Implementation notes state what ran on the device (nothing; said explicitly).

## What was verified (strict points from the brief)
- **DST:** spring-forward crosses the gap in one continuous step (`dst_spring_gap`); the repeated fall-back hour is
  blocked by the day mark (`dst_fall_back_no_double`). A fall-back at local midnight is harmless too: the crossing loop
  does not run backwards, and a "tomorrow" mark is kept (only `> today + 1` is cleared). OK.
- **Invalid clock at boot / first valid tick / sync jumps / midnight / millis wrap:** core and tests OK (`invalid_clock`,
  `boot_*`, `sync_jump_*`, `midnight_crossing`, `mono_wraps`); the wrapper uses `uint32_t` differences; an invalid tick
  resets `have_prev_`, so the next valid tick follows the boot rules. Exception: pending zones on a discontinuous tick
  while running (required 2).
- **Multiplier vs bed max and watchdog:** `gp.enqueue_zones` → `enqueue_zone` → `clamp_` to the engine's
  `max_run_seconds` (55 min bed max <= `max_on_time` 60 min), WARN when cut; 200 % can't exceed the watchdog. OK.
- **Service mode / locked / disabled zones:** `skip_if: gp.inhibited` → `mark_skipped` (pending cleared, marked for the
  day, "skipped: service mode"); `gp.enqueue_zones` and `gp.start_queue` also refuse while inhibited. Locked / disabled /
  wet zones go through the engine queue's `skip_reason`, unchanged. OK. (After a STOP or a service-mode entry the pending
  zones stay, see required 1.)
- **Flash writes:** `save_()` + `global_preferences->sync()` run only on a fire, a miss, a future-mark clear or a zone done
  (in practice about `slots x (1 + zones)` commits per day, about 8/day with 2 slots x 3 zones; NVS skips unchanged blobs). Negligible
  wear. Note: `sync()` also flushes other components' pending preferences early. That's harmless.
- **Principle 2:** `on_run` = `gp.enqueue_zones` + `gp.start_queue` only; the hub has no engine symbol (codegen test
  checks it). OK.
- **Entities:** 11 per slot (enable, start, 7 days, zones, multiplier; all `entity_category: config`, restored) + 4 per
  group = 26 new HA entities with 2 slots. Matches the human decisions (5 → 11 per slot because days became switches).
- **018 guarantees:** `stop_all` only additionally records `stop_ms_`; inhibit, clamp and history are unchanged. The
  adapted 018 tests (`test_gp_yaml_shape`, `test_entity_names_kept`, `test_device_uses_groups_form`,
  `test_substitutions_resolve`) only exclude the new hook / names / file and aren't weakened.
- **Host scenario:** three program runs on one prefs dir prove the per-zone mark (zone 1 completed → never re-runs in
  phase 2; the interrupted zone 2 re-runs; nothing in phase 3; disabled slot 2 never runs). It's a meaningful check.

## Findings
### Required
1. `components/garden_schedule/schedule_core.h:390-396`, `components/gp/gp.h:223-224`,
   `packages/greenhouse/lvgl_page.yaml:166` — **a user STOP (or entering service mode) does not settle the slot: the
   stopped zone and the zones still queued stay `pending` and run again.**
   - Home STOP is `gp.stop_all` without `clear_queue`, so the queue keeps the scheduled zones and `completed = false`
     keeps their pending bits.
   - A reboot inside the catch-up window (OTA right after the STOP, restart button, power blip) re-fires the pending
     mask, and `gp.start_queue` starts the kept queue. Watering resumes unattended after the user explicitly stopped it.
     With required 2 it can also resume without a reboot, on a clock jump.
   - The human decision covers a *power cut* mid-slot, not a deliberate STOP. The README's "not when it was stopped"
     makes the re-run look intended, but no human decision or test backs it.
   - Direction: a STOP / service-mode entry settles today's pending zones of every slot. For example a `gp` group
     `on_stop` trigger → `garden_schedule.cancel_pending` (result text "stopped"); keep the power-cut path as is. Add a cpp
     case (`stop_clears_pending`) and a host / gp scenario step (STOP mid-slot → restart inside the window → nothing
     runs).
   - If the human prefers the current behaviour, write it into "Human decisions" and the README rules and test it
     explicitly instead.
2. `components/garden_schedule/schedule_core.h:378-402` — **pending zones are re-fired on every discontinuous tick, not
   only after a restart.**
   - A clock jump > 5 s while the device stays up hits the `last_fired_day == today && pending != 0` branch. Causes: an
     HA / SNTP resync after a long outage, a manual time change in the emulator, host suspend, or a transient invalid
     clock that resets `have_prev_`.
   - Inside the window it emits a second `Fire`: "ran (catch-up)" is published again and `gp.start_queue` is called
     again. Only `gp.enqueue_zones`' "already queued or running" check prevents a double run. Zones that are pending but
     not queued are queued and started again: engine-skipped zones, or zones removed by a STOP with `clear_queue` or by
     the valve-test entry.
   - Past the window, a run **still in progress** is reported as `missed (N min late)` (WARN, `last_result`, `day_runs`
     = MISSED) and its pending is cleared.
   - Neither Decision 3 ("not fired today" slots only) nor the human decision (restart after a power cut) asks for this.
     `restart_reruns_only_pending_zones` only checks the jump *after* pending reached 0, so the path is untested.
   - Direction: resume pending zones only on the first valid tick after boot (a `resumed_` flag in the core, set after
     the first valid tick). Later discontinuities treat a fired slot as handled. cpp cases: fire → `jump` +20 min with
     pending → no fire, no missed; fire → `jump` +90 min with pending → no missed, pending kept; `invalid()` then valid
     again without a reboot → no resume.
3. `tests/` — **the semantics of `on_zone_finished(zone, completed)` are untested where they decide "done" vs
   "pending".**
   - Only `completed = true` is exercised (host scenario, zone 1). Nothing checks that `stop_all` within the 3 s window
     gives `false`, or that a manual / service run gives `false`.
   - Nothing checks what a watchdog-ended run gives. Today a watchdog-ended queue run is `completed = true`, i.e.
     "done", so a faulty valve is not re-run. That's sensible, but undocumented.
   - Nothing checks what an HA turn-off of the engine's "Greenhouse irrigation" switch gives (no `stop_ms_`, so
     "done").
   - Direction: extend `tests/configs/gp_layer_sim.yaml` (or a small new scenario) to log `zone/completed` from
     `on_zone_finished` for a normal queue completion, `stop_all` mid-run and a manual `gp.run_zone`. Document the
     watchdog and engine-switch cases (see 4).
4. `components/gp/README.md` (not touched by the diff) — **the gp contract doesn't list what this task added to it.**
   Missing: `gp.enqueue_zones {mask, pct}` (no re-queue of queued/running zones, clamp), condition `gp.inhibited`, and
   the group trigger `on_zone_finished (zone, completed)` with the exact meaning of `completed`. CLAUDE.md names
   that README as the contract that screens, schedules and HA rely on (principle 2), and §64-77 lists every other
   action/condition. Add them there.
5. `components/gp/gp.h:150-158` (`start_queue`) → `components/garden_zones/sprinkler.cpp:732-741` — **a slot that fires
   during a manual full cycle silently drops the rest of the cycle** (D2 was "to verify"; the notes say "not exercised").
   - During a cycle `queue_enabled()` is false, so `start_from_queue()` goes on to `set_auto_advance(false)`. The current
     zone finishes, the scheduled zones run, and the remaining cycle zones never run, with no log.
   - The brief requires no silent skips. Direction, as a minimum: a WARN in `GpGroup::start_queue` / `enqueue_zones` when a
     non-queue run is active, plus a README / SPEC line. Better: let the human pick between this and "queue only, start
     when the lane is idle", and add a scenario step for the chosen behaviour.
6. `tasks/019-schedules.md` acceptance criteria — two boxes are ticked but not done (Implementation notes say so):
   - the minimum ESP32 / sim compile;
   - the `script/test` wall time before/after.

   Untick them (leaving them to CI), or run them and record the results.

### Suggestions
1. `components/garden_schedule/garden_schedule.h:86-87`, `246-247` — marks are persisted by registration **index**, not by
   slot number. Commenting out or reordering a slot include moves today's mark / pending zones to another slot. Index
   the blob by `slot number - 1` (already unique, 1..8).
2. `components/garden_schedule/__init__.py:125` — the default `zone_count` counts **all** `gp_zone` entries. With a
   second group (lawn), the greenhouse zone list would accept the other group's zone numbers. Count per group, or set
   `zone_count` explicitly in `schedule.yaml`.
3. `packages/greenhouse/schedule.yaml:27` — no explicit `time_id: ha_time` (the task's shape-test row asked for it), so
   the hub takes the first `time:` entry. Set it explicitly so a future SNTP / RTC entry order can't change the clock.
4. A slot enabled, or moved to an earlier start, *after* its time passed today doesn't run while the device is up, but a
   reboot within 60 min runs it (Decision 3 allows this). Worth one README line.
5. After a power cut outside the window the slot is "missed", but the 014-persisted engine queue still holds its
   unfinished zones. The next `gp.start_queue` runs them, with yesterday's durations if that's tomorrow's slot. Likewise
   any `on_run` starts zones the user queued by hand and didn't start. Document it, or dequeue a missed slot's pending
   zones.
6. `components/gp/gp.h:223` — stop detection is a 3 s window on `millis()`; a `stop_ms_` from ~49.7 days earlier
   matches again for 3 s after the wrap (negligible). If required 1 adds an explicit stop signal, use a per-zone flag
   instead.
7. "Greenhouse next run text" and "Greenhouse last schedule" are screen / diagnostic data. Consider `entity_category:
   diagnostic` (26 new entities is noisy in HA). HA rendering of the empty `device_class: timestamp` text sensor is
   still to verify (listed).
8. `components/garden_schedule/garden_schedule.h:262-271` — a next run in a spring-forward gap (e.g. 02:30 on the
   change day) gets an ISO offset from `recalc_timestamp_local()` on a non-existent local time; the core fires it at
   03:00. Cosmetic: one line in the README.
9. Engine-skipped zones (wet soil, disabled, locked) stay pending while "last schedule" says `ran`. This is already a
   follow-up; after required 2 they only matter on a restart.

Not blocking (legacy / out of scope): none.

## Round 2

Verdict: **APPROVE**

Range reviewed: `git diff 155e6ec HEAD` (commits `edaca80..d4c7c6d`). I also checked the whole range `8440aea..HEAD` against the
two human decisions of 2026-10-11 (task file, "Human decisions" items 6 and 7).

### Checks run
(in the `gp-dev-014` devcontainer, repo at `/workspaces/garden-pilot`)
- `script/lint` → `esphome config OK: garden-pilot.yaml` (yamllint clean)
- `script/test-cpp` → `74 test cases, 0 failed checks` (incl. the new `test_gp_deferred_start` and 4 new `test_schedule` cases)
- `UV_OFFLINE=1 GP_REQUIRE_CXX=1 script/test` → `749 passed in 1327.28s (0:22:07)`, exit 0, no skips.
  `test_garden_zones.py::test_safety_host_scenario` passed here; I didn't see the 018 CI flake.
- ESP32 compile was not re-run by the reviewer (the implementer reports the pinned compile OK). `test_schedule_codegen`
  runs for the pinned and minimum versions and asserts `CancelPendingAction`, `StopTrigger`, `ClearQueueAction`, so the new
  schema is accepted by both.
- Hygiene grep over the round 2 diff (IPs, local paths, SSIDs, passwords) → no hits.

### Round 1 required items
1. STOP / service mode settles the slot — **resolved** (human decision 6). `GpGroup::stop_all` and `set_inhibit(true)`
   fire the new `on_stop`. `packages/greenhouse/gp.yaml` → hook script `gp_gh_stopped`, extended in `schedule.yaml` with
   `garden_schedule.cancel_pending` + `gp.clear_queue`. `Scheduler::stop_pending()` keeps the day mark, so there is no
   catch-up and no second run today. It saves at once.
   - Tests: cpp `stop_settles_the_slot_and_nothing_resumes_after_a_restart`, `stop_settles_every_slot_with_pending_zones`,
     `a_power_cut_without_a_stop_still_resumes_the_pending_zones`, `a_stopped_slot_does_not_fire_again_today_but_fires_tomorrow`.
   - Host scenario: phase 4 (STOP mid-slot → idle, queue 0, `#2 stopped`) and phase 5 (restart inside the window → nothing
     runs).
   - Boot safety: I checked that no `gp.stop_all` / `gp.inhibit` can fire at boot. `gp_service_mode` is a non-restored
     global, and the valve-test scripts only run from the page's `on_load` / `on_unload`. The gp_zone switch stops only
     when it is on. So the power-cut resume path is intact (scenario phase 2 still passes).
2. Resume only after boot — resolved in round 1 fixes, unchanged here.
3. `on_zone_finished` semantics tested — resolved in round 1 fixes (gp scenario step 9), comment updated.
4. gp contract README — **resolved**. The README now covers `gp.enqueue_zones`, `gp.inhibited`, `on_zone_finished` with
   the exact `completed` table, plus the new `gp.clear_queue`, `on_stop` and the deferred start.
5. Slot during a manual cycle — **resolved** (human decision 7). `gp` holds back `enqueue_zones` and `start_queue` while a
   non-queue run is active (`start_must_wait`, pure `components/gp/deferred_start.h`). It applies them 5 s after the last
   zone stopped.
   - I checked the cycle gap in the engine: `Sprinkler::fsm_transition_from_valve_run_()` moves `active_req_` to the next
     valve in the same step, so `active_zones()` is never empty between two cycle zones. The pre-check can't slip through
     a gap.
   - Host scenario 5(b): the cycle beds run >= 55 s each undisturbed, then the slot's beds run at 10 %, starting >= 4 s
     after the cycle.
   - Scenario 5(a): a STOP cancels a held-back start and enqueue.
6. Acceptance boxes — **resolved**: the wall-time and minimum-compile boxes are now unticked, with the reason in the notes.

### Implementer's round 2 deviations (assessment)
- **Holding back `enqueue_zones` as well as `start_queue`:** needed, and a good catch. In groups mode the engine picks
  queued zones at the next zone change even mid-cycle, so deferring only the start would still cut the cycle. Accepted.
- **Generalised to every `gp.start_queue` and to any non-queue run, not only schedules and full cycles:** this goes
  beyond the literal decision. It now also covers a manual single-zone run, a cycle started from the engine main switch,
  and a user pressing start-queue during a manual cycle. It is consistent and documented in the gp README ("Never cuts a
  cycle short"), and safer than the old behaviour. Accepted. Listed below for the human to confirm.
- **A cycle zone finishing after the slot fired counts as done, and the zone runs again after the cycle:** the zone was
  watered, so the done mark is truthful. The extra run is the slot's own run at its percentage, documented in the
  component README. Accepted.
- **Held-back request in RAM only:** the pending mask is persisted, so a power loss before the deferred run resumes those
  zones inside the window. Matches decision 1 ("only power-loss-cut zones re-run"). Accepted.
- **HA turning off the engine's main switch is not a STOP:** documented (component README rule and table, gp README).
  - Effect: the remaining scheduled zones stay pending and stay **queued** (`group.h` `shutdown()` keeps the queue). A
    restart inside the window resumes them.
  - Also, the next `gp.start_queue` (for example the next slot) runs those leftover zones too.
  - The decision says "a user STOP (`gp.stop_all` from any caller)"; this entity is outside gp, so it is a gap, not a
    violation. Human decision listed below. Not blocking.
- **`gp.enqueue_zone` (single) not held back:** this is a pre-018 / 018 behaviour of a manual action, not a schedule path.
  Accepted as a follow-up (suggestion 2).

### Findings
#### Required
None.

#### Suggestions
1. `packages/greenhouse/schedule.yaml:78-83` (`!extend gp_gh_stopped`) — with schedules on, every STOP clears the **whole** engine queue. That
   includes zones the user queued by hand, and the gp_zone switch's `stop_all(false)` and the HA `gp_stop_all`. So
   `gp.stop_all`'s `clear_queue: false` has no effect on the greenhouse. The task notes this ("a config without schedules
   keeps the old STOP behaviour"), but the gp README's `gp.stop_all` row doesn't. Add one sentence there, or dequeue only
   the zones in the settled pending masks (that needs the hub to return them). See human decision B.
2. `components/gp/gp.h:96` (`enqueue_zone`) — a single `gp.enqueue_zone` / HA `gp_enqueue_zone` during a manual cycle is
   still picked by the engine mid-cycle. Follow-up: route it through the same hold-back, or document it in the gp README
   row.
3. `components/gp/gp.h:194-201` (`set_inhibit`) — no scenario step covers "entering service mode settles the slot" on its
   own. The valve-test entry calls `stop_all` first, so it is covered in practice. A one-line host step
   (`gp.inhibit: true` mid-slot → `last` ends with `stopped`) would pin the `set_inhibit` path in case the valve test
   changes.
4. `components/gp/gp.h:312-318` (`run_blocks_queue_`) — `start_must_wait` uses `busy`, so a cycle that the user **pauses** through an engine
   entity (`running` false while paused) would let the deferred start fire after 5 s and cut the paused cycle. gp has no
   pause action today, so this is theoretical. If a pause entity is ever exposed, treat `paused` as busy.
5. Carried over from round 1, still open and non-blocking: suggestions 1-3 and 5-9 (round 1 suggestion 4 is fixed). Note
   for suggestion 5: a STOP now clears the queue, so only the power-cut-outside-the-window and HA-main-switch paths still
   leave stale queued zones.

### For the human (decisions to confirm, not blocking)
- **A.** The hold-back applies to **every** `gp.start_queue` / `gp.enqueue_zones` while any non-queue run is active
  (manual zone run, a cycle from HA's main switch, a start-queue press during a manual cycle). It is not limited to
  schedules firing during a full cycle. OK?
- **B.** With schedules on, any STOP (Home STOP button, HA `gp_stop_all`, turning off a zone switch, valve test) also
  clears the manually queued zones, not only the schedule's. OK, or should only the schedule's zones be dequeued?
- **C.** Turning off the engine main switch "Greenhouse irrigation" in HA is **not** treated as a STOP: today's remaining
  scheduled zones stay queued and pending. They run after a restart inside the catch-up window, or with the next queue
  start. Accept as documented, or follow up (for example hide the main switch from HA, or have gp detect an external
  shutdown)?

### Acceptance criteria (re-checked)
- [x] `script/test-cpp` — 74/74 here.
- [x] `pytest -m unit` — part of the full run.
- [x] `script/lint` — clean here.
- [x] `script/test` — 749 passed here.
- [ ] wall time before/after — honestly unticked (22:07 here vs 16:18 in round 1; the longer host scenario explains it).
- [ ] minimum ESP32 / sim compile — unticked, left to CI (minimum codegen row green here).
- [x] no `garden_zones.` / `sprinkler.` in schedule files; no `on_time:` cron — unchanged, the tests enforce it.
- [ ] CI green — not visible to the reviewer.
- [x] Docs — SPEC §4, CLAUDE.md gotcha, component README and gp README updated. The top-level READMEs don't describe STOP
      or cycle behaviour, so no sync was needed.
- [x] Hardware statement — "Not verified on hardware: nothing of round 2".
