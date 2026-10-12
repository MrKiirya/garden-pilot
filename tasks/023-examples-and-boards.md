# 023 — Example configs in `examples/`, 12-relay breadboard profile, LilyGO T-Relay-S3 profile

Status: implemented (awaiting review)
Roadmap: new stage "Examples and remote packages" (added to SPEC §9 by this task); supports stage 5 (end-user path)
Spec sections: SPEC §2.2 (target hardware), §4.2 (loading our own component), §5 (modularity), §6 (compatibility), §7 (testing), §9 (roadmap)
Hardware check: the author's ESP32-S3 DevKitC-1 breadboard with the ILI9341/XPT2046 display board and the 12-LED indicator board (no real relays); see "Hardware verification". The LilyGO T-Relay-S3 profile is config-checked only. Its display-connector pins and relay bit map are "verify on the board".

Branch: `task/023-examples-and-boards`, stacked on `task/022-ci-speed` (rebase onto `master` after 022 merges).

## Goal
Users get four complete, ready-to-copy device configs in `examples/`. Each is an entry file like `garden-pilot.yaml`:
the same ILI9341 display and XPT2046 touch, LVGL pages and greenhouse page, using the shared `packages/`, `hardware/`
and `components/` through relative paths, with secrets passed in the same substitution pattern. The examples are:

1. `examples/minimal-1-bed.yaml`
2. `examples/beds-with-pump.yaml` (3 beds one at a time + a pump)
3. `examples/soil-sensors.yaml` (per-bed probes with the task 013 soil skip)
4. `examples/relay-module-8ch.yaml` (a generic 8-channel relay module wired to the breadboard)

CI validates every example with `esphome config` (no new compile or host build). The breadboard profile grows to 12
relay outputs on safe ESP32-S3 pins, with a wiring table. A new `hardware/lilygo-t-relay-s3.yaml` drives the LilyGO
T-Relay-S3 (6 relays) and its 6-relay expansion through the 74HC595 shift registers, plus the same display board on
its soldered header. The roadmap gets a "remote packages + private config repo" stage and a "lawn one zone at a time,
flowers in parallel, shared pump" item.
The lawn/flowers package and the author's own `examples/my-garden.yaml` are **task 024**, outlined under "Out of scope".

## Context

### Why `examples/` needs path changes (checked in the ESPHome source, tag 2026.9.1)
- `!include` resolves relative to the **including file** (`yaml_util.py`, `IncludeFile.load`:
  `self.parent_file.parent / self.file`). `examples/x.yaml` therefore writes `!include ../packages/...` and
  `hardware: !include ../hardware/<board>.yaml`.
- `external_components` with a local source resolves through `CORE.relative_config_path(path)`
  (`components/external_components/__init__.py`), and that joins onto `CORE.config_dir`, which is the **directory of the
  main config file** (`core/__init__.py`). The literal `source: components` in `packages/greenhouse/irrigation.yaml`,
  `packages/greenhouse/schedule.yaml` and `packages/core/gp.yaml` would look for `examples/components/` and fail. The
  vendored font `file: packages/lvgl/fonts/Montserrat-Bold.ttf` in `packages/lvgl/screensaver.yaml` has the same problem
  (the implementer confirms the font path resolution in `esphome/components/font/__init__.py` at 2026.9.1 and notes it).
- `!secret` looks for `secrets.yaml` in the directory of the file that contains the tag, and does not fall back when
  that file is the main config (`yaml_util.py`). An example therefore reads `examples/secrets.yaml`, which
  `.gitignore` already ignores (the `secrets.yaml` pattern matches at any depth; `.esphome/` too).
- `esphome/config.py` runs packages, then substitutions, then external components, so a substitution can be used in
  `external_components` `source`. The implementer verifies this with the config rows.
- `script/config` and `script/compile` stage only the basename of the config, so they cannot handle `examples/*.yaml`
  today.

### Display examples and bed counts
- The greenhouse page, valve test and screensaver expect beds 1-3 until stage 9 (CLAUDE.md, `bed.yaml` header). The
  existing matrix has no "1 bed + LVGL" row.
