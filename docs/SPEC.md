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
  skipped. Today (task 005) a bed can have such a sensor as a reporting-only `sensor` (`packages/greenhouse/
  bed_soil.yaml`); skipping a run when wet comes with `garden_zones` (stage 7).
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
- A bed is one `packages/greenhouse/bed.yaml` (task 005) included N times through `!include` with `vars` (`bed`, `bed_name`, `relay`; an optional `bed_soil.yaml` adds a soil sensor). Inside:
  valve, sensors, heating thermostat, a `garden_zone:` entry for the component. For this the component uses
  `MULTI_CONF`, with a shared `garden_zones:` hub that owns the queue and groups.
  **Verify with a first test build** that lists from different packages merge as expected.
- **Screens:** LVGL YAML has no loops. Bed layouts as fixed variants (1 / 2 / 3 / 6 beds, see design drafts
  D03–D05) or generated YAML — **open**.
- Hardware is a separate package: `hardware/<board>.yaml` with real pins (also `esp32:` and the display/touch
  orientation and calibration) and `hardware/sim.yaml` for tests (template switches and sensors instead of GPIO).
  Exists after task 004: `hardware/esp32-s3-devkitc1-breadboard.yaml` and `packages/core/` (network, time); task 006
  splits the network package into `core/api.yaml`, `core/ota.yaml` and `core/network.yaml` (Wi-Fi + captive portal)
  and adds `core/time_host.yaml` (PC clock, same id `ha_time`) and `packages/display_sdl.yaml` (SDL window + mouse
  touch, same ids as `display_touch.yaml`).
  Task 005 adds (done):
  - `packages/greenhouse/bed.yaml`, included once per bed with `vars` (`bed`, `bed_name`, `relay`); it adds one
    valve to the stock `gh_sprinkler` with `!extend` (lists in an extended item are concatenated in package order,
    so the order of the bed blocks is the valve order). At least 2 beds with the stock sprinkler (it forbids the
    controller switches and the enable switch with one valve); a 1-bed greenhouse comes with `garden_zones`.
  - optional `packages/greenhouse/bed_soil.yaml` per bed (reporting soil moisture sensor; vars `bed`, `bed_name`,
    `adc_pin`, `cal_dry_v`, `cal_wet_v`); one ADC pin serves one probe.
  - the board profile holds the raw relay drivers as internal switches `board_relay_N` (the same ids in every
    profile) and names analog inputs `adc_N_pin` (ADC1 only with Wi-Fi); features never use GPIO numbers.
  - `hardware/sim.yaml` (`host:` + template relays that log every state change) is the board profile of the PC
    emulator (task 006, `garden-pilot-sim.yaml`, §7); it cannot be combined with `core/network.yaml` (Wi-Fi),
    `core/ota.yaml`, `display_touch.yaml` or the DHT/ADC sensors (the host platform has none of them).

