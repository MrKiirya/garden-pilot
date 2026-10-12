# 012 — `garden_zones` groups and lanes: generated controllers, shared pump, `garden_zone:` entries

Status: in-review (round 1 changes done; Gate decided: (b))
Roadmap: SPEC §9 item 7 "`garden_zones` component" (part 2 of 4; stage plan in `tasks/008-garden-zones-core.md`)
Spec sections: SPEC §3, §4 (garden_zones: parallelism, pump), §4.2, §5 (bed package, `MULTI_CONF`), §6, §7 items 3-4,
§9 item 7; CLAUDE.md core principles 1, 2, 3, 4, 7
Hardware check: none. The device keeps the stock `sprinkler` (`garden-pilot.yaml`, `packages/`, `hardware/` are not
touched; `test_device_unchanged` stays). Everything runs in host test builds with template relays.

## Goal
`garden_zones` gets the configuration form described in SPEC §4: groups of zones by water source, each with
`max_parallel: 1 | all | N`. The component's Python code generates one stock-style controller ("lane") per parallel
slot, assigns zones to lanes statically, wires an optional pump shared by all lanes of a group, and registers all lanes
with each other so the pump stays on while any lane needs it. A zone can be declared inline under `garden_zones: zones:`
or as a separate `garden_zone:` entry (`MULTI_CONF`), so a package included once per bed can add its own zone (the
pattern task 014 will use for `bed.yaml`). A new group object gives lane-aware actions addressed by group + zone number
(queue, remove, manual run, start queue, start cycle, shutdown) and a group-level queue view. The 008 list form of
`garden_zones:` keeps working unchanged. Pure lane logic is unit tested in C++ and Python; a host scenario on the sim
board proves parallel lanes, the shared pump, `max_parallel: 1`, package merging of `garden_zone:` entries and per-lane
queue persistence.

## Context

### Carried over from 008 (tasks/008-garden-zones-core.md, tasks/008-review.md)
- Stage plan: 012 = this task; 013 = max on-time watchdog + soil skip — **the watchdog also covers the pump** (forced
  off when it has been on longer than a limit, or when it is on with no open valve; limits configurable; human decision
  2026-10-02); 014 = switch the device. Until 013 lands, no device config may load `garden_zones` (principle 4 is met by
  not shipping it).
- Fork discipline: every change to a forked file (`__init__.py`, `automation.h`, `sprinkler.h`, `sprinkler.cpp`) sits in
  a `GZ-PATCH-BEGIN(<id>)` / `GZ-PATCH-END(<id>)` region with a section in `PATCHES.md`; `test_fork_diff_is_documented`
  and `test_patch_ids_documented` enforce it. **New logic goes into new, non-forked files** in the component directory.
- C++ tests: minimal harness `tests/cpp/minitest.h`; `script/test-cpp` builds every `tests/cpp/*.cpp` into one binary,
  so a new test source is picked up without editing the script. `GP_REQUIRE_CXX=1` (devcontainer configs) turns
  compiler skips into failures. The implementer machine of 008 had no C++ compiler: **run the cpp/host checks in the
  devcontainer** (`devcontainer exec --workspace-folder . script/test`) and say in Implementation notes where they ran.
- Open 008 follow-ups that are **not** part of this task: `next_valve`/`previous_valve` vs a pending manual-run resume;
  a manual run during a full cycle marks the zone cycle-complete (review round 1, suggestion 1); missing scenario cases
  (user pause before `run_valve`, busy full cycle, `shutdown` during a manual run). Item 7 of the round-1 suggestions
  (record host-compile CI timings against the 6-minute Gate) applies here too (see Gates).

