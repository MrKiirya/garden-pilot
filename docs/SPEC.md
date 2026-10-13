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
  Task 023 adds `hardware/lilygo-t-relay-s3.yaml` (config-checked only, not run on a real board): ESP32-S3-WROOM-1U
  N16R8, 6 relays (10 A) behind an HT74HC595 (data GPIO7, clock GPIO5, latch GPIO6, nOE GPIO4) and its 6-relay
  expansion on the same chain (`sn74hc595`, `sr_count: 2`: relays 1-6 = outputs 0-5, relays 7-12 = outputs 8-13 of the
  chain, to verify on the board); the display board sits on the 14-pin TFT header H1 (CS GPIO8, RST GPIO3, DC GPIO46,
  MOSI GPIO11, CLK GPIO13, MISO GPIO12, BL GPIO9, touch CS GPIO10, IRQ GPIO14; source: the vendor schematic
  `T-Relay6-ESP32S3-Rev1.1.pdf`). RTC (PCF8563, I2C GPIO16/17, INT GPIO18) and the DS18B20 spot (GPIO21) are not used yet.
- **Self-assembled ("breadboard") build:** a generic ESP32-S3 dev board + ILI9341/XPT2046 + a relay module,
  as in §2.1. Since task 023 the profile has up to 12 relay outputs on safe pins (the author's 12-LED indicator
  board stands in for the relays); the wiring table is in the profile header.
- Active-low relay modules are not supported (no `inverted:`): they energise while the ESP32 resets. Use a
  high-level-trigger module.

The project must not depend on one specific board.

## 3. The ESPHome `sprinkler` component: limits that shape the design
Checked against `esphome/components/sprinkler/` on the `dev` branch, 2026-10-01:
- **One valve at a time** per controller. A second `valve_op` exists only for overlap during transitions.
  Parallel watering needs several `sprinkler:` blocks, and a valve belongs to exactly one controller.
  At a run-to-run transition the stock code starts the next valve before it switches the finished one off, so both are
  on for up to one main-loop pass. Accepted by design (human decision 2026-10-10): the pump must never run against
  closed valves; a deliberate longer overlap is the stock `valve_overlap` option.
- **Closed queue.** `queued_valves_` is `protected`. Public API: `queued_valve()` (next), `total_queue_time()`,
  `clear_queued_valves()`. No list, no "is zone N queued", no removal of one zone. Duplicates are allowed.
  The queue does not survive a reboot.
- **`start_single_valve()` turns off `auto_advance` and `queue_enable`**: a manual RUN breaks the queue.
  The current greenhouse page uses it for its RUN buttons.
- Queued zones run **even if their enable switch is off**.
- The `Sprinkler` class is `final` (since July 2026): it cannot be subclassed.
- The device and the emulator no longer use the stock `sprinkler` (task 014); the limits above are kept for reference
  (the forked engine works around them, see §4).
