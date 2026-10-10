# 013 — `garden_zones` safety: max on-time watchdog (valves and pump) and per-zone soil-moisture skip

Status: in-review
Roadmap: SPEC §9 item 7 "`garden_zones` component" (part 3 of 4: 008 core, 012 groups/lanes, **013 watchdog + soil**,
014 device switch)
Spec sections: SPEC §3, §4 (garden_zones: Safety, Soil moisture, pump), §6, §7 items 3-4, §9 item 7; CLAUDE.md core
principles 1, 2, 4, 7
Hardware check: none. The device keeps the stock `sprinkler` (`garden-pilot.yaml`, `garden-pilot-sim.yaml`,
`packages/`, `hardware/` are not touched). Everything runs in C++ unit tests and host test builds with template relays.
The watchdog on real relays is part of the 014 hardware check.

**Stacked on task 012.** 012 (groups, lanes, shared pump) is implemented but not merged yet. Branch
`task/013-watchdog-and-soil-skip` from `task/012-groups-and-lanes`; the PR targets that branch (or `master` after 012
is merged, then rebase before review). Build on 012's files as they are: `groups.py`, `group.h`, `lanes.h`,
`lane_plan.py`, `components/garden_zone/`. If the 012 review changes one of them, re-read it before you start. Do not
edit 012's test config `tests/configs/garden_zones_groups_sim.yaml` or its scenario.

## Goal
The groups form of `garden_zones:` gets the safety net that SPEC §4 and principle 4 require before 014 may load the
component on a device: a **watchdog** that watches every zone's raw valve switch and the group's pump switch by their
real state, independent of the sprinkler state machine and its run durations, and forces them off when a valve has been
on longer than its `max_on_time`, when the pump has been on longer than `pump_max_on_time`, or when the pump is on with
no open valve of its group for longer than `pump_idle_timeout`. A trip is logged at ERROR, fires an `on_watchdog_trip`
trigger and latches a lockout (zone, or whole group for a pump trip) until `garden_zones.reset_watchdog` or a reboot.
Every limit has a safe default and a hard range; the watchdog is on by default and can be disabled only explicitly with `never` (human decision 2026-10-10, see below). Second, a zone can have an optional
**soil-moisture sensor**: when the zone's turn comes in a queue or a cycle and the soil is wetter than the threshold,
the zone is skipped (logged); an unavailable or stale reading has a defined, configurable behaviour. Pure logic is unit
tested in C++ and Python; a host scenario proves that the actuators really go off.

## Context

### What 012 gives us (read the files; do not re-plan them)
- `groups.py`: `GROUP_SCHEMA`, `ZONE_SCHEMA` (shared with `components/garden_zone/`), `final_validate_groups()`
  (called from the `groups` region of `__init__.py`), `to_code_groups()` generating lanes `<group>_lane_<n>` and one
  `GardenZonesGroup` per group (`group.h`), group actions `garden_zones.queue_zone` / `run_zone` / ... .
- A pump belongs to exactly one group (validation error otherwise), so "no open valve of its group" is well defined.
- Lanes are stock `Sprinkler` controllers in lane mode; their queue persists; a restored queue never starts by itself.
- Fork discipline (008): every change in a forked file (`__init__.py`, `automation.h`, `sprinkler.h`, `sprinkler.cpp`)
  sits in a `GZ-PATCH-BEGIN(<id>)` / `GZ-PATCH-END(<id>)` region documented in `PATCHES.md`
  (`test_fork_diff_is_documented`, `test_patch_ids_documented`). **New logic goes into new, non-forked files.**
- `script/test-cpp` builds every `tests/cpp/*.cpp` (C++17, `-Wall -Wextra -Werror`); new sources are picked up
  automatically. Run cpp/host checks in the devcontainer (`GP_REQUIRE_CXX=1` there) and say where they ran.

### Sources checked (pinned ESPHome 2026.9.1; fork base = tag 2026.9.1; minimum 2026.6.3, SPEC §6)
- **How the stock code switches actuators** (`components/garden_zones/sprinkler.cpp`, identical to upstream outside
  the GZ regions): `SprinklerValveOperator::run_()` / `kill_()` call `valve_on_()` / `valve_off_()` (raw
  `valve_switch->turn_on/turn_off()`) and `pump_on_()` / `pump_off_()` → `Sprinkler::set_pump_state()`, which keeps the
  pump on while another registered controller reports `pump_in_use()`. A valve is turned off only by its operator's
  `loop()` (`start_delay_ + run_duration_` elapsed), by `stop()` / `shutdown()`, or by `all_valves_off_()`. Nothing in
  the stock code bounds the on-time of a raw switch that was turned on by anyone else, and `Sprinkler::loop()` disables
  itself when idle (`disable_loop()`). Hence the watchdog is a **separate component** that polls the raw switches'
  `state` in its own `loop()` (never disabled) and calls `turn_off()` itself; it does not use sprinkler timers.
- Between two zones of one lane without a switching delay the next valve starts in the same transition
  (`fsm_transition_from_valve_run_`), so a shared pump typically stays on **continuously for a whole queue**:
  `pump_max_on_time` bounds a watering session, not one zone. Documented in the README.
- Pump-before-valve and valve-after-pump phases (checked in the fork: `set_valve_start_delay` /
  `pump_start_valve_delay` sets `start_delay_is_valve_delay_`, and `SprinklerValveOperator::start()` then calls
  `pump_on_()` first): `pump_start_valve_delay` is the "pump on, no valve open yet" phase and `pump_stop_pump_delay`
  (pump stays on after the valve) the "valve closed, pump still on" phase, so "pump on, no valve open" is a legal
  state for that long. `pump_start_pump_delay` (valve first) and `pump_stop_valve_delay` (pump off first, valve stays
  open) only make "valve on" last longer than the run. Hence the validation rules below.
