# 010 — Review (round 1)

Verdict: APPROVE

Scope: working tree of `task/010-boot-and-valve-test` against `task/009-generic-screens` (untracked `tasks/011-*`
ignored). No blocking issues. Suggestions below are non-blocking. The emulator and device items are still open for the
author.

## Checks run
- `script/lint` → yamllint clean; `esphome config OK: garden-pilot.yaml` (ESPHome 2026.9.1).
- `GP_REQUIRE_SDL=1 script/test` (with a stub `sdl2-config` on `PATH`) → `404 passed in 26.30s`.
- Minimum version, offline: `uv run --no-project --with esphome==2026.6.3 esphome config` on both `garden-pilot.yaml`
  and `garden-pilot-sim.yaml` (staged copies with `secrets.example.yaml`) → both exit 0.
- Normalized `esphome config` dump of the device, 009 (`git archive`) vs. the working tree, split into top-level
  sections: `api`, `binary_sensor`, `button`, `captive_portal`, `display`, `logger`, `number`, `ota`, `sensor`, `spi`,
  `sprinkler`, `switch`, `text_sensor`, `time`, `touchscreen` are byte-identical. Only `esphome` (on_boot),
  `globals`, `interval`, `lvgl`, `script`, `substitutions` and `wifi` (on_connect) differ. The sorted list of `name:` values
  is identical (26 each), so no Home Assistant entity was added, renamed or removed.
- Read the sprinkler C++ in both 2026.9.1 (`.venv`) and 2026.6.3 (uv cache): `start_single_valve`, `shutdown`,
  `fsm_*` and `SprinklerValveOperator::stop` are the same in the parts this task relies on.

## Safety walk-through (state flow, end to end)
Facts from the sprinkler source (both versions):
- `shutdown()` resets `active_req_` and `next_req_`, kills every valve operator immediately (there is no pump and no
  stop delay here) and enters `STOPPING` for 1 s.
- `start_single_valve()` returns without doing anything in standby or when the multiplier is 0. Otherwise it sets
  `next_req_` with the explicit `run_duration`. The multiplier is not applied to an explicit duration.
- In `STOPPING`, `fsm_kick_` does nothing, so the request is picked up only after STOPPING → IDLE (1 s) and then
  `manual_selection_delay` (default 1 s).

What follows for each path in the brief:
- **TEST tap:** the guard starts at T. The valve opens at about T+2 s. The guard shuts down at T+10, before the
  sprinkler's own `run_duration` ends at T+12. Each tap therefore gives at most 10 s from the tap, and about 8 s of real
  opening (see Suggestion 1). Nothing relies on `run_duration` alone.
- **Re-tap or a second row** (`gp_valve_test_start` restart, guard restart): the first action is `shutdown`, which
  kills the open valve at once. Only one valve is ever on. The early return for `valve_number == active_valve()`
  can't fire, because `active_req_` was just reset and the operator is IDLE. Re-tapping every <10 s keeps a bed
  watering in pulses. Each pulse is bounded and needs a deliberate tap; `on_click` fires on release, so a stuck touch
  doesn't repeat it.
- **STOP, EXIT or page unload during the guard delay or the 2 s start window:** the guard is stopped and `shutdown`
  resets `next_req_`, so a pending valve never opens.
- **10 min session:** it is restarted only by a test start. `gp_service_exit` stops its own caller, which is safe:
  `stop_complex` zeroes `num_running_`, so `play_next_` does nothing. Then `lvgl.page.show: setup_page` →
  `on_unload` → `gp_service_leave` (a second shutdown, harmless).
- **1 s poller vs. a test start:** the whole start runs in one main-loop pass, so the guard is already running when
  `next_req_` is set. The poller can't interleave and can't kill the test's own valve. After the guard's shutdown,
  `active_valve()` is empty (operators IDLE), so there is no false WARN.
  - External starts during a guard window are not blocked, but the guard's shutdown at T+10 bounds them too
    (single valve, full cycle and zone switch all go through `active_req_` / `next_req_`, and `shutdown` resets both).
  - Outside the guard: a running valve is caught within 1 s. A pending `next_req_` is caught about 1 s after it opens.
    The queue is cleared.
- **Reboot:** `gp_service_mode` has `restore_value: false`, the first page is `boot_page` (so the valve page's
  `on_load` can't fire at boot), and the actuators keep their safe defaults (`test_gpio_actuators_are_safe` /
  `test_board_relays_are_safe` green).
