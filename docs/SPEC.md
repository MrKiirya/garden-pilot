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

### 2.2 Target hardware
Two kinds of builds are supported, each as a board profile `hardware/<board>.yaml` (§5) that holds all pins:
- **Ready-made board:** an ESP32-S3 board with relays on board plus a display connector or free SPI pins
  (the author's target is the LILYGO T-Relay-S3). Check which pins remain free for the SPI display and touch.
- **Self-assembled ("breadboard") build:** a generic ESP32-S3 dev board + ILI9341/XPT2046 + a relay module,
  as in §2.1.

The project must not depend on one specific board.

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

**Own component `garden_zones`, built from a fork of `sprinkler`** — only the stateful irrigation logic.
Decision: no intermediate MVP on the stock `sprinkler`; we copy `esphome/components/sprinkler/` into
`components/garden_zones/` (loaded via `external_components`) and change as little of it as possible:
- **Queue (patched):** an open queue (list, "is zone N queued", remove one zone) that survives reboot; a manual
  run of one zone does not break the queue; disabled zones are skipped.
- **Parallelism without rewriting the state machine:** the stock one-valve-at-a-time controller stays; parallel
  watering uses several controllers ("lanes"). Zones are grouped by water source; each group has
  `max_parallel`:
  - `max_parallel: 1` → one controller for the group, one shared queue (e.g. lawn on a pump);
  - `max_parallel: all` → one controller per zone, all can run at once (e.g. greenhouse beds on a gravity barrel);
  - in between → zones are assigned to lanes statically (documented limit: two zones of the same lane never run
    together even if another lane is idle). Dynamic lanes are a later option.
  The component's Python code generates the controllers from a `groups:` / `zones:` config, e.g.:
  ```yaml
  garden_zones:
    groups:
      - {id: greenhouse, max_parallel: all}
      - {id: lawn, max_parallel: 1, pump: lawn_pump}
    zones:
      - {name: Bed 1, group: greenhouse, valve: valve_bed1}
  ```
  To verify when planning: how a pump shared by zones in different controllers behaves.
- **Safety:** a watchdog for maximum valve on-time (principle 4).
- **Soil moisture (optional per zone):** any ESPHome sensor; if present and the soil is wet, the zone's run is
  skipped.
- **History** of runs per zone (wanted; see the backlog in §9).

It takes valves from YAML by id and exposes standard ESPHome entities (switch / number / sensor / text_sensor),
actions and conditions, so everything shows up in Home Assistant. New logic goes into plain C++ classes without
ESPHome dependencies where practical (unit-testable).

**Licence:** ESPHome's C++ runtime is GPLv3 (its Python code is MIT). The forked files keep their original
copyright/licence headers, are marked as modified, and `components/garden_zones/` carries the GPLv3 text; the
rest of this repository stays MIT. The README states this.

**Cost:** every ESPHome update may need our patches re-ported; keeping the diff to the stock component small is
a goal, and the weekly canary (task 003) warns early.

**Rejected:** plain C++ without ESPHome (loses HA, OTA and easy repetition); one huge do-everything component;
big logic in lambdas; rewriting `sprinkler`'s one-valve state machine for parallel zones.

**Bed heating:** stock `climate: thermostat` (or `bang_bang`) per bed, one 230 V cable per bed, N beds
configurable. The temperature input is any ESPHome sensor: the probes bundled with floor-heating kits are usually
NTC thermistors (`adc` + `resistance` + `ntc`), DS18B20 also works. Main mode: keep the soil above a minimum so it
does not freeze; a greenhouse air sensor can be an extra input. Firmware guards: maximum on-time and maximum soil
temperature (principle 4). Electrical safety (RCD, contactor vs. relay, hardware over-temperature cut-off) is
documented as recommendations, the builder decides; the author's own build is documented as an example.

**Schedules** live on the device and run without Home Assistant or Wi-Fi; HA is optional (it can edit and
trigger them).

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

So screens and HA do not depend on the engine. The current greenhouse page still calls the stock `sprinkler`
directly; it moves to `gp_*` when the layer is introduced.
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
- Hardware is a separate package: `hardware/<board>.yaml` with real pins (also `esp32:` and the display/touch
  orientation and calibration) and `hardware/sim.yaml` for tests (template switches and sensors instead of GPIO).
  Exists after task 004: `hardware/esp32-s3-devkitc1-breadboard.yaml` and `packages/core/` (network, time).
  Task 005 adds `bed.yaml` with `vars` and `hardware/sim.yaml`.

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
- **Pinned (development):** ESPHome **2026.9.1** (`pyproject.toml`, exact pin; Dependabot proposes bumps).
- **Minimum supported:** ESPHome **2026.6.3** (`[tool.garden-pilot] esphome-minimum` in `pyproject.toml`;
  lowest release that passes `esphome config` and the CI compile; never below 2026.2.3, the sprinkler
  `millis()` fix, §3). Releases 2026.6.0-2026.6.2 reject the display `dimensions` (mipi_spi "Invalid offsets").
- CI compiles both on every PR, and a weekly canary builds the latest stable ESPHome and opens or closes the
  `canary-failure` issue.

## 7. Testing without hardware
1. `esphome config` for every module combination: the matrix in `tests/test_config_matrix.py` (variants built from
   the real entry file) runs in CI job `checks` via `script/test`; more variants come with task 005.
2. `esphome compile` for ESP32 (CI jobs `compile (pinned)` and `compile (minimum)`, weekly canary).
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
- **UI language** is chosen at build time (a substitution in the entry file, `en` / `ru`): only one language
  and its glyphs are baked into flash.
- Built today: `home_page` only follows the tokens. `greenhouse_page`, `lawn_page` and `touch_test_page` still
  use the default LVGL theme. Bottom nav is a placeholder (ZONES → greenhouse, WATER → lawn, SETUP → touch test).
- Known UI defects: the Home "NEXT" label shows the remaining queue time (hours dropped), not the next scheduled
  run — there are no schedules yet.
- The Home clock updates `home_clock_label` from `time.on_time_sync`, which can fire before LVGL is
  ready (same pattern as the `number.on_value` gotcha in `CLAUDE.md`). Since task 004 this code lives in
  `packages/lvgl/page_home.yaml` (`!extend ha_time`), so `packages/core/` no longer depends on the Home page.

## 9. Roadmap
1. **Process scaffold** (task 001): agent guide, agents, task templates, this spec, uv + pinned ESPHome,
   scripts, repo checks.
2. **Devcontainer** (task 002): `.devcontainer/` with one Dockerfile and two configs (default; opt-in `sdl/` that
   forwards the host X11 display). Docker and rootless Podman; Python 3.14 + uv + the ESPHome pinned in
   `uv.lock`; ESP-IDF / PlatformIO caches in named volumes. USB passthrough on Linux only (env-driven); on
   Windows/macOS flash the first time from the host or web.esphome.io, then OTA by IP. `script/sdl-smoke` proves
   a window opens. Verified by the author on Linux with rootless Podman in VS Code (incl. USB flash and OTA); Windows not verified yet; Docker Engine and macOS untested.
3. **CI** (task 003): `.github/workflows/ci.yml` runs `checks` (yamllint, `esphome config`, pytest) and
   `compile (pinned|minimum)` in the devcontainer on every PR and push to `master`; `canary.yml` builds the latest
   ESPHome weekly and reports through one `canary-failure` issue; Dependabot covers actions, uv and devcontainer
   images. The `master` ruleset lives in `.github/rulesets/master.json` (required checks `checks`,
   `compile (pinned)`, `compile (minimum)`; squash-only PRs) and is applied by a repo admin with `gh api`. The `config` matrix over module combinations arrived with task 004 (`tests/test_config_matrix.py`).
4. **Modular layout**, two tasks. Task 004: `hardware/` board profile, `packages/core/`, secrets as entry-file
   substitutions, config matrix. Task 005: `bed.yaml` with `vars`, `hardware/sim.yaml`, more matrix rows.
5. **Lightweight end-user path:** ESPHome Device Builder (HA add-on or the `ghcr.io/esphome/esphome`
   container) + remote packages from this repo + first flash via web.esphome.io, then OTA; no devcontainer
   needed. Depends on stage 4.
6. **`garden_zones` component** (fork of `sprinkler`, §4): patched open queue, groups with `max_parallel`
   via lanes, watchdog, optional soil-moisture skip.
7. **`gp_*` layer** on top of `garden_zones`, screens switched to it.
8. **Screens on the design system:** Greenhouse (proposal), Home, navigation; bed layout variants; UI language
   at build time.
9. **Time without HA:** SNTP fallback (and RTC if needed) so schedules work offline.
10. **Schedules** (WATER tab), **bed heating** (thermostats + heating screens), alerts.
11. **Host + SDL** test harness and screenshot checks.

### 9.1 Backlog (ideas, separate tasks once the base is ready)
Optional modules; most can be built and tested without the physical sensors (`hardware/sim.yaml`):
- **Watering history** per zone, on screen and in HA (wanted first).
- Barrel water level sensor: don't water when empty, alert.
- Pump dry-run protection (flow or pressure sensor).
- Flow meter: litres per zone, watering by volume.
- Global run-time multiplier (e.g. ×1.5 in hot weather).
- Cycle and soak (water in several passes).
- Rain delay (sensor or HA command; lawn).
- Dynamic lanes for `max_parallel` between 1 and all.
- Heating: night-tariff window and schedule modes.

## 10. Open questions
**Screens** (decide with the design work, roadmap stage 8)
1. Which drafts from the canvas to keep?
2. Bed layouts: fixed variants or generated YAML?

### 10.1 Decided (2026-10-01)
- **Board:** board profiles, ready-made (T-Relay-S3-like) and self-assembled builds (§2.2).
- **Zones:** configurable N zones in groups by water source; the author has 3 greenhouse beds (gravity barrel,
  all at once) and a planned lawn with several zones (pump, one at a time) (§4).
- **Engine:** fork of `sprinkler` as `garden_zones`, no stock-`sprinkler` MVP; parallelism via lanes (§4).
- **Soil moisture:** optional per zone, skips the run when wet (§4).
- **Water-source sensors and extra watering features:** backlog (§9.1).
- **Schedules:** on the device, HA optional (§4).
- **Heating:** one cable per bed, any temperature sensor, frost protection first; safety documented as
  recommendations (§4).
- **UI language:** chosen at build time (§8).
- **Minimum ESPHome:** 2026.6.3, the technical floor found by scanning `esphome config` (task 003, §6).

## 11. Sources
- ESPHome `esphome/components/sprinkler/` (`dev`, 2026-10-01) and its commit history.
- https://esphome.io/components/sprinkler/
- https://esphome.io/components/external_components/
- https://esphome.io/components/host/
- https://esphome.io/components/display/sdl/
- https://docs.wokwi.com/wokwi-ci/github-actions
- https://containers.dev/implementors/spec/
- https://docs.astral.sh/uv/guides/integration/docker/
- https://docs.astral.sh/uv/guides/integration/dependabot/
- https://github.com/devcontainers/ci/blob/main/docs/github-action.md
- https://github.com/actions/cache
- https://docs.github.com/en/code-security/dependabot/working-with-dependabot/dependabot-options-reference
- https://github.com/dependabot/dependabot-core/issues/5103
- https://code.claude.com/docs/en/devcontainer
- https://github.com/microsoft/wslg/blob/main/samples/container/Containers.md
- https://docs.podman.io/en/latest/markdown/podman-run.1.html
