# garden_zones

GardenPilot's irrigation engine: a modified copy of ESPHome's
[`sprinkler`](https://esphome.io/components/sprinkler/) component (tag `2026.9.1`) with an open, persistent queue.

**Status:** in development; not used by the device yet (roadmap stage 7: groups and lanes, watchdog and soil skip,
switching the device). It must not drive a real valve before the maximum on-time watchdog exists. It is loaded only
by `tests/configs/garden_zones_sim.yaml` and `tests/configs/garden_zones_groups_sim.yaml` (host builds with simulated
relays).

## Use

```yaml
external_components:
  - source: components
    components: [garden_zones]

garden_zones:
  - id: gz
    main_switch: {name: Irrigation}
    auto_advance_switch: {name: Auto advance}
    queue_enable_switch: {name: Queue}
    persist_queue: true            # default
    valves:
      - {valve_switch_id: relay_1, enable_switch: {name: Zone 1 enabled}, run_duration: 10min}
      - {valve_switch_id: relay_2, enable_switch: {name: Zone 2 enabled}, run_duration: 10min}
```

The schema and the `garden_zones.*` actions are those of the stock `sprinkler` plus:

- `garden_zones.run_valve: {id, valve_number, run_duration}` — manual run that keeps auto-advance and the queue
- `garden_zones.remove_queued_valve: {id, valve_number}`
- condition `garden_zones.is_valve_queued: {id, valve_number}`
- option `persist_queue` (default `true`)

## Groups and lanes (dict form)

Zones are grouped by water source; each group has `max_parallel: 1 | all | N`. The component generates one
stock-style controller (a "lane") per parallel slot and registers all lanes with each other, so a pump shared by the
lanes of a group stays on while any lane needs it.

```yaml
external_components:
  - source: components
    components: [garden_zones, garden_zone]

garden_zones:
  groups:
    - {id: beds, max_parallel: all}                         # one lane per zone
    - {id: lawn, max_parallel: 2, pump_switch_id: lawn_pump}  # 2 lanes, round-robin: zone i -> lane i mod 2
    - {id: solo, max_parallel: 1}                           # one lane, one shared queue
  zones:                                                    # inline zones (optional)
    - {group: lawn, valve_switch: Lawn 1, valve_switch_id: relay_3, run_duration: 10min}

garden_zone:                                                # one list item per package (MULTI_CONF)
  - group: beds
    valve_switch: Bed 1
    valve_switch_id: relay_1
    run_duration_number: Bed 1 run duration
```

- Zone numbers are 0-based per group: inline `zones:` first, then `garden_zone:` entries in package order.
- **Always write `garden_zone:` as a list item** (`- group: ...`): ESPHome merges two dict-form entries from
  different packages into one zone (silent loss); lists concatenate in package order.
- Group options: `name`, `max_parallel`, `pump_switch_id`, `pump_start_pump_delay` / `pump_stop_pump_delay` /
  `pump_start_valve_delay` / `pump_stop_valve_delay` (applied to every lane), `persist_queue` (default `true`).
- Zone options: `group`, `valve_switch`, `valve_switch_id`, `enable_switch`, `run_duration` or
  `run_duration_number` (as the stock valve), `lane` (only with an integer `max_parallel`; all-or-none per group).
- Group `id` is required. Mixing the list form of `garden_zones:` with `garden_zone:` entries fails at the entry's
  `group:` reference (a list-form config declares no group).
- Pinned lanes left without zones are not generated (logged at config time) and the remaining lanes are renumbered
  (`lane: 2` can become `<group>_lane_1`), which changes the queue preference key.
- Lane limits: with `max_parallel: N` two zones of the same lane never run together even if another lane is idle.
  A pump belongs to one group; a `valve_switch_id` to one zone. Lanes have no controller entities (no main switch,
  auto advance, ...) yet; a zone's switch starts a single-valve run on its lane. The queue of each lane is persisted
  under a key derived from its zones, so a changed layout drops the saved queue.
- Actions (`id` = the group id; numbers and durations are templatable): `garden_zones.queue_zone` (never starts),
  `garden_zones.remove_queued_zone`, `garden_zones.run_zone` (manual run on the zone's lane),
  `garden_zones.start_group_queue` (every lane with a non-empty queue), `garden_zones.start_group_cycle`,
  `garden_zones.shutdown_group` (this group only); condition `garden_zones.is_zone_queued`.
- C++: `GardenZonesGroup::queued_zones()` interleaves the lanes (first entry of each lane, then the second, ...);
  exact start order only with equal durations.
- The 008 list form above keeps working; it cannot be combined with `garden_zone:` entries. **It has no watchdog and
  no soil skip**: a device must use the groups form.

## Safety: watchdog and soil moisture skip (groups form)

Every group gets a watchdog, on by default (a limit is disabled only explicitly with `never`, like
`update_interval: never`; each disabled limit logs a WARN `watchdog disabled by config` naming the group / zone at boot).
It polls the real state of each zone's raw valve switch and of
the group's pump switch in its own loop, independent of the sprinkler state machine and of run durations, and turns
an actuator off when a limit is exceeded. A trip is logged at ERROR, fires `on_watchdog_trip` (variables `zone`: int,
`-1` = pump, and `reason`: `max_on_time`, `pump_max_on_time` or `pump_idle`) and latches a lockout until
`garden_zones.reset_watchdog: <group id>` or a reboot (latches are not persisted; the actuators come up off).

| Key | Where | Default | Range |
|---|---|---|---|
| `max_on_time` | group (default for its zones), zone (override) | `60min` | any duration from 1 s (at most 30 days) or `never` |
| `pump_max_on_time` | group, only with `pump_switch_id` | `2h` | any duration from 1 s (at most 30 days) or `never` |
| `pump_idle_timeout` | group, only with `pump_switch_id` | `10s` | any duration from 1 s (at most 30 days) or `never` |
| `on_watchdog_trip` | group, optional trigger | none | |

- A valve on for more than its `max_on_time` is forced off, its lane is shut down (the queue is kept; nothing restarts
  by itself) and **that zone** is locked. The pump is forced off when it was on for more than `pump_max_on_time`, or
  was on with no open valve of its group for more than `pump_idle_timeout`; a pump trip shuts down every lane of the
  group and locks **the pump and all zones of the group**.
- `never` (group or zone `max_on_time`, `pump_max_on_time`, `pump_idle_timeout`) disables that one limit: nothing is
  forced off for it, and the config-time checks that compare run durations to it are skipped for that zone / pump. The
  rest of the watchdog (lockout, stuck-relay retries, the other limits) stays active. 30 days is the longest value a
  32-bit millisecond timer tracks wrap-safely.
- `pump_max_on_time` bounds a watering session, not one zone: between two zones of a lane without a switching delay
  the shared pump stays on continuously for a whole queue.
- While locked, an actuator that is seen on is forced off again (WARN, once per 10 s); an actuator that stays on after
  a forced off is commanded off at most once per second (ERROR "stuck relay?", once per 10 s). A locked zone is
  skipped when the queue or a cycle reaches it, and `run_zone` refuses it (WARN).
- `garden_zones.reset_watchdog: <group id>` clears every latch of the group; condition
  `garden_zones.watchdog_tripped: <group id>` is true while any latch is set.
- Validation (config time): `longest_run + pump delays + 2 s <= max_on_time` for every zone, where `longest_run` is
  `run_duration` or the `run_duration_number`'s `max_value` (the stock default of 86400 s therefore needs a lower
  `max_value` or a higher `max_on_time`) and the pump delays are the larger of `pump_start_pump_delay` /
  `pump_start_valve_delay` plus `pump_stop_valve_delay` (the valve stays open while the pump stops); the limit is the
  zone's own `max_on_time` if set, else the group's. `pump_max_on_time >=` every zone limit;
  `pump_idle_timeout >= max(pump_start_valve_delay, pump_stop_pump_delay) + 2 s` (`pump_start_valve_delay` is the
  "pump on, valve not yet open" phase, `pump_stop_pump_delay` the "valve closed, pump still on" phase); the raw valve
  and pump switches must be found under `switch:` and resolve to `restore_mode` `ALWAYS_OFF` or `RESTORE_DEFAULT_OFF`
  (a switch that cannot be resolved is an error, not a skip). Run durations passed at runtime to `queue_zone` /
  `run_zone` are not checked; the watchdog trips instead.

A zone can have a soil moisture sensor:

```yaml
garden_zone:
  - group: beds
    valve_switch: Bed 1
    valve_switch_id: relay_1
    run_duration: 10min
    soil_moisture:
      sensor_id: bed_1_soil      # required, a sensor (usually %)
      skip_above: 60             # required, same unit as the sensor
      max_age: 30min             # optional, 1 s .. 24 h; an older reading counts as unavailable
      when_unavailable: water    # water (default) | skip
```

- Checked when the zone's turn comes in a queue or a cycle (not when it is queued): wetter than `skip_above`
  (strictly greater; equal waters) -> the zone is skipped (INFO log `Valve N skipped: soil moisture 72.0 > 60.0`).
- Unavailable = no reading yet, NaN, or older than `max_age`. `when_unavailable: water` runs the zone as scheduled
  (WARN) so a broken probe does not silently stop watering; `skip` skips it.
- Staleness counts from the sensor's last state callback. A sensor that publishes only on change (for example the
  `homeassistant` platform, or `delta` / `throttle` filters) looks stale after `max_age` while the soil is stable, which
  with `when_unavailable: skip` stops watering: add a `heartbeat` filter or use a larger `max_age`. The unavailable WARN is
  logged at most once a minute per zone.