- **Boot sequence:** it only sets globals, updates labels and shows `home_page`. It has no actuator action (test
  enforced). `on_boot` priority -100 runs after LVGL setup. No page uses `lvgl.page.next` / `previous`, so the boot and
  valve pages can only be reached by an explicit `page.show`.
- Only `sprinkler.start_single_valve` / `shutdown` / `clear_queued_valves` on `gh_sprinkler` are used. There is no
  `switch.*` and no `board_relay_*`.

## Acceptance criteria
- [ ] Step 0 a–d recorded for both versions. Not run (no emulator or devcontainer in the implementer's session; stated
  in Implementation notes). Covered statically by me: (a) `run_duration` validates on both versions and the C++ honours
  it as an explicit, unmultiplied override; (b) `spinner` with `arc_color` / `indicator` validates on 2026.6.3. (c) and
  (d) are runtime items and remain for the author's emulator run.
- [x] `script/lint`, `script/test` all pass (404 passed). Re-run by me; minimum version also validates.
- [ ] CI green. Not verifiable here (no push); for the main session.
- [x] Normalized config diff vs. 009: only the new pages, scripts, globals, interval, `wifi.on_connect`, `on_boot` and
  the SERVICE tile; `switch` / `sprinkler` / `number` / entity names unchanged. Re-derived independently (see Checks).
- [x] Docs updated: SPEC §8 (boot screen, valve test / service mode), CLAUDE.md (package order, boot rule, "Valve test
  limit" gotcha), design/README.md Pages.
- [ ] Emulator (author). Open. Note Suggestion 1: expect about 8 s of open time and a countdown that stops near 2 s.
- [ ] Device (author). Open.
- [x] Implementer states that no emulator/device item was checked.

## Findings
### Required
None.

### Suggestions
1. `packages/greenhouse/lvgl_valve_test.yaml:50-56` — effective open time is about 8 s, not 10 s.
   - Because `shutdown` always precedes `start_single_valve`, the sprinkler is in `STOPPING` (1 s) and then waits
     `manual_selection_delay` (1 s) before opening. The guard, started at the tap, closes the valve about 8 s after it
     opens. The "OPEN - N s" countdown (from 10) is cut off at about 2 s.
   - This is safe, since it is shorter. But the caption "Opens one valve for 10 s" and the emulator criterion "closed
     after 10 s" will look like a bug to the author.
   - Direction: document it in the file header and SPEC §8 ("up to 10 s from the tap"). Don't extend the guard to
     compensate without the author's decision.
2. `packages/greenhouse/lvgl_valve_test.yaml:219` — the caption hard-codes "10 s" while the limit is a substitution.
   Interpolate `${valve_test_max_time}` (as the boot caption does), so lowering the limit keeps the text truthful.
3. `tests/test_service.py:116-119` — the poller check is string-based.
   - It asserts that `script.is_running` and `gp_valve_test_guard` appear somewhere in the interval. Dropping the
     `not:` (which would make the poller kill every test valve) or moving the shutdown out of the gated `if` would
     still pass.
   - Assert the structure instead: the first `if` has `and` containing `not: {script.is_running: gp_valve_test_guard}`
     and the `gp_service_mode` lambda, and `sprinkler.shutdown` / `clear_queued_valves` sit in that `if`'s `then`.
4. `tests/test_service.py:122-129` — `test_leaving_the_page_ends_service_mode` doesn't assert
   `{"script.stop": "gp_service_session"}` in `gp_service_leave`. Without it, a stale session would call
   `gp_service_exit` 10 min later and force `setup_page` from wherever the user is. Add the assertion.
5. `packages/greenhouse/lvgl_valve_test.yaml:120-176` — the three status blocks repeat the same `snprintf` lambda. This
   is acceptable under the existing pattern (`sprinkler_lvgl_status.yaml`); fold it into a loop or helper when stage 8
   generalizes the rows.
6. `packages/lvgl/page_boot.yaml:16` — `gp_boot_done` is set but read nowhere yet. This is fine if task 011 (the
   screensaver) uses it; otherwise drop it then.

### Follow-ups (not this task)
- `start_single_valve` leaves `queue_enable` off after a test (`start_full_cycle` re-enables auto-advance, the queue
  stays off). This is existing SPEC §3 behaviour, but now a Setup action triggers it too. Consider mentioning it in the
  SPEC §8 service-mode note, or restoring it in stage 8's `gp_*` layer.
- Stage 8: move the valve test behind `gp_*` and block HA starts before they open a valve (already listed in the task).
- Open questions 1–2 of the task (is 10 s enough for motorised valves; service mode exposed to HA) remain for the
  author.