### Sources checked (pinned ESPHome 2026.9.1; the fork is a copy of tag 2026.9.1)
- **Pump coordination across controllers exists in stock code and needs no patch.** In the fork
  (`components/garden_zones/__init__.py`, last loop of `to_code`) every controller of one `garden_zones:` block gets
  `add_controller()` with every other controller → `Sprinkler::other_controllers_`. `Sprinkler::set_pump_state(pump,
  false)` (`sprinkler.cpp`) asks every other controller `pump_in_use(pump)` and keeps the pump on if any says yes
  ("Leaving pump on because another controller instance is using it"); `pump_in_use()` is true while a valve operator
  with that pump is `ACTIVE` (or `STARTING`/`STOPPING` with a pump/valve delay configured). `set_pump_state(pump, true)`
  always turns it on. `configure_valve_pump_switch()` de-duplicates pumps per controller. The upstream docs
  (<https://esphome.io/components/sprinkler/>) do not describe this; it is source-only behaviour, so the host scenario
  must prove it. Consequence: **all lanes of all groups must be controllers registered with each other** — the group
  codegen must emit the same `add_controller()` cross-registration.
- **Single-valve lanes need an auto-advance state.** `Sprinkler::auto_advance()` returns `true` when no
  `auto_advance_switch` is set, `set_auto_advance()` is a no-op without the switch, and queue runs are not marked
  cycle-complete (`fsm_transition_from_valve_run_`: only `CYCLE`/`USER` requests are). `start_from_queue()` calls
  `reset_cycle_states_()`. So a lane without an auto-advance switch would **start a full cycle of its zones after its
  queue drains**. The stock schema forbids `auto_advance_switch` / `main_switch` / `enable_switch` on one-valve
  controllers (`validate_sprinkler`), and stock `to_code` only passes the enable switch to `add_valve()` for multi-valve
  controllers. Hence Decision 5 (a small C++ patch `lanes`) and Decision 4 (the group codegen calls `add_valve(valve,
  enable)` itself; C++ `add_valve` accepts an enable switch for any valve count).
- `controller_sw_` (main switch) is only stored by `set_controller_main_switch()` and never dereferenced elsewhere in
  `sprinkler.cpp`, so lanes without a main switch are null-safe. A zone's switch (`valve_switch` entity) turning on runs
  stock `StartSingleValveAction` on its lane, turning off runs `ShutdownAction` on its lane (`Sprinkler::add_valve`).
  That is the HA behaviour per zone in this task; moving it to the queue-friendly manual run is stage 8.
- **Package merge** (`esphome/config_helpers.py::merge_config`, identical at 2026.6.3 and 2026.9.1): dicts merge key by
  key (scalar: last wins), lists are concatenated in package order. Then `config.py` wraps a non-list `MULTI_CONF`
  config into a one-item list (`if not isinstance(self.conf, list): self.conf = [self.conf]`). Consequences:
  - `garden_zone:` written as a **list** in N packages → N entries in package order (works);
  - written as a **dict** (one zone, no dash) in two packages → the two dicts are merged key by key **into one zone**
    (silent loss). Hence the rule "always write `garden_zone:` as a list item" and the check in the table below;
  - `garden_zones: {zones: [...]}` in several packages also concatenates (inline zones merge the same way).
- `esphome/loader.py`: a component's `to_code` is optional (`getattr(module, "to_code", None)`); external components
  import as `esphome.components.<name>`, so `components/garden_zone/` can import the shared zone schema from
  `esphome.components.garden_zones`. `FINAL_VALIDATE_SCHEMA` sees the whole config (`esphome/final_validate.py`,
  `full_config`). Codegen-time IDs (`ID(name, is_declaration=True, type=...)`) are an established pattern
  (`esphome/components/lvgl/lvcode.py`), and `CORE.config` is read in `to_code` by core components
  (`esphome/components/lvgl/__init__.py`).
- Minimum 2026.6.3: `merge_config` checked on GitHub at the tag (same code). Loader, `MULTI_CONF` wrapping and
  `final_validate` are long-standing but were not diffed; the `config` checks on `minimum` below prove them.

## Decisions (planner; product points confirmed by the human, see "Decisions (human, 2026-10-02)")
1. **Two top-level forms of `garden_zones:`.** The 008 **list** form (stock controllers) is unchanged. The new **dict**
   form is `{groups: [...], zones: [...]}`. `CONFIG_SCHEMA` (patch region `groups` in `__init__.py`) dispatches by type:
   a dict with `groups` → the groups schema; anything else → the stock path. `to_code` dispatches the same way at its
   top. Mixing (a list form plus `garden_zone:` entries) fails validation with a clear message.
2. **Schemas** (in a new non-forked module `components/garden_zones/groups.py`):
   ```yaml
   garden_zones:
     groups:
       - id: greenhouse            # declare_id(GardenZonesGroup), required
         name: "Greenhouse"        # optional, used in lane names and logs
         max_parallel: all         # 1 | all | positive int, required
         pump_switch_id: lawn_pump # optional switch id, shared by every zone of the group
         pump_start_pump_delay: 2s # optional; also pump_stop_pump_delay / pump_start_valve_delay /
                                   # pump_stop_valve_delay, same Exclusive rules as stock; applied to every lane
         persist_queue: true       # optional, default true (008 Decision 5), applied to every lane
     zones:                        # optional; same schema as one garden_zone: entry
       - group: greenhouse         # use_id(GardenZonesGroup), required
         valve_switch: "Bed 1"     # zone switch entity, as stock valve_switch (name or full switch schema)
         valve_switch_id: board_relay_1   # required, the raw switch
         enable_switch: "Bed 1 enable"    # optional, allowed for any lane size
         run_duration: 10min       # exactly one of run_duration / run_duration_number (stock rules and defaults)
         lane: 0                   # optional, only with an integer max_parallel (Decision 3)
   garden_zone:                    # MULTI_CONF, always a list item
     - group: greenhouse
       valve_switch: "Bed 2"
       valve_switch_id: board_relay_2
   ```
   The zone schema reuses the stock valve sub-schemas (`switch.switch_schema(SprinklerControllerSwitch)`,
   `number.number_schema(SprinklerControllerNumber)` with the stock defaults and `validate_min_max`), so entity names,
   restore behaviour and saved run durations behave exactly like stock valves (needed by 014). All entity IDs are
   declared at validation time (zone schema); only lane controllers get codegen-time IDs (Decision 4).
   **Pump key:** `pump_switch_id` (the stock name) instead of SPEC's illustrative `pump:`; SPEC §4 example is updated.
   A group must have at least one zone; a pump switch may belong to **one group only** (validation error; human
   decision 3); a zone's `valve_switch_id` may appear once across all zones; a `pump_switch_id` must not equal any
   `valve_switch_id`.
3. **Static lane assignment** (pure Python in `components/garden_zones/lane_plan.py`, no ESPHome imports, unit tested):
   zone order = inline `zones:` first, then `garden_zone:` entries in package order; per group, zone number = index in
   that order (0-based, the address used by group actions).
   - `max_parallel: 1` → one lane with all zones (one shared queue, one valve at a time);
   - `max_parallel: all` → one lane per zone;
   - `max_parallel: N` → N lanes; **round-robin** by zone number (zone i → lane i mod N); explicit `lane: k`
     (0 ≤ k < N) pins a zone, but then **every** zone of that group must have `lane:` (all-or-none; mixing is an
     error); a lane left without zones is not generated (logged at config time); `N >= zone count` without pins behaves
     like `all`;
   - `lane:` with `1` or `all` is an error. Documented limit (SPEC §4): two zones of the same lane never run together
     even if another lane is idle.
   The planner returns per group a list of lanes, each an ordered list of zone numbers; the valve index of a zone inside
   its lane is its position in that list.
4. **Codegen** (`groups.py`, called from the dispatching `to_code`): zones are read from the validated config (inline
   zones + `CORE.config.get("garden_zone", [])`). Per lane: a `Sprinkler` with a codegen-time ID
   `<group id>_lane_<n>` and name `"<group name> lane <n>"`, `cg.register_component`, `add_valve(valve_sw, enable_sw or
   nullptr)`, `configure_valve_switch`, `configure_valve_run_duration_number`, `configure_valve_pump_switch` (group pump),
   pump delays, `set_persist_queue`, and the queue preference key `fnv1_hash("garden_zones_queue:<lane id>:<comma-joined
   valve_switch_id of the lane's zones>")` (a changed lane layout invalidates the saved queue instead of restoring it
   into other zones). No controller-level entities are created for lanes (no main / auto-advance / queue-enable /
   standby / multiplier / repeat switches or numbers). Then the stock-equivalent cross-registration: every lane
   `add_controller()` every other lane of the whole block. Per group: one `GardenZonesGroup` (Decision 6) with its
   lanes and its zone → (lane, valve) table. The stock list path keeps using the upstream `to_code` untouched.
5. **Patch `lanes` in `sprinkler.h` / `sprinkler.cpp`** (the only forked C++ change): a lane flag set by
   `set_lane_mode(true)`; when it is set and no auto-advance switch exists, `set_auto_advance(x)` stores `x` in a member
   and `auto_advance()` returns it (default `false`). Stock configs (flag off) behave exactly as upstream. Result:
   `start_from_queue` (sets it false) drains the lane's queue and goes idle; `start_full_cycle` (sets it true via
   `prep_full_cycle_`) cycles the lane's enabled zones; `start_single_valve` / `run_valve` behave as in 008. Keep the
   region small; list it in `PATCHES.md` with re-port notes. (The per-lane flag is also what the 014 group
   "auto advance" switch will drive for every lane at once.)