- The implementer first checks whether `minimal-1-bed.yaml` with the full LVGL set (greenhouse page, valve test,
  screensaver) passes `esphome config`. If it fails, the minimal example leaves out exactly the packages that need
  beds 2-3 and says so in its header and in the implementation notes. Absent zones are allowed to show as empty
  (`ZoneView` `ABSENT`).
- The 8-channel example has 8 beds, and the page and valve test show beds 1-3 only. Its header says so and points to
  stage 9.
- Examples leave out `touch_dot_test` and `lvgl_page_touch_test` (debug only). They keep `lvgl_network_wifi` and
  `lvgl_boot_wifi`.

### Pump in the greenhouse group (example 2)
- `packages/greenhouse/irrigation.yaml` declares group `gh_zones` without a pump. A second package cannot add
  `pump_switch_id` to that group item, because `garden_zones: groups:` items are not merged by id. Any merge
  assumption is unverified, so it is not relied on.
- Group options and limits come from `components/garden_zones/README.md`: `pump_switch_id`, `pump_max_on_time`
  (default 2h, must be >= every zone limit), `pump_idle_timeout` (default 10s, must be >= max(start-valve, stop-pump
  delay) + 2 s), and the pump switch must resolve to `ALWAYS_OFF` / `RESTORE_DEFAULT_OFF`.

### LilyGO T-Relay-S3 (researched; *verify on the board* = not certain)
- Module ESP32-S3-WROOM-1U, 16 MB flash, 8 MB octal PSRAM (N16R8), USB-C, BOOT/RST. No built-in display, but "2 x 10-pin
  expansion seats for optional LCD" (2.4" TFT). The author's ILI9341/XPT2046 board plugs into a female header soldered
  there. Those connector pins are **not in the text docs** (LilyGO wiki), so every display/touch pin in the profile is
  *verify on the board*. The implementer checks the schematic in Xinyuan-LilyGO/LilyGo-T-Relay (`schematic/` folder)
  for the LCD header and cites it. If it is not found, the values are placeholders and the header says "do not flash
  until verified".
- 6 relays (10 A) driven by an SN74HC595: DATA GPIO7, CLOCK GPIO5, LATCH GPIO6, nOE GPIO4. CH1..CH6 = SR1..SR6, CH7 =
  green LED, CH8 = red LED. RTC on I2C SDA GPIO16 / SCL GPIO17 / IRQ GPIO18 (the Tasmota template uses address 0x51:
  *verify the chip*). There is a reserved DS18B20 interface with no pin given. The W5500 variant uses SPI 9/11/13, CS
  3, RST 8, INT 12. Source: `docs/RELAY_ESP32S3.MD` in that repo.
- Expansion boards chain further 74HC595s (Tasmota `Shift595DeviceCount` = main + expansions). The author's
  expansion has 6 relays on a ribbon cable.
