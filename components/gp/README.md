# gp — the engine-neutral irrigation layer

MIT licence (like the repository). Screens, the screensaver, the valve test, schedules and Home Assistant read irrigation
state and start or stop watering **only** through this contract; no package outside the engine files names
`garden_zones`. The component never includes an engine header: it talks to the engine through the abstract
`gp::Engine` (`engine.h`), and an adapter implements it (today `components/garden_zones/gp_engine.h`, GPLv3, next to the
engine it adapts).

Files: `zone_model.h`, `alerts.h`, `history.h`, `format.h`, `format_history.h` and `engine.h` are pure C++17 without ESPHome includes
Files: `zone_model.h`, `alerts.h`, `history.h`, `format.h` (+ `format_screens.h`), `layout.h` and `engine.h` are pure C++17 without ESPHome includes
(unit tests in `tests/cpp/`); `gp.h` is the ESPHome glue; `__init__.py` the schema and codegen. `components/gp_zone/`
adds the per-zone Home Assistant switch.

## Configuration
```yaml
gp:                               # hub, once per device (packages/core/gp.yaml)
  id: gp_hub                      # not "gp": an id may not equal an integration name
  groups:                         # one item per irrigation group (packages/greenhouse/gp.yaml)
    - id: gp_greenhouse
      name: "Greenhouse"
      key: greenhouse             # addresses the group in the generic Home Assistant actions
      garden_zones_id: gh_zones   # engine selector: exactly one engine key per group
gp_zone:                          # one list item per zone (packages/greenhouse/bed.yaml)
  - group: gp_greenhouse
    position: 1                   # 1-based, as on screen; positions must be exactly 1..N of the engine group
    name: "Greenhouse bed 1"      # the Home Assistant switch: on = run the zone, off = stop
```
The clock for "last watering" is the first `time:` of the configuration. `gp_zone:` is always a list item (dict entries
from different packages merge into one). The engine's own zone switch is `internal: true` (see `bed.yaml`), so Home
Assistant has no duplicates and does not depend on the engine.

## Read model (polled, never pushed)
Zones are addressed by the **0-based index** inside the group (= bed include order). Times in seconds.

`id(gp_greenhouse)->zone(i)` returns a `ZoneView`; an index past the zone count returns the static `ABSENT` view
(`present == false`), so a hidden card slot can poll safely.

| Field | Meaning |
|---|---|
| `present`, `name`, `short_name` | index < zone count; engine zone name; "B1" |
| `state` | `LOCKED > RUNNING > PAUSED > DISABLED > QUEUED > SKIPPED > IDLE` (`state_word()`: LOCKED, RUN, PAUSED, OFF, QUEUED, SKIPPED, IDLE) |
| `skip_reason` | engine text while `state == SKIPPED` (visible until the zone runs or is queued again, or 12 h) |
| `time_left` | RUNNING only in the current engine adapter (paused zones report none) |
| `run_duration` | configured run |
| `queue_position` | 0-based, in the engine's queue order |
| `soil` | soil moisture in percent when the zone has a sensor (`gp_zone: soil_sensor_id`, set by `bed_soil.yaml`), else empty; the revision moves when the shown whole percent changes |
| `run_total` | seconds left at the first sample of the current run (RAM only, 0 when not running or unknown): the card's progress bar goes 0 to 100 % even for a run longer than `run_duration` |
| `last_start_epoch` / `last_start_uptime` / `last_duration` | last watering: start (Unix seconds only if the clock was valid; uptime seconds), seconds the valve was open (a pause inside one run is not counted). **Persisted to flash**: epoch and duration survive a reboot, uptime does not |

`id(gp_greenhouse)->summary()`: `zone_count`, `running`, `active[]`, `queue_length`, `queue_time`, `auto_advance`,
`watchdog_tripped`, `now_zone` / `now_left`, `next_zone` (the queue only, until schedules exist), `zone_left`,
`total_left` and `revision` (bumps on any visible change; a countdown bumps it once per second while something runs).
`changed_since(uint32_t &seen)` compares the revision with a `globals` value.

