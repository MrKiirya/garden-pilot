# garden_zones

GardenPilot's irrigation engine: a modified copy of ESPHome's
[`sprinkler`](https://esphome.io/components/sprinkler/) component (tag `2026.9.1`) with an open, persistent queue.

**Status:** in development; not used by the device yet (roadmap stage 7: groups and lanes, watchdog and soil skip,
switching the device). It must not drive a real valve before the maximum on-time watchdog exists. It is loaded only
by `tests/configs/garden_zones_sim.yaml` (host build with simulated relays).

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

## Differences to the stock component

1. Open queue API: list in run order, "is zone N queued", remove one zone (`queue-api`).
2. The queue survives a reboot; it never starts by itself (`queue-persist`).
3. `run_valve`: a manual run that does not switch off auto-advance or the queue (`manual-run`).
4. Disabled zones are skipped (dropped) when the queue reaches them (`queue-skip-disabled`).

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