6. **Runtime group object** — new `components/garden_zones/group.h` (+ `group.cpp` if needed), namespace
   `esphome::garden_zones`, class `GardenZonesGroup : public Component` (only `dump_config`, no loop) holding
   `std::vector<Sprinkler *>` lanes and a `lanes::LaneMap`. Methods (zone = 0-based zone number in the group):
   - `queue_zone(zone, run_duration)` → `queue_valve` on its lane; **never starts anything** (human decision 2);
   - `remove_queued_zone(zone)` → count; `is_zone_queued(zone)`;
   - `queued_zones()` → group view that **interleaves lanes** ("round order", human decision 7): position 0 of every
     lane (lane index ascending), then position 1, … (approximates the start order; exact only with equal durations —
     documented);
   - `run_zone(zone, run_duration)` → 008 `run_valve` on its lane (other lanes untouched);
   - `start_queue()` → `start_from_queue()` on every lane whose queue is non-empty (lanes already running from their
     queue are left alone — stock early return);
   - `start_cycle()` → `start_full_cycle()` on every lane;
   - `shutdown()` → `shutdown()` on every lane of **this group only**;
   - `active_zones()` → zone numbers whose valve is active, ascending.
   Invalid zone numbers are logged and ignored. YAML (registered in `groups.py`, action/condition classes in
   `group.h`, so forked `automation.h` is not touched): actions `garden_zones.queue_zone` (`id`, `zone_number`,
   optional `run_duration`), `garden_zones.remove_queued_zone`, `garden_zones.run_zone`, `garden_zones.start_group_queue`,
   `garden_zones.start_group_cycle`, `garden_zones.shutdown_group`; condition `garden_zones.is_zone_queued`. `id` is a
   `use_id(GardenZonesGroup)`; numbers and durations are templatable (so the future `gp_*` scripts can pass `bed`).
   Group pause/resume, group entities for HA (main switch, auto advance, standby, multiplier), a queue text sensor:
   **not** in this task (human decision 4).
