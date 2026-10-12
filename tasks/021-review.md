# 021 — Review (round 1)

Verdict: APPROVE

Range: `git diff task/020-timeline-flake HEAD` (0cfba84..1560ab5), branch `task/021-review-follow-ups`.

## Checks run
(All checks ran in the devcontainer `gp-dev-014` with `UV_OFFLINE=1 GP_REQUIRE_CXX=1`, HEAD 1560ab5.)
- `script/test` → `763 passed in 1342.17s (0:22:22)`, no skips
- `script/test-cpp` → `78 test cases, 0 failed checks`
- `script/lint` → clean, `esphome config OK: garden-pilot.yaml`
- ESP32 compile not re-run (the caller allowed skipping it; the implementer reports pinned compile OK, flash 68.2 %).

## Safety review (focus items)
- **Main switch at boot:** `restore_mode: DISABLED`. I checked pinned `switch.cpp::get_initial_state_with_restore_mode()`:
  the DISABLED mask returns `{}`, so `TemplateSwitch::setup()` runs neither action. No `gp.stop_all` at boot, so the
  019 power-cut resume is intact. The scenario pins it: `stop_hook` must not appear before `s1_a`.
- **Service mode:** ON → `gp.full_cycle`, which checks `inhibited_` first. The step 8 latch (`gpt_r3_seen`) plus
  relay 1-3 and `queue_length == 0` prove that no start path opens a valve, and that the switch is back OFF.
  `optimistic: false`, so the state comes from the model only.
- **HA entity stability:** the name "Greenhouse irrigation" and the `switch` domain are unchanged, so the object id
  and the ESPHome unique id (`<mac>-switch-greenhouse_irrigation`) stay the same. Only the YAML id changes, and that is
  internal. `test_entity_names_kept` passes. Still needs a check on the device after OTA (hardware note).
- **OFF = full STOP:** `stop_all` cancels held-back work (`cancel_deferred_` now clears `deferred_cycle_` too), shuts
  the engine down and fires `on_stop`. Tested in 9d (`completed=0`, `stop_hook`) and in schedule phase 4.
- **Hold-back while stopping:** only the *start* paths (`start_queue`, `full_cycle`) check `stopping()`. Enqueues pass
  through (10b shows that a queued zone survives the STOPPING→IDLE transition). When the deferred start fires, it
  re-enters `start_queue()` / `full_cycle()`. Those re-check inhibit and `stopping()`, so a lane that is still
  stopping simply re-defers: no lost start, and no start that bypasses the inhibit. `stop_all`, `set_inhibit(true)`
  and `clear_queue` cancel it. The R2-3 drop was shown red before the fix (notes: `start_after_stop=0`,
  `cycle_after_stop=0`).
- **`enqueue_zone` hold-back:** this reuses `run_blocks_queue_(false)` and `MAX_DEFERRED`. When applied, it goes
  through `enqueue_zone()` again (inhibit, range and clamp re-checked). `enqueue_zones` now calls `queue_now_` directly,
  so there is no double deferral. 10d covers it.
- **Deviations:**
  - `delay_off` keeps its end-state check: accepted. From idle the valve opens about 0.1 s after ON by design, so a
    latch would be wrong there. The latch is on `quick_off` and on the inhibit step, which are the safety-relevant
    windows.
  - The host does not reload history: the cause is confirmed. Pinned `host/preferences.h` `save()`/`load()` return
    false for `len > 255`, and the gp blob is about 1.4 KB. The cpp full-ring memcpy round trip covers the layout.
    The NVS load path on the ESP32 is still untested (follow-up).

## Acceptance criteria
- [x] `script/test-cpp` all pass incl. 4 new cases — 78 cases, 0 failed (limits x2, stopping, full-ring blob).
- [x] `uv run pytest -m unit` — included in the `script/test` run, all passed.
- [x] `script/lint` clean, `esphome config` OK (the sim config rows are in `script/test`, passed with SDL available).
- [x] `script/test` all pass, no skips — 763 passed. Wall times recorded "after" only (gp 280 s, greenhouse 247 s,
      schedule 56 s); the "before" times were not recorded, so the ≤ +1 min delta is not demonstrated. Full run 22:22
      versus the reported baseline of about 25 min, so there is no visible regression.