- **Where a zone's turn is decided** (`Sprinkler::load_next_valve_run_request_`): the `queue-skip-disabled` region
  drops disabled entries from the queue head with `queue_ops::pop_next_enabled(queue, predicate)`; the cycle branch
  picks `next_valve_number_in_cycle_()`, which skips valves that are disabled or already `valve_cycle_complete`.
  Manual runs (`run_valve`, `start_single_valve`, the zone's switch entity, a resume after a manual run) arrive as a
  pending `next_req_` and never reach those branches. `prep_full_cycle_()` turns **on** every enable switch when no
  valve is enabled (`any_valve_is_enabled_()`), so a skip must **not** be implemented by changing `valve_is_enabled_()`.
  Cycle repeats (`repeat_count_`) call `prep_full_cycle_()` and pick the first valve directly; lanes have no repeat
  entity (no controller-level entities, 012 Decision 4), so the repeat path is not hooked (documented limit).
- **Sensors** (`esphome/components/sensor/sensor.h` at 2026.9.1 and 2026.6.3, fetched from GitHub): `float state` is
  NaN until a value arrives; `add_on_state_callback(F&&)` takes `void(float)`. `has_state()` lives in `EntityBase`
  (`esphome/core/entity_base.h` at 2026.9.1). Not diffed at 2026.6.3: the `config`/`codegen` rows on `minimum` prove it.
- **Switch restore modes** (`esphome/components/switch/__init__.py`, 2026.9.1): `RESTORE_DEFAULT_OFF`,
  `RESTORE_DEFAULT_ON`, `ALWAYS_OFF`, `ALWAYS_ON`, `RESTORE_INVERTED_DEFAULT_OFF`, `RESTORE_INVERTED_DEFAULT_ON`,
  `DISABLED`. The breadboard profile uses `RESTORE_DEFAULT_OFF` for `board_relay_N`, `hardware/sim.yaml` uses
  `ALWAYS_OFF` (CLAUDE.md principle 4 allows both). Read the resolved `restore_mode` of the referenced switch from
  `fv.full_config` (defaults are filled in there); `switch_schema()` takes `default_restore_mode` per platform, so
  confirm in the source what template and gpio switches resolve to when the key is omitted (012's error-test head has
  template switches without `restore_mode`; they must still validate).
- ESPHome triggers with arguments (`Trigger<int, std::string>` + `automation.build_automation(trigger, [(int, "zone"),
  (cg.std_string, "reason")], conf)`) are the stock pattern; codegen-time IDs as in 012 (`ID(..., is_declaration=True,
  type=...)` + `CORE.component_ids`).

## Decisions (planner; safe defaults chosen, see Open questions)
- **Human decision 2026-10-08:** keep `max_on_time` default 60 min, overridable per group and per zone (as below,
  up to the 4 h cap). In 014, run durations above the limit are lowered or the user raises `max_on_time`.

### 1. Configuration (new keys in `groups.py`; `garden_zone:` gets the zone keys automatically via `ZONE_SCHEMA`)
```yaml
garden_zones:
  groups:
    - id: lawn
      max_parallel: 2
      pump_switch_id: lawn_pump
      max_on_time: 60min          # default for the group's zones; default 60min; range 1s..4h
      pump_max_on_time: 2h        # only with pump_switch_id; default 2h; range 1s..4h
      pump_idle_timeout: 10s      # only with pump_switch_id; default 10s; range 1s..5min
      on_watchdog_trip:           # optional trigger; vars: zone (int, -1 = pump), reason (std::string)
        - logger.log: ...
  zones:
    - group: lawn
      valve_switch: "Lawn 1"
      valve_switch_id: lawn_valve_1
      run_duration: 15min
      max_on_time: 30min          # optional per-zone override; range 1s..4h
      soil_moisture:              # optional
        sensor_id: lawn_1_soil    # use_id(sensor.Sensor), required
        skip_above: 60            # float, same unit as the sensor (usually %), required
        max_age: 30min            # optional, default 30min, range 1s..24h; an older reading counts as unavailable
        when_unavailable: water   # water | skip, default water
```
- **Superseded by the human decision 2026-10-10:** no 4 h / 5 min caps; any duration from 1 s (technical maximum 30 days)
  or `never` (disabled explicitly, WARN at boot, run-vs-limit checks skipped). Original text: no way to disable the
  watchdog, `max_on_time` and `pump_max_on_time` capped at 4 h, `pump_idle_timeout` at 5 min. `pump_max_on_time` / `pump_idle_timeout` without `pump_switch_id` → error.
- Validation (pure rules in a new `components/garden_zones/safety_rules.py`, standard library only, called from
  `final_validate_groups()` and from the group/zone schemas; messages name the group and zone):
  - **Zone limit vs. configured run:** `longest_run + pump_delays + 2 s <= max_on_time`, where `longest_run` =
    `run_duration`, or the `run_duration_number`'s `max_value` (× 60 when its `unit_of_measurement` is `min`, as
    `Sprinkler::valve_run_duration` does), and `pump_delays` = the larger of the group's `pump_start_pump_delay` /
    `pump_start_valve_delay` (conservative) plus its `pump_stop_valve_delay` (0 if none); the limit is the zone's own
    `max_on_time` if set, else the group's. A zone with the stock default number `max_value` (86400 s) therefore fails
    under the default limit: the message tells the user to lower `max_value` or raise `max_on_time`. Run durations
    passed at runtime (`queue_zone` / `run_zone` `run_duration`) are not checked here; the watchdog catches them.
  - `pump_max_on_time >=` every zone's effective `max_on_time` in the group (else one normal zone run trips the pump).
  - `pump_idle_timeout >= max(pump_start_valve_delay, pump_stop_pump_delay) + 2 s`.
  - The raw `valve_switch_id` and `pump_switch_id` switches must resolve to `restore_mode` `ALWAYS_OFF` or
    `RESTORE_DEFAULT_OFF`; any other mode → error ("an actuator must be OFF after boot").
- The 008 **list form** of `garden_zones:` gets no watchdog and no soil skip (it stays a test-only path); README and
  SPEC say that a device must use the groups form (014 does).

