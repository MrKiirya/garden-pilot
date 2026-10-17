# garden_schedule

Device-side watering schedules (MIT, engine-agnostic). A hub (`garden_schedule:`) reads the entities of up to 8
slots (`garden_schedule_slot:` list items) once per second and fires `on_run(zone_mask, multiplier_pct, slot)` when a
slot is due. The YAML routes that to the `gp_*` layer (`packages/greenhouse/schedule.yaml`: `gp.enqueue_zones` +
`gp.start_queue`), so the engine's safety (watchdog lockout, disabled zones, soil skip, service mode) applies
unchanged. The rules live in the pure header `schedule_core.h`, unit tested with a fake clock
(`tests/cpp/test_schedule.cpp`); the editor draft and the list texts of the on-device screens are the pure header
`schedule_ui.h` (`tests/cpp/test_schedule_ui.cpp`).

## Slot (Home Assistant entities, all `entity_category: config`, restored from flash)
For slot N of the greenhouse (`packages/greenhouse/schedule_slot.yaml`, one include per slot, 4 in the entry files, max 8):

| Entity | Default |
|---|---|
| `Greenhouse schedule N` (switch) | OFF |
| `Greenhouse schedule N start` (time) | from the include (`06:00`, `07:00`) |
| `Greenhouse schedule N Mon` ... `Sun` (7 switches) | ON (daily) |
| `Greenhouse schedule N zones` (text: `all` or bed numbers such as `1 3`) | `all` |
| `Greenhouse schedule N multiplier` (10-200 %, step 10) | 100 |

Per group: switch `Greenhouse schedules` (master, default ON; slots default OFF, so nothing waters until a slot is
enabled), text sensors `Greenhouse next run` (timestamp, ISO 8601 with offset, empty when none), `Greenhouse next run
text` (`Tue 06:00` / `--:--`) and `Greenhouse last schedule` (`06:00 #1 ran`, `ran (catch-up)`, `missed (90 min late)`,
`skipped: service mode`). A zone list that is invalid (only possible over the API) disables the slot with one warning;
zone numbers above the group's zone count are dropped with a warning.

## Rules
- **Clock:** no valid clock = nothing fires, nothing is marked. The clock is the first `time:` (Home Assistant or SNTP).
- **Run mark = (local day, start minute).** A slot counts as handled today only while its start is the one it ran
  with, so it runs once per start and local day. Crossing the start time in local time fires; the mark makes the
  repeated hour of a DST fall-back harmless (the clock crosses 01:30 twice, the mark blocks the second) and the
  skipped hour of a spring-forward is crossed in one step. **Moving a slot to a later time than now** (the screen's
  SAVE or Home Assistant) crosses the new start and runs it again the same day, also after a STOP settled the earlier
  run; the new run replaces the mark and the pending zones. Saving or re-enabling the same start never clears a mark.
  Moving a slot to a time that has already passed today does not run it (no crossing; only a boot or a clock jump
  catches it up, inside the window). Catch-up, `next_run` and `day_runs` use the same rule.
- **Catch-up:** the first valid tick after boot and every tick after a clock jump (more than 5 s off the monotonic
  timer) do not fire by crossing. A slot of today whose start has passed runs when it is at most `catch_up_window`
  late (default 60 min, `0s` = never, at most 6 h); otherwise it is logged as missed (warning) and marked for the day.
  Slots of earlier days are never caught up.
