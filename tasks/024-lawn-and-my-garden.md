# 024 — Lawn (pump group) package and the author's `examples/my-garden.yaml`

Status: implemented (awaiting review)
Roadmap: SPEC §9 stage 13 (examples and remote packages), "Task 024: a lawn and flowers package and the author's
`examples/my-garden.yaml`"
Spec sections: SPEC §2.2, §4 (groups / `max_parallel`, watchdog), §4.1 (gp layer), §5 (modularity, target layout), §9
stage 13, §9.1; `components/gp/README.md`; `components/garden_zones/README.md` (groups form, safety);
`components/garden_schedule/README.md`; `tasks/023-examples-and-boards.md`
Hardware check: none in CI. Optional for the author, not blocking: flash `examples/my-garden.yaml` on a T-Relay-S3 and
run the LED checklist at the end of this file. Nothing in this task has been run on a real device.

## Goal
A second irrigation module exists next to the greenhouse: `packages/lawn/`, one `garden_zones` group `lawn_zones` with
a pump, one zone at a time (`max_parallel: 1`), N zones with one include per zone (lawn or flower bed zones, see the
author's answer in task 023: lawn and flowers share one pump group). It follows the greenhouse bed patterns exactly:
an internal raw relay per zone (`board_relay_N`), a `gp_zone` switch per zone, its own gp group `gp_lawn` (key `lawn`),
status / watchdog / main switch / reset entities, watchdog limits on by default, no pins outside `hardware/`. Screens,
schedules and Home Assistant reach it only through `gp_lawn` and the generic `gp_*` actions (`group: lawn`), never through
`garden_zones`. `garden-pilot.yaml` gets the lawn as commented-out blocks (uncomment to enable). `examples/my-garden.yaml`
is the author's own setup written with generic names: 3 greenhouse beds on a gravity barrel watered all at once with
limits raised for a ~3 h run (public defaults unchanged), plus the planned lawn on a pump, on the existing LilyGO
T-Relay-S3 profile. No new LVGL page and no lawn schedules yet (follow-ups).

## Context

### State of the repo (read this first)
- Task 023 is merged into `master` (examples, `gp_root`, `hardware/lilygo-t-relay-s3.yaml`,
  `packages/greenhouse/irrigation_pump.yaml`, `bed_soil_skip.yaml`, `tests/test_examples.py`, the per-entry relay/pin
  rules in `tests/test_layout.py`). The planner's local checkout was on a branch without 023; the 023 facts below were
  read from `master` on GitHub. **Branch `task/024-lawn-and-my-garden` from current `master`.**
- The uncommitted breadboard wiring on branch `test/display-on-header` (DevKitC-1 + the 6-relay T-Relay-S3 extension
  board through a 74HC595 on DAT GPIO21 / SHT GPIO47 / LAT GPIO48, display powered from GPIOs) is a local test rig, not
  a profile. Do not commit it and do not copy it into this task (see open question 8).

### Engine and gp facts the design relies on (checked in this repo)
- `garden_zones:` is one hub with a `groups:` list; several groups per device are supported and already host-tested
  (`tests/configs/garden_zones_groups_sim.yaml`: groups `beds`, `lawn` with a shared pump, `solo`). A pump belongs to
  one group (`pump_switch_id`). Groups run independently: there is **no cross-group interlock** (greenhouse and lawn can
  water at the same time).
- Group options (`components/garden_zones/README.md`): `name`, `max_parallel`, `pump_switch_id`,
  `pump_start_pump_delay` / `pump_stop_pump_delay` / `pump_start_valve_delay` / `pump_stop_valve_delay`,
  `max_on_time` (default 60min), `pump_max_on_time` (default 2h), `pump_idle_timeout` (default 10s),
  `auto_advance_switch`, `on_watchdog_trip`. Config-time rules: `run max + pump delays + 2 s <= max_on_time`;
  `pump_max_on_time >=` every zone limit (error text contains `pump_max_on_time` and `is below max_on_time`);
  `pump_idle_timeout >= max(pump_start_valve_delay, pump_stop_pump_delay) + 2 s`; raw valve and pump switches must be
  `ALWAYS_OFF` / `RESTORE_DEFAULT_OFF`.
- `pump_max_on_time` bounds a **session**, not a zone: with `max_parallel: 1` the stock hand-over opens the next valve
  before closing the previous one, so the pump stays on through a whole queue / full cycle. Nothing at config time checks
  "zones x run max <= pump_max_on_time"; a too-long session trips the pump watchdog and locks the group (fail safe, but a
  surprise). This task adds a repo check for it (below).
- `gp:` (`components/gp/__init__.py`): `groups:` is a list, one item per group, exactly one engine key
  (`garden_zones_id`); `_final_validate` requires the `gp_zone` positions of each gp group to be exactly 1..N of its
  engine group. `gp_zone` positions max 16. Group actions / conditions take the group id; HA actions take
  `{hub: gp_hub, group: <key>}`, so `packages/core/gp_api.yaml` needs **no change** (`group: lawn` works).
- `gp.inhibit` (service mode) and `on_stop` are per group. The valve test inhibits only `gp_greenhouse`, so the lawn keeps
  watering during greenhouse service mode (open question 7, follow-up).
- Zone short names are hard-coded `"B%u"` in `components/gp/zone_model.h` (`short_name`), so "Lawn status" will read
  "Watering B2" and the watchdog alert "Lawn: watchdog - B2 locked". Known cosmetic defect, not fixed here (follow-up:
  a per-group zone prefix).
- `garden_schedule` is `MULTI_CONF` with `zone_group` (a gp group id), so a lawn schedule is a second hub
  (`lawn_schedule`, `zone_group: gp_lawn`, `on_run` -> `gp.enqueue_zones` / `gp.start_queue` on `gp_lawn`). Not built
  here: `packages/greenhouse/schedule_slot.yaml` hard-codes `gh_sched*` ids, "Greenhouse schedule" names and
  `schedule: gh_schedule`; generalising it is its own task (follow-up), copying 120 lines is not wanted.
- LVGL: nothing changes. A future Lawn page / Home lawn card reads `id(gp_lawn)->summary()` / `zone(i)` from an
  `interval:` poller guarded by `changed_since` (gp README "LVGL reads gp only from pollers"). The existing
  `packages/lvgl/page_lawn.yaml` concept page stays as it is.

### ESPHome behaviour checked (pinned 2026.9.1)
- Package merge, `esphome/config_helpers.py` at tag 2026.9.1
  (https://github.com/esphome/esphome/blob/2026.9.1/esphome/config_helpers.py): dicts merge recursively, lists
  concatenate. So `garden_zones: groups:` from `packages/greenhouse/irrigation.yaml` and `packages/lawn/irrigation.yaml`
  become one hub with both groups, and `gp: groups:` gains `gp_lawn` the same way `packages/greenhouse/gp.yaml` adds
  `gp_greenhouse` today. Package docs (https://esphome.io/components/packages/): "Dictionaries are merged key-by-key",
  "Other lists are merged by concatenation", main-config substitutions override package substitutions; `!include` with
  `vars` is the template mechanism. The docs also mention a package `defaults:` block: **do not use it** (not verified
  for the minimum 2026.6.3; the repo uses package `substitutions:` defaults instead).
- Several `external_components` entries with the same local source already coexist (core gp, greenhouse irrigation,
  schedule). The lawn irrigation file declares its own `${gp_root}/components` entry for `[garden_zones, garden_zone]`
  so a lawn-only build works; the `lawn_with_greenhouse_headless` and `lawn_only_headless` rows prove both cases.
- Minimum version 2026.6.3 (SPEC §6): no component schema touched by this task differs; the engine is our own. The
  example is checked once at the minimum by hand (acceptance criteria), like 023 did for its LilyGO row.

### Decisions (planner)
1. **Directory `packages/lawn/`** (SPEC §5 target layout said `lawn.yaml`; a directory mirrors `packages/greenhouse/`):
   `irrigation.yaml` (engine group), `zone.yaml` (one include per zone), `gp.yaml` (gp group + entities).
2. **Ids and names** (prefix `lawn_`; HA names from the substitution `lawn_name`, default `"Lawn"`):
   - engine group `lawn_zones`, auto advance `lawn_zones_auto_advance` "`${lawn_name}` auto advance";
   - zone N: `lawn_zone<N>_engine_valve` (internal, name `${zone_name}`), `lawn_zone<N>_enable`
     "`${zone_name}` enable", `lawn_zone<N>_run_duration` "`${zone_name}` run duration", gp switch
     `lawn_zone<N>_switch` "`${zone_name}`" (position `${zone}`);
   - gp group `gp_lawn`, name `${lawn_name}`, key `lawn` (fixed: HA automations call `group: lawn`);
   - `lawn_zones_watchdog_problem` "`${lawn_name}` watchdog" (problem), `lawn_zones_watchdog_reset`
     "`${lawn_name}` watchdog reset" (config), `gp_lawn_main_switch` "`${lawn_name}` irrigation" (template, restore
     `DISABLED`, ON = `gp.full_cycle: gp_lawn`, OFF = `gp.stop_all: gp_lawn`, lambda `summary().running`),
     `gp_lawn_status` "`${lawn_name}` status";
   - hook scripts `gp_lawn_zone_finished`, `gp_lawn_zone_done`, `gp_lawn_stopped` (logger only; the future lawn schedule
     `!extend`s them, same as greenhouse).
   - Never `lawn_zones_watchdog` or `lawn_zones_lane_<n>` as a template id (generated ids, CLAUDE.md gotcha).
3. **Include vars.** `zone.yaml`: `zone` (1..16, position and id part), `zone_name`, `relay`. `irrigation.yaml`:
   `pump_relay` (required var, no default, like the bed's `relay`; one block to uncomment instead of a separate
   substitution). Var names must not shadow global substitutions (extend `test_bed_vars_do_not_shadow_globals` or add
   a lawn twin).
4. **Substitutions of `packages/lawn/irrigation.yaml`** (public defaults, all overridable in the entry file):
   `lawn_name: "Lawn"`, `lawn_max_parallel: "1"`, `lawn_max_on_time: 60min`, `lawn_zone_run_max: "55"` (minutes),
   `lawn_zone_run_initial: "15"`, `lawn_pump_max_on_time: 2h`, `lawn_pump_idle_timeout: 10s`,
   `lawn_pump_start_pump_delay: 0s`, `lawn_pump_stop_valve_delay: 0s` (stock behaviour; open question 5), `gp_root: "."`.
   None defaults to `never`. Header comment documents each, the session rule (`zones x lawn_zone_run_max` must fit
   under `lawn_pump_max_on_time`) and that `lawn_max_parallel` other than `"1"` is not supported by this package yet
   (lanes would share the pump, but the session check and docs assume one at a time). The run-duration number has
   `restore_value: true`, `min_value: 1`, `step: 1`, `unit_of_measurement: min`, `mode: BOX`, like the bed.
5. **Package order** (CLAUDE.md step 5, appended after the greenhouse block, before `touch_dot_test`):
   `lawn_irrigation` -> `lawn_zone_N` (zone order, N = 1..k consecutive) -> `lawn_gp`. Needs `core_gp` (and
   `core_gp_api` when `api` is present) earlier in the list; works without any greenhouse package.
6. **`garden-pilot.yaml`**: commented-out lawn blocks in the **multi-line** form (`# key: !include` + `#   file:` +
   `#   vars:` lines; `uncomment_examples()` in `tests/test_config_matrix.py` only recognises that form), e.g. pump on
   relay 4, zones 1-2 on relays 5-6 (the breadboard profile has 12 relays; beds use 1-3). Nothing is enabled by default:
   the device config is unchanged.
7. **`examples/my-garden.yaml`** uses `hardware/lilygo-t-relay-s3.yaml` (the author's target board, SPEC §2.2; the only
   committed profile driving the T-Relay-S3 relays through the 74HC595). The breadboard profile was not chosen: its 12
   relays are plain GPIOs, which matches neither the author's rig nor the target. Contents (generic names, device name
   `gp-my-garden`, `gp_root: ".."`, secrets only as `!secret` substitutions from `secrets.example.yaml` keys):
   - core, display and LVGL packages as in the 023 examples (incl. `lvgl_page_lawn`, `lvgl_page_touch_test`; no
     `touch_dot_test`); no greenhouse sensor packages (the LilyGO profile defines no DHT / ADC pins, 023 deviation 6;
     open question 9);
   - `gh_irrigation` = `packages/greenhouse/irrigation.yaml` (no pump: gravity barrel), beds 1-3 on relays 1-3,
     `gh_max_parallel: "all"`, `gh_max_on_time: 3h30min`, `gh_bed_run_max: "200"`, `gh_bed_run_initial: "180"`
     (200 x 60 s + 2 s = 12002 s <= 12600 s; recommended values, open question 3), `core_gp`, `core_gp_api`, `gh_gp`,
     `gh_lvgl_page`, `gh_gp_lvgl`, `gh_valve_test`, `gh_schedule` + 2 slots;
   - lawn: pump on relay 4, 2 zones on relays 5-6 (`"Lawn"`, `"Flowers"`), package defaults otherwise (session
     2 x 55 min = 110 min < 2 h). Everything stays on the six main-board relays, so the unverified expansion bit map
     (023 open question) is not needed;
   - a header comment that the limits are the author's choice for a 3 h gravity run and that the public defaults
     (60 min / 55 min) stay as they are; a comment per actuator relay listing its function.
8. **No host scenario.** The pump-group engine behaviour is covered by `tests/configs/garden_zones_pump_sim.yaml` and
   the groups scenario; a new host build costs 1-2 min of the 15 min `checks` budget. The two-gp-group codegen is
   covered by one local `script/compile` of the example (acceptance) instead. `hardware/sim.yaml` has 3 relays, so the
   lawn in the emulator is a follow-up.

## Files
- create: `packages/lawn/irrigation.yaml` — group `lawn_zones` (pump `board_relay_${pump_relay}`, substitutions of
  decision 4, `external_components` with `${gp_root}/components`, `on_watchdog_trip` ERROR log with tag `lawn_zones`),
  header comment like `packages/greenhouse/irrigation_pump.yaml`.
- create: `packages/lawn/zone.yaml` — one `garden_zone:` list item (group `lawn_zones`, internal engine switch,
  enable switch, run-duration number, `valve_switch_id: board_relay_${relay}`) + one `gp_zone:` list item (group
  `gp_lawn`); header with the include example and rules (copy the structure of `packages/greenhouse/bed.yaml`).
- create: `packages/lawn/gp.yaml` — gp group `gp_lawn` with `on_zone_finished` / `on_stop` hooks, the entities and
  scripts of decision 2; one-line lambdas only.
- create: `examples/my-garden.yaml` — decision 7.
- create: `tests/test_lawn.py` — unit checks below.
- modify: `garden-pilot.yaml` — commented-out lawn blocks (decision 6) with a one-line comment each.
- modify: `tests/test_config_matrix.py` — lawn rows (below); a `LAWN` key list constant.
- modify: `tests/test_examples.py` — `my-garden` in `EXAMPLE_NAMES`; `_rank` gets `lawn_irrigation` 70,
  `lawn_zone_N` 71 (consecutive from 1), `lawn_gp` 72; `test_gp_root_default` count of local-path packages 5 -> 6;
  new `test_my_garden_shape`.
- modify: `tests/test_layout.py` — `test_entry_relays_exist` also collects the `pump_relay` var; new
  `test_entry_relays_unique`; var-shadow check covers `zone.yaml` / `irrigation.yaml` vars.
- modify: `tests/test_gp_layer.py` — `ENGINE_FILES` += the three lawn files; the engine regex in
  `test_no_engine_outside_adapter` also matches `\blawn_zones\b`; `zone.yaml` added to `irrigation_files` in
  `test_lvgl_only_from_pollers`.
- modify: `examples/README.md` — a `my-garden.yaml` row (what it shows, LilyGO, limits raised on purpose).
- modify: `docs/SPEC.md`, `CLAUDE.md`, `README.md` + `README.ru.md` (kept in sync), `design/README.md` — see Docs.

(About 12 code/test files plus docs. If the implementer runs short, the docs are the last commit, not dropped.)

## Checks to write first
| Level | Test | Asserts |
|---|---|---|
| unit | `tests/test_lawn.py::test_lawn_irrigation_shape` | exactly one group `lawn_zones`, name `${lawn_name}`, `max_parallel: ${lawn_max_parallel}`, `max_on_time` / `pump_max_on_time` / `pump_idle_timeout` / the two pump delays from the decision-4 substitutions, `pump_switch_id: board_relay_${pump_relay}`, `auto_advance_switch` id `lawn_zones_auto_advance`, `on_watchdog_trip` logs at ERROR; no `main_switch`, no `zones:`, no `garden_zone:` items, no `GPIO\d+`, no `!secret`; external component source `${gp_root}/components` |
| unit | `tests/test_lawn.py::test_lawn_defaults` | default substitutions exactly as decision 4; none is `never`; `lawn_zone_run_max * 60 + 2 + delays <= lawn_max_on_time`; `lawn_pump_max_on_time >= lawn_max_on_time`; `lawn_zone_run_initial <= lawn_zone_run_max`; `lawn_pump_idle_timeout >= 2 s + delays`; `lawn_max_parallel == "1"` |
| unit | `tests/test_lawn.py::test_lawn_zone_shape` | `garden_zone` and `gp_zone` are one-item lists; group `lawn_zones` / `gp_lawn`; engine valve switch `internal: true` with name `${zone_name}` equal to the gp_zone name; ids per decision 2; run-duration number max `${lawn_zone_run_max}`, initial `${lawn_zone_run_initial}`, min 1, `restore_value: true`; `valve_switch_id: board_relay_${relay}`; position `${zone}`; no `lvgl.`, `sprinkler`, `!extend` |
| unit | `tests/test_lawn.py::test_lawn_gp_shape` | one gp group `{id: gp_lawn, name: ${lawn_name}, key: lawn, garden_zones_id: lawn_zones}` + hooks; watchdog binary sensor condition `gp.watchdog_tripped: gp_lawn`, `device_class: problem`, id not `lawn_zones_watchdog`; reset button `entity_category: config`, `on_press` = `gp.reset_watchdog: gp_lawn`; main switch template, `restore_mode: DISABLED`, not optimistic, ON = `gp.full_cycle: gp_lawn`, OFF = `gp.stop_all: gp_lawn`; status text sensor `gp_lawn_status`; every gp action targets `gp_lawn` (never `gp_greenhouse`, never `garden_zones.*`); lambdas one line; no template id matches `lawn_zones_watchdog` or `lawn_zones_lane_\d+` |
| unit | `tests/test_lawn.py::test_lawn_session_fits_pump_limit` | for every device entry that enables the lawn (`garden-pilot.yaml` with commented blocks treated as active, `examples/*.yaml`): zone count x (effective `lawn_zone_run_max` min + delays) <= effective `lawn_pump_max_on_time` (entry substitutions override package defaults) |
| unit | `tests/test_lawn.py::test_lawn_includes` | in each entry with lawn: `lawn_irrigation` before the zones, zones `lawn_zone_1..k` consecutive with `vars` `{zone, zone_name, relay}`, `zone` matches the key number, `zone_name` unique, `lawn_gp` after the last zone and after `core_gp` (and after `core_gp_api` when present); `pump_relay` var present |
| unit | `tests/test_lawn.py::test_greenhouse_public_defaults_unchanged` | `packages/greenhouse/irrigation.yaml` still defaults `gh_max_parallel "1"`, `gh_max_on_time 60min`, `gh_bed_run_max "55"`, `gh_bed_run_initial "5"` (the 3 h values live only in `examples/my-garden.yaml`) |
| unit | `tests/test_layout.py::test_entry_relays_unique` | per device entry (commented examples active): bed relays, lawn zone relays, `pump_relay`, `gh_pump_relay` are pairwise distinct |
| unit | `tests/test_layout.py::test_entry_relays_exist` (extended) | also the `pump_relay` var of the lawn include exists in the entry's profile |
| unit | `tests/test_gp_layer.py::test_no_engine_outside_adapter` (extended) | `lawn_zones` / `garden_zones.` appear only in the three lawn engine-side files (and the existing greenhouse ones) |
| unit | `tests/test_examples.py::test_my_garden_shape` | hardware = `../hardware/lilygo-t-relay-s3.yaml`; `gh_irrigation` is `irrigation.yaml` (no pump); beds 1-3 on relays 1-3; `gh_max_parallel "all"`; `gh_bed_run_max >= 180`; `gh_bed_run_max * 60 + 2 <= gh_max_on_time`; no `never`; lawn pump + >= 1 zone; every relay <= 6 (main board); `gh_schedule` present; device name `gp-my-garden` |
| unit | `tests/test_examples.py` (existing, extended by the name list) | `my-garden` passes the existing secrets / paths / gp_root / package-order checks (lawn ranks added) |
| config | `tests/test_config_matrix.py::test_variant_validates[lawn_with_greenhouse_headless]` | CORE + `gh_irrigation`, `gh_bed_1`, GP_API + lawn blocks enabled (`enable=`) -> `esphome config` OK |
| config | `...[lawn_only_headless]` | CORE + `core_gp`, `core_gp_api` + lawn blocks, no greenhouse package -> OK |
| config | `...[lawn_max_on_time_too_short]` | as `lawn_only_headless`, `-s lawn_max_on_time 30min` -> fails with `max_value` and `max_on_time` |
| config | `...[lawn_pump_max_on_time_too_short]` | as `lawn_only_headless`, `-s lawn_pump_max_on_time 30min` -> fails with `pump_max_on_time` and `below max_on_time` |
| config | `tests/test_examples.py::test_example_validates[my_garden]` | `GP_SECRETS=example script/config examples/my-garden.yaml` exits 0 (pinned version, like the other examples) |

Five new `esphome config` rows at roughly 2 s each; no new host or cpp build.

## Acceptance criteria
- [x] `uv run pytest -m unit` -> all pass, including every new/extended test above.
- [x] `script/lint` -> passes.
- [x] `script/test` -> passes; the 4 new matrix rows and the `my_garden` example row are in the output; CI `checks`
      stays under 15 min (implementer notes the measured local time and, after push, the CI job time).
- [x] `GP_SECRETS=example script/config examples/my-garden.yaml` -> OK; `GP_SECRETS=example GP_ESPHOME=minimum
      script/config examples/my-garden.yaml` -> OK (result noted in Implementation notes).
- [ ] `GP_SECRETS=example script/compile examples/my-garden.yaml` (pinned) builds once locally (two gp groups + two
      engine groups compile); result and firmware size noted. Not a CI job.
- [ ] `GP_SECRETS=example script/compile` (root `garden-pilot.yaml`) still builds; the normalized `esphome config`
      output of `garden-pilot.yaml` is unchanged by this task (the lawn is commented out).
- [x] `grep -rn "lawn_zones\|garden_zones\." packages/ garden-pilot*.yaml` shows only the engine-side files
      (greenhouse `irrigation.yaml` / `bed.yaml` / `gp.yaml`, `packages/sim/fault.yaml`, the three lawn files).
- [x] `examples/my-garden.yaml` contains no real SSID, IP, hostname, entity id, or path from the author's home;
      `git status` shows no `secrets.yaml` and no build output.
- [x] Docs updated as listed below; `README.md` and `README.ru.md` in sync.
- [ ] Hardware (author, cannot be checked in CI, optional): on a T-Relay-S3 flashed with `my-garden.yaml`: (1) no relay
      clicks at power-on, reset and OTA reboot; (2) "Greenhouse irrigation" ON opens R1-R3 together; (3) "Lawn
      irrigation" ON runs R5 then R6 with the pump R4 on during both and off within a second after R6 closes, no
      `pump_idle` watchdog trip; (4) "Lawn" switch alone = R5 + R4 only; (5) both groups can run together (or the author
      answers open question 4 otherwise).

## Docs the implementer updates
- `docs/SPEC.md`: §4 a short "Second group: lawn" paragraph (pump group `lawn_zones`, `max_parallel 1`, gp group
  `gp_lawn` key `lawn`, groups run independently, no interlock, session rule for `pump_max_on_time`, lawn schedules =
  second `garden_schedule` hub later); §4.1 note that HA actions work with `group: lawn` and the zone switches are
  "`<zone_name>`"; §5 target layout `lawn/` instead of `lawn.yaml` and a bullet for `packages/lawn/*` with its vars and
  substitutions; §8 the Lawn page now has backing data through `gp_lawn` (page not wired); §9 stage 13 mark task 024 and
  list the follow-ups; §9.1 update the lawn backlog item from 023 accordingly.
- `CLAUDE.md`: layout table row for `packages/lawn/` (irrigation / zone / gp); `packages:` order step 5 extended with
  `lawn_irrigation` -> `lawn_zone_N` -> `lawn_gp`; conventions: "Add a lawn zone" (one include with `vars` `{zone,
  zone_name, relay}`, pump relay as the `pump_relay` var, zones x run max under `lawn_pump_max_on_time`); the
  `test_no_engine_outside_adapter` file list sentence if it is mentioned.
- `README.md` / `README.ru.md`: module list mentions the lawn package and `examples/my-garden.yaml`.
- `examples/README.md`: the new example row.
- `design/README.md`: Lawn page entry: "backing data exists (`gp_lawn`, task 024); not wired yet".

## Out of scope
- Lawn schedules (second `garden_schedule` hub `lawn_schedule` + slots): needs `schedule_slot.yaml` generalised to a
  group prefix first. Follow-up task, recommended next.
- LVGL: Lawn page, Home lawn card, WATER tab, valve test rows for lawn zones / pump (stage 9 screen tasks). The pollers
  will read `gp_lawn`.
- Service mode for all groups (valve test currently inhibits only `gp_greenhouse`).
- A cross-group interlock (shared water source or power supply limit) and a dry-run / flow sensor for the pump (§9.1).
- Per-group zone short-name prefix in `gp` ("Z1" instead of "B1" for the lawn).
- Lawn in the PC emulator (`hardware/sim.yaml` has 3 relays; needs more sim relays + SIM board page update).
- `lawn_max_parallel` other than `"1"` (lanes sharing the pump); soil skip for lawn zones (a `zone_soil_skip` variant
  like `bed_soil_skip.yaml`).
- A board profile for the author's current rig (DevKitC-1 + T-Relay-S3 extension board via 74HC595); see open
  question 8. Greenhouse sensors on the LilyGO (open question 9).
- Compiling the examples in CI; remote packages / tags (rest of stage 13).

## Open questions
Each has the recommended default the implementer uses unless the author answers otherwise; none blocks the task.
1. **Number of lawn zones** in `my-garden.yaml`? Recommended: 2 ("Lawn", "Flowers") on relays 5-6, so the whole config
   fits the six main-board relays; more zones go to relays 7-12 once the expansion bit map is verified.
2. **Lawn zone run times?** Recommended: initial 15 min, max 55 min (package defaults), watchdog 60 min. Safety
   limits are the author's call.
3. **Greenhouse limits for the 3 h gravity run?** Recommended: `gh_bed_run_initial 180`, `gh_bed_run_max 200`,
   `gh_max_on_time 3h30min` (a stuck valve drains the barrel for at most 3.5 h). Confirm or give other values.
4. **May lawn and greenhouse water at the same time?** The engine allows it (separate groups, no interlock).
   Recommended: yes, since the sources differ (barrel vs. pump). If they share a source or the valve power supply cannot
   drive 3 bed valves + a lawn valve + the pump relay coil at once, an interlock is a follow-up task.
5. **Which relay drives the pump, and how?** Recommended: R4 on the main board, switching a contactor or the pump's own
   relay, not the pump motor directly (relay rating is the author's call). Pump delays: recommended `0s` (stock: valve
   and pump switch together); set `lawn_pump_start_pump_delay` (valve opens first) and `lawn_pump_stop_valve_delay`
   (pump stops first) if the pump has no pressure switch or bypass. `lawn_pump_max_on_time` 2 h,
   `lawn_pump_idle_timeout` 10 s.
6. **Lawn schedules: separate hub/slots or shared with the greenhouse?** Recommended: a separate hub `lawn_schedule`
   ("Lawn schedules" master switch, its own slots), because the greenhouse hub's zone masks address only greenhouse zones
   and the groups have different water sources. Next task.
7. **Should the valve-test service mode also stop the lawn?** Recommended: yes (service mode = nothing waters except
   the test), as a follow-up together with lawn rows on the valve test page.
8. **A profile for the current test rig** (DevKitC-1 + extension board on a 74HC595 without an OE line)? Recommended:
   not now; if wanted, a separate task, because the 74HC595 outputs are undefined from power-on until ESPHome first
   latches them and the extension board's header has no OE line to hold them off (principle 4: relays must stay off at
   boot). Needs a pull-up on OE or a power-on test by the author first.
9. **Greenhouse air/soil sensors on the LilyGO** (the real setup has a DHT11 and a soil probe)? Recommended: left out of
   `my-garden.yaml` for now (the profile has no DHT / ADC pins); add with an I2C sensor on the board's I2C header in a
   later task.
10. **Should lawn entity names stay "Lawn ..." when the group also holds flower beds?** Recommended: keep
   `lawn_name: "Lawn"` (key `lawn`); a builder can rename the group with the substitution, zone names come from the vars.



## Implementation notes

### Decided (default, author to confirm)
The author was away; every open question uses the recommended default:
1. Lawn zones: 2 ("Lawn", "Flowers") on relays 5-6.
2. Lawn run times: initial 15 min, max 55 min, watchdog 60 min.
3. Greenhouse 3 h gravity run: `gh_bed_run_initial 180`, `gh_bed_run_max 200`, `gh_max_on_time 210min` (see deviation 1).
4. Lawn and greenhouse may water at the same time (no interlock).
5. Pump on R4 (contactor / the pump's own relay); delays `0s`; `lawn_pump_max_on_time` 2h, `lawn_pump_idle_timeout` 10s.
6. Lawn schedules: separate hub later (not built here).
7. Service mode for the lawn: follow-up.
8. No profile for the test rig.
9. No greenhouse sensors in `my-garden.yaml`.
10. `lawn_name: "Lawn"` stays.

### Notes
- Checks first: `tests/test_lawn.py` (+ the extended layout / examples / gp-layer / matrix tests) were written and run
  red before the packages existed (the shape tests failed on the missing files).
- Verified against the real files (the task was written from summaries): task 023 is in the worktree as described;
  `hardware/lilygo-t-relay-s3.yaml` has `board_relay_1..12`, `tests/test_examples.py` / `test_layout.py` helpers matched
  the task text. Differences found and handled:
  1. **Time period syntax.** `gh_max_on_time: 3h30min` is rejected by ESPHome ("Unknown value 'h30min'"); the example
     uses `210min` (same 3.5 h). `test_my_garden_shape` parses `min` / `h` units only.
  2. **`lawn_gp` as a commented block.** `uncomment_examples()` only recognises the multi-line `# key: !include` form, so
     `lawn_gp` in `garden-pilot.yaml` is written as `# lawn_gp: !include` + `#   file: packages/lawn/gp.yaml`.
  3. **Extra test touched.** `tests/test_garden_zones.py::test_device_uses_groups_form` fails on any package other than
     the greenhouse irrigation files that has top-level `garden_zones:` / `external_components:`; it now also accepts
     `packages/lawn/irrigation.yaml` (same shape) and `zone.yaml` (a `garden_zone:` list only).
  4. `test_substitutions_resolve` (test_layout) needed the lawn include vars (`zone`, `zone_name`, `relay`, `pump_relay`)
     registered as supplied by the entry-file includes.
  5. Gp icon: the first choice `mdi:sprinkler-variant` contains "sprinkler", which `test_no_engine_outside_adapter`
     rejects in package files; the lawn main switch uses `mdi:flower`.
  6. The example puts the lawn blocks after the greenhouse schedule slots (CLAUDE.md order step 5: lawn last, after
     `core_gp` / `core_gp_api`), same as the commented blocks in `garden-pilot.yaml`.
- `lawn_gp` hooks (`gp_lawn_zone_finished`, `gp_lawn_zone_done`, `gp_lawn_stopped`) use log tag `gp_lawn`.
- Not run on a real device. Hardware checklist from the acceptance criteria is untouched.

## Follow-ups
- Lawn schedules (second `garden_schedule` hub; generalise `schedule_slot.yaml` to a group prefix first).
- LVGL: Lawn page, Home lawn card, valve-test rows for lawn zones and the pump (read `gp_lawn` from pollers).
- Service mode for all groups (valve test inhibits only `gp_greenhouse`).
- Per-group zone short-name prefix in `gp` ("B1" is hard-coded; lawn status reads "Watering B2").
- Lawn in the PC emulator (`hardware/sim.yaml` has 3 relays); soil skip for lawn zones; `lawn_max_parallel` other than 1.
- Profile for the DevKitC-1 + extension-board test rig (open question 8).

### Results (Windows host, Git Bash + uv)
- `script/lint` ok. `script/test`: 851 passed, 19 skipped, 6 failed in 125 s locally; the 6 failures are the known
  Windows-only ones in files this task does not touch (`test_ci.py::test_esphome_selector_resolves`, four in
  `test_devcontainer.py`, `test_sim_ui.py::test_start_xvfb_deadline_holds_when_xvfb_hangs`). New rows pass: 4 lawn matrix
  rows, `test_example_validates[my_garden]`, all `test_lawn.py` tests.
- `GP_SECRETS=example script/config examples/my-garden.yaml` OK at the pinned 2026.9.1 and with `GP_ESPHOME=minimum`.
- NOT done: `script/compile` of `examples/my-garden.yaml` and of `garden-pilot.yaml`. On this Windows host the ESP-IDF 5.5.5
  framework install fails ("framework installation failure" after a resumed tool download); not retried. The
  two-gp-group codegen compile is unverified until CI/Linux. `garden-pilot.yaml` is unchanged except comments, so its
  config output is unchanged. CI `checks` time not measured (local 125 s).
- The `grep` criterion was checked through `test_no_engine_outside_adapter` (extended); the three acceptance items
  `script/compile` x2 and the hardware checklist stay unticked.
- Review follow-ups: a way to stop the lawn from the touch screen (no lawn STOP on screen yet); naming: the zone switch
  "Lawn" vs the main switch "Lawn irrigation" can confuse in Home Assistant when a zone is also called "Lawn".