- [x] R2-3 step red before the fix — stated in the notes with the observed log.
- [x] `git grep gh_zones_main_switch -- . ':!tasks'` → only the negative assertion in `tests/test_service.py:79`.
      Taken literally, `git grep main_switch -- packages` hits `packages/greenhouse/gp.yaml:49`
      (`gp_greenhouse_main_switch`, the planner-chosen id). The intent (no engine `main_switch:` key) is met and is
      also asserted by the shape and codegen tests.
- [x] `garden_zones.` / `gh_zones` allow-list unchanged — `test_no_engine_outside_adapter` passes.
- [ ] ESP32 pinned compile + flash/RAM delta — compile reported OK by the implementer (not re-run here); no baseline,
      so no delta. Minimum ESP32 and sim host compile left to CI (open, as the task allows).
- [x] Docs updated: gp README, schedule README, CLAUDE.md (layout row + convention), SPEC §4.1. README.md /
      README.ru.md do not mention the main switch.
- [ ] CI green — not verified by this review.
- [x] Notes state "not verified on a real device" plus the breadboard check list.

## Findings
### Required
None.

### Suggestions
1. `components/gp/gp.h` `start_queue()` / `full_cycle()` deferral branches: a held-back start is a single slot, and the
   last request wins. A deferred `full_cycle` (HA ON right after OFF) is silently replaced by a later deferred
   `start_queue` (a schedule slot in the same ~2 s stopping window), and the reverse also happens. Only an INFO
   "deferred" line is logged. This is unlikely and not unsafe (it runs less, not more), but it contradicts "no start
   lost without a trace". Direction: log a WARN when one pending kind replaces the other, or keep both flags and run
   the cycle (which covers all zones) when either is set.
2. `tests/configs/gp_layer_sim.yaml` step 10: no step shows that a STOP cancels a start held back *while stopping*
   (OFF, ON after 300 ms, OFF again → no relay within about 10 s). The code path (`cancel_deferred_` clears
   `deferred_cycle_`) is correct by inspection and shared with the 019-tested cancel. A short sub-step would pin it
   with the `gpt_r3_seen`-style latch on relay 1 and no new program run.
3. `packages/greenhouse/gp.yaml:46` comment "an ON that gp refuses (service mode, watchdog)": `gp.full_cycle` refuses
   only on inhibit. A watchdog lock is handled by the engine, which skips locked zones. The visible result is the
   same (the switch falls back to OFF), but the comment and Decision 3 overstate what gp does. Reword the comment, or
   add a `watchdog_tripped` refusal with a WARN.
4. Task notes, deviation "history reload": the text says the large blob "would also garble neighbouring entries". In
   the pinned version `host/preferences.h` rejects `len > 255` in `save()`/`load()` (it returns false) before the
   file writer's `uint8_t len` is reached, so nothing is garbled. Correct the note so a later task does not chase a
   corruption bug.
5. `components/gp/gp.h` `run_blocks_queue_()` sets `block_stopping_` as a side effect only for `block_reason_()`.
   Returning the reason (or passing `stopping` into the log call) would avoid hidden state in a predicate.
   Cosmetic.

## Human decisions (pending, not blocking)
- **019 question C / task OQ1:** "Greenhouse irrigation" OFF is a full gp STOP (settles today's slots; the schedule
  hook clears the queue). This is implemented safely and tested. If the author rejects it, drop Decision 1 and keep
  the rest.
- **OQ3:** OFF while idle also settles pending slots and clears the manual queue. Note: HA automations that send
  `switch.turn_off` defensively (e.g. "turn off irrigation at sunset") will now cancel a scheduled slot's pending
  resume for the day. The author should know this before confirming.
- **OQ2:** a zone added with "+Q" or HA `gp_enqueue_zone` during a manual run or cycle is not shown as queued until
  5 s after the run ends.
- Cosmetic: the main switch shows OFF in HA for about 2 s after ON (switching delay), and also while a start is held
  back after a STOP (up to about 5-7 s), before the cycle actually starts.

## Follow-ups (from the implementer, agreed)
- ESP32 NVS reload of the gp history blob is not covered by any automated check (the host limit is 255 bytes); verify
  on the breadboard or shrink / split the blob.
- gp history is saved after the done-mark callbacks (up to 60 s lost on a power cut).
- Optional C++ `GpGroupSwitch` with an optimistic window.