- **Done mark per zone:** a fired slot keeps the list of its zones that did not complete. A zone leaves the list when
  its queue run ends normally (`garden_zones` group -> `gp` `on_zone_finished` -> `garden_schedule.zone_done`, not when
  it was stopped), and the marks are written to flash immediately. After a power cut inside the window only the
  zones still in the list run again (an interrupted zone runs its full duration again). The list of a past day is
  dropped, and so is the list of a run whose start was moved meanwhile (INFO log): the new start is then evaluated like
  an unfired slot (window or missed), with the full zone mask.
  When a zone counts as done (`on_zone_finished completed`; pinned by the gp host scenario
  `tests/test_gp_layer.py`, step 9):

  | How the zone's run ended | Done? |
  |---|---|
  | queue run ended by itself | yes |
  | `gp.stop_all` (STOP button, also with `clear_queue`) within 3 s before the end | no; the STOP settles the slot instead (below), so the zone is not resumed |
  | manual / service run (`gp.run_zone`) | no (only queue runs count) |
  | Home Assistant turns off the "Greenhouse irrigation" main switch (= `gp.stop_all`) | no (a STOP, see below) |
  | engine watchdog ends a queue run | yes (no stop signal; not testable: scheduled runs are clamped below the limit) |
  | zone skipped by the engine (disabled, locked, wet soil) | it never runs, so it stays pending ("last schedule" still says `ran`) |
- **Pending zones resume only after a restart:** the first valid tick after boot re-fires the pending zones of today's
  slot (inside the window; outside it they are logged as missed). A later clock jump (HA / SNTP resync, a transient
  invalid clock) never re-fires them and never reports a slot that was already fired as missed.
- **A user STOP settles the slot** (decision 2026-10-11): a `gp.stop_all` (STOP button, Home Assistant, the zone switch
  turned off) or entering service mode drops today's pending zones of **every** slot (`garden_schedule.cancel_pending`,
  wired in `packages/greenhouse/schedule.yaml` to the group's `on_stop`), clears the engine queue (`gp.clear_queue`) and
  any held-back start, and "last schedule" shows `stopped` (not `missed`). The slot stays marked for the day: no catch-up,
  nothing runs again after a restart. Only zones cut by a power loss / reboot (no STOP) are re-run inside the window.
  Turning off the "Greenhouse irrigation" main switch in Home Assistant is a STOP too (its OFF action is `gp.stop_all`),
  also while nothing runs.