Target layout:
```
garden-pilot.yaml          # device entry file, modules commented out
garden-pilot-sim.yaml      # PC emulator entry file (host + SDL), same packages
hardware/                  # esp32-<board>.yaml (pins, relay drivers), sim.yaml
packages/
  core/                    # api, ota, network (Wi-Fi), time, time_host
  display_touch.yaml, display_sdl.yaml   # device display + touch; emulator window + mouse
  sim/                     # emulator only: simulated sensors, auto drift, SIM board page
  lvgl/                    # pages
  greenhouse/bed.yaml, bed_soil.yaml, ...   # lawn.yaml, heating.yaml, ...
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
   the real entry file) runs in CI job `checks` via `script/test`; 2 beds, a bed with its own soil sensor and the sim board were added by task 005; task 006 adds rows for the emulator entry file `garden-pilot-sim.yaml` (the two SDL rows need `sdl2-config`; `GP_REQUIRE_SDL=1` in CI makes a missing one a failure).
2. `esphome compile` for ESP32 and for the host emulator build `garden-pilot-sim.yaml` (CI jobs `compile (pinned)` and `compile (minimum)`, weekly canary for the device build).
3. Unit tests of the `garden_zones` core (GoogleTest or Catch2).
4. **`host` platform (task 006, done):** `script/sim` builds and runs `garden-pilot-sim.yaml` on Linux: the real LVGL
   pages and irrigation packages, template relays from `hardware/sim.yaml` (state changes logged as
   `SIM relay_N ON/OFF`), the clock from the PC. It works fully without Home Assistant; HA can add it by IP (port
   6053, public dummy key `sim_api_encryption_key`, a separate device "GardenPilot Sim"; no mDNS on host, no OTA).
   The API has `reboot_timeout: 0s` there (the default would end the program after 15 min without a client).
   `web_server` is not available on the host platform (`cv.only_on` ESP32/ESP8266/BK72XX/LN882X/RP2/RTL87XX), and no
   third-party shim is used: manual control of simulated values goes through the native API (`script/sim-ctl`) and
   an on-screen "SIM board" page, both in task 007 (implemented, below). `on_time_sync` does not fire on host; the Home clock refreshes
   from its 30 s interval. The host build is compiled in CI (`compile (pinned|minimum)`, same jobs as the device).
   The sim entry file needs SDL2 dev files even for `esphome config` (the devcontainer image has them; tests skip
   the SDL rows without `sdl2-config` unless `GP_REQUIRE_SDL=1`, which CI sets).
   **Simulated sensors and SIM board (task 007, implemented; PC check and CI pending):** `packages/sim/` (never included by the device): template
   numbers `Sim air temperature` / `Sim air humidity` / `Sim soil moisture` / per-bed `... sim soil moisture` are the
   source of truth (`restore_value: false`, defaults 22 C / 60 % / 50 %); template sensors with the device ids and
   names (`gh_air_temperature`, `gh_air_humidity`, `gh_soil_moisture_pct`, `gh_bedN_soil_moisture`) read them. The
   "Sim auto drift" switch (default OFF) dries soil 1 % per 60 s and raises it 1 % per 10 s while the relevant relay
   runs. The sim-only `SIM` button (top layer) opens a page with relay indicators, one slider per value and the drift
   switch. `script/sim-ctl` (`aioesphomeapi`, no new dependency) lists, reads and sets entities of the running
   emulator; it is unit-tested with a fake client. The device config is unchanged (normalized `esphome config` diff).
5. **`display: platform: sdl`:** LVGL screens in a window, mouse instead of touch (done, `display_sdl.yaml`); in CI
   `headless: true` (2026.9.1 and later only) and BMP screenshots compared with references (stage 12).
6. Integration scenarios through `aioesphomeapi` against the host build (stage 12; task 007 only unit-tests `sim-ctl` with a fake client, a real scenario needs a headless host build in CI).
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
   substitutions, config matrix. Task 005 (done): `bed.yaml` with `vars`, optional `bed_soil.yaml`, board relays,
   `hardware/sim.yaml`, more matrix rows. Follow-up: page/status poller for other bed counts (stage 9).
5. **Lightweight end-user path:** ESPHome Device Builder (HA add-on or the `ghcr.io/esphome/esphome`
   container) + remote packages from this repo + first flash via web.esphome.io, then OTA; no devcontainer
   needed. Depends on stage 4.
6. **PC emulator (host + SDL)**, two tasks. Task 006 (part 1): `garden-pilot-sim.yaml` + `script/sim`, split of the
   network package, SDL display/touch package, PC clock, runs without Home Assistant, optional HA by IP, host build
   compiled in CI. Task 007 (part 2): simulated sensors with settable values, manual control without HA (a sim-only
   "SIM board" LVGL page and `script/sim-ctl` over the native API) and the "Sim auto drift" switch (default OFF; when
   ON soil slowly dries and rises while that bed's relay runs). Both parts implemented (done once the PR merges: CI and the PC check are still open).
7. **`garden_zones` component** (fork of `sprinkler`, §4): patched open queue, groups with `max_parallel`
   via lanes, watchdog, optional soil-moisture skip.
8. **`gp_*` layer** on top of `garden_zones`, screens switched to it.
9. **Screens on the design system:** Greenhouse (proposal), Home, navigation; bed layout variants; UI language
   at build time.
10. **Time without HA:** SNTP fallback (and RTC if needed) so schedules work offline.
11. **Schedules** (WATER tab), **bed heating** (thermostats + heating screens), alerts.
12. **Screenshot checks in CI:** headless SDL screenshots, BMP comparison against references and `aioesphomeapi`
    scenarios against the host build.

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
**Screens** (decide with the design work, roadmap stage 9)
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
