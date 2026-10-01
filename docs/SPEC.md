# GardenPilot — product specification

Status: draft. Items marked **open** are not decided yet; see §10.

## 1. What it does
GardenPilot is an ESPHome controller for a garden plot:
- **Irrigation** of greenhouse beds, lawn and other zones through valves (and optionally a pump).
- **Bed heating**: a buried 230 V heating cable plus a soil temperature probe per bed, switched by a relay or
  contactor.
- **Sensors**: soil moisture, air temperature/humidity, soil temperature.
- **Local touch UI** on a 320×240 display (LVGL), dark theme, see `design/`.
- **Home Assistant** integration through the native ESPHome API (all entities, actions and state visible in HA).

The project is public and meant to be repeated by others, so it is **modular** (enable a feature by
uncommenting one package) and **configurable** (pins, counts and names via substitutions).

## 2. Hardware
### 2.1 Current prototype (what the YAML targets today)
- ESP32-S3 DevKitC-1 N16R8, ESP-IDF framework (`garden-pilot.yaml`).
- ILI9341 320×240 SPI display (`mipi_spi`) + XPT2046 resistive touch on the same SPI bus
  (`packages/display_touch.yaml`).
- 3 greenhouse bed valves on GPIO relays, **gravity-fed from a shared barrel, no pump**
  (`packages/greenhouse/irrigation.yaml`).
- One resistive soil moisture probe (FC-28 type, analog + digital output) for the whole greenhouse.
- DHT11 for greenhouse air temperature/humidity (interim; an I2C sensor is planned).
- No soil temperature probes and no heating hardware yet.

### 2.2 Target hardware — **open**
A ready-made board with a display connector, relays and free GPIOs is planned (earlier notes mention
LILYGO T-Relay-S3; to be confirmed). Pins will move to `hardware/<board>.yaml` (§5).

## 3. The ESPHome `sprinkler` component: limits that shape the design
Checked against `esphome/components/sprinkler/` on the `dev` branch, 2026-10-01:
- **One valve at a time** per controller. A second `valve_op` exists only for overlap during transitions.
  Parallel watering needs several `sprinkler:` blocks, and a valve belongs to exactly one controller.
- **Closed queue.** `queued_valves_` is `protected`. Public API: `queued_valve()` (next), `total_queue_time()`,
  `clear_queued_valves()`. No list, no "is zone N queued", no removal of one zone. Duplicates are allowed.
  The queue does not survive a reboot.
- **`start_single_valve()` turns off `auto_advance` and `queue_enable`**: a manual RUN breaks the queue.
  The current greenhouse page uses it for its RUN buttons.