7. **Pure helper `components/garden_zones/lanes.h`** (header-only, standard library only, namespace
   `esphome::garden_zones::lanes`, C++17, GPLv3 header like `queue_ops.h`): `struct ZoneRef {size_t lane; size_t
   valve;}`; `class LaneMap` built from a `std::vector<ZoneRef>` (index = zone number) with `route(zone)` →
   `std::optional<ZoneRef>`, `zone_of(lane, valve)` → `std::optional<size_t>`, `lane_count()`, `zone_count()`,
   `static bool valid(table)` (every lane's valves are exactly `0..k-1`, no duplicate pair, no empty lane between
   used lanes); `round_order(per_lane_run_orders, map)` → zone numbers; `lanes_to_start(per_lane_queue_sizes)` → lane
   indices; `active_zones(per_lane_active_valve, map)` → sorted zone numbers. `GardenZonesGroup` only calls these.
8. **`garden_zone` component** — new directory `components/garden_zone/` (`__init__.py` only): `MULTI_CONF = True`,
   `DEPENDENCIES = ["garden_zones"]`, `CONFIG_SCHEMA` = the shared zone schema imported from
   `esphome.components.garden_zones`, **no `to_code`** (codegen is done by `garden_zones`). Loading:
   `external_components: [{source: components, components: [garden_zones, garden_zone]}]`. `garden_zones`'
   `FINAL_VALIDATE_SCHEMA` checks the cross-zone rules of Decision 2/3 over inline + `garden_zone:` zones. Licence: the
   new directory carries the repo licence (**MIT**, human decision 5) with a one-line header; it contains no
   ESPHome-derived code. The root README licence paragraph stays as is (it names only `components/garden_zones/` as
   GPLv3).
9. **Coexistence:** the stock `sprinkler` is untouched; the 008 list-form config and its scenario keep passing as they
   are (no edits to `tests/configs/garden_zones_sim.yaml`).

**Gates.**
- If the codegen-time lane IDs / `CORE.config` read (Decisions 4, 8) do not work on pinned or minimum: stop, record the
  exact error in Implementation notes, and propose the fallback in Follow-ups (declare lane IDs at validation time from
  the inline `zones:` only and defer `garden_zone:`); the reviewer escalates. Do not invent a third mechanism.
- If the 2026.6.3 `config` check of the groups config fails: `xfail(strict=True)` with the error + Follow-up (as 008).
- CI time: the new host compile is **pinned only**; `minimum` gets `config` + `compile --only-generate`. If `script/test`
  in CI grows by more than **6 minutes** over master (both host builds together), report timings and move the groups
  host scenario's second boot to a Follow-up. Record the measured CI timings in Implementation notes.

