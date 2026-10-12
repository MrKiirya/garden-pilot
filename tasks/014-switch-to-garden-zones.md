# 014 — Switch the device and the PC emulator from the stock `sprinkler` to `garden_zones`

Status: in-review
Roadmap: SPEC §9 item 7 "`garden_zones` component" (part 4 of 4: 008 core, 012 groups/lanes, 013 watchdog + soil,
**014 device switch**)
Spec sections: SPEC §3, §4, §4.1, §4.2, §5, §6, §7 items 1-5, §8 (valve test, screensaver), §9 item 7; CLAUDE.md core
principles 1-4, 7
Hardware check: yes, partly. The breadboard ESP32 (display, relay board, one temperature sensor) is the only device;
the **PC emulator is the main verification bar**. On the breadboard: flash, relays switch in bed order, valve test,
one forced watchdog trip on a real relay, reboot during watering (relays come up OFF). Real valves and water, the power
budget of several valves at once and soil probes stay unverified.

**Stacked on task 013.** Branch `task/014-switch-to-garden-zones` from `task/013-watchdog-and-soil-skip`; the PR targets
that branch (or `master` after 012/013 merge, then rebase before review). 013 is being implemented while this is
written: **re-read 013's files as implemented** (`groups.py`, `group.h`, `watchdog*.h`, `safety_rules.py`, README) and
use the names it actually shipped (action `garden_zones.reset_watchdog`, condition `garden_zones.watchdog_tripped`,
group keys `max_on_time` / `on_watchdog_trip`, class `GroupWatchdog`). Where this file guesses a 013 name, 013 wins —
mark such spots "to verify by the implementer" in Implementation notes.

## Goal
`garden-pilot.yaml` and `garden-pilot-sim.yaml` run the greenhouse beds on `garden_zones` instead of the stock
`sprinkler`: one group `gh_zones` ("Greenhouse"), declared in `packages/greenhouse/irrigation.yaml`; every
`packages/greenhouse/bed.yaml` include adds its zone as a `garden_zone:` list item, so a **1-bed greenhouse** works
(headless; the page still expects beds 1-3 until stage 9). The 013 watchdog is active on every bed relay with
`max_on_time` 60 min by default (overridable), and the bed run-duration number fits under it. Home Assistant keeps the
same entity names ("Greenhouse irrigation", "Greenhouse auto advance", "Greenhouse bed N", "... enable",
"... run duration"); two entities are added (watchdog problem sensor and reset button). The greenhouse page, Home
status, valve test / service mode and screensaver status keep working, with mechanical adaptations of their calls.
Checks first: pytest shape checks, config matrix rows (incl. 1 bed and `max_parallel: all`), a host scenario over the
real packages, device compile on pinned + minimum, and concrete emulator scenarios.

## Context