- Queued zones run **even if their enable switch is off**.
- The `Sprinkler` class is `final` (since July 2026): it cannot be subclassed.
- No functional changes since spring 2026. The `millis()` overflow fix (esphome#14299) shipped in
  **2026.2.3** — the lowest version we can support. Built-in latching valve support was removed (#12603).

## 4. Architecture
**YAML** — hardware and ready-made components: `switch: gpio` (valves, pump, heating relays), sensors, LVGL,
`time`, API, OTA. Bed heating uses the stock `climate: thermostat` (or `bang_bang`), one per bed.

**Own C++ component `garden_zones`** (later) — only the stateful irrigation logic:
- an open queue that survives reboot;
- parallel groups with an "N zones at once" limit;
- a watchdog for maximum valve on-time;
- watering by soil moisture threshold;
- history.

It takes valves from YAML by id and exposes standard ESPHome entities (switch / number / sensor / text_sensor),
actions and conditions, so everything shows up in Home Assistant. Its core is a plain C++ class without ESPHome
dependencies (unit-testable); the ESPHome component is a thin wrapper.

**Rejected:** plain C++ without ESPHome (loses HA, OTA and easy repetition); one huge do-everything component;
big logic in lambdas.

**Alternative for an early stage:** a fork of `sprinkler` in `components/` via `external_components` with the
missing queue methods. Downside: every ESPHome update means porting our changes. **Open** (§10, Q6).

### 4.1 The `gp_*` layer
Screens, schedules and automations never call `sprinkler` / `garden_zones` directly, only `gp_*` scripts and
entities:

```yaml
script:
  - id: gp_run_bed      # param: bed
  - id: gp_queue_bed    # param: bed
  - id: gp_stop_all
  # ...
# entities: gp_bed1_state, gp_queue_text, ...
```

So the MVP can run on `sprinkler` and later swap the engine for `garden_zones` without touching screens or HA.
The full list of `gp_*` actions and entities is a roadmap task.

### 4.2 Loading our own component
```yaml
external_components:
  - source: components            # development and cloned repos
    components: [garden_zones]
  # users without a clone pin a tag, never a branch:
  # - source: github://MrKiirya/garden-pilot@v1.0
  #   components: [garden_zones]
```

## 5. Modularity
- Many small YAML files, not one big file.
- The entry file lists modules, most of them commented out: uncomment a line to get a bed, the lawn, heating.
- A bed is one `packages/bed.yaml` included N times through `!include` with `vars` (id, name, pins). Inside:
  valve, sensors, heating thermostat, a `garden_zone:` entry for the component. For this the component uses
  `MULTI_CONF`, with a shared `garden_zones:` hub that owns the queue and groups.
  **Verify with a first test build** that lists from different packages merge as expected.
- **Screens:** LVGL YAML has no loops. Bed layouts as fixed variants (1 / 2 / 3 / 6 beds, see design drafts
  D03–D05) or generated YAML — **open**.
- Hardware is a separate package: `hardware/<board>.yaml` with real pins and `hardware/sim.yaml` for tests
  (template switches and sensors instead of GPIO).

Target layout:
```
garden-pilot.yaml          # entry file, modules commented out
hardware/                  # esp32-<board>.yaml, sim.yaml
packages/
  core/                    # network, time, api, ota
  lvgl/                    # pages
  bed.yaml, lawn.yaml, heating.yaml, ...
components/garden_zones/   # __init__.py, *.h, *.cpp
design/                    # tokens.json, README, icons
docs/
tasks/
tests/
```

## 6. Compatibility
- **Pinned (development):** ESPHome **2026.9.1** (`pyproject.toml`, exact pin).
- **Minimum supported:** at least **2026.2.3** (sprinkler `millis()` fix, §3). The exact floor is set by CI in
  roadmap task 003 (our LVGL options may need a newer release).
- CI builds both the minimum and the pinned version; a weekly canary builds the latest stable ESPHome without
  committing and warns before a release breaks us.

## 7. Testing without hardware
1. `esphome config` for every module combination (CI).
2. `esphome compile` for ESP32 (CI).
3. Unit tests of the `garden_zones` core (GoogleTest or Catch2).
4. **`host` platform:** firmware runs on Linux/macOS, the API works and HA can connect by IP; no GPIO, hence
   `hardware/sim.yaml`.
5. **`display: platform: sdl`:** LVGL screens in a window, mouse instead of touch; in CI `headless: true` and
   BMP screenshots compared with references.
6. Integration scenarios through `aioesphomeapi` against the host build.
7. Optional: Wokwi (ESP32 + ILI9341 emulation, `wokwi-cli` in GitHub Actions).

## 8. Design
- Rules and tokens: `design/README.md`, `design/tokens.json`, icons in `design/icons/`.
- The live design lives in claude.ai artifacts (author's account): the design system and the screens canvas
  (pages "Screens": Home / Greenhouse / Lawn, and "Drafts": D01–D25). The repo keeps a snapshot of what the
  firmware depends on; token changes are synced into the repo by PR.
- Built today: `home_page` only follows the tokens. `greenhouse_page`, `lawn_page` and `touch_test_page` still
  use the default LVGL theme. Bottom nav is a placeholder (ZONES → greenhouse, WATER → lawn, SETUP → touch test).
- Known UI defects: the Home "NEXT" label shows the remaining queue time (hours dropped), not the next scheduled
  run — there are no schedules yet.
- `packages/network.yaml` updates `home_clock_label` from `time.on_time_sync`, which can fire before LVGL is
  ready (same pattern as the `number.on_value` gotcha in `CLAUDE.md`), and makes `network` depend on the Home
  page package.

## 9. Roadmap
1. **Process scaffold** (task 001): agent guide, agents, task templates, this spec, uv + pinned ESPHome,
   scripts, repo checks.
2. **Devcontainer** (task 002): reference environment for Linux/Windows/macOS, USB flashing, SDL window.
3. **CI** (task 003): lint, `config` matrix, `compile` (min + pinned ESPHome), canary, Dependabot, `master`
   ruleset.
4. **Modular layout:** `hardware/`, `packages/core/`, `bed.yaml` with `vars`, `hardware/sim.yaml`.
5. **`gp_*` layer** on top of `sprinkler` (MVP), screens switched to it.
6. **Screens on the design system:** Greenhouse (proposal), Home, navigation; bed layout variants.
7. **Time without HA:** SNTP fallback (and RTC if needed) so schedules work offline.
8. **Schedules** (WATER tab), **bed heating** (thermostats + heating screens), alerts.
9. **`garden_zones` component:** open queue, parallel groups, watchdog, threshold watering, history.
10. **Host + SDL** test harness and screenshot checks.

## 10. Open questions
**Hardware**
1. Final board and display? Touch controller? How many relays, which GPIOs are free?
2. Soil moisture sensors (capacitive analog? I2C?) — one per bed or one per greenhouse? Soil temperature probes
   for heating (DS18B20)?
3. Water source per zone: barrel (gravity), mains, pump? Flow meter or pressure sensor planned?

**Irrigation**
4. How many zones now and planned (greenhouse beds, lawn, drip)? How many may water at once (gravity feed may
   not have the pressure for parallel zones)?
5. Which `sprinkler` features are actually needed (repeat, multiplier, reverse, pump, valve overlap)?
6. Start on `sprinkler` + `gp_*` (MVP) or go straight to `garden_zones` (or a `sprinkler` fork)?
7. Where do schedules live: on the device, in HA, or both? Must it work without HA?

**Heating**
8. How many heated beds, cable power, relay vs. contactor, RCD and a hardware over-temperature cut-off?
   Night-tariff binding?
9. Which modes are needed: OFF / ALWAYS / NIGHT / FROST?

**Screens**
10. Which drafts from the canvas to keep?
11. Bed layouts: fixed variants or generated YAML?
12. UI language: English only, Russian, or selectable?

**Repository**
13. Exact minimum ESPHome version (task 003).

## 11. Sources
- ESPHome `esphome/components/sprinkler/` (`dev`, 2026-10-01) and its commit history.
- https://esphome.io/components/sprinkler/
- https://esphome.io/components/external_components/
- https://esphome.io/components/host/
- https://esphome.io/components/display/sdl/
- https://docs.wokwi.com/wokwi-ci/github-actions