- Newer revisions hold nOE high, so relays do nothing until GPIO4 is driven low (LilyGo-T-Relay issue #21).
- ESPHome `sn74hc595` (esphome.io/components/sn74hc595; `sn74hc595.cpp` at 2026.9.1): the GPIO variant takes
  `data_pin`, `clock_pin`, `latch_pin`, `oe_pin`, `sr_count`. Output pins are `{sn74hc595: <id>, number: N}`. Pin `N` =
  bit `N % 8` of register `N / 8`, and register 0 is the one nearest the MCU. `setup()` drives OE high, shifts and
  latches the state, then drives OE low. Before setup (power-on, reset, OTA reboot) the outputs depend on the board's
  OE pull-up: *verify that no relay clicks at power-on*. The implementer confirms the component on the minimum
  supported 2026.6.3 once and notes it.
- Assumed bit map (*verify on the board*): main CH1..CH6 = `number` 0..5 (LEDs 6/7, unused), expansion relays 1..6 =
  `number` 8..13. If the board counts SR outputs from Q1, shift by one. The profile header names the one place to
  change.
- Display/touch pins must not collide with 4-7 (shift register), 16-18 (RTC) or 0/3/19/20/26-37/43-46.

### ESP32-S3 DevKitC-1 N16R8 pins (breadboard profile)
- Avoid: 26-32 (flash), 33-37 (octal PSRAM), 19/20 (USB), 43/44 (UART0), 0/3/45/46 (strapping).
- Already used: 4 (DHT11), 6 (adc_1), 7 (soil DO), 8/9/10 (SPI), 11/12/13 (display), 15/18 (touch), 21/47/48 (relays
  1-3).
- Relays 4-12 (author keeps the proposal, **to verify by the author** against his board): 4 = GPIO14, 5 = GPIO16, 6 =
  GPIO17, 7 = GPIO38, 8 = GPIO39, 9 = GPIO40, 10 = GPIO41, 11 = GPIO42, 12 = GPIO5. `adc_2_pin` = GPIO1, `adc_3_pin` =
  GPIO2 (ADC1) for per-bed probes. GPIO38 is the RGB LED line on DevKitC-1 v1.1 (GPIO48, relay 3, on v1.0).
  GPIO39-42 are the pin JTAG (unused; the S3 debugs over USB-JTAG). The profile header marks the table "to verify by
  the author".

### Author's answers (2026-10-12)
- All examples have the display + touch; there are no headless examples. 023 = boards + examples 1-4 + roadmap; 024 =
  lawn/flowers package + `examples/my-garden.yaml`.
- For now lawn + flowers are **one group with the pump, one zone at a time** (`max_parallel: 1`). "Lawn one zone at a
  time, flowers in parallel, shared pump" goes on the roadmap. Why it needs work: today "a pump belongs to one group",
  so it needs either lanes with different parallelism (pinned lanes, at the cost of lawn and flowers overlapping) or a
  fork patch for a pump shared across groups.
- Breadboard pins 4-12: keep the proposal; the author verifies them later.
- LilyGO: the profile has display + touch on the soldered header (pins to verify), and sn74hc595 relays 6 + 6.
- The private override file is deferred to the remote-packages stage.

### Decisions made by the planner (author to confirm)
1. **Path substitution `gp_root`** (default `"."`, in every package with a repo-relative path: `irrigation.yaml`,
   `irrigation_pump.yaml`, `schedule.yaml`, `core/gp.yaml`, `lvgl/screensaver.yaml`). Examples set `gp_root: ".."`. This
   is also the first step of the remote-packages stage.
2. **Pump variant of the greenhouse group:** new `packages/greenhouse/irrigation_pump.yaml`, used **instead of**
   `irrigation.yaml` under the same package key `gh_irrigation` (so the package order and every `gh_zones` reference
   stay valid). It is the same group plus `pump_switch_id: board_relay_${gh_pump_relay}`, `pump_max_on_time:
   ${gh_pump_max_on_time}` (default `2h`, the component default) and `pump_idle_timeout: ${gh_pump_idle_timeout}`
   (default `10s`). Example 2 uses relays 1-3 for the beds and relay 4 for the pump, `gh_max_parallel: "1"`, and the
   component defaults for the limits. Those defaults are documented and changing them is the user's call. Duplication
   with `irrigation.yaml` is accepted; a test keeps the two files equal apart from the pump keys.
3. **Per-entry pin check** replaces "every profile defines every pin any package uses". Each entry file
   (`garden-pilot.yaml`, `examples/*.yaml`) must get every `${*_pin}` used by **its** packages and vars from **its**
   profile. A profile may define only pins that some package, entry file or the profile itself uses. Every
   `board_relay_N` an entry references must exist in its profile. Relay ids no longer have to be equal across
   profiles: each profile has contiguous `board_relay_1..N`, N >= 3. `hardware/sim.yaml` keeps 3 relays.
4. **LilyGO touch calibration and orientation** start as copies of the breadboard values (same display board), marked
   "verify". `sr_count: 2` always: `board_relay_1..12` (1-6 main, 7-12 expansion); without the expansion, relays 7-12
   do nothing. The status LEDs and RTC are not defined (RTC = stage 10).
5. **Active-low relay modules are not supported** (no `inverted:`): they energise while the ESP32 resets. The profile
   header, `examples/README.md` and example 4 say to use a high-level-trigger module or set its jumper to H.
6. **Soil skip needs a bed variant:** a second package cannot add `soil_moisture:` to an existing `garden_zone:` list
   item. New `packages/greenhouse/bed_soil_skip.yaml` = `bed.yaml` + `soil_moisture: {sensor_id:
   gh_bed${bed}_soil_moisture, skip_above: ${skip_above}, max_age: 30min, when_unavailable: water}`. It is used
   instead of `bed.yaml`, together with that bed's `bed_soil.yaml`. Vars: `bed`, `bed_name`, `relay`, `skip_above`.
7. **Device names:** `gp-minimal`, `gp-beds-pump`, `gp-soil-sensors`, `gp-relay-8ch`.
8. **CI cost:** examples run `esphome config` at the **pinned** version only: 4 rows + 1 LilyGO row (example 1 with
   the LilyGO profile swapped in). LVGL configs take about 30-40 s each under xdist, inside the 15-min `checks` budget.
   Record the measured time.
9. **Roadmap:** new SPEC §9 stage 13 "Examples and remote packages". Its items are 023 (this), 024 (lawn/flowers
   package + `my-garden.yaml`), and "remote packages + private config repo": packages usable as ESPHome remote packages
   (`external_components` git source pinned to a tag, font path, includes with `vars`), a CI check of a remote-mode
   example, version tags `vX.Y.Z`, and a git-ignored private override file; the author then moves his config to a
   private repo. Add to §9.1 backlog: "Lawn one zone at a time, flowers in parallel, one shared pump" (lanes with
   different parallelism in one group, or a pump shared across groups via a fork patch).

## Files
- create: `examples/README.md` — the four examples, how to use one (`cp secrets.example.yaml examples/secrets.yaml`,
  `uv run esphome run examples/<file>.yaml`), the `gp_root: ".."` rule, the active-low warning, and how to switch an
  example to `hardware/lilygo-t-relay-s3.yaml` (change the `hardware:` include; relay numbers stay 1..12).
- create: `examples/minimal-1-bed.yaml` — 1 bed on relay 1, full device stack (core, display_touch, LVGL, gp), see
  "Display examples and bed counts".
- create: `examples/beds-with-pump.yaml` — 3 beds on relays 1-3 one at a time, `gh_irrigation:
  !include ../packages/greenhouse/irrigation_pump.yaml`, `gh_pump_relay: "4"`, full stack, schedule hub + 1 slot.
- create: `examples/soil-sensors.yaml` — 3 beds via `bed_soil_skip.yaml` + `bed_soil.yaml` on
  `${adc_1_pin}`..`${adc_3_pin}` (example calibration as in `garden-pilot.yaml`), `skip_above: "60"`, full stack
  (without `gh_sensors_soil`, which would share `adc_1`), schedule hub + 1 slot.
- create: `examples/relay-module-8ch.yaml` — 8 beds on relays 1-8, `gh_max_parallel: "1"`, full stack, schedule hub +
  1 slot; header: high-level-trigger module only, the page shows beds 1-3 until stage 9.
- create: `hardware/lilygo-t-relay-s3.yaml` — `esp32:` (board `esp32-s3-devkitc1-n16r8`, esp-idf; *verify*),
  `sn74hc595:` hub `board_sr` (`${sr_data_pin}` GPIO7, `${sr_clock_pin}` GPIO5, `${sr_latch_pin}` GPIO6, `${sr_oe_pin}`
  GPIO4, `sr_count: 2`). `board_relay_1..12` as `platform: gpio` with `pin: {sn74hc595: board_sr, number: N}`,
  `internal: true`, `restore_mode: ALWAYS_OFF`. Every display/touch pin and setting the packages use, marked *verify on
  the board*. Header: sources, bit-map table, the verify list.
- create: `packages/greenhouse/irrigation_pump.yaml` — decision 2.
- create: `packages/greenhouse/bed_soil_skip.yaml` — decision 6.
- create: `tests/test_examples.py` — the checks below.
- modify: `hardware/esp32-s3-devkitc1-breadboard.yaml` — `board_relay_4..12`, `relay_4_pin`..`relay_12_pin`,
  `adc_2_pin`, `adc_3_pin`; header wiring table (relay N → GPIO → LED/relay channel, "to verify by the author") and
  the avoided-pin list; module text → "up to 12 relay outputs (LED indicator board or a high-level-trigger relay
  module)".
