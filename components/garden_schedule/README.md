# garden_schedule

Device-side watering schedules (MIT, engine-agnostic). A hub (`garden_schedule:`) reads the entities of up to 8
slots (`garden_schedule_slot:` list items) once per second and fires `on_run(zone_mask, multiplier_pct, slot)` when a
slot is due. The YAML routes that to the `gp_*` layer (`packages/greenhouse/schedule.yaml`: `gp.enqueue_zones` +
`gp.start_queue`), so the engine's safety (watchdog lockout, disabled zones, soil skip, service mode) applies
unchanged. The rules live in the pure header `schedule_core.h`, unit tested with a fake clock
(`tests/cpp/test_schedule.cpp`).

## Slot (Home Assistant entities, all `entity_category: config`, restored from flash)
For slot N of the greenhouse (`packages/greenhouse/schedule_slot.yaml`, one include per slot, 2 by default, max 8):

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
- **One run per slot per local day.** Crossing the start time in local time fires; the day mark makes the repeated hour
  of a DST fall-back harmless and the skipped hour of a spring-forward is crossed in one step. Editing the start time
  after today's run does not run it again today.
- **Catch-up:** the first valid tick after boot and every tick after a clock jump (more than 5 s off the monotonic
  timer) do not fire by crossing. A slot of today whose start has passed runs when it is at most `catch_up_window`
  late (default 60 min, `0s` = never, at most 6 h); otherwise it is logged as missed (warning) and marked for the day.
  Slots of earlier days are never caught up.
- **Done mark per zone:** a fired slot keeps the list of its zones that did not complete. A zone leaves the list when
  its queue run ends normally (`garden_zones` group -> `gp` `on_zone_finished` -> `garden_schedule.zone_done`, not when
  it was stopped), and the marks are written to flash immediately. After a power cut inside the window only the
  zones still in the list run again (an interrupted zone runs its full duration again). The list of a past day is
  dropped.
- **Skip:** `skip_if` is a list of `{condition, reason}`; the first true one turns a due slot into a skip (marked for the
  day). The greenhouse uses `gp.inhibited` (service mode). A rain sensor or a rain-delay entity adds an item.
- **Multiplier:** slot percent x global percent (`set_global_pct()`, fixed 100 today), clamped to 10-200 %. The `gp`
  layer cuts every run to the zone's run-duration maximum, so a multiplier can never exceed the watchdog limit.
- A zone that is already queued or running is not queued again.

## Data for screens (C++ accessors on the hub)
`next_run()` -> `{slot index, local day, start minute}` over the next 8 days; `day_runs(offset)` -> that day's runs
sorted by start with `PENDING / FIRED / MISSED / SKIPPED`; `next_run_text()`. Durations for a timeline bar are not
computed here (they need the engine's per-zone durations).

## Hub options
`id`, `time_id` (default: first `time:`), `catch_up_window`, `zone_count` (default: number of `gp_zone` entries, else
16), `master_switch_id`, `next_run_id`, `next_run_text_id`, `last_result_id`, `skip_if`, `on_run`. Action:
`garden_schedule.zone_done: {id, zone}` (0-based zone).

## Not verified on a device
A scheduled run with Home Assistant off and SNTP as the only clock, a power cut inside/outside the catch-up window,
and the clock being valid right after an OTA reboot are not verified on real hardware (the emulator and the unit tests
cover the logic). DST is covered by unit tests only.