### 2. Watchdog runtime
- **Pure core** `components/garden_zones/watchdog_core.h` (header-only, standard library only, namespace
  `esphome::garden_zones::watchdog`, GPLv3 short header like `lanes.h`). Suggested API (names may change if the tests
  follow):
  - `enum class Reason : uint8_t { MAX_ON_TIME, PUMP_MAX_ON_TIME, PUMP_IDLE, LOCKED_OUT, STILL_ON }`
  - `class OnTimer { void update(bool on, uint32_t now); bool on() const; uint32_t on_for(uint32_t now) const; }` —
    continuous on-time since the last off→on edge seen, **wrap-safe** (`now - since` in `uint32_t`); an actuator seen
    on at the first update is timed from that update.
  - `struct Command { enum Kind { FORCE_OFF_ZONE, FORCE_OFF_PUMP, SHUTDOWN_LANE_OF_ZONE, SHUTDOWN_GROUP } kind;
    int zone; Reason reason; bool new_trip; }`
  - `class GroupGuard { GroupGuard(std::vector<uint32_t> zone_max_ms, std::optional<uint32_t> pump_max_ms,
    std::optional<uint32_t> pump_idle_ms); std::vector<Command> update(const std::vector<bool> &zones_on,
    std::optional<bool> pump_on, uint32_t now); bool zone_locked(size_t) const; bool pump_locked() const;
    bool tripped() const; void reset(uint32_t now); }`
  - Rules: a zone trips when `on_for > zone_max_ms` (strictly greater) → `SHUTDOWN_LANE_OF_ZONE` + `FORCE_OFF_ZONE`
    (`new_trip = true`), zone latched. The pump trips when `on_for > pump_max_ms` (reason `PUMP_MAX_ON_TIME`) or when
    it has been on with **no zone of the group on** for more than `pump_idle_ms` (reason `PUMP_IDLE`; the idle timer
    starts at the later of "pump on" and "last zone off") → `SHUTDOWN_GROUP` + `FORCE_OFF_ZONE` for every zone that
    is on + `FORCE_OFF_PUMP`; pump **and all zones of the group** latched. While latched, an actuator seen on gets
    `FORCE_OFF_*` (reason `LOCKED_OUT`, plus `SHUTDOWN_LANE_OF_ZONE` for a zone) on the same update; a tripped
    actuator still on after a forced off is commanded off again at most once per 1000 ms (reason `STILL_ON`).
    `new_trip` is true only on the first command of a trip. `reset()` clears all latches and restarts the timers of
    actuators that are still on from `now`.
- **ESPHome glue** `components/garden_zones/watchdog.h` (+ `.cpp` if preferred): `class GroupWatchdog : public
  Component` (setup priority after hardware, e.g. `setup_priority::DATA`; `loop()` never disabled). It holds the raw
  valve switches (zone order), the pump switch, the group's lanes and the zone → (lane, valve) routing (from the
  group), a `GroupGuard`, and a `Trigger<int, std::string>`. `setup()` turns every monitored actuator off. `loop()`
  reads `switch->state` of every actuator, calls `GroupGuard::update(..., millis())` and executes the commands:
  `SHUTDOWN_LANE_OF_ZONE` → `lane->shutdown(false)` (queue kept, nothing restarts by itself); `SHUTDOWN_GROUP` →
  `shutdown(false)` on every lane of the group; `FORCE_OFF_*` → raw `turn_off()`. Order: shutdown first, then the raw
  `turn_off()` (idempotent). Logs (tag `garden_zones.watchdog`): new trip → **ERROR** `group '<name>' zone <n>
  ('<switch name>') on for <s> s > max_on_time <s> s: forced off, zone locked` (pump variants name the reason);
  `LOCKED_OUT` → WARN and `STILL_ON` → ERROR ("still ON after a forced off: stuck relay?"), each rate-limited to once
  per 10 s per actuator. The trigger fires once per new trip with `zone` (-1 for the pump) and `reason`
  (`max_on_time`, `pump_max_on_time`, `pump_idle`). Latches are **not persisted** (no preferences in the watchdog).
- One watchdog per group, created by `to_code_groups()` with a codegen-time ID `<group id>_watchdog`; the group gets a
  pointer to it (`GardenZonesGroup::set_watchdog`). Limits are passed in milliseconds.
- YAML: action `garden_zones.reset_watchdog: <group id>` (clears every latch of the group, INFO log) and condition
  `garden_zones.watchdog_tripped: <group id>` (true while any latch of the group is set). Registered in `groups.py`,
  classes in `group.h` or `watchdog.h` (forked `automation.h` untouched).

### 3. Zone skip hook (one small fork patch, `zone-skip`)
- `sprinkler.h` / `sprinkler.cpp`, new region `zone-skip`: `void set_valve_skip_check(std::function<const char *(size_t
  valve)> check)` stored in a member; `nullptr` result = run, otherwise the reason text for the log. Used only in
  `load_next_valve_run_request_` and only when no request is already pending and no manual run is active
  (`!next_req_.has_request() && !manual_run_active_`):
  - **queue:** entries at the head for which the check returns a reason are dropped like disabled ones (saved,
    INFO log `Valve %zu skipped: <reason>`); combine with the existing `queue-skip-disabled` loop (one predicate
    "enabled and not skipped", adjust that region and its `PATCHES.md` section) so mixed disabled/skipped heads work;
  - **cycle:** before the cycle branch picks a valve, the valves that `next_valve_number_in_cycle_(first_valve)` would
    return are checked in order; a skipped valve is marked cycle-complete (INFO log) and the next one is checked.
  - Without a check set (stock configs, 008 list form) behaviour is unchanged.
- `GardenZonesGroup` sets one check per lane mapping (lane, valve) → zone and answering, in this order: zone locked by
  the watchdog → `"locked by the watchdog"`; soil verdict skip → `"soil moisture 72.0 > 60.0"` /
  `"soil sensor unavailable"`. `GardenZonesGroup::run_zone()` refuses a **locked** zone (WARN, nothing starts) but
  never applies the soil rule. A zone's HA switch (stock `start_single_valve` on its lane) bypasses the group: for a
  locked zone the watchdog forces it off on its next loop (lockout enforcement); the soil rule does not apply to it.