### What exists (read, do not re-plan)
- `packages/greenhouse/irrigation.yaml`: stock `sprinkler` `gh_sprinkler` with `main_switch` (id
  `gh_sprinkler_main_switch`, "Greenhouse irrigation", INFO logs on on/off) and `auto_advance_switch` "Greenhouse
  auto advance". `bed.yaml` adds a valve with `!extend gh_sprinkler`: `valve_switch: "${bed_name}"`, `enable_switch:
  "${bed_name} enable"`, `run_duration_number` id `gh_bed${bed}_run_duration` (initial 5, min 1, **max 120**, `min`,
  restore), `valve_switch_id: board_relay_${relay}`.
- Callers of `gh_sprinkler` (all legacy, CLAUDE.md "migrate in stages 7-9"):
  `packages/greenhouse/lvgl_page.yaml` (RUN `start_single_valve` 0..2, `+Q` `queue_valve`, STOP via `gp_confirm` →
  `shutdown`, "Run Q" `start_from_queue`), `sprinkler_lvgl_status.yaml` (1 s poller: standby / paused / active valve,
  AA/Q/Rev line, time left, queue time, Home `gh_home_irr_status`, `gh_home_next_label`), `lvgl_valve_test.yaml`
  (`shutdown`, `clear_queued_valves`, `start_single_valve` with `run_duration: ${valve_test_max_time}`, guard script,
  1 s service poller using `active_valve()` / `queued_valve()` / `time_remaining_active_valve()`),
  `screensaver_status.yaml` (`active_valve()` → "Bed N").
- Sim packages (`packages/sim/*`) only read `board_relay_N`; they need no change.
- Board profiles: breadboard `board_relay_N` are `RESTORE_DEFAULT_OFF`, `hardware/sim.yaml` `ALWAYS_OFF` — both pass
  013's restore-mode rule.
- 012 group API (`group.h`): `queue_zone`, `remove_queued_zone`, `is_zone_queued`, `queued_zones()` (round order),
  `run_zone` (008 manual run: pauses and resumes the lane's current zone, keeps the queue), `start_queue`,
  `start_cycle`, `shutdown`, `active_zones()`. YAML actions `garden_zones.queue_zone / remove_queued_zone / run_zone /
  start_group_queue / start_group_cycle / shutdown_group`, condition `is_zone_queued`. **Missing for 014:** group
  entities (main switch, auto advance), a clear-queue action, read accessors for time left / queue time / auto advance /
  watchdog state. 012 human decision 4: "In 014 the existing 'Greenhouse irrigation' / 'Greenhouse auto advance'
  entities become group entities with the same names. Auto advance = one switch per group: on → each lane advances to
  its next zone; off → all lanes stop after their current zone." 012 follow-up: the group auto-advance switch must set
  the lanes' stored auto-advance explicitly (`PATCHES.md` `lanes`).
- 013 "What 014 needs": device uses the groups form; bed `run_duration_number` `max_value` must fit under the zone
  limit (`max_value × 60 + start_delay + 2 s <= max_on_time`); HA-visible watchdog state + reset; soil wiring (human
  threshold); valve test keeps working on `run_zone`; hardware trip check. **Human decision 2026-10-08:**
  `max_on_time` default 60 min, overridable per group and zone (cap 4 h); run durations above it are lowered or the
  user raises `max_on_time`.

### Sources checked (pinned ESPHome 2026.9.1 installed in `.venv`; minimum 2026.6.3)
- `esphome/config.py` (2026.9.1): order is `do_packages_pass` → `do_substitution_pass` → `do_external_components_pass`,
  so `external_components:` may live in a package and use resolved substitutions. Minimum: not diffed — the config rows
  on `minimum` prove it.
- `esphome/__main__.py` (2026.9.1): global option `-s/--substitution KEY VALUE` (append), passed to `read_config` as
  command-line substitutions that override file substitutions. Long-standing; **to verify by the implementer** on
  2026.6.3 (one `script/config`-style run with `GP_ESPHOME=minimum`).
- `esphome/components/template/binary_sensor/__init__.py` (2026.9.1): `lambda` and `condition` are exclusive options;
  `condition:` can use 013's `garden_zones.watchdog_tripped`. Minimum proven by the config rows.
- `esphome/core/entity_base.h` at 2026.9.1 (installed) and at tag 2026.6.3 (GitHub raw): `make_entity_preference<T>()`
  exists in both; preferences are keyed by the object-id hash (`get_object_id_hash() ^ device_id`). Hence a
  run-duration number or enable switch with the **same name** restores the value saved by the stock sprinkler (same
  object id) — expected; verified by emulator scenario E2 and on the device.
- Fork `sprinkler.cpp` `SprinklerControllerNumber::setup()`: a restored value is published **without clamping** to
  `min..max`. With `max_value` lowered from 120 to 55, a saved 90 min would run 90 min and trip the watchdog at 60 min →
  bed locked. Decision 6 adds a tiny clamp patch.
- Fork `Sprinkler::set_controller_main_switch()` / stock `to_code`: main switch state lambda = any zone switch on or an
  active request; ON → `ResumeOrStartAction` (resume a paused run, else full cycle), OFF → `ShutdownAction`.
  Auto-advance switch schema: `entity_category: config`, `default_restore_mode: RESTORE_DEFAULT_OFF`. A
  `SprinklerControllerSwitch` polls its state lambda in `loop()` only when a lambda is set before `setup()`.
- Staging: `script/config`, `script/compile`, `script/sim` and `tests/test_config_matrix.py` already copy
  `components/` next to the staged entry file, so `external_components: [{source: components, ...}]` resolves there and
  from the repo root (`uv run esphome run garden-pilot.yaml`).
- `script/sim-ui` (015) starts `script/sim` with the caller's environment (so an env var reaches `script/sim`);
  `script/sim-ctl` supports `list | get | set (number) | switch`, no button press.
- **Not compiled before:** the fork on **ESP32** and on **2026.6.3** (012/013 compile the host build on pinned only;
  minimum got `--only-generate`). See Gates.

## Human decisions (2026-10-10; these override the planner defaults below)
- `gh_max_parallel` default **1** in the greenhouse package (safe for any power supply); the author sets `all` for
  himself later. Keep the public `garden-pilot.yaml` on the defaults.
- Watchdog (from 013, decided the same day): default `max_on_time` 60 min, **no hard cap**, and it can be disabled
  explicitly with `never` (group or zone). Bed run duration max default stays 55 min (fits the 60 min default);
  users with longer runs raise both substitutions (or set `never`). Use 013's final names and semantics.
- HA entity names "Greenhouse watchdog" (problem binary sensor) and "Greenhouse watchdog reset" (button): OK.
- Brief handover overlap of two valves (one loop pass) is accepted stock behaviour (013 removed its handover
  patch); pump protection first. `valve_overlap` stays available, not set for the greenhouse (no pump).
- Soil skip is not wired in 014 (follow-up).

## Decisions (planner; safe defaults, see Open questions)
1. **One group, ids and names.** In `irrigation.yaml` (sketch, not literal YAML):
   ```yaml
   substitutions:
     gh_max_parallel: "1"        # 1 = one valve at a time (today's behaviour); "all" = every bed at once
     gh_max_on_time: 60min       # watchdog limit per bed valve (013); raise it together with gh_bed_run_max
     gh_bed_run_max: "55"        # run-duration number max, minutes; must satisfy max*60 + 2 s <= gh_max_on_time
     gh_bed_run_initial: "5"     # run-duration number initial value, minutes (<= gh_bed_run_max)
   external_components:
     - source: components        # remote-package users pin a tag instead (SPEC §4.2; stage 5 follow-up)
       components: [garden_zones, garden_zone]
   garden_zones:
     groups:
       - id: gh_zones
         name: "Greenhouse"
         max_parallel: ${gh_max_parallel}
         max_on_time: ${gh_max_on_time}
         main_switch:            # id gh_zones_main_switch, "Greenhouse irrigation", mdi:water-pump, INFO logs as today
         auto_advance_switch: "Greenhouse auto advance"
         on_watchdog_trip:       # logger.log level ERROR, tag gh_zones, zone + reason
   binary_sensor:                # template "Greenhouse watchdog", id gh_zones_watchdog, device_class problem,
                                 # condition: garden_zones.watchdog_tripped: gh_zones
   button:                       # template "Greenhouse watchdog reset", id gh_zones_watchdog_reset,
                                 # entity_category config, on_press: garden_zones.reset_watchdog: gh_zones
   ```
   Lane ids become `gh_zones_lane_<n>`. No pump in the greenhouse group (gravity barrel). `gh_max_parallel` default
   **1** keeps today's one-valve-at-a-time behaviour and power draw; SPEC §10.1 says the author's beds can run all at
   once — switching to `all` is the human's call (power supply, barrel flow), Open question 1.
2. **`bed.yaml`** becomes one `garden_zone:` **list item** (`- group: gh_zones`) with the same `valve_switch`,
   `enable_switch`, `run_duration_number` (id, name, `initial_value: ${gh_bed_run_initial}`, `max_value:
   ${gh_bed_run_max}`, rest unchanged), `valve_switch_id: board_relay_${relay}`. Zone number = bed include order (0, 1,
   2 = beds 1, 2, 3), as today's valve number. Minimum bed count becomes **1**.
3. **Group entities** (component work in non-forked `groups.py` + `group.h`): optional group keys `main_switch` and
   `auto_advance_switch` with the stock sub-schemas (same class `SprinklerControllerSwitch`, same defaults incl.
   auto-advance `entity_category: config` and `RESTORE_DEFAULT_OFF`). Behaviour:
   - main switch ON → `start_cycle()` of the group; OFF → `shutdown()`; state = any zone of the group active.
     Difference to stock: no "resume a paused run" (groups have no pause, 012) — documented.
   - auto-advance switch: write → `set_auto_advance(x)` on every lane; state = any lane `auto_advance()`; at group
     `setup()` the restored switch state is pushed to the lanes. `start_cycle` / `start_queue` change the lane flags as
     in 012 and the switch follows through its state lambda.
4. **Read accessors and one action on `GardenZonesGroup`** (`group.h`, `groups.py`): `clear_queue()` + action
   `garden_zones.clear_group_queue: <group>`; `optional<uint32_t> time_remaining_zone(zone)` (the lane's
   `time_remaining_active_valve()` when that zone is the lane's active valve); `optional<uint32_t> time_remaining()`
   (max over lanes of `time_remaining_current_operation()`); `uint32_t queue_time()` (max over lanes of
   `total_queue_time()`: lanes run in parallel); `bool auto_advance()`; `bool watchdog_tripped()` and `bool
   zone_locked(zone)` if 013 did not add them. Thin, no new state; covered by the host scenario.
5. **Callers, minimal mechanical adaptation.** Principle 2 conflict noted: the adapted calls still address `gh_zones`
   directly. This is the legacy path CLAUDE.md lets migrate in stages 7-9; the `gp_*` layer is stage 8 (follow-up); no
   new `gp_*` scripts here.
   - `lvgl_page.yaml`: Bed N → `garden_zones.run_zone {id: gh_zones, zone_number: N-1}` (manual run now keeps the
     queue: a documented behaviour improvement); `+Q BN` → `queue_zone`; STOP (still via `gp_confirm`) →
     `shutdown_group`; "Run Q" → `start_group_queue`.
   - `sprinkler_lvgl_status.yaml` (file and package key `gh_sprinkler_lvgl` keep their names to limit churn; rename is a
     follow-up): main line priority "Watchdog: locked" (tripped) > "Running: B1 B3" (all active zones) > "Irrigation:
     idle" (standby/paused lines dropped: no group standby/pause); modes line `"AA:%s  Q:%u"` (auto advance, number of
     queued zones); "Zone left" = smallest remaining time of the active zones; "Total left" = `time_remaining()`;
     "Queue" = `queue_time()` + `next B<first of queued_zones()>`; Home status "Alarm" (tripped) / "Watering" / "Idle";
     Home NEXT = `queue_time()` as today. ASCII only (the old `"Paused · Bed%u"` with `·` disappears). No new colours
     or font sizes (the greenhouse page still uses the default theme).
   - `lvgl_valve_test.yaml`: `sprinkler.shutdown` → `garden_zones.shutdown_group: gh_zones`; `clear_queued_valves` →
     `garden_zones.clear_group_queue: gh_zones`; `start_single_valve` → `garden_zones.run_zone {id: gh_zones,
     zone_number: valve, run_duration: ${valve_test_max_time}}`; poller uses `active_zones()` / `queued_zones()` /
     `time_remaining_zone()`. Limit, guard script and service-mode semantics unchanged. A bed locked by the watchdog is
     refused by `run_zone` (013) and its row stays "closed" (UI notice = follow-up). Re-measure the tap-to-open delay in
     the emulator log; update the "~2 s / ~8 s" comment, the CLAUDE.md gotcha and SPEC §8 only if it changed.
   - `screensaver_status.yaml`: "Bed N" = first active zone, `"Bed N+"` when more than one is active.
6. **Fork patch `number-clamp`** (`sprinkler.cpp`, one `GZ-PATCH` region + `PATCHES.md` section): in
   `SprinklerControllerNumber::setup()` a restored value outside `min..max` is clamped and logged at WARN. Keeps a value
   saved under the old 120 min max from tripping the watchdog after the upgrade.
7. **Emulator tooling for the watchdog scenario** (sim-only, cuttable last):
   - `script/sim`: optional `GP_SIM_SUBST="key=value key=value"` → `-s key value` per pair before `run`
     (`script/sim-ui start` inherits the environment). Documented in the script header and SPEC §7.
   - `packages/sim/fault.yaml` (sim entry only, after `sim_drift`): template switch "Sim rogue relay 1" (id
     `sim_rogue_relay_1`, state = `board_relay_1` state) whose turn-on calls `switch.turn_on: board_relay_1` directly —
     simulates a relay switched on outside the engine (bug or welded contact). Header: fault injection, never in a
     device file.
   Why both: the 013 validation keeps every configured run under `max_on_time`, so no normal UI/HA path can trip the
   watchdog; a trip needs a fault, and a short limit needs a short bed max (and initial value).
8. **Soil skip is not wired** in 014 (`bed_soil.yaml` stays reporting-only): a separate include cannot add
   `soil_moisture:` to the bed's id-less `garden_zone:` entry, and the threshold is the human's value. Follow-up with
   Open question 4.
9. **Docs:** SPEC §3 (one sentence: the device no longer uses the stock sprinkler; limits kept for reference), §4.1
   (page uses `garden_zones.*` until stage 8), §5 (bed = `garden_zone:` list item, 1 bed possible, the substitutions),
   §7 (`GP_SIM_SUBST`, fault switch), §8 (valve test on `run_zone`, watchdog line on the page), §9 item 7 status.
   CLAUDE.md: layout rows (`bed.yaml`, `packages/greenhouse/*`, `components/garden_zones/` "used by the device",
   `packages/sim/` fault), package-order notes (at least 1 bed), conventions ("Add a bed"; the `sprinkler` bullet becomes
   a `garden_zones` bullet: HA uses zone switches + group entities, raw relays internal), gotchas (bed max vs
   `max_on_time`). README.md / README.ru.md: line 12 (engine) and the "at least 2 beds" sentence, kept in sync.
   `components/garden_zones/README.md`: group entities, new action/accessors, `number-clamp`.

**Gates.**
- **ESP32 / minimum compile of the fork:** first do `GP_SECRETS=example script/compile` on pinned and with
  `GP_ESPHOME=minimum`, with only Decisions 1-2 in place. If the fork does not compile on ESP32 or on 2026.6.3, stop,
  record the exact error in Implementation notes and escalate (options for the human: raise the minimum, or a
  version-specific fork patch). Do not add version switches on your own.
- **Flash/RAM:** record ESP32 flash and RAM usage before/after (compile output); report if flash grows by more than 5 %
  of the app partition (no action required).
- **CI time:** the new host scenario is pinned only. If `script/test` in CI grows by more than 4 minutes over the 013
  branch, report the timings and propose folding it into the 013 safety scenario as a follow-up.

## Files
Component (`components/garden_zones/`, GPLv3):
- modify: `groups.py` — `main_switch`, `auto_advance_switch` group keys + codegen; `clear_group_queue` action.
- modify: `group.h` — group entity wiring, `clear_queue()`, read accessors (Decisions 3, 4).
- modify: `sprinkler.cpp`, `PATCHES.md` — region `number-clamp` (Decision 6).
- modify: `README.md` — group entities, accessors, clear action, clamp.

Device / emulator YAML:
- modify: `packages/greenhouse/irrigation.yaml` — Decision 1 (replaces the `sprinkler:` block).
- modify: `packages/greenhouse/bed.yaml` — Decision 2 (header too: 1 bed allowed, max vs limit).
- modify: `packages/greenhouse/lvgl_page.yaml`, `sprinkler_lvgl_status.yaml`, `lvgl_valve_test.yaml`,
  `screensaver_status.yaml` — Decision 5.
- modify: `garden-pilot.yaml`, `garden-pilot-sim.yaml` — comments ("at least 1 bed", where to override `gh_max_parallel`
  / `gh_max_on_time` / `gh_bed_run_max`); sim: `sim_fault` include (Decision 7).
- create: `packages/sim/fault.yaml`; modify: `script/sim` — Decision 7 (cuttable).

Tests:
- create: `tests/configs/greenhouse_zones_sim.yaml` — host scenario over the real packages (below).
- create: `tests/test_greenhouse_zones.py` — shape checks + config/codegen/host rows for the new config.
- modify: `tests/test_layout.py` (bed shape, ≥ 1 bed), `tests/test_service.py` (allowed actions / ids),
  `tests/test_screens.py` (STOP action), `tests/test_screensaver.py` (reads only `gh_zones`),
  `tests/test_config_matrix.py` (rows + optional `subst` field), `tests/test_garden_zones.py`
  (`test_device_unchanged` → `test_device_uses_groups_form`; `test_garden_zone_entries_are_lists` now covers `bed.yaml`).

Docs: `docs/SPEC.md`, `CLAUDE.md`, `README.md`, `README.ru.md` (Decision 9).

About 28 paths — well above the ~10-file budget; most test and doc edits are mechanical id/action renames, and the
switch cannot be split without leaving the device half on each engine. Cut order if the budget runs out: emulator
tooling (Decision 7 and scenario E5) → the parallel scenario E6 → README wording beyond the two sentences. Not
cuttable: Decisions 1-6, all checks in the table except the two marked cuttable, the host scenario, the device compiles,
scenarios E1-E4.

## Checks to write first
| Level | Test | Asserts |
|---|---|---|
| unit | `tests/test_layout.py::test_bed_shape` (rewritten) | `bed.yaml` top-level keys == `{"garden_zone"}`, a **list** of one item with `group: gh_zones`, `valve_switch: "${bed_name}"`, `enable_switch: "${bed_name} enable"`, `valve_switch_id: board_relay_${relay}`, number id `gh_bed${bed}_run_duration`, `max_value: ${gh_bed_run_max}`, `initial_value: ${gh_bed_run_initial}`, unit `min`; no `sprinkler`, `!extend`, `GPIO\d+`, `!secret`, `lvgl`. |
| unit | `tests/test_layout.py::test_bed_includes` (adapted) | ≥ 1 bed (was 2); entry beds still 1, 2, 3 in order between `gh_irrigation` and `gh_lvgl_page`. |
| unit | `tests/test_greenhouse_zones.py::test_irrigation_shape` | `irrigation.yaml`: no `sprinkler:`; `external_components` `[garden_zones, garden_zone]` with `source: components`; one group `gh_zones`, `max_parallel: ${gh_max_parallel}`, `max_on_time: ${gh_max_on_time}`, main switch "Greenhouse irrigation", auto advance "Greenhouse auto advance", `on_watchdog_trip` present; binary_sensor `device_class: problem`; button calling `garden_zones.reset_watchdog: gh_zones`; substitution defaults `gh_max_parallel: "1"`, `gh_max_on_time: 60min`, `gh_bed_run_max: "55"`, `gh_bed_run_initial: "5"`. |
| unit | `test_bed_max_fits_watchdog` | With 013's `safety_rules.py` (imported by path) and the default substitutions: 55 min fits 60 min; 60 min with 60 min fails (the default is the binding choice). |
| unit | `test_no_stock_sprinkler_in_device_files` | No `sprinkler:` key, no `sprinkler.` action, no `gh_sprinkler` under `packages/`, `hardware/`, both entry files. |
| unit | `tests/test_garden_zones.py::test_device_uses_groups_form` (replaces `test_device_unchanged`) | Both entry files include `gh_irrigation`; `garden_zones` appears only in `packages/greenhouse/irrigation.yaml` (groups form, dict), `garden_zone:` only in `bed.yaml` (list). |
| unit | `test_garden_zone_entries_are_lists` (existing) | Now finds `packages/greenhouse/bed.yaml` and passes. |
| unit | `tests/test_service.py` (adapted) | Allowed actions in the valve test == `{garden_zones.run_zone, garden_zones.shutdown_group, garden_zones.clear_group_queue}`, every target `gh_zones`; `run_zone` has `run_duration: ${valve_test_max_time}` and runs only inside the service-mode `if`; shutdown before guard before `run_zone`; enter = shutdown + clear; leave/exit/stop = shutdown; `valve_test_max_time` <= 10 s; no raw relay, no zone switch, no `gh_zones_main_switch`. |
| unit | `tests/test_screens.py` STOP check (adapted) | STOP still goes through the guarded `gp_confirm`, then `garden_zones.shutdown_group: gh_zones`. |
| unit | `tests/test_screensaver.py` (adapted) | `screensaver_status.yaml` reads `id(gh_zones)` only, no action key (`garden_zones.`, `switch.`); package order `gh_sprinkler_lvgl` < `gh_screensaver_status` unchanged. |
| unit | ASCII UI text check (existing in `test_screens.py`) | Still passes over the changed files. |
| unit | `test_sim_fault_is_sim_only` (cuttable with Decision 7) | `packages/sim/fault.yaml` is included only by `garden-pilot-sim.yaml`; its switch id starts with `sim_`; header says fault injection. |
| unit | `test_sim_subst_parsing` (cuttable with Decision 7) | `script/sim` turns `GP_SIM_SUBST="a=1 b=2s"` into `-s a 1 -s b 2s` (stub `_esphome` or a testable shell function; implementer's choice). |
| unit | `test_greenhouse_zones_config_shape` | `tests/configs/greenhouse_zones_sim.yaml`: includes `hardware/sim.yaml`, `packages/greenhouse/irrigation.yaml` and `bed.yaml` 3× with vars; substitutions `gh_max_on_time: 90s`, `gh_bed_run_max: "1"`, `gh_bed_run_initial: "1"`; no `!secret`, `api:`, `wifi:`, `ota:`, `GPIO\d+`. |
| config | `tests/test_config_matrix.py` rows | Existing rows pass with the new engine; new rows: `beds_1_headless` (CORE + `gh_irrigation` + `gh_bed_1`), `sim_beds_1` (sim hardware + irrigation + bed 1), `beds_3_parallel_headless` (CORE + irrigation + beds 1-3 with `-s gh_max_parallel all`; `Variant` gets an optional `subst` tuple passed as `-s` args), `max_on_time_too_short` **expected failure** (`-s gh_max_on_time 30min`) whose output names `max_value` and `max_on_time`. |
| config | `test_greenhouse_zones_codegen[pinned\|minimum]` | `compile --only-generate` of the device entry with example secrets: `main.cpp` has `gh_zones_lane_0` and no `gh_zones_lane_1`, one `GardenZonesGroup`, one watchdog (013 class) with limit `3600000`, main / auto-advance switch setters once each, no stock `sprinkler::Sprinkler`. With `-s gh_max_parallel all`: lanes `_0.._2`. |
| config | `test_entity_names_kept[pinned]` | From the `esphome config` output of the device entry: switches "Greenhouse irrigation", "Greenhouse auto advance", "Greenhouse bed 1..3", "Greenhouse bed 1..3 enable"; numbers "Greenhouse bed 1..3 run duration"; new "Greenhouse watchdog" (binary_sensor) and "Greenhouse watchdog reset" (button); no other irrigation entity. |
| host | `test_greenhouse_zones_host_compile` (pinned) | The staged scenario config compiles for `host` (fixed staging dir under `.esphome/`, as 012/013). |
| host | `test_greenhouse_zones_host_scenario` (pinned) | One run; `GZTEST` assertions below. |
| compile | CI `compile (pinned)`, `compile (minimum)` | Device ESP32 and emulator host builds with `garden_zones` (Gate). |

### Host scenario (`tests/configs/greenhouse_zones_sim.yaml`)
Test harness over the **real** `irrigation.yaml` + 3× `bed.yaml` on `hardware/sim.yaml`, short limits by substitution
(`gh_max_on_time: 90s`, `gh_bed_run_max: "1"`, `gh_bed_run_initial: "1"`), no LVGL, no API. A 100 ms `interval` logs
`GZTEST t=<millis> state=<r1 r2 r3 as 0/1>` on change (small lambda reading switch states only); steps log
`GZTEST step=N`; `on_boot` late priority, `wait_until` with timeouts. Zone runs use `run_duration: 2s..6s` on
`queue_zone` / `run_zone` to keep the scenario short; the main-switch steps only check the first transitions (the
number values are 1 min). Keep the whole run under ~3 min (step 5 dominates).
1. All relays 0; `gh_zones_watchdog` off; the three run-duration numbers read 1.
2. **Main switch:** `switch.turn_on: gh_zones_main_switch` → r1 goes 1 first (bed order) and never two relays at 1
   together; the main switch state is 1 while running; `switch.turn_off` → all 0 within 1 s, main switch state 0.
3. **Auto advance off stops after the current zone:** main switch on, then turn "Greenhouse auto advance" off
   (`switch.turn_off` by id) while r1 runs → when r1 ends nothing else starts within 5 s. (If this needs the full 1 min,
   accept the time or set bed 1's number to 1 min and keep it the only long step besides 5.)
4. **Queue + manual run:** `queue_zone` 0 and 2 (3 s), `start_group_queue` → r1 then r3, never r2; then `queue_zone` 0
   (6 s), start, after 1 s `run_zone` 1 (2 s) → r1 pauses, r2 runs, r1 resumes (008 semantics); `queue_zone` 1 +
   `clear_group_queue` → `queued_zones()` empty.
5. **Watchdog on the real bed package:** raw `switch.turn_on: board_relay_2` → off after 90 000 < Δ <= 91 000 ms;
   `gh_zones_watchdog` state 1; `run_zone` 1 refused (r2 stays 0); `button.press: gh_zones_watchdog_reset` → watchdog
   state 0; `run_zone` 1 (2 s) runs.
6. **Valve-test-like sequence:** `shutdown_group`, `run_zone` 2 with `run_duration: 10s` → r3 open ≤ 10 s, no trip.
7. Log `GZTEST done`. Global: no relay continuously 1 for more than 91 s; never two relays at 1 together.

Timing note: `max_on_time` must be ≥ 62 s with a 1 min bed max (013 rule), so ~62 s is the floor if the CI Gate is hit.
The clamp patch (Decision 6) needs a second boot with a pre-seeded preference; it is verified by emulator scenario E2
instead, not here.

### Emulator scenarios (manual, the main verification bar; record results in Implementation notes)
Run in the devcontainer (SDL config with `script/sim`, or `script/sim-ui` on a private Xvfb). Read the tap coordinates
of the bottom nav (ZONES, SETUP) and the SERVICE tile from `packages/lvgl/page_home.yaml` / `page_setup.yaml` (to verify
by the implementer); greenhouse page buttons: Bed 1/2/3 at (56,161) / (160,161) / (264,161), `+Q` row at y 194, STOP
(56,226), Run Q (160,226). Shots land in `.esphome/shots/` (git-ignored); list their names and what they show in
Implementation notes. Relay order is read from the log lines `SIM relay_N ON/OFF`.
- **E1 entity continuity:** on the 013 branch `script/sim-ui start`, `script/sim-ctl list > before.txt`,
  `script/sim-ui stop`; same on the 014 branch → `after.txt` (scratch files, not committed). `diff` of the object_id
  column: added only `greenhouse_watchdog`, `greenhouse_watchdog_reset` and the sim-only `sim_rogue_relay_1`; nothing
  removed.
- **E2 restored values + clamp:** on the 013 build `script/sim-ctl set "Greenhouse bed 2 run duration" 7` and bed 3 to
  90 (allowed there, max 120); then start the 014 build (same `.esphome/sim-prefs/`) → `get` bed 2 = 7 (kept), bed 3 =
  55 (clamped, WARN in the log).
- **E3 greenhouse page + full cycle:** set all three run durations to 1; shot `gh_before` of the greenhouse page;
  `script/sim-ctl switch "Greenhouse irrigation" on` → relay_1 ON, then relay_1 OFF / relay_2 ON, then relay_3, never two
  at once; shot `gh_running` shows "Running: B1"; `switch "Greenhouse irrigation" off` → all OFF. Tap Bed 2 → relay_2
  runs; tap `+Q B1` and Run Q → order in the log; STOP → confirm dialog → confirm → all OFF; shot `gh_after`; Home
  status label shows "Watering" / "Idle" accordingly.
- **E4 valve test:** SETUP → SERVICE; TEST bed 1 → relay_1 ON then OFF ≤ 10 s after the tap (note the measured open
  time); while in service, `sim-ctl switch "Greenhouse bed 2" on` → WARN "external start blocked" and relay_2 OFF within
  ~1 s; EXIT SERVICE. Screensaver: wait 1 min while a bed runs → "Bed N" with the dot (shot `saver_running`).
- **E5 watchdog trip (Decision 7):** `GP_SIM_SUBST="gh_max_on_time=90s gh_bed_run_max=1 gh_bed_run_initial=1"
  script/sim-ui start`; `sim-ctl switch "Sim rogue relay 1" on` → after ~90 s an ERROR trip log, relay_1 OFF,
  `sim-ctl get greenhouse_watchdog` = on, greenhouse page main line "Watchdog: locked" (shot `gh_watchdog`), Home status
  "Alarm"; tap Bed 1 → relay_1 stays OFF; restart the emulator → watchdog off (latch not persisted). Optional, if Home
  Assistant is connected to the emulator: press "Greenhouse watchdog reset" there instead of restarting.
- **E6 parallel (optional):** `GP_SIM_SUBST="gh_max_parallel=all"`, main switch on → relays 1-3 ON together; page shows
  "Running: B1 B2 B3"; screensaver "Bed 1+".

## Acceptance criteria
- [x] `uv run pytest -m unit` → all pass.
- [x] `script/lint` → clean; `esphome config OK` for `garden-pilot.yaml`.
- [x] `script/test` → all pass (config matrix incl. new rows; in the devcontainer with `GP_REQUIRE_SDL=1
      GP_REQUIRE_CXX=1`: no skips); wall time before/after in Implementation notes.
- [~] (pinned device compile OK; minimum device compile blocked offline, emulator builds ran in script/test and sim-ui) `GP_SECRETS=example script/compile` and `GP_SECRETS=example GP_ESPHOME=minimum script/compile` → ESP32 builds OK
      (Gate); flash/RAM before/after recorded. Same two for `garden-pilot-sim.yaml`.
- [x] `git grep -n -e gh_sprinkler -e 'sprinkler\.' -e '^sprinkler:' -- packages hardware garden-pilot.yaml
      garden-pilot-sim.yaml` → no hits.
- [x] `git grep -n 'GZ-PATCH-BEGIN' -- components` → 013's ids plus `number-clamp`, each with a `PATCHES.md` section.
- [~] Emulator scenarios E1-E4 (E2 and the before-list of E1 not done, see notes) done and reported (E5/E6 unless cut); the E1 diff matches the expected additions only.
- [ ] CI green for `checks`, `compile (pinned)`, `compile (minimum)`; timings against the Gate recorded.
- [x] Docs updated as in Decision 9; README.md and README.ru.md in sync.
- [x] Implementation notes state what ran on the breadboard device and what did not.

**Needs real hardware (not CI):** flash + boot (relays OFF, boot screen, then Home); "Greenhouse irrigation" ON clicks
relays 1→2→3 one at a time (run durations at 1 min); valve test on a real relay (measured open time ≤ 10 s); a forced
watchdog trip on a real relay using a **local, uncommitted** override (entry-file substitutions `gh_max_on_time: 90s`,
`gh_bed_run_max: "1"`, `gh_bed_run_initial: "1"` plus a temporary internal template button that calls `switch.turn_on:
board_relay_1`; describe the snippet in Implementation notes, never commit it) → relay forced OFF after ~90 s, ERROR
log, "Greenhouse watchdog" on in HA, reset button clears it; reboot during watering → relays OFF after boot, queue
restored but not started; HA shows the same entity names as before plus the two new ones. **Unverifiable here:** real
valves/water, several valves at once on the real power supply, soil probes.

## Out of scope
- `gp_*` layer and moving screens/HA to it (stage 8); renaming `sprinkler_lvgl_status.yaml` / `gh_sprinkler_lvgl`.
- Wiring bed soil sensors into `soil_moisture:` (Decision 8, Open question 4).
- Page layouts for other bed counts (stage 9); the greenhouse page stays beds 1-3 (1 bed = headless only).
- On-screen watchdog reset, a per-bed "LOCKED" notice in the valve test; `sim-ctl press` for buttons.
- Group pause/resume, standby, multiplier, repeat, queue text sensor; lawn group; pump.
- Remote-package `external_components` source pinned to a tag (stage 5).
- Open 008/012/013 follow-ups.

## Open questions (safe defaults chosen)
1. **[human]** `gh_max_parallel`: default `1` (today's behaviour, one valve at a time). SPEC §10.1 says the author's
   beds can run all at once — set `all` only if the valve power supply and relay board handle 3 valves together.
2. **[human]** `gh_bed_run_max` default **55 min** under `max_on_time` 60 min (59 is the highest the 013 rule allows; 55
   leaves room for a future start delay). Users who need longer runs raise both substitutions.
3. **[human]** Names of the two new HA entities: "Greenhouse watchdog", "Greenhouse watchdog reset".
4. **[human]** Bed soil skip threshold (`skip_above`, %) and the mechanism (e.g. a `soil` var on `bed.yaml`) — follow-up.
5. Main switch ON starts a full cycle and no longer resumes a paused run (groups have no pause); accepted for now.
6. A restored run duration above the new max is clamped (Decision 6) rather than reset to the initial value.

## Implementation notes
Ran in dev container `gp-dev-014` (podman). **Nothing ran on a real device.**
- Component: `groups.py` / `group.h` got group keys `main_switch` / `auto_advance_switch` (class `SprinklerControllerSwitch`, stock defaults), action `garden_zones.clear_group_queue`, accessors `clear_queue`, `set_auto_advance`, `auto_advance`, `any_zone_active`, `zone_locked`, `time_remaining_zone`, `time_remaining`, `queue_time`; the restored auto-advance switch state is pushed to the lanes in the group's `setup()`. Fork patch `number-clamp` (`sprinkler.cpp` + PATCHES.md). 013 names used as shipped (`reset_watchdog`, `watchdog_tripped`, `max_on_time`, `on_watchdog_trip`, `GroupWatchdog`); `never` works for `gh_max_on_time`.
- **Bug found by the ESP32 compile gate (013 latent):** `WatchdogTripTrigger` was `Trigger<int, std::string>` but YAML trigger args are `int32_t` (= `long` on Xtensa): the device build failed ("no matching function for call to Automation<long, string>"). Host builds never saw it. Fixed in `watchdog.h` (`Trigger<int32_t, std::string>`); the YAML log uses `(int) zone`.
- Deviations: (a) the binary sensor id is `gh_zones_watchdog_problem` (`gh_zones_watchdog` is the generated watchdog component id and clashes); (b) the auto-advance switch got the id `gh_zones_auto_advance` (needed by the host scenario); (c) the host scenario and the emulator watchdog scenario use `gh_bed_run_max=2`, `gh_bed_run_initial=1`, `gh_max_on_time=125s`, because the bed number has `min_value: 1` and `max_value: 1` is rejected by ESPHome ("max_value must be greater than min_value"); the scenario therefore takes ~4 min (spec said ~3); (d) tap-to-open delay of the valve test measured in the host scenario: relay opens ~2.0 s after `run_zone`, unchanged, so the "~2 s / ~8 s" wording stays.
- ESP32 pinned compile (`GP_SECRETS=example script/compile garden-pilot.yaml`): OK. Flash 1198235 -> 1213599 bytes (+15364, +0.8 % of the 1835008 app partition), RAM 115635 -> 116147 (baseline = HEAD of 013 branch built from `git archive`). `GP_ESPHOME=minimum` ESP32 compile: **not done** - with `UV_OFFLINE=1` the platformio penv install failed ("Failed to install Python dependencies into penv", needs network); CI `compile (minimum)` covers it. Codegen (`--only-generate`) on minimum passes (`test_greenhouse_zones_codegen[minimum]`). Emulator host compile of `garden-pilot-sim.yaml`: covered by the emulator runs / CI.
- Checks: `script/test-cpp` 26 cases ok; `script/lint` clean; unit 559 passed; host scenario `test_greenhouse_zones_host_scenario` passes (~4 min). `script/test` (`UV_OFFLINE=1 GP_REQUIRE_CXX=1`, SDL + sim-ui present): **636 passed, 0 skipped in 11m42** (013 branch: 6m25, so +5m17: over the 4 min Gate; the host scenario alone is ~4 min, the new host build ~1 min; proposal: fold the greenhouse scenario into the 013 safety scenario or shorten step 3/5 later). Emulator scenarios below.
- **Emulator scenarios** (`script/sim-ui` + `script/sim-ctl`, screenshots in `.esphome/shots/`):
  - E1 entity continuity: partly. `sim-ctl list` of the 014 build shows every old object id (greenhouse_auto_advance, greenhouse_irrigation, greenhouse_bed_1..3 (+_enable, _run_duration), sensors) plus the new `greenhouse_watchdog`, `greenhouse_watchdog_reset` and sim-only `sim_rogue_relay_1`; the pinned-config name check is `test_entity_names_kept`. A before-list from a 013 build was not taken (no second build tree could be run via sim-ui in the turns available).
  - E2 restored value + clamp: **not done** (needs a 013 build to save 90 min); the clamp is only compile-verified. Check on the breadboard / by hand.
  - E3 PASS: run durations set to 1; main switch on -> relay_1 ON, 60 s later relay_2 ON (relay_1 OFF the same ms: accepted stock handover), then OFF; shot `gh_running.png` ("Running: B1", AA:on); main switch off -> all OFF; Bed 2 tap -> relay_2 runs (`gh_bed2.png`); `+Q B1` then Run Q while bed 2 runs does nothing (lane busy, as in stock); STOP -> dialog (`gh_stop_dialog.png`) -> STOP ALL -> relay_2 OFF (`gh_after.png`); Home status "Idle" (`home_idle.png`). One first tap on Bed 2 right after the switch was off did not start (not reproduced; the second tap worked).
  - E4 PASS: SETUP -> SERVICE (`service_page.png`); TEST bed 1 tapped at 00:18:41 -> relay_1 ON 00:18:43, OFF 00:18:51 (open 8 s, ~2 s start delay, unchanged; `valve_test_open.png`); `sim-ctl switch "Greenhouse bed 2" on` -> relay_2 ON and immediately `service mode: external start blocked` + relay_2 OFF the same second; EXIT SERVICE. Screensaver while a bed runs shows "Bed 2" with the dot (`saver_running.png`).
  - E5 PASS (`GP_SIM_SUBST="gh_max_on_time=125s gh_bed_run_max=2 gh_bed_run_initial=1"`): rogue relay on at 00:20:46 -> ERROR trip `zone 0 ... on for 125 s > max_on_time 125 s: forced off` at 00:22:51, relay_1 OFF, `greenhouse_watchdog` = on, page "Watchdog: locked" (`gh_watchdog.png`), Home "Alarm" (`home_alarm.png`), tap Bed 1 -> relay_1 stays OFF; restart -> `greenhouse_watchdog` off (latch not persisted). Reset button via HA not tried.
  - E6 PASS (`GP_SIM_SUBST="gh_max_parallel=all"`): main switch on -> relays 1-3 ON in the same second (`gh_parallel.png`); screensaver "Bed 1+" (`saver_parallel2.png`).
  - `script/sim-ui stop` done, nothing left running.
- Not wired: soil skip (Decision 8). `-s` on `minimum` (2026.6.3) not separately verified beyond the config-matrix rows running on pinned.
### Review suggestions (round 1)
- 1: `script/sim` header example now uses `gh_max_on_time=125s gh_bed_run_max=2 gh_bed_run_initial=1`.
- 2: host scenario step 3 also asserts relays 2 and 3 are never on between `s3_a` and `s3_c`.
- 4: new config-matrix row `max_on_time_never` (`gh_max_on_time never`, beds 1-2) must pass.
- 6: `"number-clamp"` indentation fixed in `tests/test_garden_zones.py`.
- 3 / 5: automated number-clamp check (and restored auto-advance push to lanes) not done: needs a second host boot with shared prefs; listed as a follow-up.

## Follow-ups
- Automated number-clamp check (second host run with the same prefs dir and a lower `gh_bed_run_max`, or a C++ harness case); same second boot could cover the restored auto-advance switch push (`group.h`).
- 013: the watchdog trip log repeats the label ("zone 0 ('group 'Greenhouse' zone 0 ('Greenhouse bed 1')')"): `groups.py` passes the full zone label to `add_zone`, the watchdog formats it again.
- Run `GP_ESPHOME=minimum` ESP32 compile with network (CI `compile (minimum)`), E2 (clamp) and E1 before-list with a 013 build.
- Scratch left under git-ignored `.esphome/` (`baseline-build`, `baseline-tree` with a `.venv` symlink, `scratch`); delete by hand.
- CI time Gate exceeded (+5m17 locally), see notes.
- Hardware check on the breadboard ESP32 (never run here): flash; relays OFF after boot; "Greenhouse irrigation" ON clicks relays 1->2->3 one at a time (run durations at 1 min); valve test measured open time <= 10 s; a forced trip with a local, uncommitted override (entry substitutions `gh_max_on_time: 125s`, `gh_bed_run_max: "2"`, `gh_bed_run_initial: "1"` plus a temporary internal template button calling `switch.turn_on: board_relay_1`); reboot during watering (relays OFF, queue restored not started); HA entity names as before plus the two new ones; the 120 -> 55 min max clamp of a saved run duration.