- modify: `packages/greenhouse/irrigation.yaml`, `packages/greenhouse/schedule.yaml`, `packages/core/gp.yaml` —
  `source: ${gp_root}/components` + `gp_root: "."` default.
- modify: `packages/lvgl/screensaver.yaml` — font `file: ${gp_root}/packages/lvgl/fonts/Montserrat-Bold.ttf`; adapt
  `tests/test_screensaver.py` if it reads the literal path.
- modify: `tests/test_layout.py` — decision 3; allow `sn74hc595` in `test_hardware_profiles_shape`;
  `test_hardware_board_settings_are_used` accepts keys used inside the profile; `test_gpio_actuators_are_safe` covers the
  LilyGO switches.
- modify: `script/config`, `script/compile` — configs in a subdirectory. With example secrets: stage the repo folders
  + the config at its relative path, with `secrets.example.yaml` next to it. With real secrets: `<dir>/secrets.yaml` if
  present, else stage (compile: under the git-ignored `.esphome/`) with the root `secrets.yaml` next to the config.
  Never write a `secrets.yaml` into the checkout.
- modify: `CLAUDE.md` — layout rows (`examples/`, the LilyGO profile, `irrigation_pump.yaml`, `bed_soil_skip.yaml`);
  conventions: `gp_root`, `../` includes in examples, the per-entry pin rule (replaces "every board profile defines
  the same board_relay_N ids"), the active-low warning; command `script/config examples/<file>.yaml`.
- modify: `README.md` + `README.ru.md` (in sync) — "Examples" section and the two boards.
- modify: `docs/SPEC.md` — §2.2 (LilyGO facts, 12-relay breadboard), §4.2 (`gp_root`), §5 (examples, per-entry pins,
  pump variant, bed_soil_skip), §7 (example rows), §9 (decision 9) and §9.1.

That is about 22 files, many of them short docs or copies of the entry file. If the implementer runs short, the
LilyGO profile (its file, the row and the SPEC §2.2 text) can be split off as a follow-up; the implementation notes
must then say so.

## Checks to write first
| Level | Test | Asserts |
|---|---|---|
| unit | `tests/test_examples.py::test_examples_exist` | the four example files + `README.md` exist; each is an entry file (`esphome:` with a unique `name`, `packages:`, `logger` INFO or stricter) and includes `display_touch`, `lvgl_base` and `gh_lvgl_page` (or the minimal example's documented subset) |
| unit | `tests/test_examples.py::test_example_secrets_pattern` | every `!secret` in an example sits under top-level `substitutions:` with a key from `secrets.example.yaml`; none elsewhere |
| unit | `tests/test_examples.py::test_example_paths` | every `!include` starts with `../packages/` or `../hardware/` and exists; `gp_root == ".."`; exactly one `hardware:` package |
| unit | `tests/test_examples.py::test_gp_root_default` | every package with a local `external_components` source or font `file:` uses `${gp_root}/...` and defines `gp_root: "."`; no literal `source: components` under `packages/` |
| unit | `tests/test_examples.py::test_example_package_order` | package keys follow the CLAUDE.md order (hardware, core_*, display_touch, lvgl_*, gh_irrigation, beds (+soil), core_gp, core_gp_api, gh_gp, ..., gh_schedule, slots) |
| unit | `tests/test_layout.py::test_irrigation_pump_matches` | `irrigation_pump.yaml` equals `irrigation.yaml` apart from `pump_switch_id`, `pump_max_on_time`, `pump_idle_timeout` and their substitution defaults; the pump relay of example 2 is not a bed relay |
| unit | `tests/test_layout.py::test_entry_pins_defined_by_profile` | for `garden-pilot.yaml` and each example: the `${*_pin}` of its active packages and vars ⊆ its profile's pins |
| unit | `tests/test_layout.py::test_entry_relays_exist` | every `relay` var / `gh_pump_relay` / `board_relay_N` an entry references exists in its profile |
| unit | `tests/test_layout.py::test_board_relays_are_safe` (changed) | contiguous `board_relay_1..N`, N >= 3, internal, OFF restore mode; breadboard and LilyGO N == 12; sim N == 3 |
| unit | `tests/test_layout.py::test_breadboard_relay_pins_safe` | breadboard `relay_N_pin` unique, not in {0, 3, 19, 20, 26..37, 43..46}, no collision with any other `*_pin` |
| unit | `tests/test_layout.py::test_lilygo_profile` | `sn74hc595` hub `sr_count: 2` with its four pin substitutions; 12 relays with `number` 0-5 and 8-13 each once, `ALWAYS_OFF`, no `inverted: true`; display/touch pins not in {4..7, 16..18, 0, 3, 19, 20, 26..37, 43..46} |
| unit | `tests/test_layout.py::test_bed_soil_skip_shape` | `bed_soil_skip.yaml` = `bed.yaml` + a `soil_moisture` block with `sensor_id: gh_bed${bed}_soil_moisture`; an entry that includes it also includes `bed_soil.yaml` for the same bed |
| config | `tests/test_examples.py::test_example_validates[<file>]` | `script/config examples/<file>.yaml` with `GP_SECRETS=example` exits 0 (pinned), for each of the 4 examples |
| config | `tests/test_examples.py::test_example_validates[minimal_on_lilygo]` | example 1 with `hardware:` swapped to `../hardware/lilygo-t-relay-s3.yaml` validates (staged copy) |
| config | `tests/test_examples.py::test_script_config_subdir` | `script/config examples/minimal-1-bed.yaml` passes and leaves no `examples/secrets.yaml` |

`tests/test_config_matrix.py` stays green unchanged (the `full` row covers the 12-relay breadboard and `gp_root: "."`).

## Acceptance criteria
- [x] `uv run pytest -m unit` → green, including all new unit checks.
- [x] `script/lint` → green (yamllint covers `examples/`).
- [x] `script/test` → green; the 5 new `config` rows pass; CI `checks` stays under 15 min (measured time noted).
- [x] `GP_SECRETS=example script/config examples/<file>.yaml` → `esphome config OK` for all four examples.
- [x] Example 1 with the LilyGO profile on `GP_ESPHOME=minimum` validates (run by hand, result noted).
- [x] `GP_SECRETS=example script/compile` (root entry, pinned) still builds, locally once or via CI `compile (pinned)`.
- [x] `git status` after the checks: no `examples/secrets.yaml`, no build output in the checkout.
- [x] `grep -rn "source: components" packages/` → no match outside comments.
- [x] CLAUDE.md, README.md, README.ru.md, SPEC §2.2/§4.2/§5/§7/§9/§9.1 updated; the two READMEs match section for
      section.
- [ ] **Hardware (author, not CI):** "Hardware verification" below. The result goes in the implementation notes, or
      the notes say it wasn't done.

### Hardware verification (author's breadboard + display board + 12-LED indicator board)
1. Check the relay 4-12 pins in the profile table against the board, then wire LEDs 1-12 to them. Flash
   `garden-pilot.yaml`.
2. At power-on, after RST and across an OTA reboot, **all 12 LEDs stay dark** (watch GPIO38 on a v1.1 board).
3. The HA switches "Greenhouse bed 1..3" light LEDs 1-3 only; LEDs 4-12 never light. The display and touch work.
4. `examples/beds-with-pump.yaml`: a bed run lights its LED **and** LED 4 (pump); the pump LED goes dark when the queue
   ends; no "pump_idle" watchdog trip in a normal run.
5. `examples/relay-module-8ch.yaml`: zone switches 1-8 light LEDs 1-8 one at a time; LEDs 9-12 stay dark.
6. LilyGO (optional, later): display/touch pins of the soldered header checked against the profile before the first
   flash; no relay clicks at power-on; `board_relay_1..12` map to the expected relays (fix the bit map otherwise).

## Out of scope
- **Task 024 — lawn/flowers package and `examples/my-garden.yaml`** (the author's config, display + touch, breadboard
  profile; header says how to switch to LilyGO):
  - Greenhouse: 3 beds on relays 1-3, gravity, `gh_max_parallel: all`, `gh_bed_run_max: "180"`, `gh_max_on_time:
    195min`.
  - Lawn + flowers: **one** `garden_zones` group with the pump, `max_parallel: 1`. Zones "Front lawn", "Back lawn",
    "By the beds", "Flowers 1", "Flowers 2" on relays 4-8, zone run max 45 min (zone `max_on_time` stays at the 60-min
    default, which must cover 45 min + pump delays + 2 s). Pump on relay 9, `pump_max_on_time: 3h`, `pump_idle_timeout`
    default 10 s. That is 9 outputs.
  - Modular packages: an engine-side group package with a pump (vars: group key, name, `max_parallel`, `max_on_time`,
    pump relay and limits) declaring `${group}_zones` and the gp group `gp_${group}` (main switch, status, watchdog
    sensor + reset), plus one zone include per zone adding a `garden_zone:` and a `gp_zone:` list item. Home Assistant
    reaches them only through `gp_*` (principle 2). It must verify that `garden_zones: groups:` lists from two
    packages concatenate (config row) before relying on it.
  - Hardware check: LEDs 4-9 including the pump LED, pump idle behaviour, both groups side by side.
  - LVGL pages for lawn/flowers belong to stage 9 (the `page_lawn.yaml` placeholder stays).
- "Lawn one zone at a time, flowers in parallel, shared pump" (pinned lanes, or a fork patch for a pump shared across
  groups): §9.1 backlog item, its own task.
- Remote packages, version tags, the CI remote-mode check, the private config repo and the private override file: the
  new roadmap stage.
- LilyGO status LEDs, RTC, DS18B20.
- Compiling the examples in CI (config only).
- Active-low relay support.

## Open questions
1. **LilyGO:** board revision and expansion board (the same 74HC595 chain?); does the bit map 0-5 / 8-13 hold; does
   the board pull nOE high at power-on; which ESP32 pins does the soldered display header carry? The answers go into
   the profile after the author checks the board.

<!-- Filled in by implementer -->
## Implementation notes

### What changed
- `gp_root` (default `"."`) in `irrigation.yaml`, `irrigation_pump.yaml`, `schedule.yaml`, `core/gp.yaml`, `lvgl/screensaver.yaml`
  (`source: ${gp_root}/components`, font `${gp_root}/packages/lvgl/fonts/...`). Verified: the substitution is expanded
  before `external_components` and the font are loaded (the four example config rows pass with `gp_root: ".."`).
  The font path resolution in `esphome/components/font` was not read separately; the config rows prove it resolves
  against the main config's directory.
- `script/config` and `script/compile` accept configs in a subdirectory (staged at the relative path, secrets file next
  to it; real-secrets rule as in "Files"; `GP_SECRETS=example` stages `examples/` too, the checkout stays clean).
  `tests/test_devcontainer.py::test_sim_script` compared `script/sim` and `script/compile` path lists; adapted
  (compile no longer lists `$CONFIG` in the loop; the config is copied after it).
- Breadboard profile: `board_relay_4..12`, `relay_4_pin..relay_12_pin`, `adc_2_pin`, `adc_3_pin`; header has the avoided
  pins, the "display/touch pin -> GPIO" table the author asked for (VCC 3.3 V from a V pin, GND from a G pin, signals to
  the S pin of the GPIO, SPI lines shared between display and touch) and the relay table (marked to verify by the author).
- `hardware/lilygo-t-relay-s3.yaml`, `packages/greenhouse/irrigation_pump.yaml`, `bed_soil_skip.yaml`, the four
  `examples/*.yaml` + `examples/README.md`, `tests/test_examples.py`, per-entry pin/relay tests in `tests/test_layout.py`.
- Docs: CLAUDE.md, README.md + README.ru.md (new "Examples" / "Примеры" section, same place), SPEC §2.2, §4.2, §5, §7, §9
  (stage 13) and §9.1.

### LilyGO: the vendor schematic WAS found
`Schematic/T-Relay6-ESP32S3-Rev1.1.pdf` (Xinyuan-LilyGO/LilyGo-T-Relay, `main`) page 1 gives the 14-pin TFT header H1
and the HT74HC595 wiring, so the display/touch pins are not placeholders: CS GPIO8, RST GPIO3, DC GPIO46, MOSI GPIO11,
CLK GPIO13, MISO GPIO12, BL GPIO9, touch CS GPIO10, touch IRQ GPIO14. H1 follows the usual 14-pin order of the 2.4"
ILI9341 + XPT2046 modules, so the author's display board should plug straight in. Shift register: DATA GPIO7, SHIFT
GPIO5, LATCH GPIO6, nOE GPIO4; QA..QF = relays 1-6, QG/QH = the LEDs; SQH goes to CN1 `DATA1` (the expansion chain).
Still "verify on the board": the bit map (the vendor chain example numbers outputs 0..N without skipping the LEDs), no
click at power-on, the orientation/calibration (copies of the breadboard values).

### Deviations
1. **Display pins GPIO3 and GPIO46 on LilyGO.** The planner's test forbade 0/3/45/46 for display/touch pins, but the
   board itself wires TFT_RST to GPIO3 and TFT_DC to GPIO46 (strapping pins). `test_lilygo_profile` forbids the real
   conflicts (4-7, 16-18, 19-21, 26-37, 43-45, 0) and allows 3 / 46 only for `display_reset_pin` / `display_dc_pin`. The
   profile header lists them under "verify".
2. **Backlight.** TFT_BL is GPIO9 and the packages have no backlight handling, so the LilyGO profile adds an internal
   switch `board_backlight` (`restore_mode: ALWAYS_ON`, pin `${display_backlight_pin}`). The safety tests exempt exactly
   this id (display backlight, not an actuator); `test_board_relays_are_safe` pins it to the LilyGO profile.
3. **`lvgl_page_touch_test` stays in the examples.** The task said to leave it out, but the Setup page navigates to
   `touch_test_page`, so the config fails without it. Only `touch_dot_test` is left out.
4. **`gh_screensaver_status` (and the sensors) are left out of all examples.** `screensaver_status.yaml` reads
   `gh_air_temperature` / `gh_soil_moisture_pct`, which need `gh_sensors_air` / `gh_sensors_soil` (DHT pin and `adc_1`
   that LilyGO does not define, and `adc_1` that soil-sensors uses per bed). Without it the screensaver has no status
   line and no "bed running" indicator. Each example and `examples/README.md` say how to add them.
5. **Minimal example needed no LVGL subset.** `esphome config` passes with the full LVGL set and one bed (the absent
   beds show as empty), so `minimal-1-bed.yaml` is the same stack with one bed.
6. **Soil example drops `gh_screensaver_status`** (see 4) and cannot be switched to the LilyGO profile (no ADC pins);
   its header says so.
7. `test_hardware_profiles_define_every_pin_used` was split into `test_entry_pins_defined_by_profile` (per entry) and
   `test_hardware_profiles_define_only_used_pins` (global). `test_analog_pins_named_by_function` no longer requires an
   ADC pin in the LilyGO profile. Several existing shape tests (greenhouse zones, gp layer, schedule, garden_zones
   package rules) were adapted to `gp_root` and to the two new variant files (their rules apply to them too).
8. Example 1 on LilyGO uses a staged copy built by the test itself (not `script/config`, which only takes repo files).

### Checks and results (devcontainer gp-dev-014)
- `uv run pytest -m unit`: 726 passed. `script/lint`: ok.
- Config rows: 4 examples + `minimal_on_lilygo` + `test_script_config_subdir`: 6 passed (~9 s total, so CI time is
  not an issue). Example 1 + LilyGO on `GP_ESPHOME=minimum` (2026.6.3): `Configuration is valid`.
- Compile (ESP32, pinned, example secrets): `garden-pilot.yaml` ok; `examples/beds-with-pump.yaml` ok.
- Full `script/test`: 826 passed in 9m40s (4 workers, `GP_REQUIRE_CXX=1`); the 6 new config rows are a small part of it.

### Not verified (hardware)
- Nothing was flashed or run on a board. The author's checklist ("Hardware verification" 1-6) is open: relay pins 4-12,
  all LEDs dark at power-on/RST/OTA (GPIO38 on a v1.1 board), pump LED behaviour, 8-channel example, LilyGO header pins
  and relay bit map.

## Follow-ups
- The examples have no screensaver status line (needs sensors); a sensor-less variant of `screensaver_status.yaml`
  (running-bed indicator only) would fix it.
- `soil-sensors.yaml` cannot use the LilyGO profile; a LilyGO profile with analog pins is not possible on that board
  without wiring an external input.
- Open question 1 (LilyGO revision, bit map, nOE pull-up) stays with the author.