### 4. Soil skip
- **Pure core** `components/garden_zones/soil_skip.h` (standard library only, namespace
  `esphome::garden_zones::soil`): `enum class WhenUnavailable { WATER, SKIP }`, `enum class Verdict { RUN, SKIP_WET,
  RUN_UNAVAILABLE, SKIP_UNAVAILABLE }`, `Verdict decide(bool has_value, float value, uint32_t age_ms, float
  skip_above, uint32_t max_age_ms, WhenUnavailable)`. Unavailable = no value, NaN, or `age_ms > max_age_ms`. Wet =
  `value > skip_above` (strictly greater; equal runs). Plus a wrap-safe `age_ms(now, last_update)` helper.
- Glue in `group.h` (or a small `zone_soil.h`): per zone with `soil_moisture`, the sensor pointer, threshold, max age,
  policy and the `millis()` of the last state callback (`add_on_state_callback`), so a sensor that stopped updating is
  stale. Evaluated **when the zone's turn comes** (queue head / cycle pick), not when it is queued; a running zone is
  not stopped when the soil gets wet (follow-up). `RUN_UNAVAILABLE` logs WARN `zone <n>: soil sensor unavailable,
  watering as scheduled`.
- Applies to queue and cycle runs only; manual runs (`run_zone`, the zone switch) always run (the user asked for it).

### 5. Coexistence
The 012 scenario and codegen checks keep passing unchanged (default limits are far above their run durations). The
groups config gets a default watchdog per group; `test_groups_codegen` counts stay valid (watchdogs are new objects,
not lanes).

**Gates.**
- If the soil sensor API (`has_state`, callback) or the trigger codegen differs on 2026.6.3: `xfail(strict=True)` the
  `minimum` row with the exact error + Follow-up (as in 008/012); do not add version switches.
- CI time: the new host build is **pinned only**; `minimum` gets `config` + `compile --only-generate`. If `script/test`
  in CI grows by more than **4 minutes** over the 012 branch, report the timings and propose folding the safety scenario
  into the 012 groups config as a Follow-up. Record the measured timings in Implementation notes.

## Files
Component (`components/garden_zones/`, GPLv3):
- create: `watchdog_core.h` — pure guard (Decision 2).
- create: `watchdog.h` (+ `watchdog.cpp` optional) — `GroupWatchdog` component, reset action, tripped condition.
- create: `soil_skip.h` — pure soil verdict (Decision 4).
- create: `safety_rules.py` — pure validation rules (Decision 1), no `esphome` import.
- modify: `groups.py` — group/zone keys, validation calls, watchdog + soil codegen, action/condition/trigger registration.
- modify: `group.h` — watchdog pointer, per-lane skip checks, soil per zone, lockout refusal in `run_zone`.
- modify: `sprinkler.h`, `sprinkler.cpp` — region `zone-skip` (+ the adjusted `queue-skip-disabled` region).
- modify: `PATCHES.md` (section `zone-skip`, updated `queue-skip-disabled`, new non-forked files), `README.md` (watchdog
  semantics, defaults and ranges, pump session limit, lockout/reset, soil skip, unavailable policy, list form has no
  watchdog).

Tests:
- create: `tests/cpp/test_watchdog.cpp`, `tests/cpp/test_soil_skip.cpp`.
- create: `tests/configs/garden_zones_safety_sim.yaml` — safety host scenario (below).
- modify: `tests/test_garden_zones.py` — new checks; `NEW_FILES` / `ALL_FILES` / header / ESPHome-free checks cover the
  new files.

Docs (short edits only):
- modify: `docs/SPEC.md` — §4 "Safety" and "Soil moisture" bullets (what exists now, defaults, unavailable policy),
  §9 item 7 one status sentence.
