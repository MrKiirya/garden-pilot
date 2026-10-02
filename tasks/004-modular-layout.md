# 004 — Modular layout, part 1: hardware profile, core packages, config matrix

Status: done
Roadmap: SPEC §9 item 4 "Modular layout" (part 1 of 2; part 2 is the follow-up task listed under "Out of scope")
Spec sections: SPEC §2.1, §2.2, §4, §5, §6, §7 (item 1), §8 (last bullet), §10.1; CLAUDE.md core principles 2, 3, 4, 6
Hardware check: yes. The author flashes the breadboard build (ESP32-S3 DevKitC-1 N16R8 + ILI9341/XPT2046 + relay
module) and confirms nothing changed: screen, touch, navigation, all three valves, the sensors and the Home
Assistant entities. CI cannot check this.

## Goal
Restructure the firmware YAML into the SPEC §5 layout **without changing what the device does**. All pins move
into one board profile, `hardware/esp32-s3-devkitc1-breadboard.yaml`, which also holds the `esp32:` block.
Wi-Fi, API, OTA and time move into `packages/core/`. Packages no longer contain `!secret`: the entry file assigns
secrets to substitutions, so the packages can later be used as remote packages (stage 5). `network` no longer
depends on the Home page. A pytest-driven **config matrix** checks several entry-file variants (full device,
headless core only, full without the touch debug overlay) with `esphome config` in the existing `checks` CI job.
Developers get one place to change pins and one line per module in the entry file. Users see no change: same
firmware, same entities.

## Context

### Current state (read before planning)
- `garden-pilot.yaml` holds `esphome:`, `esp32:` (board `esp32-s3-devkitc1-n16r8`, `esp-idf`), `logger: INFO`
  and 12 packages. `tests/test_esphome_config.py::test_entry_file_is_a_package_list` pins its top-level keys to
  `{esphome, esp32, logger, packages}`. This task changes that test.
- Pins are spread across files:
  - `packages/display_touch.yaml` has literal pins: SPI clk `GPIO9`, mosi `GPIO10`, miso `GPIO8`; display cs
    `GPIO13`, dc `GPIO11`, reset `GPIO12`; touch cs `GPIO18`, irq `GPIO15`.
  - `packages/greenhouse/substitutions.yaml` has `gh_dht_pin: GPIO4`, `gh_valve_zone{1,2,3}_pin: GPIO21/47/48`,
    `gh_soil_ao_pin: GPIO6`, `gh_soil_do_pin: GPIO7`, and the soil calibration `gh_soil_cal_dry_v` /
    `gh_soil_cal_wet_v`.
- `packages/network.yaml` uses `!secret` five times (`api_encryption_key`, `ota_password`, `wifi_ssid`,
  `wifi_password`, `wifi_ap_password`). It also defines `time: homeassistant` (`id: ha_time`) with an
  `on_time_sync` that updates `home_clock_label`, plus a 30 s `interval` that does the same. So the network
  package depends on `packages/lvgl/page_home.yaml` (SPEC §8).
- Legacy coupling that this task **keeps**: the greenhouse sensors and `sprinkler_lvgl_status.yaml` update LVGL
  ids on the Home and Greenhouse pages; `page_home.yaml` navigates to `greenhouse_page`, `lawn_page` and
  `touch_test_page`; `greenhouse/lvgl_page.yaml` calls `sprinkler.*` directly. So the greenhouse, LVGL pages
  and display only validate together. The matrix in this task therefore has only "core only" and "everything"
  style variants. Finer variants come with part 2.
- The raw valve switches already have `internal: true` and `restore_mode: RESTORE_DEFAULT_OFF`. There is no
  max on-time guard; that is planned for stage 6 (`garden_zones` watchdog).
- `script/config` already copies `packages`, `hardware` and `components` into its temp dir, so a new
  `hardware/` folder needs no script change. `tests/test_ci.py` pins the CI check names to `checks`,
  `compile (pinned)` and `compile (minimum)`, and the ruleset in `.github/rulesets/master.json` requires them.
  **Do not add a CI job.** The matrix runs as pytest inside `checks` (`script/test`).