- Forked into `components/garden_zones/` from tag 2026.9.1 (task 008): open persistent queue, manual run that keeps
  the queue, disabled zones skipped; see `components/garden_zones/PATCHES.md`.
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
      - {id: lawn, max_parallel: 2, pump_switch_id: lawn_pump}   # lanes by round-robin: zone i -> lane i mod 2
    zones:                       # inline zones; or one `garden_zone:` list item per package (see §5)
      - {group: greenhouse, valve_switch: Bed 1, valve_switch_id: valve_bed1, run_duration: 10min}
  ```
  Verified (task 012): all lanes of a block are registered with each other (stock `add_controller`), so a pump
  shared by lanes stays on while any lane still needs it; a pump belongs to one group only for now.
- **Safety (task 013, groups form):** a watchdog per group, on by default (a limit is disabled only explicitly with `never`, with a WARN at boot). It watches the real state of every
  raw valve switch and the pump switch, independent of the sprinkler state machine: a valve on longer than
  `max_on_time` (default 60 min, per group or zone, any duration or `never`), a pump on longer than `pump_max_on_time` (default 2 h,
  a watering session, any duration or `never`) or on with no open valve longer than `pump_idle_timeout` (default 10 s, any duration or `never`) is
  forced off, logged at ERROR and latched (zone, or the whole group for a pump trip) until
  `garden_zones.reset_watchdog` or a reboot. Raw actuators must be `ALWAYS_OFF` / `RESTORE_DEFAULT_OFF`; a zone's
  longest configured run must fit under its limit (validated at config time). The 008 list form has no watchdog.
- **Soil moisture (optional per zone, task 013):** any ESPHome sensor via `soil_moisture:` (`sensor_id`, `skip_above`,
  `max_age` 30 min, `when_unavailable: water | skip`, default `water`); checked when the zone's turn comes in a queue
  or a cycle, skipped when wetter (queue and cycle only; manual runs ignore it). Before `garden_zones` is on the
  device (014), a bed's sensor is reporting-only (task 005, `packages/greenhouse/bed_soil.yaml`).
- **History** of runs per zone (wanted; see the backlog in §9).

**Second group: lawn (task 024).** `packages/lawn/` adds the pump group `lawn_zones` (`max_parallel: 1`, pump from the
`pump_relay` var) next to the greenhouse group `gh_zones`, with its own gp group `gp_lawn` (key `lawn`). Lawn and flower
zones share the pump, one include per zone. Groups run independently: the lawn and the greenhouse can water at the same
time, there is no cross-group interlock. `pump_max_on_time` bounds a whole session: with one zone at a time the pump
stays on through a queue or full cycle, so (zones) x `lawn_zone_run_max` must fit under it (a repo test checks the entry
files). Lawn schedules will be a second `garden_schedule` hub later.

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

**Schedules** live on the device and run without Home Assistant or Wi-Fi once the clock was set (HA time or SNTP);
HA is optional (it can edit and trigger them). Task 019 (`components/garden_schedule/`, MIT, engine-agnostic): each
group has 2 slots by default (max 8). A slot = start time, 7 day switches, a zone list ("all" or bed numbers) and one
run-time multiplier (10-200 % of each zone's own run duration). A due slot queues its zones through `gp.enqueue_zones`
and `gp.start_queue`, so the watchdog lockout, disabled zones and service mode apply unchanged. Rules: one run per slot
per local day (DST safe); a slot missed by a power cut or a late clock still runs when the device is back within the
catch-up window (60 min by default, 0 = never), later it is logged as missed; the "done" mark is per zone, written to
flash when the zone's queue run completes, and a restart inside the window runs only the zones that did not complete; a user STOP (the STOP button, Home Assistant, turning the "Greenhouse irrigation" main switch off, or entering service mode) settles
the slots (their pending zones are dropped, "stopped", the queue is cleared, nothing resumes after a restart); a slot
that fires while a manual full cycle runs waits: the cycle runs to its end, then the slot's zones run;
master switch "Greenhouse schedules" (default ON), every slot defaults OFF. Entities: [component README](../components/garden_schedule/README.md).

### 4.1 The `gp_*` layer
Screens, schedules, the valve test and Home Assistant never call `garden_zones` directly, only the `gp` contract
(task 018): a per-zone read model addressed by zone index, a group summary (running, queue, now/next, revision), an
alert table and a fixed set of `gp.*` actions, implemented by the C++ component `components/gp/` (MIT) over an engine
adapter (`components/garden_zones/gp_engine.h`, GPLv3). Full contract, names and the polling rule:
[components/gp/README.md](../components/gp/README.md).

- Home Assistant gets ONE generic action set for all groups (`gp_run_zone` etc. with `group` and a 1-based `zone`), one
  switch per zone from the gp layer ("Greenhouse bed N"; the engine's zone switches are internal), a "Greenhouse status"
  and an "Alert" text sensor; settings entities have `entity_category: config`. The same actions address the lawn with
  `group: lawn`; its zone switches are named after the zone ("Lawn", "Flowers").
- The last watering of each zone and the last 100 runs are persisted to flash after each run; the full history stays
  in Home Assistant.
- "Home Assistant disconnected" is a quiet header icon, not an alert.
- LVGL reads `gp` only from pollers.
- Not done yet (follow-ups): soil reading in the model and the soil-sensor alert, service-mode inhibit for HA zone
  switches, air-sensor alerts.

### 4.1a Time sources
The clock id `ha_time` is the only one features use. `packages/core/time.yaml` (`time: homeassistant`) and
`packages/core/time_sntp.yaml` (`time: sntp`, id `sntp_time`, task 016) both write the same system clock, so the
device has valid time with Home Assistant offline as long as Wi-Fi reaches an NTP server. SNTP is on by default
(comment out `core_time_sntp` for HA-only time); servers are the `sntp_server_1..3` substitutions, default
`0/1/2.pool.ntp.org`. An SNTP sync does not fire `ha_time.on_time_sync`, so readers poll (the Home clock lags at
most 30 s). **Timezone:** the `timezone` substitution
(default `UTC`, an IANA name such as `Europe/Berlin` or a POSIX string) is applied as `timezone: ${timezone}` to both
`ha_time` and `sntp_time`, so the zone is known after a reboot without Home Assistant. Because a timezone is set,
Home Assistant no longer overrides the zone: users must set their own zone in the entry file (`substitutions:`),
otherwise the clock and the schedule start times (local day, §4 Schedules) run in UTC. The default carries no personal zone. The emulator
uses `time: host` without `timezone` (it keeps the PC's zone detected at build time; no `sntp` on `host`). An RTC chip for "no Wi-Fi at all" is a follow-up.

### 4.2 Loading our own component
```yaml
external_components:
  - source: components            # development and cloned repos
    components: [garden_zones, garden_zone]
  # users without a clone pin a tag, never a branch:
  # - source: github://MrKiirya/garden-pilot@v1.0
  #   components: [garden_zones, garden_zone]