- modify: `CLAUDE.md` — only one gotcha line if the implementer finds it useful ("a `garden_zones` group's watchdog
  cannot be disabled; a zone's `run_duration_number` `max_value` must fit under `max_on_time`"). Nothing else.

About 17 paths (above the ~10-file budget: 2 short doc edits, 3 small pure files, 1 test config). If the implementer
runs out of budget, cut in this order: the stuck-relay scenario step → the soil cycle step → Follow-ups. The watchdog
steps of the scenario and all C++/unit checks are not cuttable.

## Checks to write first
| Level | Test | Asserts |
|---|---|---|
| cpp | `test_watchdog.cpp` "OnTimer continuous on-time" | off at 0, on at 100 → `on_for(1100)` = 1000; off at 1200 → 0; on at 1300 → timed from 1300; on at the first update (500) → timed from 500. |
| cpp | "OnTimer millis wrap" | on at `0xFFFFFC18`, `on_for(1000)` = 2000. |
| cpp | "zone trips strictly after max_on_time" | limit 3000, on at 0: update at 3000 → no command; at 3001 → `SHUTDOWN_LANE_OF_ZONE` + `FORCE_OFF_ZONE` zone 0, `MAX_ON_TIME`, `new_trip`; `zone_locked(0)`; zone 1 (on since 0, limit 5000) untouched; `pump_locked()` false. |
| cpp | "trip fires once, then lockout and retries" | still on at 3100 → no command (inside 1000 ms); at 4002 → `FORCE_OFF_ZONE` `STILL_ON`, `new_trip` false; off at 4100, on again at 4200 → `FORCE_OFF_ZONE` + shutdown `LOCKED_OUT` on that update. |
| cpp | "reset clears latches and restarts timers" | after a trip, `reset(5000)` with the zone still on → no command until 8001, trip again at 8001; `tripped()` false right after reset. |
| cpp | "pump idle" | idle limit 2000: pump on at 0, no zone → `PUMP_IDLE` at 2001 with `SHUTDOWN_GROUP` + `FORCE_OFF_PUMP`; pump + zone on → never idle; zone off at 5000 with pump on → idle trip at 7001, not earlier. |
| cpp | "pump max on-time across alternating zones" | pump on from 0, zones alternate every 1500 ms (each < zone limit 3000), pump limit 5000 → no zone trip; at 5001 `PUMP_MAX_ON_TIME`: `SHUTDOWN_GROUP`, `FORCE_OFF_ZONE` for the zone that is on, `FORCE_OFF_PUMP`; every `zone_locked(i)` and `pump_locked()` true. |
| cpp | "no pump configured" | `pump_on` = nullopt → never a pump command; zone rules unchanged. |
| cpp | `test_soil_skip.cpp` "threshold" | `skip_above` 60: 60.0 → `RUN`; 60.1 → `SKIP_WET`; 10 → `RUN`. |
| cpp | "unavailable" | no value / NaN / `age_ms` 3001 with `max_age_ms` 3000 → `RUN_UNAVAILABLE` (WATER) or `SKIP_UNAVAILABLE` (SKIP); `age_ms` == `max_age_ms` is fresh; `age_ms(1000, 0xFFFFFC18)` = 2000. |
| cpp | `test_cpp_unit_tests` (existing) | Wrapper still runs all cases (old and new). |
| unit | `test_safety_rules_zone_limit` | `safety_rules` (imported by path): run 1 s / limit 3 s → ok; run 2 s / limit 3 s → error (2 + 0 + 2 > 3); `run_duration_number` `max_value` 120 `min` with the 60 min default → error naming `max_value` and `max_on_time`; 50 `min` → ok; a `pump_start_pump_delay` is added to the run. |
| unit | `test_safety_rules_pump` | `pump_max_on_time` below a zone's effective limit → error; `pump_idle_timeout` 3 s with `pump_start_valve_delay` 2 s → error, 4 s → ok; `pump_*` keys without a pump → error. |
| unit | `test_safety_rules_restore_mode` | `ALWAYS_OFF`, `RESTORE_DEFAULT_OFF` ok; `ALWAYS_ON`, `RESTORE_DEFAULT_ON`, `RESTORE_INVERTED_DEFAULT_OFF`, `RESTORE_INVERTED_DEFAULT_ON`, `DISABLED` → error naming the switch id. |
| unit | `test_safety_files_are_esphome_free` | `safety_rules.py` imports only the standard library; `watchdog_core.h`, `soil_skip.h` include only `<...>` standard headers. |
| unit | `test_watchdog_not_persisted` | `watchdog_core.h`, `watchdog.h` (and `.cpp`) contain no `preference` / `global_preferences`. |
| unit | `test_new_files_headers` (extended) | New component files have the short GPLv3 header. |
| unit | `test_fork_diff_is_documented`, `test_patch_ids_documented` (existing) | Pass with the new `zone-skip` region; ids in code == `PATCHES.md` sections. |
| unit | `test_safety_test_config_shape` | Safety config: includes `hardware/sim.yaml`; `external_components` `[garden_zones, garden_zone]`; groups `beds`, `lawn` (pump), `stuck` as in the scenario; every local raw switch `restore_mode: ALWAYS_OFF`; no `!secret`, no `api:`/`wifi:`/`ota:`, no `GPIO\d+`. |
| unit | `test_device_unchanged` (existing) | Still passes. |
| config | `test_safety_config[pinned\|minimum]` | Staged safety config passes `esphome config`; in the printed config zone 1 of `beds` shows the soil defaults `max_age: 30min` and `when_unavailable: water`. |
| config | `test_safety_defaults[pinned]` | The staged 012 groups config (no safety keys) passes `esphome config`; the printed config shows `max_on_time: 60min` on every group, `pump_max_on_time: 2h` and `pump_idle_timeout: 10s` on `lawn` only. |
| config | `test_safety_config_errors[...]` (pinned) | Generated configs fail with the expected message: run duration too close to `max_on_time`; default number `max_value` with default limit; `max_on_time: 0s`; `max_on_time: 5h`; `pump_max_on_time` without pump; `pump_max_on_time` < zone limit; `pump_idle_timeout` too short for `pump_start_valve_delay`; `pump_stop_valve_delay` pushes a run over `max_on_time`; per-zone `max_on_time` override too short for the run / above `pump_max_on_time`; unknown soil `sensor_id`; `when_unavailable: maybe`; valve switch `restore_mode: ALWAYS_ON`; pump `restore_mode: RESTORE_DEFAULT_ON`. |
| config | `test_safety_codegen[pinned\|minimum]` | `compile --only-generate` of the safety config: `main.cpp` has one `GroupWatchdog` per group (3), the configured limits in ms (3000, 5000, 2000), one `set_valve_skip_check` per lane, one `add_on_state_callback` per soil zone (2). |
| config | `test_groups_codegen` (012, existing) | Still passes unchanged. |
| host | `test_safety_host_compile` (pinned) | Safety config compiles for `host` (own fixed staging dir under `.esphome/`). |
| host | `test_safety_host_scenario` (pinned) | One run; asserts the `GZTEST` lines below with timings from `t=<millis>`. |
| host | `test_groups_host_scenario` (012, existing) | Still passes (no false trips with default limits). |

### Safety host scenario (`tests/configs/garden_zones_safety_sim.yaml`)
Test harness, not a device config (header says so). `hardware/sim.yaml` gives `board_relay_1..3`; local template
switches `gz_valve_4`, `gz_valve_5`, `gz_pump` (`internal`, `optimistic`, `ALWAYS_OFF`) and `gz_stuck` (state from a
`globals` flag; `turn_on_action` sets it, `turn_off_action` only increments a counter global: a welded relay). Template
sensors `gz_soil_1`, `gz_soil_2` (`update_interval: never`, set with `sensor.template.publish`; publish `NAN` for
unavailable). Groups (all run durations 1 s):
- `beds`, `max_parallel: all`, `max_on_time: 3s`: zone 0 `board_relay_1`; zone 1 `board_relay_2` with soil
  `gz_soil_1`, `skip_above: 60` (`max_age`, `when_unavailable` left at their defaults); zone 2 `board_relay_3` with soil
  `gz_soil_2`, `skip_above: 60`, `max_age: 3s`, `when_unavailable: skip`.
- `lawn`, `max_parallel: 2`, `pump_switch_id: gz_pump`, `max_on_time: 3s`, `pump_max_on_time: 5s`,
  `pump_idle_timeout: 2s`: zones 0 `gz_valve_4`, 1 `gz_valve_5`.
- `stuck`, `max_parallel: 1`, `max_on_time: 3s`: zone 0 `gz_stuck`.
Every group has `on_watchdog_trip` logging `GZTEST trip group=<g> zone=<zone> reason=<reason> t=<millis>`. A 50 ms
`interval` logs `GZTEST t=<millis> state=<relay1..3,v4,v5,stuck as 0/1> pump=<0/1>` on change (small lambda reading
switch states only). Steps (`on_boot` late priority, `wait_until` with timeouts; each step logs `step=N`):
1. `tripped beds=0 lawn=0 stuck=0` (condition); all actuators 0.
2. **Valve limit through the sprinkler:** `run_zone beds 0` with `run_duration: 20s` → relay 1 on at t0 and off at t1
   with 3000 < t1 − t0 <= 4000; one `trip group=beds zone=0 reason=max_on_time`; `beds.active_zones()` empty
   afterwards; relay 1 stays 0 for the next 3 s; `tripped beds=1`.
3. **Lockout:** `run_zone beds 0` → relay 1 never 1; `queue_zone beds 0` + `start_group_queue: beds` → relay 1 never 1
   and `beds` queue empty afterwards; raw `switch.turn_on: board_relay_1` → back to 0 within 500 ms; no second `trip`
   line for zone 0. `reset_watchdog: beds` → `tripped beds=0`; `run_zone beds 0` (1 s) runs ~1 s, no trip.
4. **Independent of the sprinkler:** raw `switch.turn_on: board_relay_3` (no sprinkler call) → off after 3000 < Δ <=
   4000 ms, `trip group=beds zone=2 reason=max_on_time`. `reset_watchdog: beds`.
5. **Normal pump use:** `queue_zone lawn 0` and `lawn 1`, `start_group_queue: lawn` → v4, v5 and pump run and stop, no
   `trip` line, `tripped lawn=0`.
6. **Pump idle:** raw `switch.turn_on: gz_pump` (no valve) → pump off after 2000 < Δ <= 3000 ms, `trip group=lawn
   zone=-1 reason=pump_idle`; `run_zone lawn 0` refused (v4 stays 0). `reset_watchdog: lawn`.
7. **Pump session limit:** raw pump on, then raw v4 / v5 alternating every 1.5 s (each valve < 3 s) → at 5000 < Δ <=
   6000 ms after the pump went on: pump, v4 and v5 all 0, one `trip ... zone=-1 reason=pump_max_on_time`, no zone
   trip. `reset_watchdog: lawn`.
8. **Soil skip** (asserted through relay states and the `beds` queue, logged as `queue=<...>` after each start):
   publish `gz_soil_1` = 72 → queue `beds 1`, start → relay 2 never 1, queue empty afterwards. Publish 40 → queue,
   start → relay 2 runs. Publish 72 → `run_zone beds 1` → relay 2 runs (manual ignores soil). Publish `NAN` → queue,
   start → relay 2 runs (default `water`). `gz_soil_2` never published → queue `beds 2`, start → relay 3 never 1
   (`skip`); publish 40 → runs; wait 4 s (stale > 3 s) → queue, start → relay 3 never 1. **Cycle:** `gz_soil_1` = 72,
   `gz_soil_2` = 40 → `start_group_cycle: beds` → relays 1 and 3 run, relay 2 never 1.
9. **Stuck relay:** raw `switch.turn_on: gz_stuck` → `trip group=stuck zone=0 reason=max_on_time` after 3000 < Δ <=
   4000 ms; the state stays 1; 4 s later the turn-off counter is >= 3 and <= 6 (retries at most once per second);
   then clear the flag → state 0; `tripped stuck=1` until `reset_watchdog: stuck`.
10. Log `GZTEST done`.
Global assertion over the whole run: no state line shows a valve continuously at 1 for more than its limit + 1000 ms
(the stuck relay in step 9 excepted), and the pump never more than 6000 ms.

## Acceptance criteria
- [x] `sh script/test-cpp` → builds with `-Wall -Wextra -Werror`; all cases (old and new) pass. Ran in the devcontainer
      or another environment with a compiler (say which).
- [x] `uv run pytest -m unit` → all pass.
- [x] `GP_REQUIRE_CXX=1 uv run pytest tests/test_garden_zones.py` → all pass, no skips; `minimum` rows pass or are
      `xfail(strict=True)` under the Gate with the error recorded.
- [x] `script/lint` → clean; `esphome config OK: garden-pilot.yaml`.
- [x] `script/test` → all pass; local wall time before/after in Implementation notes.
- [x] `git diff task/012-groups-and-lanes --stat -- garden-pilot.yaml garden-pilot-sim.yaml packages hardware .github
      script tests/configs/garden_zones_sim.yaml tests/configs/garden_zones_groups_sim.yaml
      tests/configs/garden_zone_entry.yaml` → empty.
- [x] `git grep -n 'GZ-PATCH-BEGIN' -- components` → ids are exactly `includes`, `queue-api`, `queue-persist`,
      `queue-skip-disabled`, `manual-run`, `groups`, `lanes`, `zone-skip`, each with a `PATCHES.md` section (the `valve-handover` region of review round 1 was removed in round 3).
- [x] `git grep -n -i 'preference' -- 'components/garden_zones/watchdog*'` → no hits.
- [x] `components/garden_zones/README.md` documents keys, defaults, ranges, validation rules, trip/lockout/reset, the
      pump session meaning of `pump_max_on_time`, soil skip scope (queue/cycle only) and the unavailable policy;
      `docs/SPEC.md` §4 and §9 item 7 updated as listed, nothing else.
- [ ] CI on the PR green for `checks`, `compile (pinned)`, `compile (minimum)`; CI timings recorded against the Gate.
- [x] Implementation notes say that nothing ran on a real device and list the scenario results.

Needs real hardware: nothing in this task. Watchdog trips on real relays (and that `RESTORE_DEFAULT_OFF` relays come up
off after a reboot during watering) belong to the 014 hardware check.

## Out of scope
- Switching the device / emulator to `garden_zones` (014), HA entities, `gp_*` scripts, UI notices (014 / stage 8).
- Watchdog or soil skip for the 008 list form; a watchdog for heating relays (stage 11, `climate` guards).
- Stopping a running zone when the soil becomes wet; soil re-check on cycle repeats; rain delay, flow/dry-run
  protection (backlog §9.1).
- Persisting latches across reboots; automatic latch clearing.
- Clamping a runtime `run_duration` of `queue_zone` / `run_zone` to the zone limit (the watchdog trips instead).
- The open 008/012 follow-ups.

### What 014 needs from 013
- The device must use the groups form; every bed zone needs a `run_duration_number` `max_value` that fits under the
  zone limit: today `bed.yaml` allows **120 min** while the default `max_on_time` is **60 min** → 014 lowers
  `max_value` or sets `max_on_time` (human decision, see Open questions).
- An HA-visible watchdog state: e.g. a template `binary_sensor` (`device_class: problem`) from
  `garden_zones.watchdog_tripped` and a reset button calling `garden_zones.reset_watchdog`, via `gp_*` (stage 8).
- Wiring `bed_soil.yaml` sensors (`gh_bedN_soil_moisture`, %) into `soil_moisture:` with a threshold (human value).
- The valve test page (10 s limit, `gp_valve_test_guard`) must keep working on top of group `run_zone`; its limit is
  far below `max_on_time` (no conflict).
- Hardware check: a forced trip on a real relay (e.g. a temporary `max_on_time: 10s`) and a reboot during watering.

## Open questions (safe defaults chosen; the human confirms or changes them)
1. **Limits:** zone `max_on_time` default 60 min, `pump_max_on_time` default 2 h, `pump_idle_timeout` default 10 s,
   hard cap 4 h for both on-time limits, no way to disable. Long drip runs (> 4 h) would need a higher cap.
2. **Unavailable soil sensor:** default `when_unavailable: water` (fail-open to the schedule; the run stays bounded by
   its duration and the watchdog) instead of `skip` (a broken probe would silently stop watering). Stale after
   `max_age` 30 min.
3. **Lockout:** latched until `reset_watchdog` or reboot, not persisted. A valve trip locks only that zone; a pump trip
   locks the whole group.
4. **Valve trip stops the lane:** the other queued zones of that lane stay queued but do not continue by themselves
   (vs. advancing to the next zone automatically).
5. **Threshold comparison:** skip when `value > skip_above` (equal waters); the soil rule never blocks manual runs.
6. **Restore modes:** `RESTORE_DEFAULT_OFF` stays allowed for raw relays (matches the breadboard profile and CLAUDE.md)
   rather than requiring `ALWAYS_OFF`; the watchdog and `Sprinkler::setup()` turn them off at boot anyway.

<!-- Filled in by implementer -->
## Implementation notes
- Where checks ran: dev container `gp-dev-012` (podman, this checkout mounted), `UV_OFFLINE=1`, `GP_REQUIRE_CXX=1`. Nothing ran on a real device.
- Results: `script/test-cpp` 24 cases ok (-Wall -Wextra -Werror); `script/lint` clean (`esphome config OK: garden-pilot.yaml`);
  `script/test`: 598 passed, 1 skipped in ~5m35 (012 branch baseline not re-measured here; the new rows are ~1.5 min host scenario + ~1 min host build, pinned only). Includes `minimum` (2026.6.3) rows for `test_safety_config` and `test_safety_codegen`: they pass, no xfail needed.
- Safety scenario results: all ten steps pass (valve limit via sprinkler, lockout, raw turn-on forced off, reset, pump idle, pump session limit, soil skip queue/cycle/manual/NaN/stale, stuck relay with at most one retry per second).
- Decisions/deviations: (a) `AUTO_LOAD.append("sensor")` in `__init__.py` (zone-skip region) because `group.h` includes `sensor/sensor.h`. (b) Duration lower bounds in the scenario are relaxed by 100 ms (50 ms state-log sampling). (c) A raw turn-on of a locked relay is cut before the 50 ms log can see it, so step 3 logs the state right after the call and 500 ms later. (d) Default pump limits are built as `TimePeriod(hours=2)` / `(seconds=10)` so the printed config shows `2h` / `10s`. (e) `skip_reason` is also called per cycle pick; the unavailable WARN can repeat per check. (f) `gz_attempt` needs `script.wait` in the scenario. (g) CLAUDE.md got the one gotcha line; no other CLAUDE.md change.
- Cut order not needed: nothing was cut.
- CI timings / CI green: not measured here (no push by the implementer).
- Hardware to check in 014: forced trip on a real relay, reboot during watering, `RESTORE_DEFAULT_OFF` relays off after boot.
## Follow-ups
- Soil re-check on cycle repeats; stopping a running zone when soil gets wet (out of scope here).

## Review round 1 fixes
Implementation notes (round 1):
- **Required 1 (lane race), also fixes 012's flaky `test_groups_host_scenario`.** New `GZ-PATCH` region `valve-handover`
  (`SprinklerValveOperator::handover()` + a loop in `fsm_transition_from_valve_run_`): when a run timer finished and
  `valve_overlap` is **not** set, the finished valve is switched off right before the next valve starts (shared pump
  untouched). With `valve_overlap` the deliberate overlap is unchanged (human constraint: water hammer / pump
  protection); also unchanged: interrupted runs, and a stop delay that is a valve delay with a pump. The reproduced
  same-lane overlap of the 012 flake ("assert not True", `state=0000011`) is exactly this window, so the fix covers
  012's flake; 012's scenario was not edited. Deterministic checks (not a 200 ms poll): the new `pair` group
  (`max_parallel: 1`, two zones) in the safety scenario counts overlaps in the valves' own `on_state` callbacks
  (`handover starts=4 overlaps=0`); verified that this check fails with the handover loop disabled. A new host config
  `tests/configs/garden_zones_overlap_sim.yaml` (list form) covers both cases: `plain` -> 0 overlaps, `ovl` with
  `valve_overlap: 1s` -> overlap still present (`test_valve_handover_host_scenario`). The groups form does not expose
  `valve_overlap`, so lanes always get the handover. Documented in PATCHES.md, README, SPEC §3.
- **Required 2:** `pump_idle_timeout` rule now uses `pump_start_valve_delay` (pump-first phase) in `groups.py`,
  `safety_rules.py`, README, the `idle-too-short` case and the Context bullet of this task.
- **Required 3:** the zone-limit rule adds `pump_stop_valve_delay` (case `stop-valve-delay`, unit rows).
- **Required 4:** the safety config's `pair` zone 2 has `max_on_time: 5s` (group 3 s): codegen asserts
  `add_zone(..., 5000)`; config-error cases `zone-override-too-short` and `pump-below-zone-override`.
- Suggestions done: error assertions use the rules' own wording or ESPHome's message (not echoed text); watchdog and
  guard reuse member buffers (no per-loop allocation once warmed up); an unresolvable restore-mode switch is a config
  error (never skipped); README note on soil staleness (`heartbeat`); stale soil readings are dropped for good by the
  group's `loop()` (no 49.7-day wrap); the soil unavailable WARN is limited to once a minute per zone.
- Results (round 1, `gp-dev-012`): `script/test-cpp` 24 cases ok; `script/lint` clean; `script/test` 607 passed, 1 skipped
  (`test_sim_ui`, no Xvfb) in 5m44. Flake check: the 012 `test_groups_host_scenario` and the 013 `test_safety_host_scenario`
  were run together 6 times in a row (separate pytest invocations), 6/6 passed for each (before the reviewer saw 1 of 12
  runs overlap); plus the full run and the overlap scenario. Nothing ran on a real device.

### Review round 2 fixes (round 3 of work; human decision 2026-10-10)
- **Human decision on R2-1:** keep the ORIGINAL stock handover. A brief overlap of two valves of a lane (up to one main-loop
  pass) is accepted by design; the priority is that the pump never runs against closed valves (water hammer). The
  `valve-handover` GZ-PATCH region of round 1 is removed entirely (`sprinkler.h`, `sprinkler.cpp` are stock again in that
  place; PATCHES.md section, README item and patch-id list entry are gone). The round-1 statement above that the patch also
  fixes 012's flake is superseded: the flake is the accepted stock overlap, and the test is made tolerant instead.
- **Tests of the accepted behaviour:** `tests/configs/garden_zones_overlap_sim.yaml` now measures, in the valves' own
  `on_state` callbacks, the longest time both valves of a controller were on: `plain` < 100 ms, `ovl` with
  `valve_overlap: 1s` between 900 and 1300 ms (deliberate overlap still happens). The safety scenario's `pair` group
  asserts `max_ms < 100` instead of `overlaps=0`.
- **012 `test_groups_host_scenario` (only its assertions changed, `garden_zones_groups_sim.yaml` untouched):** the three
  "never together" asserts (steps 3, 4, 5) use `_brief_overlap_only()`: a both-on entry in the on-change state log is
  allowed only as a single entry, never two in a row. It no longer depends on the 200 ms poll catching the handover.
- **Pump scenario (reviewer request, adapted):** new `tests/configs/garden_zones_pump_sim.yaml` +
  `test_pump_start_delays_host_scenario`: groups `pa` (`pump_start_pump_delay: 1s`) and `vb` (`pump_start_valve_delay: 1s`),
  two 3 s zones each. Events come from the switches' state callbacks. Asserts: each valve open 2.9-4.5 s (a full run,
  plus the start delay for the first valve of `pa`), the pump has one session (a same-millisecond off/on at the handover
  is merged), no gap between the zones in which the pump runs without a valve, the pump runs at most 1.3 s before the first
  valve (the configured start phase) and at most 0.3 s after the last.