## Files
Component (`components/garden_zones/`, GPLv3 directory):
- modify: `__init__.py` — region `groups`: `CONFIG_SCHEMA` dispatch, `to_code` dispatch, `FINAL_VALIDATE_SCHEMA`,
  import of `groups.py`. Nothing else.
- modify: `sprinkler.h`, `sprinkler.cpp` — region `lanes` (Decision 5).
- create: `groups.py` — group/zone schemas, actions/condition registration, lane codegen (Decisions 2, 4, 6).
- create: `lane_plan.py` — pure lane assignment (Decision 3); no `esphome` import.
- create: `lanes.h` — pure C++ helper (Decision 7).
- create: `group.h` (+ `group.cpp` if the implementer prefers) — `GardenZonesGroup` + action/condition classes.
- modify: `PATCHES.md` — sections `groups`, `lanes`; note the new non-forked files.
- modify: `README.md` — groups/lanes YAML example, `garden_zone:` list-item rule, lane limits, pump sharing, actions.

New component:
- create: `components/garden_zone/__init__.py` — Decision 8.

Tests:
- create: `tests/cpp/test_lanes.cpp` — cases below.
- create: `tests/configs/garden_zones_groups_sim.yaml` — groups host scenario (below).
- create: `tests/configs/garden_zone_entry.yaml` — a zone package included twice with `vars` (mirrors the future
  `bed.yaml`): one `garden_zone:` list item from vars `zone_name`, `relay`.
- modify: `tests/test_garden_zones.py` — new checks below; `_stage()` takes the config path(s) to stage; `ALL_FILES`,
  header and ESPHome-free checks cover the new files.

Docs (short edits only):
- modify: `docs/SPEC.md` — §4: pump finding (one sentence) + example with `pump_switch_id`, `garden_zone:` and the
  round-robin default; §4.2: `components: [garden_zones, garden_zone]`; §5: "verified (task 012): lists concatenate in
  package order; write `garden_zone:` as a list item"; §9 item 7: one status sentence, including "013's watchdog also
  covers the pump".
- modify: `CLAUDE.md` — layout row for `components/garden_zone/` (MIT); one gotcha line: "`garden_zone:` is always a
  list item (`- group: ...`): two dict-form entries from different packages merge into one zone".

About 16 paths, above the ~10-file budget: 4 are short doc edits and 2 are small test configs; the work is
`groups.py`, `lane_plan.py`, `lanes.h`, `group.h`, the two patch regions and the tests. If the implementer runs out of
budget, cut in this order: second boot of the groups scenario → `start_group_cycle` scenario step → Follow-ups.

