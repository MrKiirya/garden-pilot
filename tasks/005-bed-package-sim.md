# 005 — Modular layout, part 2: bed package, optional bed soil sensor, board relays, sim board, more matrix rows

Status: implemented (awaiting review)
Roadmap: SPEC §9 item 4 "Modular layout" (part 2 of 2; part 1 is task 004)
Spec sections: SPEC §3, §4 (soil moisture optional per zone), §5, §6, §7 (items 1 and 4), §10 (screens question 2);
CLAUDE.md core principles 2, 3, 4, 7
Hardware check: yes. The author flashes the branch firmware on the breadboard build and repeats the task 004 device
checklist (see Acceptance criteria). The optional per-bed soil sensor is **not** enabled on the author's device, so it
is validated by `esphome config` only. CI cannot check hardware.

## Goal
A greenhouse bed becomes one package, `packages/greenhouse/bed.yaml`, included once per bed from the entry file with
`!include` + `vars` (bed number, bed name, board relay). Adding or removing a bed is one block in `garden-pilot.yaml`
instead of editing the irrigation file. A bed can optionally get its own soil moisture sensor through a second
include, `packages/greenhouse/bed_soil.yaml`; a bed without a sensor needs no extra lines. The sensor only reports
(skipping a run when wet is `garden_zones`, stage 6). The raw relay drivers move into the board profile under
board-function ids (`board_relay_1` …), so a new `hardware/sim.yaml` can replace them with template switches and the
irrigation part of the firmware validates without any real board. The config matrix gets rows for 2 beds, a bed with
its own soil sensor, and the sim board. The author's device behaves exactly as before: same Home Assistant entities,
same saved run durations, same pins, same greenhouse-wide soil probe.

## Context

### Current state (master after task 004)
- `packages/greenhouse/irrigation.yaml` defines three raw valve switches (`platform: gpio`, ids
  `gh_valve_zone{1,2,3}_sw`, `internal: true`, `RESTORE_DEFAULT_OFF`, pins `${relay_N_pin}`) and one stock
  `sprinkler:` entry `gh_sprinkler` with `main_switch` (`gh_sprinkler_main_switch`, "Greenhouse irrigation", log
  triggers), `auto_advance_switch: "Greenhouse auto advance"` and three `valves:` items. Each valve has
  `valve_switch: "Greenhouse bed N"`, `enable_switch: "Greenhouse bed N enable"`, a `run_duration_number` with id
  `gh_bedN_run_duration`, name "Greenhouse bed N run duration" (initial 5, 1–120 min, `restore_value: true`,
  `mode: BOX`, icon `mdi:timer-outline`) and `valve_switch_id: gh_valve_zoneN_sw`.
- `packages/greenhouse/sensors_soil.yaml` is the greenhouse-wide probe: `platform: adc` on `${soil_ao_pin}`, id
  `gh_soil_moisture_pct`, name "Greenhouse soil moisture", median → `calibrate_linear` (`soil_cal_dry_v` /
  `soil_cal_wet_v`, defaults in its own `substitutions:` block) → clamp 0–100, plus LVGL updates in `on_value`; and a
  gpio `binary_sensor` on `${soil_do_pin}`.
- `hardware/esp32-s3-devkitc1-breadboard.yaml` has only `esp32:` and `substitutions:` (14 `*_pin` keys plus display
  and touch orientation/calibration). `tests/test_layout.py::test_hardware_profiles_shape` allows only
  `{substitutions, esp32, psram}`.
- Legacy coupling that stays (do not fix here):
  - `packages/greenhouse/lvgl_page.yaml` calls `sprinkler.start_single_valve` / `queue_valve` with fixed
    `valve_number: 0/1/2`, `sprinkler.shutdown` and `start_from_queue` on `gh_sprinkler`;
  - `packages/greenhouse/sprinkler_lvgl_status.yaml` reads `gh_bed1_run_duration` … `gh_bed3_run_duration`;
  - `sensors_air_dht.yaml` and `sensors_soil.yaml` update LVGL labels.
  So the greenhouse page, its status poller and the greenhouse-wide sensors still need exactly three beds plus the
  display. Only `gh_irrigation`, the bed packages and the bed soil packages are display-free.
- `tests/test_config_matrix.py` builds variants line by line from the real entry file. Its builder handles one-line
  package entries only: continuation lines of a dropped multi-line entry would be kept (they are indented and not a
  comment), so it must learn to drop a whole block. It also cannot add a package; this task teaches it to
  **uncomment** a commented-out example block (what a user does, SPEC §5).