```
Task 023: the literal `source: components` is `source: ${gp_root}/components` in every package that has a local source
(`irrigation.yaml`, `irrigation_pump.yaml`, `schedule.yaml`, `core/gp.yaml`), and the screensaver font file is
`${gp_root}/packages/lvgl/fonts/...`. Each of those packages defines `gp_root: "."`; an entry file in a subdirectory
(`examples/*.yaml`) sets `gp_root: ".."`. Reason (ESPHome 2026.9.1): `!include` resolves against the including file,
but `external_components` local sources and font files resolve against the directory of the main config file, and
`!secret` reads `secrets.yaml` next to the file that contains the tag. The substitution is expanded before
`external_components` is loaded (verified by the example config rows). A remote-package user replaces the source by a
git source and the font by a URL or a local copy (roadmap stage 13).

## 5. Modularity
- Many small YAML files, not one big file.
- The entry file lists modules, most of them commented out: uncomment a line to get a bed, the lawn, heating.
- A bed is one `packages/greenhouse/bed.yaml` (task 005) included N times through `!include` with `vars` (`bed`, `bed_name`, `relay`; an optional `bed_soil.yaml` adds a soil sensor). Inside:
  valve, sensors, heating thermostat, a `garden_zone:` entry for the component. For this the component uses
  `MULTI_CONF`, with a shared `garden_zones:` hub that owns the queue and groups.
  Verified (task 012): lists from different packages concatenate in package order, so write `garden_zone:` as a list
  item (`- group: ...`); two dict-form entries merge into one zone.
- **Screens:** LVGL YAML has no loops. Bed layouts as fixed variants (1 / 2 / 3 / 6 beds, see design drafts
  D03–D05) or generated YAML — **open**.
- Hardware is a separate package: `hardware/<board>.yaml` with real pins (also `esp32:` and the display/touch
  orientation and calibration) and `hardware/sim.yaml` for tests (template switches and sensors instead of GPIO).
  Exists after task 004: `hardware/esp32-s3-devkitc1-breadboard.yaml` and `packages/core/` (network, time); task 006
  splits the network package into `core/api.yaml`, `core/ota.yaml` and `core/network.yaml` (Wi-Fi + captive portal)
  and adds `core/time_host.yaml` (PC clock, same id `ha_time`) and `packages/display_sdl.yaml` (SDL window + mouse
  touch, same ids as `display_touch.yaml`).
  Task 005 adds (done):
  - `packages/greenhouse/bed.yaml`, included once per bed with `vars` (`bed`, `bed_name`, `relay`); since task 014 it is
    one `garden_zone:` list item of the group `gh_zones` declared in `packages/greenhouse/irrigation.yaml` (the order
    of the bed blocks is the zone order). One bed is enough (headless; the greenhouse page still expects beds 1-3).
    The group has the substitutions `gh_max_parallel` (default `"1"`: one valve at a time; `"all"` = every bed at once),
    `gh_max_on_time` (watchdog, default `60min`, `never` disables it), `gh_bed_run_max` (run-duration number max, minutes,
    default `55`) and `gh_bed_run_initial` (default `5`); `gh_bed_run_max * 60 s + 2 s <= gh_max_on_time` is enforced.
  - since task 018 each bed also adds a `gp_zone:` list item (the Home Assistant switch of the gp layer); `packages/core/gp.yaml`, `gp_api.yaml` and `packages/greenhouse/gp.yaml` come after the last bed.
  - optional `packages/greenhouse/bed_soil.yaml` per bed (reporting soil moisture sensor; vars `bed`, `bed_name`,
    `adc_pin`, `cal_dry_v`, `cal_wet_v`); one ADC pin serves one probe.
  - the board profile holds the raw relay drivers as internal switches `board_relay_N` (contiguous from 1, see task 023
    below) and names analog inputs `adc_N_pin` (ADC1 only with Wi-Fi); features never use GPIO numbers.
  - task 023: **per-entry pins and relays.** Profiles no longer define the same `board_relay_N` ids: each has contiguous
    `board_relay_1..N` (N >= 3: breadboard 12, LilyGO 12, sim 3). Every entry file (`garden-pilot.yaml`,
    `examples/*.yaml`) must get every `${..._pin}` its packages and vars use, and every relay it references (bed
    `relay`, `gh_pump_relay`), from ITS profile; a profile may define only pins that something uses.
  - task 023: **variants.** `packages/greenhouse/irrigation_pump.yaml` is `irrigation.yaml` plus `pump_switch_id:
    board_relay_${gh_pump_relay}`, `pump_max_on_time` (`gh_pump_max_on_time`, default `2h`) and `pump_idle_timeout`
    (`gh_pump_idle_timeout`, default `10s`); it replaces `irrigation.yaml` under the same package key (a second package
    cannot add keys to a `garden_zones: groups:` item). `packages/greenhouse/bed_soil_skip.yaml` is `bed.yaml` plus the
    `soil_moisture:` block (var `skip_above`; used together with that bed's `bed_soil.yaml`), because a second package
    cannot add `soil_moisture:` to an existing `garden_zone:` list item. Tests keep both files equal to their originals
    apart from those keys.
  - task 023: **`examples/`**: four complete entry files (`minimal-1-bed.yaml`, `beds-with-pump.yaml`,
    `soil-sensors.yaml`, `relay-module-8ch.yaml`, device names `gp-minimal`, `gp-beds-pump`, `gp-soil-sensors`,
    `gp-relay-8ch`), all with display + touch, `../` includes, `gp_root: ".."` and `examples/secrets.yaml`; see
    `examples/README.md`.
  - `hardware/sim.yaml` (`host:` + template relays that log every state change) is the board profile of the PC
    emulator (task 006, `garden-pilot-sim.yaml`, §7); it cannot be combined with `core/network.yaml` (Wi-Fi),
    `core/ota.yaml`, `display_touch.yaml` or the DHT/ADC sensors (the host platform has none of them).

Target layout:
```
garden-pilot.yaml          # device entry file, modules commented out
garden-pilot-sim.yaml      # PC emulator entry file (host + SDL), same packages
hardware/                  # esp32-<board>.yaml, lilygo-t-relay-s3.yaml (pins, relay drivers), sim.yaml
examples/                  # five complete device configs (`../` includes, gp_root: "..")
packages/
  core/                    # api, ota, network (Wi-Fi), time, time_sntp, time_host
  display_touch.yaml, display_sdl.yaml   # device display + touch; emulator window + mouse
  sim/                     # emulator only: simulated sensors, auto drift, SIM board page
  lvgl/                    # pages
  greenhouse/bed.yaml, bed_soil.yaml, ...
  lawn/irrigation.yaml, zone.yaml, gp.yaml  # pump group `lawn_zones` (var `pump_relay`), one zone per include
                                            # (vars `zone`, `zone_name`, `relay`), gp group `gp_lawn`; heating.yaml, ... later
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
Speed (task 022): `script/test` runs pytest in parallel (`pytest-xdist`, `-n ${GP_PYTEST_WORKERS:-4} --dist loadgroup`, 4 workers by default so the machine stays usable; `GP_PYTEST_WORKERS=0` = serial, `auto` = every CPU). Every host build and its tests form one xdist group (`HOST_GROUPS` in `tests/conftest.py`), so no two workers share a build directory. The schedule host scenario starts its program at a chosen second of the minute through `libfaketime` (shifted wall clock, real monotonic clock, offsets only grow), which removes the random minute-boundary waits; without the library it runs on the real clock, and `GP_REQUIRE_FAKETIME=1` (CI) turns a missing library into a failure.
1. `esphome config` for every module combination: the matrix in `tests/test_config_matrix.py` (variants built from
   the real entry file) runs in CI job `checks` via `script/test`; 2 beds, a bed with its own soil sensor and the sim board were added by task 005; task 006 adds rows for the emulator entry file `garden-pilot-sim.yaml` (the two SDL rows need `sdl2-config`; `GP_REQUIRE_SDL=1` in CI makes a missing one a failure).
1a. **Examples (task 023):** `tests/test_examples.py` checks the shape of `examples/*.yaml` (paths, secrets, package order) and runs `esphome config` (pinned version only) on the four examples, on example 1 with the LilyGO profile swapped in, and through `script/config examples/...` (which stages the config at its relative path with the example secrets next to it); no new compile or host build. `script/compile examples/<file>.yaml` works the same way.
2. `esphome compile` for ESP32 and for the host emulator build `garden-pilot-sim.yaml` (CI jobs `compile (pinned)` and `compile (minimum)`, weekly canary for the device build).
3. Unit tests of the `garden_zones` core (a minimal header-only harness, `script/test-cpp`).
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
   **Watchdog fault injection (task 014):** the watchdog never trips in normal use, so the emulator has a sim-only switch
   "Sim rogue relay 1" (`packages/sim/fault.yaml`) that turns `board_relay_1` on outside the engine, and
   `GP_SIM_SUBST="key=value ..."` (`script/sim`, `script/sim-ui start` inherits it) overrides substitutions for the run,
   e.g. `gh_max_on_time=125s gh_bed_run_max=2 gh_bed_run_initial=1` for a short limit.
5. **`display: platform: sdl`:** LVGL screens in a window, mouse instead of touch (done, `display_sdl.yaml`); headless screenshots and taps
   exist (task 015: `script/sim-ui` on a private Xvfb, X-level grab + xdotool press/move/release, works on every supported
   ESPHome version; CI job `sim-ui`, not required, uploads the PNGs). SDL `headless: true` and `snapshot` (BMP) need
   2026.9.0+ and `headless` has no touch, so they stay a stage 12 option for reference images, not a dependency.
6. Integration scenarios through `aioesphomeapi` against the host build (stage 12; screenshots and taps exist since task 015, reference-image comparison and scenarios remain; task 007 only unit-tests `sim-ctl` with a fake client, a real scenario needs a headless host build in CI).
7. Optional: Wokwi (ESP32 + ILI9341 emulation, `wokwi-cli` in GitHub Actions).

## 8. Design
- Rules and tokens: `design/README.md`, `design/tokens.json`, icons in `design/icons/`.
- The live design lives in claude.ai artifacts (author's account): the design system and the screens canvas
  (pages "Screens": Home / Greenhouse / Lawn, and "Drafts": D01–D25). The repo keeps a snapshot of what the
  firmware depends on; token changes are synced into the repo by PR.
- **UI language** is chosen at build time (a substitution in the entry file, `en` / `ru`): only one language
  and its glyphs are baked into flash.
- **Boot screen** (`boot_page`, D17): the first page; "Connecting to Wi-Fi..." with a spinner (no fake progress), valves
  stay closed. It shows Home on Wi-Fi connect (`wifi: on_connect`, device only) or after `boot_offline_timeout`
  (30 s; 3 s in the emulator, which has no Wi-Fi). It never touches an actuator. Home Assistant is not awaited.
- **Valve test and service mode** (`valve_test_page`, D18; Setup > SERVICE): TEST opens one greenhouse valve (beds 1-3)
  for at most `valve_test_max_time` (10 s hard limit counted from the tap: `run_duration` plus an independent guard script; the lane opens the valve ~2 s after the tap (switching delay, unchanged by task 014), so it is open ~8 s and the countdown stops near 2 s; since task 014 TEST runs `garden_zones.run_zone` on the group `gh_zones`, a bed locked by the watchdog is refused and its row stays "closed"); every start
  shuts down the previous valve first. While the page is open `gp_service_mode` is on: the queue is cleared and any
  run not started by the test (Home Assistant, queue) is shut down within 1 s with a WARN log. Service mode ends by
  EXIT SERVICE, by leaving the page, after 10 minutes without a test, or by a reboot (not restored). Blocking Home
  Assistant before it starts a valve needs the `gp_*` layer (stage 8).
- **Screensaver** (D23, `packages/lvgl/screensaver.yaml`): a top-layer overlay, not a page, shown after
  `screensaver_timeout` (5 min; 1 min in the emulator) without input: 40 px clock (token `clock`, custom font
  `gp_font_clock` baked from the vendored Montserrat Bold with only `0123456789:-`), a status line ("24C - soil 58%"),
  "Bed N" with a green dot while a bed runs, "Touch to wake". Any touch hides it and is swallowed by the overlay. It never
  shows on the boot screen, over a confirm dialog or in service mode. No backlight dimming yet (needs a backlight pin
  in the board profile) and no "next run" part (no schedules).
- **Screens: slots and widgets** (decided 2026-10-10, §10.2; built on the stage 8 `gp_*` layer): the bed page is up to 6 slots of
  one card template (extra slots hidden at boot, data by zone index via `gp_*`; 1-3 beds full cards, 4-6 compact
  in a grid). Home is a stack of widgets (308x172, gap 4, heights 26/40/44/76) filled by priority with a C++
  fit helper; available widgets come from the enabled packages, their order is set in SETUP and stored on the
  device.
- Built today: `home_page`, `setup_page` (draft D10), `network_page` (D11), `gh_history_page` (task 027: reached from
  a HISTORY button in the Greenhouse header, 6 rows per page with PREV / NEXT and BACK, no scrolling) and the confirm
  dialog (D14, top layer, `gp_confirm`) follow the tokens. `greenhouse_page`, `lawn_page` and `touch_test_page` still use the default
  LVGL theme. Bottom nav: DASH → home, ZONES → greenhouse, WATER → lawn, SETUP → setup (its DISPLAY tile opens the
- Built today: `home_page`, `setup_page` (draft D10), `network_page` (D11) and the confirm dialog (D14, top
  layer, `gp_confirm`) follow the tokens, and so does `schedules_page` (WATER tab, task 026: master row, three slot rows per page
  with PREV / NEXT, view only). `greenhouse_page`, `lawn_page` and `touch_test_page` still use the default
  LVGL theme. Bottom nav: DASH → home, ZONES → greenhouse, WATER → schedules (`lawn_page` stays included but has no entry point until the lawn task or the Home widgets give it one), SETUP → setup (its DISPLAY tile opens the
- Built today: `home_page`, `setup_page` (draft D10), `network_page` (D11) and the confirm dialog (D14, top
  layer, `gp_confirm`) follow the tokens. `greenhouse_page` (bed cards, task 025) and its bed detail page `gh_bed_detail_page` follow the tokens too;
  `lawn_page` and `touch_test_page` still use the default LVGL theme. Bottom nav: DASH → home, ZONES → greenhouse, WATER → lawn, SETUP → setup (its DISPLAY tile opens the
  touch test, SERVICE the valve test; CYCLE / SENSORS are "Soon"). STOP on the Greenhouse page and RESTART on the Network page ask
  touch test, SERVICE the valve test; CYCLE / SENSORS are "Soon"). The Lawn page now has backing data through
  `gp_lawn` (task 024) but is not wired to it. STOP on the Greenhouse page and RESTART on the Network page ask
  through the confirm dialog (30 s without an answer = cancel). Built-in Montserrat fonts are ASCII + LVGL symbols
  only, so UI texts are ASCII (`-`, `...`). Version, uptime, Wi-Fi and the restart button are `internal: true`.
- The Home "NEXT" label shows the next scheduled run (`06:00` today, `Tue 06:00`, `--:--`), written by the Schedules
  page package from the schedule hub (task 026). The now/next + timeline widget is a stage 9 screen task.
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
   via lanes, watchdog, optional soil-moisture skip. Task 008: fork + open/persistent queue, manual run keeps the
   queue, disabled zones skipped; task 012: `groups:` / `garden_zone:` config with generated lanes, shared pump and
   group actions (in a host test build only); task 013: watchdog for valves and the pump and the per-zone soil-moisture
   skip (host test build only); task 014: the device and the emulator run the greenhouse on `garden_zones` (group `gh_zones`,
   group entities with the old names plus "Greenhouse watchdog" and its reset button, watchdog 60 min by default).
8. **`gp_*` layer** on top of `garden_zones`, screens switched to it (task 018: read model, alerts, actions, HA surface, persisted last watering and history; soil reading follows).
9. **Screens on the design system:** Greenhouse (proposal), Home, navigation; bed layout variants; UI language
   at build time. On top of the stage 8 `gp_*` layer: bed card slots and Home widgets (§8, decided in §10.2).
10. **Time without HA:** SNTP fallback (done, task 016, `packages/core/time_sntp.yaml`, §4.1a); RTC chip if needed
    (follow-up) so schedules work offline.
11. **Schedules:** engine, entities, HA editing and next-run data on the device are done (task 019); the WATER tab view is done (task 026), its time editor
    and the now/next + day timeline widget are stage 9 screen tasks. **Bed heating** (thermostats + heating screens)
    with the heating widget, alerts.
12. **Screenshot checks in CI:** headless SDL screenshots, BMP comparison against references and `aioesphomeapi`
    scenarios against the host build. Screenshots and taps under Xvfb exist (task 015, `script/sim-ui`, CI job
    `sim-ui`); remaining: reference-image comparison and `aioesphomeapi` scenarios.

13. **Examples and remote packages.** Task 023 (this stage's first part): `examples/` (four complete device configs),
    the 12-relay breadboard profile, the LilyGO T-Relay-S3 profile, `gp_root`, the pump and soil-skip package variants.
    Task 024 (done): `packages/lawn/` (one `garden_zones` group with a pump, one zone at a time, lawn and flowers share
    it) and the author's `examples/my-garden.yaml` (LilyGO T-Relay-S3, 3 greenhouse beds on a barrel with limits raised
    for a ~3 h run, 2 lawn zones on a pump). Follow-ups: lawn schedules (a second `garden_schedule` hub; needs
    `schedule_slot.yaml` generalised to a group prefix), the Lawn page / Home card / valve-test rows reading `gp_lawn`,
    service mode for all groups, a per-group zone name prefix in `gp` ("B1" is hard-coded), the lawn in the emulator.
    Then "remote packages + private config repo": packages usable as ESPHome remote packages
    (`external_components` git source pinned to a tag, font path, includes with `vars`), a CI check of a remote-mode
    example, version tags `vX.Y.Z`, and a git-ignored private override file; the author then moves his own config to a
    private repo.

### 9.1 Backlog (ideas, separate tasks once the base is ready)
Optional modules; most can be built and tested without the physical sensors (`hardware/sim.yaml`):
- **Watering history** per zone: on screen since task 027 (History page, 6 rows per page, result `done` / `stopped` / `skipped` / `skipped wet`, skips included); in HA still open (wanted).
- Barrel water level sensor: don't water when empty, alert.
- Pump dry-run protection (flow or pressure sensor).
- Flow meter: litres per zone, watering by volume.
- Global run-time multiplier (e.g. ×1.5 in hot weather).
- Cycle and soak (water in several passes).
- Rain delay (sensor or HA command; lawn).
- Dynamic lanes for `max_parallel` between 1 and all.
- **Lawn one zone at a time, flowers in parallel, one shared pump.** Task 024 ships the simple case (lawn and flowers in
  one group, one at a time). Parallel flowers next to the lawn: today a pump belongs to one group, so this needs either
  lanes with different parallelism in one group (pinned lanes, at the cost of lawn and flowers overlapping) or a fork
  patch for a pump shared across groups. Its own task.
- Heating: night-tariff window and schedule modes.

## 10. Open questions
**Screens** (decide with the design work, roadmap stage 9)
1. Which drafts from the canvas to keep?

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

### 10.2 Decided (2026-10-10, screens, with the designer; canvas boards S0-S5, W0-W6)
- **Bed card slots** (was: fixed variants or generated YAML?): one template `card_bed.yaml` included up to 6 times
  (`vars: slot: N`); LVGL flex/grid sizes the cards; slots with index >= the group's zone count are hidden at boot.
  Cards read data by zone index through `gp_*`, never by bed ids. 1-3 beds: full cards (RUN / +Q); 4-6: compact
  cards in a 2x2 / 3x2 grid, a tap opens the bed page.
- **Home = widgets:** area 308x172 between header and nav, widgets stacked with gap 4 and fixed heights
  (26/40/44/76). Zones first (readings row if the zone has sensors, else last watering; 5+ zones as compact rows),
  the remaining height is filled by widgets in priority order, an active alert strip is always on top. A small C++
  helper decides what fits.
- **Widget choice:** YAML decides which widgets exist (a module package brings its own, e.g. heating); order and
  layout are chosen on the device in SETUP and stored (no reflash).
- **First widgets:** zones + alert strip, weather from HA, now/next + day timeline (next runs from the task 019 schedules),
  bed heating (with the heating module). Later: climate, water today.
- **Weather from HA:** the weather entity has no `forecast` attribute since HA 2024.4 (`weather.get_forecasts`
  action), and ESPHome cannot call actions, so the project documents a trigger-based HA template sensor that
  stores the forecast in attributes, read by ESPHome `homeassistant` sensors with `attribute:`. Without HA the
  weather widget is hidden.

## 11. Sources
- ESPHome `esphome/components/sprinkler/` (`dev`, 2026-10-01) and its commit history.
- https://esphome.io/components/sprinkler/
- https://esphome.io/components/time/#on-time-trigger (cron triggers are compile-time only, so slots use a C++ scheduler)
- https://esphome.io/components/datetime/ and https://esphome.io/components/text/template/ (the slot entities)
- https://esphome.io/components/external_components/
- https://esphome.io/components/host/
- https://esphome.io/components/display/sdl/
- https://esphome.io/components/time/sntp/
- https://esphome.io/components/time/
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
- https://www.home-assistant.io/blog/2023/09/06/release-20239/ (weather forecast action)
- https://www.home-assistant.io/integrations/template/ (trigger-based template sensors)