### ESPHome behaviour checked (pinned 2026.9.1, minimum 2026.6.3)
- Packages ([esphome.io/components/packages](https://esphome.io/components/packages/)):
  - Dicts merge key by key, component lists merge by `id`, other lists are concatenated.
  - "Substitutions in your main configuration will override substitutions with the same name in a package."
  - `!extend <id>` changes an entry defined by another package, and `!remove` deletes one.
  - Remote packages cannot use `!secret`. They should use substitutions that the device YAML fills in from
    its own secrets.
  - `!include` with `file:` + `vars:` exists. It is **not used in this task**; it comes in part 2.
- Substitutions ([esphome.io/components/substitutions](https://esphome.io/components/substitutions/)):
  - The docs show `!secret` as a substitution value (`bar_yellow_value: !secret yellow_secret`).
  - Command-line `-s` substitutions take precedence over the file.
  - Substitutions defined in one package are visible to the others. The current `gh_substitutions` package
    already relies on that.
- Substitutions in `!include` file names ([esphome#12213](https://github.com/esphome/esphome/pull/12213),
  merged 2026-04-08, so it should be in both 2026.6.3 and 2026.9.1) could later select the board profile through
  one substitution. **Do not use it here.** The board is chosen by one plain `!include` line. This avoids
  depending on the recently redesigned include loader
  ([esphome#12126](https://github.com/esphome/esphome/pull/12126)) before part 2 tests it on the minimum version.
- `!extend` on a `time:` entry: component lists merge by id for every component domain, so
  `time: [{id: !extend ha_time, on_time_sync: …}]` in `page_home.yaml` adds the trigger to the core clock. The
  implementer confirms this with `esphome config` on both versions (`GP_ESPHOME=minimum sh script/config`).
- If the implementer finds any of this behaving differently in 2026.6.3, record it under Implementation notes
  and in SPEC §6.

### Decisions (made with the author)
- Only one real board profile exists now: the breadboard build. **No placeholder file for the LILYGO
  T-Relay-S3.** An unvalidated profile with guessed pins would break principle 4 and the "every combination
  validates" rule. The header comment of the board profile explains how to add a board (copy the file, keep
  every `*_pin` key). Confirm under Open questions.
- `hardware/sim.yaml` (template switches/sensors, `host` platform) is part 2. To use it, the raw drivers must be
  separated from the feature logic first. That is a real design step, not a file move.
- Pin substitutions get **board-function names**, not feature names, so a ready-made relay board maps naturally.
  Use exactly these names:

  | Substitution | Breadboard value | Used by |
  |---|---|---|
  | `spi_clk_pin` | `GPIO9` | `display_touch.yaml` `spi` |
  | `spi_mosi_pin` | `GPIO10` | same |
  | `spi_miso_pin` | `GPIO8` | same |
  | `display_cs_pin` | `GPIO13` | `display` |
  | `display_dc_pin` | `GPIO11` | `display` |
  | `display_reset_pin` | `GPIO12` | `display` |
  | `touch_cs_pin` | `GPIO18` | `touchscreen` |
  | `touch_irq_pin` | `GPIO15` | `touchscreen` |
  | `relay_1_pin` | `GPIO21` | greenhouse bed 1 valve |
  | `relay_2_pin` | `GPIO47` | greenhouse bed 2 valve |
  | `relay_3_pin` | `GPIO48` | greenhouse bed 3 valve |
  | `air_dht_pin` | `GPIO4` | greenhouse DHT11 (interim) |
  | `soil_ao_pin` | `GPIO6` | greenhouse soil probe, analog |
  | `soil_do_pin` | `GPIO7` | greenhouse soil probe, digital |

  The mapping "bed N uses relay N" stays inside `greenhouse/irrigation.yaml` for now. Part 2 moves it into the
  `bed.yaml` `vars` in the entry file.
- The soil calibration (`soil_cal_dry_v: "3.16"`, `soil_cal_wet_v: "0.80"`) belongs to the probe, not to the
  board. It moves into a `substitutions:` block at the top of `packages/greenhouse/sensors_soil.yaml`. That block
  acts as a default, and the entry file can override it.
- Display geometry, touch calibration and transforms stay in `display_touch.yaml`. They are not pins (see Open
  questions).
- Secret substitutions keep the secret key names: `api_encryption_key`, `ota_password`, `wifi_ssid`,
  `wifi_password`, `wifi_ap_password`. The core packages declare **no defaults** for them, so a missing value
  fails validation and is never silently empty.
- `logger:` and `esphome:` (name, friendly_name) stay in the entry file. They are per-device knobs.

### Target entry file (shape, not literal text)
```yaml
substitutions:            # secrets are assigned here, never inside packages
  api_encryption_key: !secret api_encryption_key
  # ... ota_password, wifi_ssid, wifi_password, wifi_ap_password
esphome: {name: garden-pilot, friendly_name: GardenPilot}
logger: {level: INFO}
packages:
  hardware: !include hardware/esp32-s3-devkitc1-breadboard.yaml   # pick exactly one board profile
  core_network: !include packages/core/network.yaml
  core_time: !include packages/core/time.yaml
  display_touch: ...      # then the existing order: lvgl_base, lvgl_page_home, other pages,
  # gh_irrigation, gh_lvgl_page, gh_sensors_air, gh_sensors_soil, gh_sprinkler_lvgl, touch_dot_test
```
`gh_substitutions` disappears. Every module line keeps a short comment saying what it adds and what it requires,
e.g. "greenhouse: needs display_touch + lvgl pages until stage 7".

### Proving "no behaviour change"
1. **Normalized `esphome config` diff (required).** Run
   `GP_SECRETS=example GP_VERBOSE=1 sh script/config > <scratch>/before.txt 2>&1` on `master` (e.g. in a
   `git worktree` outside the repo) and the same command on the branch into `after.txt`. Then compare with a
   scratch helper that is **not committed**:
   - take the YAML after the `Configuration is valid!` line;
   - load it with a SafeLoader that turns `!tags` into strings (as in `tests/conftest.py`);
   - drop `substitutions`;
   - turn each top-level value into a sorted list of canonical JSON items, so package order does not matter.

   Expected result: no differences, except possibly how the five secret fields are rendered. Paste the helper
   and its output into Implementation notes.
2. **Optional, stronger:** `esphome compile --only-generate` on both trees and a diff of `main.cpp`. Expect only
   reordering (component registration order follows package order). Note it in Implementation notes if done.
3. **Entity identity:** entity `name`s and component `id`s are unchanged. So HA entity ids and the restored
   preferences (bed run durations) survive the OTA update. Check 1 covers this.

## Files
- create: `hardware/esp32-s3-devkitc1-breadboard.yaml`
  - holds the `esp32:` block moved from the entry file and `substitutions:` with exactly the 14 `*_pin` keys
    above;
  - header comment: the wiring it describes, that it is the only file with pins, how to add a board;
  - keeps the useful wiring notes from the old files (MISO on GPIO8 and not strapping GPIO3; "avoid SPI/touch
    pins").
- create: `packages/core/network.yaml`
  - `api` (encryption key `${api_encryption_key}`), `ota` (`${ota_password}`), `wifi` (`${wifi_ssid}`,
    `${wifi_password}`, `min_auth_mode: WPA2`, fallback `ap` with literal SSID `GardenPilot-AP` and
    `${wifi_ap_password}`), `captive_portal`;
  - no `!secret`, no LVGL.
- create: `packages/core/time.yaml`: `time: - platform: homeassistant, id: ha_time`. No triggers, no LVGL.
- modify: `packages/lvgl/page_home.yaml`
  - add `time: - id: !extend ha_time` with the existing `on_time_sync` clock update;
  - add the existing 30 s `interval` that updates `home_clock_label`;
  - both are moved verbatim from `network.yaml`, so the clock behaves exactly as before. Do not change the widget
    tree.
- delete: `packages/network.yaml` (content moved to the three files above).
- modify: `packages/display_touch.yaml`: the 8 literal pins become `${…}`; comments mention no GPIO numbers.
- modify: `packages/greenhouse/irrigation.yaml`: `${gh_valve_zoneN_pin}` becomes `${relay_N_pin}`; update the
  header comment. No other change.
- modify: `packages/greenhouse/sensors_air_dht.yaml`: `${gh_dht_pin}` becomes `${air_dht_pin}`.
- modify: `packages/greenhouse/sensors_soil.yaml`
  - add a `substitutions:` block with `soil_cal_dry_v` / `soil_cal_wet_v` (same values);
  - `gh_soil_ao_pin` / `gh_soil_do_pin` become `soil_ao_pin` / `soil_do_pin`; `gh_soil_cal_*` become
    `soil_cal_*`;
  - update the comments.
- delete: `packages/greenhouse/substitutions.yaml`
- modify: `garden-pilot.yaml`: new shape as above (`esp32:` moves out, `substitutions:` with the five secrets,
  `hardware` + `core_*` packages first).
- modify: `tests/test_esphome_config.py`: entry-file keys become `{substitutions, esphome, logger, packages}`.
- create: `tests/test_layout.py`: unit layout checks (see below).
- create: `tests/test_config_matrix.py`: config matrix (see below).
- modify: `docs/SPEC.md`
  - §5: mark what exists after this task (hardware profile, `packages/core/`) and what part 2 adds;
  - §7 item 1: matrix lives in `tests/test_config_matrix.py`, runs in `checks`;
  - §8 last bullet: `network` no longer depends on the Home page; the "time sync before LVGL ready" risk remains,
    now in `page_home.yaml`;
  - §9 item 4: split into this task and part 2.
- modify: `CLAUDE.md`
  - layout table: `hardware/`, `packages/core/`; remove `packages/network.yaml`;
  - `packages:` order section;
  - the legacy note that says greenhouse pins live in `packages/greenhouse/substitutions.yaml`;
  - a convention line: "pins only in `hardware/`, secrets only as entry-file substitutions".
- modify: `README.md`, `README.ru.md`: line 95 layout bullet (add `hardware/`, `packages/core/`; keep both
  languages in sync).

This is about 19 paths, but most are mechanical moves or renames. The real logic is in the two new test files and
the entry file. Do not widen the scope further.

## Checks to write first
| Level | Test | Asserts |
|---|---|---|
| unit | `tests/test_layout.py::test_pins_only_in_hardware` | In every tracked `*.yaml` outside `hardware/` (including `garden-pilot.yaml`), after stripping `#` comments, no `GPIO\d+` literal appears. |
| unit | `tests/test_layout.py::test_hardware_profiles_shape` | Every `hardware/*.yaml` has top-level keys within `{substitutions, esp32, psram}` and has `esp32` with a `board`. All substitution keys end in `_pin`. |
| unit | `tests/test_layout.py::test_hardware_profiles_define_every_pin_used` | The set of `${…_pin}` names referenced under `packages/` is a subset of the substitution keys of **each** `hardware/*.yaml`. With one profile today this is also an equality check, so no unused pins. |
| unit | `tests/test_layout.py::test_no_secret_outside_entry_file` | No tracked YAML under `packages/` or `hardware/` contains `!secret`. In `garden-pilot.yaml`, `!secret` appears only as a value of `substitutions:`. |
| unit | `tests/test_layout.py::test_substitutions_resolve` | Every `${name}` (braced form) used under `packages/` is defined in the entry `substitutions:`, in a `hardware/*.yaml`, or in a `substitutions:` block of some file under `packages/`. Catches typos and missing secrets before `esphome config`. |
| unit | `tests/test_layout.py::test_core_is_display_independent` | Files under `packages/core/` contain no `lvgl` text and no reference to ids defined under `packages/lvgl/` (e.g. `home_clock_label`). |
| unit | `tests/test_layout.py::test_gpio_actuators_are_safe` | Every `switch` entry with `platform: gpio` under `packages/` or `hardware/` has `internal: true` and `restore_mode` in `{RESTORE_DEFAULT_OFF, ALWAYS_OFF}` (principle 4; holds today, guards the move). |
| unit | `tests/test_esphome_config.py::test_entry_file_is_a_package_list` (modified) | Top-level keys are `{substitutions, esphome, logger, packages}`. The first package key is `hardware`, it includes a file under `hardware/`, and it is followed by `core_network`, `core_time`. |
| config | `tests/test_config_matrix.py::test_variant_validates[full]` | The entry file unchanged passes `esphome config` (pinned) with `secrets.example.yaml`. |
| config | `tests/test_config_matrix.py::test_variant_validates[headless]` | The entry file with only the `hardware`, `core_network`, `core_time` package lines kept passes `esphome config`. This proves core does not need the display or LVGL. |
| config | `tests/test_config_matrix.py::test_variant_validates[no_touch_debug]` | The entry file without the `touch_dot_test` line passes (the CLAUDE.md promise "comment it out to disable"). |

How the matrix builds variants:
- **Line-based from the real `garden-pilot.yaml`.** Keep the non-package lines; under `packages:`, keep only the
  lines whose key is in the variant's list. This mirrors a user commenting lines out, and the variants can never
  drift from the real file.
- Write the variant into `tmp_path`, copy `packages/` and `hardware/` (and `components/` if it exists) next to
  it, copy `secrets.example.yaml` to `tmp_path/secrets.yaml`, then run `sh script/_esphome config <variant>`.
  Never write into the checkout.
- Define the variants as one data table (name → kept package keys, or "all"), so part 2 only adds rows. Mark the
  module `pytest.mark.config`.
- Include the failure tail of the output in the assertion message, as in `test_esphome_config.py`.

## Acceptance criteria
- [x] `uv run pytest -m unit` → all pass, including the 7 new `test_layout.py` tests and the modified entry test.
- [x] `script/lint` → yamllint strict clean, `esphome config OK: garden-pilot.yaml`.
- [x] `script/test` → all pass, including `test_config_matrix.py` with 3 variants.
- [x] `GP_ESPHOME=minimum GP_SECRETS=example sh script/config` → `esphome config OK` (2026.6.3 accepts the
      substitutions-with-`!secret` and the `!extend ha_time`).
- [x] `git grep -nE 'GPIO[0-9]+' -- '*.yaml' ':!hardware/'` → only comment lines, or nothing.
- [x] `git grep -n '!secret' -- packages hardware` → no output.
- [x] `packages/network.yaml` and `packages/greenhouse/substitutions.yaml` no longer exist.
- [x] Normalized `esphome config` diff, master vs branch (procedure in Context) → no differences beyond the
      rendering of secret fields. Helper and output pasted into Implementation notes.
- [x] `tests/test_ci.py` unchanged and green (done); `.github/workflows/ci.yml` and `.github/rulesets/master.json`
      unchanged (done). CI on the PR is green (PR #7 merged with the required checks green) for `checks`, `compile (pinned)` and `compile (minimum)`.
- [x] `docs/SPEC.md`, `CLAUDE.md`, `README.md` and `README.ru.md` updated as listed in Files.
- [x] **Hardware (author, not CI):** after flashing the branch firmware (USB or OTA, `uv run esphome run
      garden-pilot.yaml`) on the breadboard build:
  - the device boots to the Home screen, and the clock appears after HA time sync and keeps updating;
  - touch works and the nav reaches Greenhouse, Lawn and Touch test and returns home;
  - the touch dot overlay still works;
  - on the Greenhouse page, RUN for bed 1/2/3 clicks the matching relay (GPIO21/47/48); STOP closes it; QUEUE +
    start runs the queue;
  - air T/RH and soil % update on Home and Greenhouse;
  - in Home Assistant the entities have the same names and ids, with no new duplicates and nothing left
    "unavailable";
  - bed run durations keep their values after the update;
  - after a power cycle all valves are OFF.

  The implementer states in Implementation notes that none of this was verified on a device.
  Verified by the author on 2026-10-02: OTA flash, screen and clock, touch and navigation, bed relays, sensors, HA
  entities.

## Out of scope
- **Part 2 (next task, proposed `005-modular-beds-sim`):**
  - `packages/bed.yaml` included N times through `!include` with `vars`, replacing the three hard-coded valves.
    Its `vars` carry id, name and the relay pin substitution. Verify how `vars`, package `defaults` and nested
    substitutions behave on 2026.6.3 vs 2026.9.1 (loader redesign esphome#12126).
  - Splitting raw drivers (GPIO switch, ADC, DHT) from feature logic so that `hardware/sim.yaml` can supply
    template switches and sensors. Uses the `host` platform, no display.
  - New matrix rows: sim + headless greenhouse, 1 bed and 3 beds.
  - Decoupling the greenhouse sensors from LVGL ids (needed for a "greenhouse without display" variant).
- LILYGO T-Relay-S3 profile. Wait until the author has the board and its verified pinout.
- Selecting the board through a substitution in the `!include` path.
- `gp_*` layer (stage 7) and `garden_zones` (stage 6). The greenhouse page keeps calling `sprinkler.*`. No max
  on-time guard is added to valves here (stage 6 watchdog), so this stays a known gap.
- Fixing the "LVGL update from `on_time_sync` before LVGL is ready" risk (SPEC §8). This task only moves the code;
  a follow-up can switch it to the interval-only pattern.
- Remote-package wiring and docs (stage 5); moving the fallback AP SSID into a substitution.
- Moving display/touch calibration and orientation into the board profile (see Open questions).

## Decisions (author's answers to the open questions)
1. **T-Relay-S3:** add nothing until the author has the board. No placeholder file.
2. **Pin names** are by board function (`relay_1_pin`, `soil_ao_pin`, `spi_clk_pin`, ...). Which relay a bed uses is
   chosen in the feature/bed module, not in the board file.
3. **Change vs. the plan:** touch calibration and display orientation (`mirror_*`, `swap_xy`, calibration values)
   also move into the board profile as substitutions, because they depend on the exact screen and mounting.
   `display_touch.yaml` references them. Values stay identical and the normalized `esphome config` diff must stay
   clean. Consequences: board profile substitution keys are no longer all `*_pin` (only the pin ones are checked
   against the 14-pin list); the "Out of scope" bullet about moving calibration is void.
4. **Touch debug overlay** stays enabled by default (no behaviour change).
5. The second part of stage 4 is task **005** (plain 3-digit numbering).

## Implementation notes
- Checks were written first (`tests/test_layout.py`, `tests/test_config_matrix.py`, modified entry test); 5 failed for
  the right reason before the change, all 227 pass after.
- Decision 3 applied: display `swap_xy`/`mirror_*` and touch calibration/orientation are board-profile
  substitutions (`display_swap_xy`, `display_mirror_x/y`, `touch_cal_{x,y}_{min,max}`, `touch_swap_xy`,
  `touch_mirror_x/y`; string values `"true"`/`"201"`, accepted by the validators). Because of this
  `test_hardware_profiles_shape` no longer requires all keys to end in `_pin`: only `*_pin` keys are compared
  with the pins used under `packages/` (equality), and an extra test `test_hardware_board_settings_are_used`
  requires every other board substitution to be referenced by a package.
- `tests/test_layout.py` lists files with `git ls-files --cached --others --exclude-standard` (own helper), so new
  files are checked before the first commit; `conftest.tracked_files` is unchanged.
- Matrix variants are built line-based from the real entry file; the `headless` variant keeps only the three
  core package lines.
- `!extend ha_time` in `page_home.yaml` works on pinned 2026.9.1 and on minimum 2026.6.3
  (`GP_ESPHOME=minimum GP_SECRETS=example sh script/config` -> OK). No difference found, SPEC §6 unchanged.
- Normalized diff (master via `git archive HEAD` in scratch vs working tree), no differences, secrets included
  (example secrets render identically):
  helper (not committed): strip lines starting `INFO `/`WARNING `, cut at `INFO Configuration is valid!`,
  load with a SafeLoader mapping `!tags` to strings, drop `substitutions`, turn every top-level value into a sorted
  list of `json.dumps(item, sort_keys=True)`, compare per section. Output: `sections: 19 19 differences: 0`.
  The optional `main.cpp` diff was not done.
- Side effect: `git rm` was used to delete the two old files, so those deletions are staged in the index.
- NOT verified on a real device (nothing flashed). The hardware checklist above is for the author.

## Follow-ups
- `script/lint` yamllint: soil comment wrapped to 120 columns (done).
- Compile (pinned/minimum) not run locally; left to CI.
