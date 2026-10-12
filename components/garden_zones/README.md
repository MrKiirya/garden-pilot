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
- The 008 list form above keeps working; it cannot be combined with `garden_zone:` entries.

## Differences to the stock component

1. Open queue API: list in run order, "is zone N queued", remove one zone (`queue-api`).
2. The queue survives a reboot; it never starts by itself (`queue-persist`).
3. `run_valve`: a manual run that does not switch off auto-advance or the queue (`manual-run`).
4. Disabled zones are skipped (dropped) when the queue reaches them (`queue-skip-disabled`).
5. `groups:` form with generated lanes (`groups`); lane mode: a controller without an auto-advance switch keeps its
   own auto-advance state, default off (`lanes`).

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