**History.** The last 100 entries are kept in RAM and written to flash with the ESPHome preferences (NVS wear-levels).
`id(gp_greenhouse)->history().at(0)` is the newest. The full history lives in Home Assistant.

*One run = one entry, "open at start, close at end".* When a zone starts, gp pushes `{epoch = start, duration =
planned seconds, zone, source, result = OPEN, detail}`; when the run ends the SAME entry is updated in place to
`{duration = valve-open seconds (a pause is not counted), result = DONE | STOPPED}` (`book::close` in `history.h`; the
entry is found by scanning for the zone's newest OPEN entry; if 100 newer entries overwrote it a closed entry is pushed
instead). Two save requests per run, nothing is written while it runs; the live time is computed in RAM
(`ZoneView::run_elapsed`). Parallel zones are several OPEN entries (at most one per zone). The pure logic is
`journal.h` (`Journal`, fake-clock tested). `HistoryEntry` stays 12 bytes and the blob 1336 bytes, magic `GP01`
(`static_assert`ed); the byte layout is:

| field | meaning |
|---|---|
| `epoch` (4) | start, Unix seconds; 0 = the clock was not valid at the start (back-filled at the end as `end - duration`) |
| `duration` (4) | OPEN / INTERRUPTED: planned seconds (0 = unknown); closed: valve-open seconds; skip: 0 |
| `zone` (1) | 0-based |
| `source` (1) | `Source`: UNKNOWN 0, MANUAL 1, QUEUE 2, SERVICE 3 (shown `test`), SCHEDULE 4, HA 5 |
| `result` (1) | `Result`: UNKNOWN 0 (old entries, render like done), DONE 1, STOPPED 2 (the end came inside the 3 s window after `stop_all`; a watchdog end is done), SKIPPED_WET 3, SKIPPED 4, OPEN 5, INTERRUPTED 6 |
| `detail` (1) | schedule run: slot 1..8; SKIPPED_WET: the zone's threshold 0..100 (255 = unknown); else 0 |

*Interrupted.* In `setup()` every OPEN entry (the run never saw its end) becomes INTERRUPTED, one save, only if any
changed. Elapsed time is not stored (no heartbeat): the page shows the upper bound from the planned duration, `<5 min`
(`?` when unknown). ESPHome keeps `save()` in RAM and flushes it every `preferences: flash_write_interval` (default
60 s, `esphome/components/preferences/__init__.py`), so a run shorter than that costs one flash write (start and end
coalesce) and a power cut within a minute of the start loses the OPEN entry (no row). A clean reboot (OTA, restart
button, `App.safe_reboot()` / `reboot()`) runs every component's `on_shutdown()` first, and `IntervalSyncer::on_shutdown()`
calls `global_preferences->sync()` (`esphome/core/application.cpp`, `esphome/components/preferences/syncer.h`, ESPHome
2026.9.1; not checked against 2026.6.3), so a run cut by a restart reads `interrupted`.

*Source.* `gp.run_zone`, `gp.enqueue_zone`, `gp.enqueue_zones` and `gp.full_cycle` take `source` (`manual` default,
`ha`, `schedule`; `service` only on `gp.run_zone`, the valve test); `gp.enqueue_zones` also takes `slot` (0..8). gp
remembers the source per zone until the run starts (`SourcePlan` in `zone_model.h`). Precedence at the start
(`pick_source`): a fresh `run_zone` intent (15 s) > the source the zone was queued with > the `full_cycle` source > QUEUE
while a queue run is active > UNKNOWN. The queued source is used up by the start; `stop_all`, `clear_queue`,
`dequeue_zone` and service mode clear it. `on_zone_finished`'s `completed` flag is NOT derived from `Source`: it is "came
from the queue / a cycle, not from `run_zone`, and not stopped" (a SCHEDULE run still marks its slot zone done).
Callers: the schedule `on_run` passes `schedule` + slot, the Home Assistant actions, the main switch and the
`gp_zone` switch pass `ha`, screen buttons keep `manual`.