- Scope: queue and cycle runs only. Manual runs (`run_zone`, a zone's own switch) ignore the soil. A running zone is
  not stopped when the soil gets wet. Cycle repeats do not re-check (lanes have no repeat entity).

## Differences to the stock component

1. Open queue API: list in run order, "is zone N queued", remove one zone (`queue-api`).
2. The queue survives a reboot; it never starts by itself (`queue-persist`).
3. `run_valve`: a manual run that does not switch off auto-advance or the queue (`manual-run`).
4. Disabled zones are skipped (dropped) when the queue reaches them (`queue-skip-disabled`).
5. `groups:` form with generated lanes (`groups`); lane mode: a controller without an auto-advance switch keeps its
   own auto-advance state, default off (`lanes`).
6. A per-valve skip check, asked when a valve's turn comes in the queue or a cycle (`zone-skip`).

**Accepted by design (stock handover):** when a run ends, the next valve of the same lane opens before the finished one
is switched off, so two valves of a lane can be on together for up to one main-loop pass. Pump protection comes first:
the pump never runs against closed valves. For a deliberate, longer overlap use the stock `valve_overlap` option (list
form).

Details and the re-port procedure for a new ESPHome release: [PATCHES.md](PATCHES.md). Every change is marked in
the code with `GZ-PATCH-BEGIN(<id>)` / `GZ-PATCH-END(<id>)`.

## Licence

The directory is distributed under the GNU General Public License v3 ([LICENSE](LICENSE)), like ESPHome's C++
runtime. `__init__.py` derives from ESPHome's MIT-licensed Python code; the MIT notice of ESPHome at tag `2026.9.1`:

```
Copyright (c) 2019 ESPHome

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```