- Round 2 suggestions: 1-2 no longer apply (they concern `handover()`).
- Results (`gp-dev-012`): see the end of this section.

### Human decision 2026-10-10: limits can be disabled with `never`
- Replaces "the watchdog cannot be disabled": no 4 h cap on `max_on_time` / `pump_max_on_time`, no 5 min cap on
  `pump_idle_timeout`; any positive duration from 1 s is accepted (technical maximum 30 days, the longest a 32-bit ms timer
  tracks wrap-safely; longer values must use `never`). `never` (the `update_interval: never` idiom) disables a limit at group
  level, zone level (`max_on_time`) or for the pump. Defaults stay on (60 min / 2 h / 10 s). Each disabled limit logs a WARN
  `watchdog disabled by config` naming the group/zone from `dump_config`; the run-vs-limit checks are skipped for such a
  zone/pump. Lockout, stuck-relay retries and the other limits stay active.
- Code: `watchdog::DISABLED` (zone sentinel) and empty optionals (pump) in `watchdog_core.h`; `_limit` validator and
  `_limit_code` in `groups.py`; codegen emits `::esphome::garden_zones::watchdog::DISABLED`.
- Tests: C++ (`disabled zone limit`, `disabled pump limits ... 6 h`), `test_safety_never_and_long_limits_config` (never at
  group, zone and both pump limits; 6 h; a 5 h run; zone `never` with the stock 86400 s number max), `test_safety_never_codegen`
  (4 x DISABLED, 21600000 for the 6 h group), error case `max-on-time-over-30-days` replaces `max-on-time-5h`.
- Docs: README, SPEC §4, CLAUDE.md gotcha line and core principle 4 updated.

Results (round 3 incl. the `never` decision, `gp-dev-012`): `script/test-cpp` 26 cases ok; `script/lint` clean; `script/test`
617 passed, 1 skipped (`test_sim_ui`) in 6m25; the 012 `test_groups_host_scenario`, the 013 safety scenario, the overlap
scenario and the pump-start-delay scenario ran together 5 more times after the full run (5/5), and 5/5 before the `never`
change. Nothing ran on a real device.