An entry can also be a **skip** (`skipped wet`, soil too wet, `detail` = the threshold the adapter reads from the
engine's text `soil moisture X > Y`, or `skipped` for any other engine skip; duration 0). A skip is recorded once per
engine skip stamp with the source the zone was queued with; it is not a "last watering" and does not fire
`on_zone_finished`.
The History page (design D20, 8 rows per page) reads it through `history_changed_since(uint32_t &seen)` (a RAM change
counter) and the glue one-liners `history_title(page)`, `history_cell(page, row, col)`, `history_colour(page, row, col)`,
`history_has_open(page)` and `history_clamp_page(page)`; they convert the epoch to local time and call the pure
formatters in `format_history.h` (`history_cells`: five cell texts and colour tones, TIME ON of an open run
`4 min...` in green, stopped / interrupted in amber).

**Alerts** (`id(gp_hub)`): fixed table of 12, entry = key, severity (`error` / `warn` / `info`), ASCII text (<= 40), since,
group. `top()` = highest severity, then newest; the oldest lowest-severity entry is dropped first, an ERROR never (the new
alert is rejected and logged). Built-in sources: `wd:<group>` ERROR "Greenhouse: watchdog - B2 locked" and `clock` INFO
"Clock not set" (5 min after boot, only with a clock). Packages add their own with `gp.alert_raise` / `gp.alert_clear`.
**"Home Assistant disconnected" is not an alert**: a quiet icon in the Home header (`home_ha_icon`, driven by a poller).
`alerts_changed_since(uint32_t &seen)` serves an alert-strip poller.

## Actions, conditions, trigger
Every action logs at INFO with tag `gp`. Group actions take `id: <group id>` or `{hub: gp_hub, group: <templatable key>}`.

| Action | Arguments | Engine call |
|---|---|---|
| `gp.run_zone` | `zone` (0-based), `duration` (optional; default the zone's), `source` (`manual` default, `ha`, `schedule`, `service`) | manual run; refused + WARN when LOCKED or out of range |
| `gp.enqueue_zone` | `zone`, `duration`, `source` (`manual` default, `ha`, `schedule`) | adds to the queue (never starts); cut to the zone's maximum (WARN). Held back like `gp.enqueue_zones` while a full cycle or another non-queue run is running: a zone added then ("+Q", Home Assistant) is not shown as queued until 5 s after that run has ended |
| `gp.enqueue_zones` | `mask` (bit n = zone n, 0-based), `pct` (percent of each zone's run duration; schedules use it), `slot` (0..8, schedule slot kept with the history entry), `source` | queues every zone of the mask in zone order for run duration x pct, cut to the zone's maximum (WARN when cut); a zone already queued or running is not queued again (INFO); bits beyond the group are ignored (WARN); refused while inhibited; never starts. **While a full cycle (or another non-queue run) is running the request is held back in gp** (the engine would pick queued zones in the middle of the cycle) and queued after that run has ended (INFO log) |
| `gp.dequeue_zone` | `zone` | removes from the queue |
| `gp.start_queue` / `gp.full_cycle` | `gp.full_cycle`: `source` (`manual` default, `ha`, `schedule`) | start the queue / a full cycle; both refused while inhibited. `start_queue` while a full cycle (or another non-queue run) is running is **deferred**: the cycle runs to its end, then (after 5 s without a running zone) the held-back `enqueue_zones` requests are queued and the queue starts (INFO logs). Never cuts a cycle short. **Also held back while the engine is still stopping** (a `gp.stop_all` shuts the lane down for about 2 s and the engine loses a queue / cycle start issued meanwhile): the start runs once the lane is idle (INFO log "deferred"); a later `stop_all` / inhibit / `clear_queue` cancels it |
| `gp.clear_queue` | - | drops every queued zone and any held-back enqueue / start (a running zone keeps running) |
| `gp.stop_all` | `clear_queue` (default false) | shut the group down; also drops any held-back enqueue / start and fires the group's `on_stop` |
| `gp.reset_watchdog` | - | reset the watchdog lock |
| `gp.alert_raise` / `gp.alert_clear` | `id: <hub>`, `key` (<= 15), `severity`, `text` | alert table only |

Conditions: `gp.zone_running {id, zone}`, `gp.any_running`, `gp.watchdog_tripped`, `gp.alert_active {id: hub, key?}`,
`gp.inhibited {id}` (true while service mode blocks starts; the schedule's `skip_if` uses it).
Triggers: `gp: on_alert_change` (logging / HA only); group `on_stop` fires on every `gp.stop_all` and when service mode is
entered (`gp.inhibit: true`); the greenhouse package hooks the schedule to it (a STOP settles the slots, see
`components/garden_schedule/README.md`); group `on_zone_finished (zone, completed)` fires when a zone's run
ends (zone 0-based). `completed` is true only for a run that came from the queue (a queue start, a scheduled run) and was
not ended by `gp.stop_all` within 3 s before it ended. It is false for manual / service runs and for stopped runs. The
Home Assistant main switch "Greenhouse irrigation" (a template switch of `packages/greenhouse/gp.yaml`: ON = `gp.full_cycle`, OFF = `gp.stop_all`) is a normal STOP: `completed` false, `on_stop` fires (tested). A run
ended by the engine watchdog also has no stop signal, so a queue run cut by it counts as completed too (a faulty valve
is not repeated by a schedule); not covered by a test, because scheduled durations are clamped below the watchdog limit. Schedules use it as the per-zone "done" mark.

## Home Assistant
One generic action set for every group (`packages/core/gp_api.yaml`): `gp_run_zone`, `gp_enqueue_zone` (`group`, `zone`
1-based, `minutes`, 0 = the configured duration), `gp_start_queue`, `gp_full_cycle`, `gp_stop_all`, `gp_reset_watchdog`
(`group`). Entities: the "Greenhouse irrigation" main switch (ON = full cycle, refused while service mode is on; OFF = full STOP, also while idle), the "Greenhouse bed N" zone switches (gp_zone), "Greenhouse status" (Idle / Watering B1 B3 /
Locked), "Alert", "Greenhouse watchdog" (problem), "Greenhouse watchdog reset". Settings entities (run durations, enable
switches, auto advance, reset button) have `entity_category: config`.

## LVGL reads gp only from pollers
Update LVGL widgets from `interval:` pollers (1 s) that start with `changed_since(...)`, never from a gp trigger,
`on_value` or an engine callback: those can fire before LVGL is ready (restore, Home Assistant). Label texts come from
`gp::fmt::*` (`format.h`), so every label lambda is one line. The bed cards use `fmt::card_*` (`format_screens.h`: state word, colours, time, progress, soil, last watering as `Moment`s converted by the glue) and `layout::bed_card(count, slot)` (`layout.h`: which of the six card slots show and where: 1-3 zones full, 4-6 compact grid). Glue on the group: `card_name(zone)`, `card_last(zone)`, `set_zone_soil(zone, sensor)`. The old debug formatters (`status_line`, `modes_line`, `durations_line`, `zone_left_line`, `total_left_line`, `queue_line`) are gone.

## Writing an adapter
Implement `gp::Engine` over your engine's group, add a key next to `garden_zones_id` in `__init__.py` (`ENGINE_KEYS`
and the codegen in `to_code`), and keep the adapter on the engine's side of the licence line. `read()` fills a
`GroupInput` (zones in index order, the active list, the queue in run order, flags); the pure model does the rest.