## Checks to write first
| Level | Test | Asserts |
|---|---|---|
| cpp | `tests/cpp/test_lanes.cpp` "LaneMap routing" | Table `[{0,0},{1,0},{0,1}]`: `route(0..2)` → given refs, `route(3)` empty; `zone_of(0,1)` = 2, `zone_of(1,1)` empty; `lane_count` 2, `zone_count` 3. |
| cpp | "LaneMap validation" | `valid` rejects a duplicate (lane, valve), a gap in a lane's valves (`{0,0},{0,2}`), an unused lane between used lanes; accepts one-lane and one-lane-per-zone tables; empty table invalid. |
| cpp | "round_order" | Map `[{0,0},{1,0},{0,1}]` (zones 0, 2 in lane 0; zone 1 in lane 1): lane queues (valve indices) `[[0,1],[0]]` → zones `0,1,2`; `[[1],[0]]` → `2,1`; `[[],[0]]` → `1` (empty lane skipped); all empty → empty. |
| cpp | "lanes_to_start / active_zones" | Only lanes with a non-empty queue; `active_zones` maps `{lane0: valve 1, lane1: none}` → zone of (0,1), sorted, empty when nothing active. |
| cpp | `test_cpp_unit_tests` (existing) | Still the wrapper; now also runs the new cases. |
| unit | `test_lane_plan_modes` | `lane_plan` (imported by path, no ESPHome): `1` → one lane `[0..n-1]`; `all` → n lanes `[[0],[1],…]`; `N=2`, 5 zones → `[[0,2,4],[1,3]]`; `N >= n` → like `all`. |
| unit | `test_lane_plan_pins` | All zones pinned → lanes from pins, zone order kept inside a lane; a pinned lane left empty is dropped; mixed pinned/unpinned → error; `lane >= N` → error; `lane` with `1`/`all` → error; message names the group. |
| unit | `test_lane_plan_is_esphome_free` | `lane_plan.py` imports only the standard library. `lanes.h` includes only `<...>` standard headers (extend `test_queue_ops_is_esphome_free`). |
| unit | `test_fork_diff_is_documented` (existing) | Still passes; the new regions `groups`, `lanes` are the only non-rename differences. |
| unit | `test_patch_ids_documented` (existing) | Ids in code == `PATCHES.md` sections incl. `groups`, `lanes`. |
| unit | `test_new_files_headers` | `groups.py`, `lane_plan.py`, `lanes.h`, `group.h`(/`.cpp`) have the short GPLv3 header (not the "modified copy" header); `components/garden_zone/__init__.py` has the MIT repo-licence header and no GPL claim. |
| unit | `test_garden_zone_entries_are_lists` | Every YAML file under `tests/configs/` and `packages/` that has a top-level `garden_zone:` key holds a **list** (guards the merge rule; `packages/` has none yet). |
| unit | `test_groups_test_config_shape` | `garden_zones_groups_sim.yaml`: includes `hardware/sim.yaml`; `external_components` lists `[garden_zones, garden_zone]`; dict form with groups `beds` (`all`), `lawn` (`2`, `pump_switch_id`), `solo` (`1`); includes `garden_zone_entry.yaml` twice; no `!secret`, no `api:`/`wifi:`/`ota:`, no `GPIO\d+`. |
| unit | `test_device_unchanged` (existing) | Still passes (no `garden_zones`/`garden_zone`/`external_components` in device files). |
| config | `test_groups_config[pinned\|minimum]` | The staged groups config passes `esphome config`; the printed config lists both `garden_zone` entries from the two includes in include order. |
| config | `test_groups_config_errors[...]` | Small generated configs (tmp dir) fail `esphome config` with the expected message: unknown group; mixed pins; `lane` with `all`; same pump in two groups; same `valve_switch_id` twice; list-form `garden_zones` plus a `garden_zone:` entry. Pinned only. |
| config | `test_garden_zone_dict_form_collapses` | Two packages each with a **dict-form** `garden_zone:` → `esphome config` shows **one** merged zone (documents the ESPHome merge behaviour behind the list-item rule). Pinned only. |
| config | `test_groups_codegen[pinned\|minimum]` | `esphome compile --only-generate` of the staged groups config; generated `main.cpp` contains lanes `beds_lane_0`, `beds_lane_1`, `lawn_lane_0`, `lawn_lane_1`, `solo_lane_0` (no `solo_lane_1`), `set_lane_mode(true)` per lane, `add_controller` 5×4 = 20 times, the lawn pump configured on the 3 lawn valves only, and 3 `GardenZonesGroup` objects. |
| host | `test_groups_host_compile` (pinned) | The staged groups config compiles for `host` (own fixed staging dir under `.esphome/`, like 008). |
| host | `test_groups_host_scenario` (pinned) | Runs the program twice (scenario below) and asserts the `GZTEST` lines. |

### Groups host scenario (`tests/configs/garden_zones_groups_sim.yaml`)
Test harness, not a device config (header says so, like 008). `hardware/sim.yaml` gives `board_relay_1..3`; the
config adds local template switches `gz_valve_4`..`gz_valve_7` and `gz_pump` (`internal: true`, `optimistic: true`,
`restore_mode: ALWAYS_OFF`). Groups and zones (2 s run durations unless stated):
- `beds`, `max_parallel: all`: zones 0, 1 = `board_relay_1`, `board_relay_2`, both via `garden_zone_entry.yaml`
  included twice (proves the package merge at runtime);
- `lawn`, `max_parallel: 2`, `pump_switch_id: gz_pump`: inline zones 0, 1, 2 = `board_relay_3`, `gz_valve_4`,
  `gz_valve_5` → lanes `[[0,2],[1]]`;
- `solo`, `max_parallel: 1`: inline zones 0, 1 = `gz_valve_6`, `gz_valve_7`, each with an `enable_switch`.
A 200 ms `interval` logs `GZTEST state=<v1..v7 as 0/1> pump=<0/1>` whenever it changes (small lambda reading switch
states only, principle 1); scripts log `GZTEST <group>_queue=<round order>` and `GZTEST <group>_active=<zones>`.
Steps (`on_boot`, late priority; `wait_until` with timeouts instead of fixed long delays):
1. log `restored lawn=…` (and beds/solo); wait 1.5 s; log the queues again (`boot_lawn=…`); clear all lane queues.
2. **beds parallel:** `queue_zone` beds 0 and 1 (3 s), `start_group_queue: beds` → some state line has v1=1 and v2=1
   together; then both 0.