### ESPHome behaviour checked (pinned 2026.9.1; minimum 2026.6.3 must be confirmed by the implementer)
- Package merge, source `esphome/config_helpers.py` at tag 2026.9.1, `merge_config`: dicts merge key by key and
  **lists are concatenated** (`old + new`), with no de-duplication by id at this stage.
- `!extend` / `!remove`, source `esphome/config.py` at 2026.9.1, `resolve_extend_remove`: after packages are merged,
  every list in the config is indexed by `id`; each `id: !extend X` item is merged into item `X` with `merge_config`
  (the index entry is replaced, so several extensions of the same id accumulate). Therefore a nested list such as
  `valves:` inside an extended `sprinkler` item is **concatenated, in package order**. A missing source id raises
  "Source for extension of ID 'X' was not found". Task 004 already uses the same mechanism for
  `time: [{id: !extend ha_time}]` across packages (works on 2026.6.3 and 2026.9.1).
- Packages docs ([esphome.io/components/packages](https://esphome.io/components/packages/)): `!include` with `file:`
  + `vars:` can include the same file several times with different values; vars are referenced as `${var}`;
  "package variables and substitutions are in fact the same thing"; a substitution takes its value from the
  **outermost** section that defines it; substitution is a single pass. A package may carry a `defaults:` block.
- Scoping of vars has regressed recently: [esphome#16264](https://github.com/esphome/esphome/issues/16264)
  ("Substitution cannot access a package variable", regression in 2026.4.4, fixed by esphome#16274) after the loader
  redesign ([esphome#12126](https://github.com/esphome/esphome/pull/12126),
  [esphome#14918](https://github.com/esphome/esphome/pull/14918)). Therefore:
  - no `substitutions:` or `defaults:` block inside `bed.yaml` / `bed_soil.yaml` (no substitution that refers to a
    var);
  - var names must not collide with any global substitution (e.g. not `soil_cal_dry_v`, which `sensors_soil.yaml`
    defines; "outermost wins" would silently override the var);
  - the one place where a var value refers to a global substitution (`adc_pin: ${adc_1_pin}`, see Decision 4) is
    verified by the spike on both versions.
- Sprinkler validation, source `esphome/components/sprinkler/__init__.py` at 2026.9.1, `validate_sprinkler`
  ([docs](https://esphome.io/components/sprinkler/)):
  - more than one valve: `main_switch` and `auto_advance_switch` are **required**;
  - one valve: `main_switch`, `auto_advance_switch`, `reverse_switch`, valve `enable_switch`, `valve_open_delay` and
    `valve_overlap` are **forbidden**;
  - `valves:` is `cv.ensure_list(...)`; validation runs on the merged config, so the base entry may have no valves.
- Host platform ([esphome.io/components/host](https://esphome.io/components/host/)): no `wifi:`, no GPIO/ADC/DHT
  hardware components; API, `ota: esphome`, preferences and SDL display are supported. Consequence: `hardware/sim.yaml`
  cannot be combined with `packages/core/network.yaml` (it contains `wifi:` and `captive_portal`), with
  `display_touch` (mipi_spi), with the greenhouse sensors (DHT, ADC) or with `bed_soil.yaml` (ADC).
- ADC on ESP32-S3 ([esphome.io/components/sensor/adc](https://esphome.io/components/sensor/adc/)): only ADC1 pins
  (GPIO1–GPIO10) are usable while Wi-Fi is active. Relevant for which pins a board profile may offer as `adc_N_pin`;
  this task adds no new pin.

## Decisions (author, 2026-10-02)
1. **Raw relays live in the board profile.** `hardware/<board>.yaml` defines the internal relay switches
   `board_relay_1` … `board_relay_N`; every board profile must define them (same set of ids in every profile).
   On the breadboard: `platform: gpio`, `internal: true`, `restore_mode: RESTORE_DEFAULT_OFF`,
   `pin: number: ${relay_N_pin}, mode: output: true` — identical to today apart from the id. The `relay_N_pin`
   substitutions stay and are used inside the profile itself. Raw sensor drivers (DHT, ADC) stay in feature files.
2. **At least 2 beds** until `garden_zones` (stage 6), because the stock sprinkler forbids the controller switches and
   the per-bed enable switch with one valve. Documented in `bed.yaml`'s header, SPEC §5 and both READMEs.
3. **Bed name is a package var.** The author's entry file keeps `bed_name: "Greenhouse bed 1..3"`, so HA entities do
   not change.
4. **Optional per-bed soil moisture sensor, in this task.**
   - Pattern: a separate optional include per bed, `packages/greenhouse/bed_soil.yaml`. A bed without a sensor has
     no `bed_soil` block at all; nothing in `bed.yaml` refers to the sensor. Rejected alternatives: a flag var in
     `bed.yaml` (ESPHome YAML has no conditionals; `!remove` tricks would be fragile), a `defaults:` block with a dummy
     pin (would create a sensor on every bed).
   - Vars (all required, no defaults): `bed`, `bed_name` (same values as the bed's own include), `adc_pin` (a
     reference to a board-function pin, e.g. `${adc_1_pin}` — never a GPIO literal), `cal_dry_v`, `cal_wet_v`
     (calibration of that probe, in volts).
   - Content: exactly one `sensor:` item, `platform: adc`, `pin: ${adc_pin}`, id `gh_bed${bed}_soil_moisture`, name
     `"${bed_name} soil moisture"`, unit `%`, `device_class: moisture`, `accuracy_decimals: 0`, and the same
     sampling and filter chain as the greenhouse-wide probe (`update_interval: 5s`, `attenuation: 12db`, `samples: 8`,
     median 5/5/1, `calibrate_linear` `${cal_dry_v} -> 0.0` / `${cal_wet_v} -> 100.0`, clamp 0–100). No `on_value`,
     no LVGL, no binary DO sensor. It only reports; no irrigation logic uses it.
   - Pin naming by function: the board profile's analog soil input `soil_ao_pin` is renamed **`adc_1_pin`** (same
     `GPIO6`). The greenhouse-wide probe in `sensors_soil.yaml` uses `${adc_1_pin}`. `soil_do_pin` stays as is. No new
     GPIO is assigned (pins are the author's call). Substitutions are dropped from the normalized diff, so this rename
     does not change the rendered config.
   - One ADC pin can serve either the greenhouse-wide probe or one bed sensor, not both (ESPHome rejects a pin used
     twice). The header of `bed_soil.yaml` and the entry-file comment say so.
   - The author's device: the entry file contains **commented-out** example blocks `gh_bed_N_soil` (at least for bed 1)
     so enabling a sensor is "uncomment and set `adc_pin` and calibration". Nothing changes on the device.
5. **Network split stays for stage 11.** `hardware/sim.yaml` is for `esphome config` only and validates irrigation +
   beds (no Wi-Fi/API, no display, no sensors).
6. **Bed valves join the existing sprinkler through `!extend`** (planner, unchanged). `irrigation.yaml` keeps the
   `gh_sprinkler` entry with `main_switch` and `auto_advance_switch` but no valves. Each bed package adds one valve:
   ```yaml
   sprinkler:
     - id: !extend gh_sprinkler
       valves:
         - valve_switch: "${bed_name}"
           # enable_switch, run_duration_number (id gh_bed${bed}_run_duration), valve_switch_id: board_relay_${relay}
   ```
   No engine change, no generated YAML; the valve order (= `valve_number` used by the page) is the order of the
   `gh_bed_N` blocks in the entry file. Rejected: one sprinkler per bed (beds could run in parallel, new HA main
   switches), generating the list (no loops in ESPHome YAML), keeping valves in `irrigation.yaml` (misses the goal).
7. **Bed vars** (all required, literal strings, no defaults): `bed` (e.g. `"1"`), `bed_name`, `relay` (board relay
   number, e.g. `"1"`). Entity names: `"${bed_name}"`, `"${bed_name} enable"`, `"${bed_name} run duration"`. Run
   duration limits and initial value stay literal in `bed.yaml`, identical to today.
8. **`hardware/sim.yaml`:** `host:` with an obviously dummy, locally administered `mac_address`
   (e.g. `"02:00:00:00:00:01"`); no `*_pin` keys; `board_relay_1..3` as `platform: template`, `optimistic: true`,
   `internal: true`, `restore_mode: ALWAYS_OFF`. Its header says exactly which packages it supports and why.
9. **Matrix rows stay inside the `checks` job.** No new CI job; the required check names `checks`,
   `compile (pinned)`, `compile (minimum)` and `tests/test_ci.py` stay unchanged.

**Gates.** If the spike (step 0 under Checks) shows that `!extend` on `gh_sprinkler` from bed packages fails on either
version, stop, set Status `blocked` and report; do not invent another structure. If only the `adc_pin: ${adc_1_pin}`
var reference fails on either version, finish everything else, leave `bed_soil.yaml` out, and report it under
Follow-ups with the exact error, so the author can choose another pattern.

### Target entry file (shape, not literal text)
```yaml
packages:
  hardware: !include hardware/esp32-s3-devkitc1-breadboard.yaml   # or hardware/sim.yaml (see its header)
  core_network: ...
  core_time: ...
  display_touch: ...  lvgl_base: ...  lvgl_page_*: ...
  # Greenhouse irrigation: the controller, then one block per bed (at least 2 with the stock sprinkler).
  # The order of the bed blocks is the valve order; the greenhouse page expects exactly beds 1-3 until stage 8.
  gh_irrigation: !include packages/greenhouse/irrigation.yaml
  gh_bed_1: !include
    file: packages/greenhouse/bed.yaml
    vars: {bed: "1", bed_name: "Greenhouse bed 1", relay: "1"}
  # Optional soil sensor for bed 1 (only reports). An ADC pin serves one probe: not together with gh_sensors_soil
  # on the same pin.
  # gh_bed_1_soil: !include
  #   file: packages/greenhouse/bed_soil.yaml
  #   vars: {bed: "1", bed_name: "Greenhouse bed 1", adc_pin: "${adc_1_pin}", cal_dry_v: "3.16", cal_wet_v: "0.80"}
  gh_bed_2: ...   # relay "2"
  gh_bed_3: ...   # relay "3"
  gh_lvgl_page: ...  gh_sensors_air: ...  gh_sensors_soil: ...  gh_sprinkler_lvgl: ...
  touch_dot_test: ...
```
Block or flow style for `vars` is the implementer's choice, as long as yamllint is clean and the matrix builder can
drop and uncomment whole blocks. Commented example blocks use the exact form `  # <key>: !include` followed by lines
starting with `  #   `, so the builder can uncomment them reliably.

### Proving "no behaviour change"
1. **Normalized `esphome config` diff (required)**, same procedure and scratch helper as task 004 (master via
   `git archive` into the scratch dir vs. branch; helper not committed). Expected differences, and nothing else:
   - `switch:` the three gpio switches are now `board_relay_1..3` instead of `gh_valve_zone1..3_sw` (same pins,
     `internal`, `restore_mode`, `mode`);
   - `sprinkler[gh_sprinkler].valves[*].valve_switch_id`: `board_relay_N` instead of `gh_valve_zoneN_sw`;
   - possibly auto-generated ids of the sprinkler's internal switches/numbers if the generator numbering shifts.
   Valve order, entity names, `gh_bedN_run_duration` ids, `restore_value`, limits, icons, the greenhouse-wide soil
   sensor (same pin `GPIO6`) and every other section must be identical. No `gh_bedN_soil_moisture` sensor appears.
   Paste the helper and its output into Implementation notes and justify each difference.
2. **Entity identity:** HA object ids and number/switch preference keys derive from entity names, which do not
   change, so HA entities and saved run durations survive. The raw relay switches are internal and nameless; if
   their restore slot changes, `RESTORE_DEFAULT_OFF` falls back to OFF, which is the safe state. State this in
   Implementation notes.
3. Optional, stronger: `esphome compile --only-generate` on both trees, diff `main.cpp`; expect only the renamed ids
   and reordering.

## Files
- create: `packages/greenhouse/bed.yaml` — header comment (what it adds, required vars, "at least 2 beds with the
  stock sprinkler", order = valve number, requires `gh_irrigation` before it and `board_relay_<relay>` in the board
  profile, optional soil sensor via `bed_soil.yaml`); one `sprinkler: - id: !extend gh_sprinkler, valves: [one
  valve]` exactly as today's valve N, parameterised by `${bed}`, `${bed_name}`, `${relay}`. No `!secret`, no GPIO, no
  LVGL, no `substitutions:`/`defaults:`.
- create: `packages/greenhouse/bed_soil.yaml` — Decision 4; header comment with wiring/calibration notes (short
  version of the `sensors_soil.yaml` header, incl. "ADC1 pins only with Wi-Fi", "one probe per ADC pin", "reports
  only; skip-when-wet is stage 6"). No `!secret`, no GPIO, no LVGL, no `substitutions:`/`defaults:`.
- modify: `packages/greenhouse/irrigation.yaml` — remove the three gpio switches and the `valves:` items; keep the
  `gh_sprinkler` entry unchanged; update the header comment (valves come from `bed.yaml`, raw relays from the board
  profile; keep the existing warnings about `on_value`/LVGL).
- modify: `packages/greenhouse/sensors_soil.yaml` — `${soil_ao_pin}` → `${adc_1_pin}`; header comment. Nothing else.
- modify: `hardware/esp32-s3-devkitc1-breadboard.yaml` — add `switch:` with `board_relay_1..3` (Decision 1); rename
  `soil_ao_pin` → `adc_1_pin` (Decision 4); update the header ("raw relay drivers live here too; every board defines
  the same `board_relay_N` ids; analog inputs are `adc_N_pin`, ADC1 only").
- create: `hardware/sim.yaml` — Decision 8.
- modify: `garden-pilot.yaml` — `gh_bed_1..3` include blocks after `gh_irrigation`, a commented-out `gh_bed_1_soil`
  example (target shape above), comments.
- modify: `tests/test_layout.py` — new and adjusted checks (table below).
- modify: `tests/test_config_matrix.py` — block-aware builder (drop and uncomment), hardware override, new rows.
- modify: `docs/SPEC.md` — §4 (soil moisture per bed exists as a reporting sensor; skip-when-wet stays stage 6), §5
  (bed package exists; valves join via `!extend`; optional `bed_soil.yaml`; board profile holds raw relays and
  `adc_N_pin`; sim board config-only; at least 2 beds with stock sprinkler), §6 (anything different on 2026.6.3),
  §7 items 1 and 4 (new matrix rows; sim is config-only until stage 11), §9 item 4 (both parts done; follow-ups).
- modify: `CLAUDE.md` — layout table (`hardware/` row: board profiles incl. raw relay drivers, `sim.yaml`;
  `packages/greenhouse/bed.yaml`, `bed_soil.yaml`), `packages:` order section (`gh_irrigation` → `gh_bed_N`
  (+ optional `gh_bed_N_soil`) in valve order → page), a convention line "add a bed = one `!include` block with
  `vars`; features reference relays as `board_relay_N` and analog inputs as `${adc_N_pin}`"; the legacy note about
  greenhouse pins if it still names `soil_ao_pin`.
- modify: `README.md`, `README.ru.md` — layout bullet (line ~95: `hardware/` also holds relay drivers and `sim.yaml`;
  greenhouse: beds, optional bed soil sensor) and one sentence "at least 2 beds until the own irrigation engine
  (roadmap stage 6)"; keep both languages in sync.
- modify: `tasks/004-modular-layout.md` — housekeeping: tick the "Hardware (author, not CI)" acceptance item and add
  "Verified by the author on 2026-10-02: OTA flash, screen and clock, touch and navigation, bed relays, sensors, HA
  entities."; tick the CI item too (PR #7 was merged with the required checks green) and set `Status: done`.

15 paths. That is just over the ~14 budget, but 6 of them are docs/housekeeping edits of a few lines each; the real
work is 2 new packages, 1 new board file, 3 YAML edits, the entry file and 2 test files. No split proposed; if the
author prefers a split, the cut is "bed_soil.yaml + `adc_1_pin` rename + its checks and matrix row" as task 006.

## Checks to write first
**Step 0 — spike (not committed), in the scratch dir, pinned and minimum** (`GP_ESPHOME=minimum`, see
`script/_esphome`):
- a: `host:` + two template switches + `sprinkler: - id: s, main_switch: …, auto_advance_switch: …` in one package,
  and two packages `!include {file: bed.yaml, vars: {…}}` each adding `sprinkler: - id: !extend s, valves: [one
  valve]`. Confirm: validates; the rendered `valves` has 2 items in package order; each has its own var values (no
  leaking between the two includes).
- b: an `esp32` config with a global substitution `adc_1_pin: GPIO6` and a package
  `!include {file: bed_soil.yaml, vars: {adc_pin: "${adc_1_pin}", …}}`. Confirm the rendered ADC pin is `GPIO6`.
Record commands and results in Implementation notes. Gates: see Decisions.

| Level | Test | Asserts |
|---|---|---|
| unit | `tests/test_layout.py::test_hardware_profiles_shape` (modified) | Top-level keys ⊆ `{substitutions, esp32, psram, host, switch}`; exactly one of `esp32` (with `board`) / `host` present. |
| unit | `tests/test_layout.py::test_hardware_profiles_define_every_pin_used` (modified) | For every profile with `esp32:`: pins referenced under `packages/` **and in `garden-pilot.yaml` (including commented example blocks)** ⊆ its `*_pin` keys, and every `*_pin` key is referenced under `packages/`, in the entry file or inside the profile itself. `sim.yaml` (has `host:`) is skipped. |
| unit | `tests/test_layout.py::test_hardware_board_settings_are_used` (modified) | Non-pin substitutions are referenced under `packages/` (unchanged rule); applies to profiles that have substitutions. |
| unit | `tests/test_layout.py::test_analog_pins_named_by_function` | No profile defines `soil_ao_pin`; analog input pin keys match `adc_\d+_pin`; no `${soil_ao_pin}` reference remains. |
| unit | `tests/test_layout.py::test_sim_profile_has_no_hardware` | `hardware/sim.yaml` exists, has `host:`, no `esp32:`, no `GPIO\d+`, no `*_pin` keys; every switch in it is `platform: template`, `internal: true`, `restore_mode: ALWAYS_OFF`. |
| unit | `tests/test_layout.py::test_board_relays_are_safe` | Every `switch` under `hardware/` (any platform) is `internal: true` with `restore_mode` in `{RESTORE_DEFAULT_OFF, ALWAYS_OFF}` and an id matching `board_relay_\d+`. All profiles define the **same set** of `board_relay_N` ids. |
| unit | `tests/test_layout.py::test_gpio_actuators_are_safe` (kept) | Still finds the gpio switches (now in the breadboard profile) and checks them. |
| unit | `tests/test_layout.py::test_no_gpio_switch_in_packages` | No `switch` with `platform: gpio` remains under `packages/`. |
| unit | `tests/test_layout.py::test_bed_includes` | Every entry-file package that includes `packages/greenhouse/bed.yaml` uses `file:`/`vars:` and supplies exactly `bed`, `bed_name`, `relay` (= the `${…}` names used in `bed.yaml`); `bed` values unique; `board_relay_<relay>` exists in every profile; at least 2 bed includes; they come after `gh_irrigation` and before `gh_lvgl_page`, with `bed` values `1, 2, 3` in order (the page's `valve_number: 0/1/2`). |
| unit | `tests/test_layout.py::test_bed_soil_includes` | Every `bed_soil.yaml` include in the entry file, **active or commented-out example** (parse examples by stripping the `# ` prefix), supplies exactly `bed`, `bed_name`, `adc_pin`, `cal_dry_v`, `cal_wet_v` (= the `${…}` names used in `bed_soil.yaml`); `adc_pin` is of the form `${adc_<n>_pin}` and that key exists in every `esp32` profile; `bed` and `bed_name` equal those of an existing bed include and the block comes after that bed's block; no two active bed soil includes share an `adc_pin`; at least one example block exists. |
| unit | `tests/test_layout.py::test_bed_soil_shape` | `bed_soil.yaml` has only the top-level key `sensor`; exactly one item, `platform: adc`, `pin: ${adc_pin}`, id containing `${bed}`, name `"${bed_name} soil moisture"`, `device_class: moisture`, `unit_of_measurement: "%"`; filters contain `calibrate_linear` with `${cal_dry_v}`/`${cal_wet_v}` and a `clamp` 0–100; no `on_value`; the text contains no `lvgl`, no `GPIO\d+`, no `!secret`, no `substitutions:`/`defaults:`. |
| unit | `tests/test_layout.py::test_bed_vars_do_not_shadow_globals` | Var names used by `bed.yaml` / `bed_soil.yaml` are not defined as substitutions in the entry file, any hardware profile or any `substitutions:` block under `packages/`. |
| unit | `tests/test_layout.py::test_substitutions_resolve` (modified) | Names used in `bed.yaml` / `bed_soil.yaml` count as defined when supplied by their `vars:` in the entry file (active or example blocks); everything else unchanged. |
| unit | `tests/test_config_matrix.py::test_builder_blocks` | `build_variant` on a small inline sample: dropping a multi-line `!include` block removes all its continuation lines; keeping it keeps them; enabling a commented example block uncomments exactly its lines (valid YAML afterwards); the hardware override rewrites only the `hardware:` include path. Marked `unit`. |
| config | `tests/test_config_matrix.py::test_variant_validates[full]` (kept) | Entry file unchanged (3 beds, breadboard, display, no bed soil sensor). |
| config | `…[headless]`, `…[no_touch_debug]` (kept) | As in task 004. |
| config | `…[beds_2_headless]` | Breadboard + core + `gh_irrigation` + `gh_bed_1` + `gh_bed_2` validates. |
| config | `…[bed_soil_headless]` | Breadboard + core + `gh_irrigation` + `gh_bed_1` + **uncommented `gh_bed_1_soil`** + `gh_bed_2` + `gh_bed_3` validates (no `gh_sensors_soil`, so `adc_1_pin` is used once). |
| config | `…[sim_beds_3]` | `hardware` overridden to `hardware/sim.yaml`; keep only `hardware`, `gh_irrigation`, `gh_bed_1..3`. |
| config | `…[sim_beds_2]` | Same with 2 beds. |

Variants table: extend the existing data table with an optional hardware override (e.g. `hardware="hardware/sim.yaml"`)
and an optional list of commented example keys to enable. The test still asserts the variant's package keys match the
request.

## Acceptance criteria
- [x] Spike a and b from step 0 recorded in Implementation notes, passing on 2026.9.1 and 2026.6.3 (or the soil gate
      applied and reported).
- [x] `uv run pytest -m unit` → all pass, including the new/modified `test_layout.py` tests and the builder test.
- [x] `script/lint` → yamllint strict clean, `esphome config OK: garden-pilot.yaml`.
- [x] `script/test` → all pass; `test_config_matrix.py` runs 7 config variants (`full`, `headless`, `no_touch_debug`,
      `beds_2_headless`, `bed_soil_headless`, `sim_beds_3`, `sim_beds_2`).
- [x] `GP_ESPHOME=minimum GP_SECRETS=example sh script/config` → `esphome config OK`.
- [x] The `bed_soil_headless` variant also validates with the minimum version (run once by hand; command and result
      in Implementation notes).
- [x] `git grep -nE 'platform: *gpio' -- packages` → only the greenhouse soil DO `binary_sensor`
      remains (the DHT uses `platform: dht`); no gpio `switch`.
- [x] `git grep -nE 'GPIO[0-9]+' -- '*.yaml' ':!hardware/'` → only comment lines, or nothing.
- [x] `git grep -n 'soil_ao_pin'` → no output outside `tasks/`.
- [x] `git grep -n '!secret' -- packages hardware` → no output.
- [x] Normalized `esphome config` diff master vs branch → only the differences listed under "Proving no behaviour
      change", each justified in Implementation notes; helper and output pasted.
- [ ] `tests/test_ci.py`, `.github/workflows/ci.yml`, `.github/rulesets/master.json` unchanged; CI on the PR green
      for `checks`, `compile (pinned)`, `compile (minimum)`.
- [x] `docs/SPEC.md`, `CLAUDE.md`, `README.md`, `README.ru.md` updated as listed (READMEs in sync, both state the
      2-bed minimum); `tasks/004-modular-layout.md` ticked and `done`.
- [ ] **Hardware (author, not CI):** flash the branch firmware (`uv run esphome run garden-pilot.yaml`, OTA is fine) and
      repeat the task 004 checklist:
  - boots to Home; clock appears after HA time sync and keeps updating;
  - touch and nav reach Greenhouse, Lawn, Touch test and back; touch dot overlay works;
  - Greenhouse page: RUN bed 1/2/3 clicks the matching relay; STOP closes it; QUEUE + start runs the queue in order;
  - air T/RH and soil % (greenhouse-wide probe) update on Home and Greenhouse;
  - in HA: same entity names and ids ("Greenhouse bed N", "… enable", "… run duration", "Greenhouse irrigation",
    "Greenhouse auto advance", "Greenhouse soil moisture"), no new entities, no duplicates, nothing "unavailable";
  - bed run durations and enable switches keep their values after the update;
  - after a power cycle all valves are OFF.

  The per-bed soil sensor is not tested on the device (not enabled there). The implementer states in Implementation
  notes that none of this was verified on a device.

## Out of scope
- `garden_zones` (stage 6) and `gp_*` (stage 7): no engine change, no max on-time guard (known gap, stage 6
  watchdog), no skip-when-wet logic using the bed soil sensor. The greenhouse page keeps calling `sprinkler.*`.
- A 1-bed greenhouse (Decision 2; comes with `garden_zones`).
- Greenhouse page layouts for other bed counts and showing per-bed soil values on screen (SPEC §10 screens
  question 2, stage 8). Follow-up: the page, its status poller (`sprinkler_lvgl_status.yaml`) and the fixed
  `valve_number: 0/1/2` hard-code three beds; a config with 2 beds and the page does not validate.
- Migrating the greenhouse-wide probe (`sensors_soil.yaml`, incl. its DO binary sensor and LVGL updates) onto
  `bed_soil.yaml`; decoupling greenhouse sensors from LVGL ids; moving DHT/ADC drivers into the board profile; sim
  template sensors.
- Assigning more ADC pins (`adc_2_pin` …) in the breadboard profile: the author's call when probes are wired.
- Splitting `packages/core/network.yaml` into API/OTA and Wi-Fi/captive-portal packages so the sim board can include
  the API (stage 11, with the host build, SDL and `aioesphomeapi` scenarios).
- LILYGO T-Relay-S3 profile; board selection by substitution in the include path; remote-package wiring (stage 5).

## Open questions
- None blocking. If the soil gate triggers (var value `${adc_1_pin}` not resolved on one version), the author picks
  another pattern in a follow-up.

<!-- Filled in by implementer -->
## Implementation notes
**Step 0 spikes (scratch dir, not committed), pinned 2026.9.1 and minimum 2026.6.3, both pass.**
- a: `host:` + template relays + `sprinkler: gh s` (main, auto advance) and two `!include {file, vars}` bed packages
  with `!extend s`: `esphome config` (`script/_esphome config a.yaml`, `GP_ESPHOME=minimum` for 2026.6.3) is valid;
  `valves` has 2 items in package order, each with its own var values (names, `bed1_run`/`bed2_run`,
  `board_relay_1/2`), no leaking.
- b: `esp32` + global `adc_1_pin: GPIO6` + include with `adc_pin: "${adc_1_pin}"`: rendered `pin: number: 6` on both
  versions. No soil gate needed.

**Decisions made / deviations.**
- Bed and soil packages, board relays, `adc_1_pin` rename, sim profile, entry-file blocks exactly as specified.
- The matrix builder is block-aware (`Variant` dataclass: mode, keys, hardware, enable); example blocks are
  recognised by `  # key: !include` + `  #   ` lines. `test_builder_blocks` is marked `unit` too, so
  `pytest -m unit` runs it. Added `test_bed_shape` (not in the table) next to `test_bed_soil_shape`.
- `test_hardware_profiles_define_every_pin_used` skips `bed.yaml`/`bed_soil.yaml` when collecting `${..._pin}`
  (their `${adc_pin}` is a var); pins used only inside the profile (`relay_N_pin`) count as used.
- The `soil_ao_pin` name is built from two string literals in `test_layout.py` so that
  `git grep -n soil_ao_pin` has no hit outside `tasks/`.
- The `gh_bed_1_soil` example is a commented block; the device config is unchanged.

**Results.** `script/lint` ok; `script/test` 251 passed (7 config variants + builder test); `uv run pytest -m unit`
243 passed; `GP_ESPHOME=minimum GP_SECRETS=example sh script/config` OK; the whole matrix on the minimum version
(`GP_ESPHOME=minimum uv run pytest tests/test_config_matrix.py`, includes `bed_soil_headless`) 8 passed.
Greps from the acceptance list: only the soil DO `binary_sensor` has `platform: gpio` under `packages`; no GPIO
literal outside `hardware/`; no `soil_ao_pin` outside `tasks/`; no `!secret` in `packages`/`hardware`.

**Normalized `esphome config` diff, master vs branch** (master = clean tree of `master`, copied before editing; both
rendered with `script/_esphome config` using `secrets.example.yaml`; helper drops `INFO`/`WARNING` lines and the
`substitutions:` block, then `diff`). Helper:
```python
import sys
t=[l for l in open(sys.argv[1]).read().splitlines() if not l.startswith(('INFO','WARNING')) and 'scratchpad' not in l]
out=[];skip=False
for l in t:
    if l=='substitutions:': skip=True; continue
    if skip and l.startswith(' '): continue
    skip=False; out.append(l)
print("\n".join(out))
```
Differences (and nothing else):
1. `switch:` block moved from after `sprinkler` to after the hardware keys (key order of the merged config; the
   board profile is the first package) and the three gpio switches are `board_relay_1..3` instead of
   `gh_valve_zone1..3_sw` (pins 21/47/48, `internal`, `RESTORE_DEFAULT_OFF`, output mode identical). Expected,
   Decision 1.
2. `sprinkler[gh_sprinkler].valves[*].valve_switch_id`: `board_relay_N` instead of `gh_valve_zoneN_sw`. Expected.
3. `lvgl.touchscreens[0]`: `long_press_time` / `long_press_repeat_time` swapped. This is run-to-run noise: master
   rendered three times in a row gave both orders. Not related to this change.
Valve order, names, `gh_bedN_run_duration` ids and options, the greenhouse-wide soil sensor (pin 6) and all other
sections are identical; no `gh_bedN_soil_moisture` appears. No generated ids shifted.

**Entity identity.** HA object ids and number/switch preference keys derive from entity names, which did not change,
so entities and saved run durations survive. The raw relays are internal and nameless; if their restore slot
changed, `RESTORE_DEFAULT_OFF` falls back to OFF, the safe state.

**Not verified.** Nothing was flashed or run on a device (relay clicks, queue, HA entities, run durations after OTA,
power-cycle OFF state, nothing "unavailable"): the hardware item stays open for the author. The bed soil sensor was
validated by `esphome config` only. `esphome compile --only-generate` main.cpp diff (optional) was not done. CI on
the PR and the unchanged-files item (`tests/test_ci.py`, workflow, ruleset: not touched here) are for the PR.
## Follow-ups
- The greenhouse page, its status poller and the fixed `valve_number: 0/1/2` still hard-code three beds; a 2-bed
  config with the page does not validate (stage 8). Bed soil values are not shown on screen.
- Sim board cannot include the API until `core/network.yaml` is split (stage 11).