- **A slot firing during a manual full cycle waits for its end** (decision 2026-10-11): `gp` holds the slot's
  `gp.enqueue_zones` / `gp.start_queue` back (INFO log) because the engine would pick queued zones in the middle of the
  cycle. The cycle runs to its end, then (after 5 s without a running zone) the slot's zones run with the slot's
  multiplier, in zone order; the done marks follow those zones as usual. The same holds for any other non-queue run (a
  manual zone run). A zone that the cycle itself runs counts as done for the slot when it finishes, but it still runs
  again after the cycle (the slot's zone list is queued as a whole). If the cycle is stopped, the held-back zones are
  settled like any STOP (nothing runs). The held-back request lives in RAM: a power loss before it ran leaves the
  zones pending, so a restart inside the window runs them.
- **Skip:** `skip_if` is a list of `{condition, reason}`; the first true one turns a due slot into a skip (marked for the
  day). The greenhouse uses `gp.inhibited` (service mode). A rain sensor or a rain-delay entity adds an item.
- **Multiplier:** slot percent x global percent (`set_global_pct()`, fixed 100 today), clamped to 10-200 %. The `gp`
  layer cuts every run to the zone's run-duration maximum, so a multiplier can never exceed the watchdog limit.
- A slot moved to a later time while its earlier run is still watering fires again at the new time: the core replaces
  the mark and the pending mask, and `gp` does not queue a zone that is still queued or running, so only the zones that
  have finished by then (or were not part of the earlier run) water again.
- A zone that is already queued or running is not queued again. Zones the engine skips stay in its queue.
- The run marks are stored by slot NUMBER (1..8), so commenting out or reordering a slot include does not move them.
- A slot that is enabled, or moved to an earlier start, after its time passed today does not run while the device is up;
  a reboot inside the catch-up window runs it (a slot moved to a later start runs at that time, see the run mark).
- **Persistence:** blob version 2 under the key `garden_schedule2:<hub id>` holds, per slot number, the mark's day, start
  minute and pending zones. On a miss the version 1 blob (`garden_schedule:<hub id>`, no minute) is read once and
  migrated with the minute `0xFFFF` ("any start"), so the day of the OTA behaves as before (no extra run). ESPHome
  never reads a blob of another size (`esphome/components/esp32/preferences.cpp` `load()`: pending-save and NVS length
  checks; `host/preferences.h` `load()`: `vec.size() != len`), so the two layouts cannot be confused.
- A slot that is missed after a power cut outside the window is not run, but the engine queue (persisted by the
  engine) may still hold its unfinished zones: the next `gp.start_queue` (any `on_run`, or a manual start) runs them
  with the old durations. Clear the queue (`gp.stop_all` with `clear_queue`) if that is not wanted. The same applies
  to zones queued by hand and not started.
- The next-run timestamp of a start time inside a spring-forward gap (for example 02:30 on the change day) gets an
  offset for a local time that does not exist; the slot itself runs at 03:00. Cosmetic.

## Data for screens (C++ accessors on the hub)
`next_run()` -> `{slot index, local day, start minute}` over the next 8 days; `day_runs(offset)` -> that day's runs
sorted by start with `PENDING / FIRED / MISSED / SKIPPED`; `next_run_text()`. Durations for a timeline bar are not
computed here (they need the engine's per-zone durations).

The Schedule screens (task 030, `packages/greenhouse/lvgl_schedules.yaml`) read the hub through one-line accessors; the
texts and the editor model are pure functions in `schedule_ui.h` / `schedule_format.h`, unit tested:
- list (design D08): `slot_count()`, `zone_count()`, `row_time(i)` (`06:00` / `--:--`), `row_label(i, group, noun)`
  (`Greenhouse - all beds`, `- bed 2`, `- beds 1 3`, `- 4 beds`; `Slot N` for an OFF slot), `row_caption(i)` (`Every day
  - 5 min each`, `Not set - tap to set up`; past 30 characters the days become `5 days`), `row_status_text(i)` /
  `row_status_color(i)` (`OFF` dim, `DONE` dim, `ACTIVE` green, `SKIP` amber for skipped / missed / stopped, `NEXT` green,
  `LATER` for an enabled slot that is neither next nor done), `row_countdown(i)` (`in 3h 28m`, `in 2d 6h`, `in 45m`;
  time to the slot's next run, also for a slot done today; `-` for an OFF slot), `summary_label(group)` /
  `summary_countdown()` (the line under the header: `18:00 - Greenhouse`, `in 3h 28m`), `next_run_short()` (`06:00`, `Tue 06:00`, `--:--`: the Home "NEXT" label). The caption durations come from
  `set_zone_seconds(provider)`, set once from the YAML (the hub never reads `gp`);
- `changed_since(seen)`: true when anything a schedule screen shows changed (the poller guard; `seen = 0` forces a
  redraw);
- editor (design D09): `begin_edit(i)` copies slot `i` from its entities into a RAM draft, `draft()` is the draft (hour /
  minute with step 5, days, zones, factor 10-200 % in steps of 10, ON), `edit_title()` (`Schedule 2`), `can_save()`
  (enabled needs a day and a zone), `save_edit()` writes **only the fields the user changed** to the slot entities (the ones
  Home Assistant edits: switch `turn_on/off`, time / text / number `make_call()`), so nothing is written per tap and a
  Home Assistant change made meanwhile survives; it logs one INFO line. `cancel_edit()` drops the draft. An index out
  of range logs a WARN and does nothing.

The screen shows the first 4 slots in include order (no paging); slots 5-8 are edited in Home Assistant. There is no
master switch and no row toggle on the screen: enabling a slot is the editor's ON switch plus SAVE.

## Hub options
`id`, `time_id` (default: first `time:`), `catch_up_window`, `zone_group` (gp group id: the default zone count counts only its `gp_zone` entries), `zone_count` (default: that count, else
16), `master_switch_id`, `next_run_id`, `next_run_text_id`, `last_result_id`, `skip_if`, `on_run`. Action:
`garden_schedule.zone_done: {id, zone}` (0-based zone).

## Not verified on a device
A scheduled run with Home Assistant off and SNTP as the only clock, a power cut inside/outside the catch-up window,
and the clock being valid right after an OTA reboot are not verified on real hardware (the emulator and the unit tests
cover the logic). DST is covered by unit tests only.