3. **lawn lanes + pump:** `queue_zone` lawn 0 (4 s), 1 (2 s), 2 (2 s) → `lawn_queue=0,1,2`; `is_zone_queued` 2 = 1;
   `remove_queued_zone` 2 → `lawn_queue=0,1`; queue 2 again; `start_group_queue: lawn`. Assert: v3 and v4 on together;
   v5 never on together with v3 (same lane); on **every** state line where v3, v4 or v5 is 1, pump is 1; pump stays 1
   when v4 finishes while v3 runs (cross-lane hold); after the lawn queue drains, the last state line has pump=0;
   beds/solo valves stay 0 during this step.
4. **solo, `max_parallel: 1`:** queue 0, 1, start → v6 and v7 never on together, both run once, then idle (no extra
   cycle after the queue drains: checks Decision 5); then turn off zone 1's enable switch, `start_group_cycle: solo` →
   only v6 runs, then idle.
5. **manual run keeps other lanes:** lawn queue 0 (4 s) and 1 (4 s), start; after ~1 s `run_zone` lawn 2 (2 s) → zone 0
   pauses and resumes after zone 2 (008 semantics within lane 0) while zone 1 in lane 1 keeps running uninterrupted
   (v4 stays 1 across the manual run); pump stays 1 throughout.
6. **group shutdown is scoped:** start beds 0 (6 s) via `run_zone` and lawn queue 1 (6 s); `shutdown_group: lawn` →
   within 1 s v4=0 and pump=0, while v1 stays 1; then `shutdown_group: beds`.
7. leave lawn 1 and 2 queued (not started), `global_preferences->sync()`, log `GZTEST done`.
Boot 2: `restored lawn=2,1` (zone 2 is first in lane 0, zone 1 first in lane 1; round order lists lane 0 first); no
state line with any valve or the pump at 1 before step 2 (a restored queue never starts by itself); per-lane keys are
distinct (beds/solo restore empty).

## Acceptance criteria
- [ ] `sh script/test-cpp` → builds with `-Wall -Wextra -Werror`; all cases pass (old and new). Ran in the devcontainer
      or another environment with a compiler (say which).
- [ ] `uv run pytest -m unit` → all pass.
- [ ] `uv run pytest tests/test_garden_zones.py` → all pass with `GP_REQUIRE_CXX=1` (no skips); `minimum` rows pass or
      are `xfail(strict=True)` under the Gate with the error recorded.
- [ ] `script/lint` → clean; `esphome config OK: garden-pilot.yaml`.
- [ ] `script/test` → all pass; local wall time before/after in Implementation notes.
- [ ] `git diff master --stat -- garden-pilot.yaml garden-pilot-sim.yaml packages hardware .github script
      tests/configs/garden_zones_sim.yaml` → empty.
- [ ] `git grep -n 'GZ-PATCH-BEGIN' -- components` → ids are exactly `includes`, `queue-api`, `queue-persist`,
      `queue-skip-disabled`, `manual-run`, `groups`, `lanes`, each with a `PATCHES.md` section.
- [ ] `git grep -n 'garden_zone:' -- tests/configs` → every hit is followed by a list item (also enforced by
      `test_garden_zone_entries_are_lists`).
- [ ] `docs/SPEC.md` (§4, §4.2, §5, §9 item 7) and `CLAUDE.md` (one layout row, one gotcha line) updated as listed,
      nothing else in them; `components/garden_zones/README.md` documents the dict form, lane limits, pump sharing, the
      list-item rule and the new actions.
- [ ] CI on the PR green for `checks`, `compile (pinned)`, `compile (minimum)`; CI timings of both host builds recorded
      against the Gate.
- [ ] Implementation notes say that nothing ran on a real device, list the scenario results of both boots, and the
      2026.6.3 results.

Needs real hardware: nothing in this task. A real pump/valve behaviour check (relay timing, pump hold between lanes) is
part of the hardware check of task 014 or of the lawn module, whichever first drives a real pump.

## Out of scope
- Max on-time watchdog for valves **and the pump** (pump forced off after a configurable maximum on-time or when on with
  no open valve), soil-moisture skip (013). Until then no device loads the component.
- Switching `bed.yaml` / `irrigation.yaml` / the greenhouse page to `garden_zones`, 1-bed greenhouse, ESP32 compile with
  the component, HA entity-name continuity (014; see human decision 4 for the group entities).
- Group-level HA entities (main switch, auto advance, queue enable, standby, multiplier, repeat), group pause/resume, a
  queue text sensor, `gp_*` scripts (014 / stage 8). Per-zone HA switch still uses stock `start_single_valve` on its lane.
- Dynamic lanes, a pump shared by several groups, valve overlap / open delay per group, master valves (backlog §9.1).
- Changing the 008 list form, its scenario, or stock `sprinkler`; refactoring upstream code.
- The open 008 follow-ups listed in Context.

## Decisions (human, 2026-10-02)
1. Lane assignment for `max_parallel: N` is round-robin by zone order; manual pinning (`lane:`) is all-or-none per group.
2. `queue_zone` never starts a lane by itself; starting is always explicit (`start_group_queue`).
3. A pump shared by two groups is rejected (validation error) for now.
4. No group HA entities in 012. In 014 the existing "Greenhouse irrigation" / "Greenhouse auto advance" entities become
   group entities with the same names. Auto advance = one switch per group: on → each lane advances to its next zone;
   off → all lanes stop after their current zone.
5. `components/garden_zone/` is MIT.
6. Task 013's max on-time watchdog covers the pump too: forced off when on longer than a limit or when on with no open
   valve; the values are configurable (noted in the stage plan line in Context).
7. The group queue view interleaves lanes: the first entry of each lane, then the second, and so on.

<!-- Filled in by implementer -->
## Implementation notes
- **Where checks ran:** dev container `gp-dev-012` (this checkout mounted at `/workspaces/garden-pilot`, `UV_OFFLINE=1`,
  `GP_REQUIRE_CXX=1`). Nothing ran on a real device; the device config is untouched (`test_device_unchanged`).
- **Gate outcome:** the codegen-time lane ids worked functionally but were registered after the core `to_code` had
  emitted `ESPHOME_COMPONENT_COUNT` (staged groups build: `defines.h` 36 vs 40 `App.register_component_` calls), so the
  last registered components never got `setup()`/`loop()` (the host scenario hung at step 5). Human decision
  2026-10-08: option (b) - declare the lane ids from the full config in `FINAL_VALIDATE_SCHEMA`
  (`final_validate_groups` adds `<group>_lane_<n>` to `CORE.component_ids` and rejects a clash with any id declared
  in the config, so `garden_zone:` entries from other packages keep working). Evidence after the fix: staged groups
  build `ESPHOME_COMPONENT_COUNT 42` vs 41 `App.register_component_` calls; the scenario reaches every step.
- **Review round 1:** new `test_groups_component_count` (count >= registered calls; pinned and minimum, via a
  module-scoped `--only-generate` fixture shared with `test_groups_codegen`) passes; new error case `lane-id-clash`;
  step 4b of the scenario waits for "solo idle" again and the test asserts every valve is off at its end; group `id`
  is required; the unreachable "list form + garden_zone" branch is dropped (documented in the README: it fails at the
  entry's `group:` reference); dropped pinned lanes are logged (info) and the README notes the renumbering;
  `GardenZonesGroup::dump_config()` logs an error when `LaneMap::valid()` is false; PATCHES.md notes the lane
  auto-advance staying `true` after `start_group_cycle`; SPEC §9 item 7 trimmed.
- **Scenario deviations from the task text:** step 5 lane-1 run is 9 s (not 4 s), step 6 runs 20 s (not 6 s), 1.5 s
  (not 1 s) after `shutdown_group`; reasonable timing margins for the 200 ms state log.
- **Results:** `script/test-cpp` 13 cases ok; `script/lint` ok; `tests/test_garden_zones.py` all pass (non-host rows
  ~12 s, host rows ~190 s incl. both boots of the scenario); minimum (2026.6.3) rows (`config`, `codegen`,
  component count, error cases) pass; full `script/test`: 558 passed, 1 skipped in 4m07s (previous run before the
  fix: 7m25s while the scenario hung on its timeouts). Baseline master time was not measured.
- **Not done:** CI host-build timings vs the 6-minute Gate (no PR yet) - record when the PR runs.
## Follow-ups
- Record CI timings of both host builds against the Gate once the PR runs.
- 013/014: a group auto-advance switch must set the lanes' stored auto-advance explicitly (see PATCHES.md `lanes`).
- Open 008 follow-ups listed in Context remain open.
