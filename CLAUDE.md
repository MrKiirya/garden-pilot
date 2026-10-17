# GardenPilot — agent guide

ESPHome firmware for a garden irrigation and bed-heating controller: ESP32 + 320×240 touch display (LVGL),
relays/valves, soil and air sensors, native Home Assistant API. Public project meant to be repeated by others,
so everything is modular and configurable.
Product spec: [docs/SPEC.md](docs/SPEC.md) — read the sections your task references, not the whole file.
Design rules and tokens: [design/README.md](design/README.md), [design/tokens.json](design/tokens.json).

## Core principles (do not violate)
1. **YAML for hardware and ready-made components** (`switch: gpio`, sensors, `climate: thermostat`, LVGL, time,
   API, OTA). **C++ only for stateful irrigation logic** (future `components/garden_zones/`), never large
   logic in lambdas.
2. **One abstraction layer, `gp_*`.** Screens, schedules and Home Assistant talk to irrigation only through
   `gp.*` actions and `gp_*` entities (`components/gp/README.md`), never to `sprinkler:` / `garden_zones` directly, so the engine can be swapped.
3. **Modules are packages.** A feature (bed, lawn, heating, …) is a package that can be enabled by uncommenting
   one line in the entry file; hardware pins live in `hardware/<board>.yaml` substitutions, not in feature files.
4. **Safety first for actuators.** Raw GPIO switches are `internal: true`; valves and heaters default OFF on boot
   (`restore_mode: RESTORE_DEFAULT_OFF` or `ALWAYS_OFF`); every actuator has a maximum on-time guard, on by default (disable only explicitly with `never`).
5. **Design tokens are the source of truth for the UI.** Colours, font sizes and geometry in LVGL YAML come from
   `design/tokens.json`; don't invent new colours or font sizes (each font size is baked into flash).
6. **Secrets only via `!secret`.** Never in tracked YAML; remote packages must not use `!secret`.
7. **Tests first** where code is testable (Python checks now, C++ core of `garden_zones` later).

These principles apply to **new and changed code**. Existing greenhouse packages predate them (the greenhouse
page calls `garden_zones.*` on the group `gh_zones` directly instead of going through `gp_*`); they migrate in
roadmap stages 7-9. Don't "fix" legacy code outside a
task's scope, and don't block a review on it — list it as a follow-up.

## Repository layout
| Path | Role |
|---|---|
| `garden-pilot.yaml` | Device entry point only: secret substitutions, `esphome:`, `logger:`, ordered `packages:`. |
| `garden-pilot-sim.yaml` | PC emulator entry point (ESPHome `host` + SDL window), same packages as the device; run with `script/sim`, never flash. |
| `examples/*.yaml` | Four complete device configs (display + touch): `minimal-1-bed`, `beds-with-pump`, `soil-sensors`, `relay-module-8ch`. `../` includes, `gp_root: ".."`, secrets in `examples/secrets.yaml` (git-ignored); `examples/README.md`. |
| `hardware/<board>.yaml` | Board profile: `esp32:` block, every GPIO pin (relays `relay_N_pin`, analog `adc_N_pin`, ...) plus display/touch orientation and calibration as substitutions, and the raw relay drivers as internal switches `board_relay_N`. |
| `hardware/lilygo-t-relay-s3.yaml` | LilyGO T-Relay-S3 (6 relays + 6 expansion through `sn74hc595` `board_sr`, display on the TFT header); config-checked only, not run on a board. |
| `hardware/sim.yaml` | Emulator profile (`host:` + template relays that log state changes) for irrigation + beds; no Wi-Fi, OTA, display or sensors. |
| `packages/greenhouse/bed.yaml` | One bed per `!include` with `vars` (`bed`, `bed_name`, `relay`): adds one `garden_zone:` list item (a zone with its enable switch and run-duration number) to the group `gh_zones`. |
| `packages/greenhouse/bed_soil_skip.yaml`, `irrigation_pump.yaml` | Variants used INSTEAD of `bed.yaml` (adds `soil_moisture` with var `skip_above`; needs that bed's `bed_soil.yaml`) and of `irrigation.yaml` (adds the shared pump `board_relay_${gh_pump_relay}`, `gh_pump_max_on_time`, `gh_pump_idle_timeout`). Tests keep them equal to the originals apart from those keys. |
| `packages/greenhouse/bed_soil.yaml` | Optional per-bed soil moisture sensor (reports only), second include with `vars`. |
| `packages/core/api.yaml`, `ota.yaml` | `api` (encryption) and `ota`; secrets arrive as substitutions. |
| `packages/core/network.yaml` | `wifi` (`min_auth_mode`, fallback `ap`), `captive_portal`; device only. |
| `packages/core/time.yaml`, `time_sntp.yaml`, `time_host.yaml` | `time: homeassistant` (device) or `time: host` (emulator), both id `ha_time`, no triggers; `time_sntp.yaml` (device only, optional) adds `sntp` as the fallback (id `sntp_time`, servers via `sntp_server_N`). |
| `packages/display_touch.yaml` | SPI, `mipi_spi` ILI9341 display, XPT2046 touch, `touch_ui` / `touch_dot_overlay` scripts. |
| `packages/display_sdl.yaml` | Emulator only: SDL display + mouse touch with the same ids and scripts as `display_touch.yaml` (keep in sync). |
| `packages/lvgl/base.yaml` | LVGL `displays` / `touchscreens` / `buffer_size` — no `pages`; also the shared header clock (`gp_header_clock_text`, script `gp_header_clock_update`, 2 s interval). |
| `packages/lvgl/page_*.yaml` | One LVGL page per file under `lvgl: pages:`. |
| `packages/lvgl/nav_bar.yaml` | The ONE bottom nav: included as a widget with vars `p` (id prefix) and `active`; page targets are substitutions `gp_nav_*_page` (defaults in `base.yaml`). Pages never draw their own nav buttons (test). |
| `packages/lvgl/screensaver.yaml` | Idle screensaver overlay on the top layer + the `clock` font token (`gp_font_clock`); status line from `packages/greenhouse/screensaver_status.yaml`. |
| `packages/lvgl/fonts/` | Vendored TTF (Montserrat Bold) + `OFL.txt` for the glyph-limited custom font. |
| `packages/lvgl/dialog_confirm.yaml` | Confirm dialog on the LVGL top layer + `gp_confirm` script (pattern in its header). |
| `packages/core/diagnostics.yaml` | Internal version / uptime / restart button for the Network page (no new HA entities). |
| `components/gp/` | The `gp_*` layer (MIT): pure model/alerts/history/format headers + ESPHome glue, `Engine` adapter interface; contract in its README. |
| `components/gp_zone/` | One `gp_zone:` list item per bed: the HA zone switch (MIT). The `garden_zones` adapter is `components/garden_zones/gp_engine.h`. |
| `packages/core/gp.yaml`, `gp_api.yaml`, `packages/greenhouse/gp.yaml` | gp hub + alert sensor; generic HA actions; greenhouse group, status/watchdog entities and the main switch "Greenhouse irrigation". `packages/greenhouse/gp_lvgl_status.yaml` = pollers for the greenhouse/Home labels. |
| `components/garden_schedule/` | Device-side schedules (MIT): hub with a pure C++ core (`schedule_core.h`, unit tested with a fake clock), engine-agnostic; fires `on_run(zone_mask, pct, slot)` and takes `garden_schedule.zone_done`. README has the rules. |
| `components/garden_schedule_slot/` | One `garden_schedule_slot:` list item per slot (schema only; the hub generates the code). |
| `packages/lvgl/page_schedules.yaml`, `packages/greenhouse/lvgl_schedules.yaml` (+ `lvgl_schedules_row*.yaml`, `lvgl_schedules_toggle*.yaml` includes) | Schedule screens (nav slot SCHEDULE, task 030): the generic shell (header, hidden HISTORY, empty state, nav) and the greenhouse list rows (D08, 4 slots) that `!extend` it, plus the editor page `gh_sched_edit_page` (D09: ON, hour / minute, days, beds, RUN TIME factor, CANCEL / SAVE) and the Home "NEXT" label. |
| `packages/greenhouse/schedule.yaml`, `schedule_slot.yaml` | Hub `gh_schedule` with master switch, next-run / last-result text sensors, `on_run` -> `gp.enqueue_zones` + `gp.start_queue`; one include per slot (`vars: {slot, start}`, 2 in the entry files, max 8). |
| `packages/greenhouse/lvgl_history.yaml`, `packages/lvgl/history_row.yaml`, `history_row_refresh.yaml` | History page `gh_history_page` (design D20: 8 rows x 5 cells from the `gp` history, a live green row for a running zone, NEWER / OLDER / BACK). Opened from the Schedule page HISTORY button (`sched_btn_history` -> no-op script `sched_history_open`, extended here); BACK returns to `schedules_page`. Entry order: `gh_lvgl_history` right after `gh_lvgl_page`, after `lvgl_page_schedules`. |
| `packages/greenhouse/*.yaml` | Greenhouse domain: substitutions, sensors, irrigation (`irrigation.yaml`: the `garden_zones` group `gh_zones` and its own entities; the watchdog sensor, reset button and status live in `gp.yaml`), LVGL page. Every config that includes `bed.yaml` also needs `core_gp` + `gh_gp` (its `gp_zone:` switch), and `core_gp_api` when `api` is present. |
| `packages/sim/*.yaml` | Emulator only (never included by `garden-pilot.yaml`): simulated sensors as settable template numbers (`sensors.yaml`, `bed_soil.yaml`), "Sim auto drift" (`drift.yaml`), watchdog fault injection "Sim rogue relay 1" (`fault.yaml`), polled Home/Greenhouse labels (`sensors_lvgl.yaml`) and the SIM board page (`page_board.yaml`). |
| `packages/touch_dot_test.yaml` | Optional touch debug overlay (`!extend touch_dot_overlay`). |
| `secrets.example.yaml` | Template with obvious dummy values; copy to git-ignored `secrets.yaml`. |
| `.devcontainer/` | Reference dev environment: shared `Dockerfile`, default config, opt-in `sdl/` config (host display). |
| `design/` | Snapshot of the design system (rules, tokens, icons); the live design lives in claude.ai artifacts. |
| `docs/SPEC.md` | Product spec, architecture, roadmap, open questions. |
| `.github/` | CI (`workflows/ci.yml`, weekly `canary.yml`) and `dependabot.yml`. |
| `components/garden_zones/` | Fork of the stock `sprinkler`, GPLv3; patches listed in `PATCHES.md`, marked `GZ-PATCH` in the code. Used by the device and the emulator (group `gh_zones`, task 014). |
| `components/garden_zone/` | One `garden_zone:` entry of a `garden_zones` group (`MULTI_CONF`, schema only); MIT like the repo. |
| `tasks/` | Task specs and reviews (see `tasks/README.md`). |
| `tests/` | pytest repo checks; `script/*` wraps all commands. |

The target layout (`components/garden_zones/`, `lawn.yaml`, `heating.yaml`, ...) is in SPEC §5; it is
introduced by roadmap tasks, not ad hoc.

### `packages:` order in `garden-pilot.yaml` (do not reorder lightly)
1. `hardware` (board profile; exactly one), then `core_api`, `core_ota`, `core_network`, `core_time`, `core_time_sntp`, `core_diagnostics` — connectivity first (the sim entry has no `core_time_sntp`).
2. `display_touch` — creates `tft_spi`, `tft_display`, `touch` (required by LVGL).
3. `lvgl_base` — LVGL wiring to those ids.
4. `lvgl_page_boot` — first page = boot screen (shows Home on Wi-Fi connect or after `boot_offline_timeout`; needs
   `core_diagnostics` and the home page); then `lvgl_page_home`, other `lvgl_page_*`, `lvgl_dialog_confirm`,
   `lvgl_screensaver`,
   `lvgl_page_setup`, `lvgl_page_network` and (device only) `lvgl_network_wifi`, `lvgl_boot_wifi`.
5. `gh_irrigation` (the engine group `gh_zones`) → `gh_bed_N` (+ optional
   `gh_bed_N_soil` after its bed) in zone order, at least 1 bed → `core_gp` → `core_gp_api` (needs `core_api`) → `gh_gp` (the gp layer; screens and Home Assistant reach irrigation only through it) → `gh_lvgl_page` → `gh_lvgl_history` → `gh_sensors_air` →
   `gh_sensors_soil` → `gh_gp_lvgl` → `gh_screensaver_status` → `gh_valve_test` (Setup > SERVICE valve test) → `gh_schedule` → `gh_schedule_slot_N` (one include per slot, N unique 1..8).
   `gh_bed_N_soil` after its bed) in zone order, at least 1 bed → `core_gp` → `core_gp_api` (needs `core_api`) → `gh_gp` (the gp layer; screens and Home Assistant reach irrigation only through it) → `gh_lvgl_page` → `gh_sensors_air` →
   `gh_sensors_soil` → `gh_gp_lvgl` → `gh_screensaver_status` → `gh_valve_test` (Setup > SERVICE valve test) → `gh_schedule` → `gh_schedule_slot_N` (one include per slot, N unique 1..8) → `gh_lvgl_schedules` (rows of the Schedules page; needs `lvgl_page_schedules`, placed after `lvgl_page_lawn`).
6. `touch_dot_test` last (extends `touch_dot_overlay` from `display_touch`).

`garden-pilot-sim.yaml` uses the same order with `hardware/sim.yaml`, `core_api`, `core_time_host`, `core_diagnostics`, `display_sdl` and
without `core_ota`, `core_network`, `lvgl_network_wifi`, the greenhouse sensors and bed soil sensors.

### ESPHome YAML conventions
- **`gp_root`:** packages with a repo-relative path (`external_components` `source`, the screensaver font) write `${gp_root}/...` and define `gp_root: "."`; entry files in `examples/` set `gp_root: ".."` and use `../packages/...` / `../hardware/...` includes (`!include` resolves against the including file, `external_components` and fonts against the main config's directory, `!secret` reads `secrets.yaml` next to the file with the tag). Never write a literal `source: components` under `packages/`.
- **Pins per entry file:** every `${..._pin}` and every relay (`board_relay_N`, bed `relay`, `gh_pump_relay`) an entry file uses must exist in ITS board profile; profiles have contiguous `board_relay_1..N` (N >= 3) and no longer have to define the same relays. Active-low relay modules are not supported (no `inverted:`): they energise while the ESP32 resets.
- **Pins only in `hardware/`, secrets only as entry-file substitutions** (`substitutions: x: !secret x`);
  packages use `${x}`. `tests/test_layout.py` enforces both.
- **Add a bed** = one `!include` block with `vars` in the entry file; features reference relays as `board_relay_N`
  and analog inputs as `${adc_N_pin}`, never GPIO numbers. One bed is enough; its run-duration max (`gh_bed_run_max`) must fit under `gh_max_on_time`.
- **Board:** match the `esp32:` board declared in the `hardware/` profile until a migration task changes it.
- **Secrets files:** `secrets.yaml` / `secrets.example.yaml` are substitution files only (no `esphome:` block);
  `.vscode/settings.json` maps them to plain YAML so the ESPHome extension doesn't validate them as devices.
- **Remote packages** must not use `!secret`: expose `substitutions` and assign secrets from the entry file or a
  local include.
- **`garden_zones`** (groups form, `components/garden_zones/README.md`): zones come from `garden_zone:` list items, every
  zone has `valve_switch_id` pointing at a real switch (the raw relay, `internal: true`). Home Assistant and automations
  use the zone switches and the group entity "Greenhouse auto advance" (the "Greenhouse irrigation" main switch is a gp-owned template switch in `packages/greenhouse/gp.yaml`: ON = `gp.full_cycle`, OFF = `gp.stop_all`) and actions
  (`garden_zones.run_zone`, `queue_zone`, `start_group_queue`, `start_group_cycle`, `shutdown_group`,
  `clear_group_queue`) — never the raw GPIO switches.
- **Adding an LVGL page:** create `packages/lvgl/page_<name>.yaml` with `lvgl: pages: [{id: <page_id>,
  widgets: …}]`, add it to `packages:` after `lvgl_base` (order matters only for the boot page), navigate with
  `lvgl.page.show: <page_id>`.
- **Touch debug overlay:** comment out `touch_dot_test` in `garden-pilot.yaml` to disable it; the no-op
  `touch_dot_overlay` script in `display_touch.yaml` stays.
- **Small, task-scoped edits;** no unrelated refactors.

### ESPHome gotchas (learned the hard way)
- Custom fonts: vendored TTF under `packages/lvgl/fonts/` (never `gfonts://`: no network at config time), glyph-limited, one per design token (`clock` = `gp_font_clock`, screensaver only); `tests/test_screensaver.py` checks size, glyphs and checksum.
- Built-in LVGL Montserrat fonts have only ASCII plus the LVGL symbols: no `·`, `…`, `×`, `‑` in UI texts
  (use `-`, `...`, `x`); `tests/test_screens.py` enforces it on the tokenized files.
- Confirm dialog: `script.execute: gp_confirm {title, body, action, danger}` → `script.wait: gp_confirm` → `if` on
  `gp_confirm_result` → the action (see `packages/lvgl/dialog_confirm.yaml`). `time.has_time` is not a condition:
  use `id(ha_time).now().is_valid()`.
- `sntp` and `homeassistant` share the system clock: read `ha_time` only; an SNTP sync does not fire `ha_time.on_time_sync` (poll); `sntp` is not available on `host`. Both device sources get `timezone: ${timezone}` (default `UTC`, set your own in the entry file); that stops Home Assistant from pushing its zone. `time_host.yaml` has no `timezone` (the emulator keeps the PC zone).
- Actions extended into a `script` run outside the `on_touch` trigger: don't use the trigger-only `touch`
  variable there; use `id(touch)->get_touch()`.
- Don't call `lvgl.*` from a `number`'s `on_value` that can fire on restore/HA before LVGL is ready; poll from
  an `interval` instead (see `packages/greenhouse/gp_lvgl_status.yaml`).
- Package merge: substitutions in the entry file win; dicts merge by key; component lists merge by `id`.
  Prefer small includes over deep `!extend` / `!remove` chains.
- The sim entry file needs `sdl2-config` (SDL2 dev files) even for `esphome config`; `web_server` is not available on
  the `host` platform, and `on_time_sync` does not fire on `host` (poll the clock from an `interval`).
- `xdotool click` is too short for LVGL to register a touch: use press, move, release with pauses (`script/sim-ui tap`). SDL `headless: true` disables the SDL touchscreen, so screenshots are X-level grabs under Xvfb instead.
- A template entity must not reuse the generated id `<group>_watchdog` (the group's watchdog component) or `<group>_lane_<n>`.
- LVGL reads `gp` only from `interval:` pollers (guard with `changed_since`), never from a gp trigger, `on_value` or API action; label texts come from `gp::fmt::*` so lambdas stay one line. The hub id is `gp_hub` (an id may not equal an integration name).
- **Header clock (task 029):** a page header shows the time with one `<page>_clock_label` (TOP_RIGHT, y 4, `montserrat_12`) and ONE `lvgl.label.update` appended to the shared script with `script: [{id: !extend gp_header_clock_update, then: [...]}]` (text `id(gp_header_clock_text)`); `packages/lvgl/base.yaml` owns the global, the script and the 2 s interval. No per-page time formatting, no `on_time_sync`. Built-in LVGL fonts in use: `montserrat_10` (caption), 12 (label), 14 (value), 16 (value-lg, boot title); custom Bold fonts `gp_font_clock`, `gp_font_button_md` (10 px transport buttons) and `gp_font_button_sm` (8 px nav / in-card buttons), the last two declared in `packages/lvgl/base.yaml` with the nav icon images (`gp_icon_house|leaf|drop|gear`, PNG in `packages/lvgl/icons/`, recoloured with `image_recolor`); no `montserrat_8`; legacy pages (greenhouse, lawn, touch test) stay on the LVGL default until rebuilt.
- Logger actions (`logger.log`) default to DEBUG: pass `level: INFO` to see them at the committed log level.
- **Valve test limit:** `valve_test_max_time` in `packages/greenhouse/lvgl_valve_test.yaml` must stay <= 10 s
  (`tests/test_service.py`); it is enforced by the `duration` of `gp.run_zone` and by the separate `gp_valve_test_guard` script. Service
  mode (`gp_service_mode`, never restored) stops other watering within 1 s. The limit counts from the tap; the start stops the group first only when something is running (stopping an idle `garden_zones` lane enters STOPPING for 1 s plus a 1 s selection delay), so an idle group opens the valve at once and it is open up to the full limit. Raising the limit is the human's call.
- A `garden_zones` group's watchdog is on by default (`max_on_time` 60 min, `pump_max_on_time` 2 h, `pump_idle_timeout` 10 s); only `never` disables a limit (WARN at boot). A zone's `run_duration_number` `max_value` (stock default 86400 s) must fit under its `max_on_time` or config fails (skipped for `never`).
- `garden_zone:` is always a list item (`- group: ...`): two dict-form entries from different packages merge into one zone.
- **Schedule screens:** the nav opens `schedules_page`; a domain adds its rows with `lvgl: pages: [{id: !extend schedules_page, widgets: [...]}]` (an `!extend` of a page appends widgets; the test helpers skip non-string page ids). The list shows the first 4 slots in include order (slots 5-8 are Home Assistant only, no paging, no scrolling). The editor edits a RAM draft in the hub (`begin_edit` / `draft()`); only SAVE (`save_edit`) writes the changed slot entities, so a tap never writes flash; there is no `garden_schedule` toggle action. Home "NEXT" is written by `lvgl_schedules.yaml`, not by `gp`. Includes with `vars` and refresh scripts keep the YAML short (tests expand them).
- **History and sources:** one run = one history entry, opened at the zone start and closed in place at its end (`components/gp/journal.h`; an entry open at boot becomes `interrupted`). The gp actions that start watering take `source` (`manual` default, `ha`, `schedule`, `service` only on `gp.run_zone`): schedules pass `source: schedule` + `slot`, Home Assistant actions / switches pass `ha`, screens keep `manual`, the valve test `service`. `completed` of `on_zone_finished` does not depend on the source. Details: `components/gp/README.md`.
- **Schedules:** the run mark is (local day, start minute): once per start and day (a repeated DST hour is blocked), but moving a slot to a later time runs it again the same day, also after a STOP; saving the same start never does (persisted as blob v2, v1 marks migrate as "any minute"); no `time: on_time` cron triggers for watering (compile-time only). A slot missed while the device was off still runs inside `gh_schedule_catch_up_window` (60min default), else it is logged as missed; the done mark is per zone (`garden_schedule.zone_done` from `gp` `on_zone_finished`), written to flash at once, and a restart runs only the zones that did not complete; a user STOP (or service mode) settles the slots (nothing resumes), a slot firing during a manual cycle runs after it (`gp` holds the enqueue back). Entities of a slot are `entity_category: config`; the skip condition is `gp.inhibited` (service mode). Rules: `components/garden_schedule/README.md`.
- Stock `sprinkler` limitations the fork works around (one valve at a time, closed queue, `start_single_valve` disables auto-advance and the
  queue, queued zones run even when disabled): SPEC §3.

## Environment
- **Devcontainer** (`.devcontainer/`, Docker or rootless Podman) is the reference environment. Verified by the author on
  Linux with rootless Podman in VS Code (incl. USB flash and OTA); Windows not verified yet; Docker Engine and macOS untested. Plain Linux shell with [uv](https://docs.astral.sh/uv/) also works.
- Python and ESPHome via **uv**: `pyproject.toml` pins `esphome==<version>` exactly; `uv.lock` is committed.
  Python version in `.python-version`.
- `.esphome/` is the local ESPHome/PlatformIO build cache — never commit or hand-edit it.

## Commands
| Purpose | Command |
|---|---|
| Install / update deps | `script/setup` (= `uv sync`) |
| Lint (yamllint + `esphome config`) | `script/lint` |
| All checks | `script/test` (pytest in parallel via xdist, 4 workers by default, includes `esphome config`; `GP_PYTEST_WORKERS=0` = serial, `N` or `auto` = other worker counts; extra args pass through) |
| Fast checks only | `uv run pytest -m unit` |
| Validate config by hand | `script/config` (uses `secrets.yaml`, or `secrets.example.yaml` if absent). For `garden-pilot-sim.yaml` a real `secrets.yaml` without `sim_api_encryption_key` fails with "Secret not defined": use `GP_SECRETS=example` (same for `script/compile`; `script/sim` always does) |
| Compile firmware | `script/compile` (real `secrets.yaml`, or `GP_SECRETS=example` to stage example secrets under `.esphome/example-build/`) |
| Other ESPHome version | `GP_ESPHOME=pinned\|minimum\|latest\|YYYY.M.P` with `script/config` / `script/compile` |
| PC emulator (host + SDL window) | `script/sim` (needs a display; always builds with `secrets.example.yaml`; Ctrl+C stops) |
| Control the running emulator | `script/sim-ctl list \| get NAME \| set NAME VALUE \| switch NAME on\|off \| text NAME VALUE \| time NAME HH:MM` (native API, `127.0.0.1:6053`, key from `secrets.example.yaml`; exit 1 = unreachable, 2 = usage) |
| Headless emulator screenshots / taps | `script/sim-ui start \| shot [NAME] \| tap X Y \| status \| stop` (private Xvfb, PNGs in `.esphome/shots/`; needs Xvfb + xdotool, in the devcontainer image; exit 3 = already running / port 6053 busy) |
| SDL window smoke check | `script/sdl-smoke` (needs a display: SDL devcontainer config or a desktop host) |
| Devcontainer from CLI | `devcontainer up --workspace-folder .` then `devcontainer exec --workspace-folder . script/test` (add `--docker-path podman` and `PODMAN_USERNS=keep-id` for Podman; `--config .devcontainer/sdl/devcontainer.json` for SDL) |
| Reproduce CI | `devcontainer up --workspace-folder .` then `devcontainer exec --workspace-folder . sh -c 'GP_SECRETS=example GP_ESPHOME=minimum script/compile'` |
| C++ unit tests | `script/test-cpp` |
| Flash / logs | `uv run esphome run garden-pilot.yaml` / `uv run esphome logs garden-pilot.yaml` |

Always pass the config path explicitly; run from the repo root. Configs in a subdirectory work too: `script/config examples/<file>.yaml` (and `script/compile`) stage the config at its relative path with `secrets.example.yaml` next to it (`GP_SECRETS=example`) or use `examples/secrets.yaml`.

## Test levels
- `unit` — pytest repo checks with no ESPHome toolchain: secrets template, public hygiene, YAML shape.
- `config` — `esphome config` on the entry file with `secrets.example.yaml` (copied into a temp dir).
- `compile` — `script/compile`: ESP32 firmware build in CI with pinned + minimum ESPHome (the weekly canary builds the latest).
- Sim entry order after the beds: `sim_bed_N_soil` right after `gh_bed_N`, then `sim_sensors`, `sim_drift`, `sim_sensors_lvgl`, `sim_page_board` (the last two are optional and LVGL-only; `sim_*` ids stay out of device files).
- The emulator entry file is checked by `esphome config` rows (need `sdl2-config`; skipped without it unless `GP_REQUIRE_SDL=1`, set in CI) and compiled in the CI `compile` jobs.
- The `host` level also has the emulator screen test (`test_sim_ui.py`: Xvfb + `script/sim-ui` shot, tap, shot). CI runs it in the separate, non-required job `sim-ui` (`GP_REQUIRE_SIM_UI=1`, screenshots uploaded as an artifact); `checks` sets `GP_SKIP_SIM_UI=1`. Elsewhere it skips without Xvfb/xdotool.
- Parallel runs: each host build + its tests is one xdist group (`HOST_GROUPS` in `tests/conftest.py`, `--dist loadgroup`); a new module fixture that builds a host program must be added there (`tests/test_harness.py` checks). The schedule scenario shifts its clock with `libfaketime` (installed in the image; `GP_REQUIRE_FAKETIME=1` in CI; without the library, e.g. an older local container, it still passes but waits for real minute boundaries; `GP_FAKETIME_LIB=<path>` points at a local build).
- `cpp` (minimal header-only harness, `script/test-cpp`) and `host` (host compile + scenario of `tests/configs/`) exist for `garden_zones`; both skip when no C++ compiler is installed.
- Later (roadmap): reference-image comparison of the `script/sim-ui` screenshots, `aioesphomeapi` integration scenarios.

## ESPHome security baseline
Per [Security Best Practices](https://esphome.io/guides/security_best_practices/); ESPHome is for a trusted LAN.
- `api:` with `encryption.key: !secret …`; `ota:` protected by a secret; unique keys per device.
- `wifi:` with `min_auth_mode: WPA2` (or WPA3); fallback `ap:` with a non-empty `!secret` password.
- `web_server:` only with `auth:` — otherwise omit it and use Home Assistant.
- `logger:` at `INFO` or stricter in committed configs; raise it only while debugging.
- External components only from trusted sources, pinned to a tag or commit.
- Optionally raise `logger: logs:` levels for `wifi` / `api` so they never log sensitive data.
- Verify the device identity before an OTA upload. Removing the fallback `ap:` is a deliberate trade-off
  (no captive-portal recovery), not a default.

## Public repo hygiene
Never commit: `secrets.yaml`, real Wi‑Fi SSIDs/passwords, API keys, OTA passwords, IPs/hostnames of the author's
network, real entity ids or device names from the author's home, local absolute paths, build caches.
`secrets.example.yaml` holds obviously fake values only.
**If a secret ever reaches git history** (even on a branch that was pushed): rotate it on the device and in HA
first, then scrub the history — tell the human, never rewrite history on your own.
The `deny` rules in `.claude/settings.json` are speed bumps, not protection: the real safeguards are these
rules and `.gitignore`. Task and review files are public too
— use generic
examples (`192.168.x.x`, `[SSID]`).

## Definition of done
- New behaviour covered by checks written first; `script/lint` and `script/test` green.
- Hardware-facing changes state what was verified on a real device, or say explicitly that it wasn't.
- `docs/SPEC.md` / this file / `design/` updated if behaviour, commands, conventions or tokens changed.
- Task file acceptance criteria all checked.

## Git & GitHub
- Default branch: **`master`**. Repo: `MrKiirya/garden-pilot` (public).
- One branch per task: `task/NNN-short-name` → draft PR → green CI → squash-merge after the human's review.
- Only the main session runs git write operations; subagents never commit, push or open PRs.
- Never rewrite published history (`push --force`, `rebase`/`reset` of pushed commits) without being asked.
- Commit messages: Conventional Commits (`feat:`, `fix:`, `test:`, `docs:`, `chore:`, `ci:`, `refactor:`).
- **No AI attribution:** no `Co-Authored-By: Claude …` trailers in commits and no "Generated with Claude Code"
  lines in PR descriptions; the author is `MrKiirya`.
- Split a task branch into **several logical commits** so the PR reads commit by commit.
- No local git pre-commit hooks; checks are enforced by `script/*` and CI.
- Personal, machine-local instructions go to the git-ignored `CLAUDE.local.md`.
- **Branch protection:** the `master` ruleset is versioned in `.github/rulesets/master.json`; a test keeps its
  required checks equal to the `ci.yml` job names. Renaming a CI job means updating the ruleset file and
  re-applying it (repo admin): `gh api --method PUT repos/MrKiirya/garden-pilot/rulesets/<id> --input
  .github/rulesets/master.json` (first time: `--method POST repos/MrKiirya/garden-pilot/rulesets`).
- **Bumping ESPHome:** Dependabot opens the `chore(deps):` PR; it stays red (`test_spec_versions_match_sources`
  fails) until `docs/SPEC.md` §6 shows the new pin, so push a `docs:` commit with that. Check that the minimum
  still holds. Raising the minimum = edit `esphome-minimum` in `pyproject.toml` and SPEC §6 in one PR. A
  `canary-failure` issue means the next bump needs a fix task first. Manual bump: edit the pin in `pyproject.toml`
  and SPEC §6, run `uv lock`, then `script/setup`, `script/lint`, `script/test`.

## Language
- Everything in the repo — YAML, code, comments, docs, task files, commit messages, PRs — is **English**.
  Exception: `README.ru.md`, the Russian copy of the README (keep both in sync).
- Chat with the author: Russian when the author writes Russian.

## Agent workflow
- **Main session = orchestrator.** Talks to the human, runs agents, does not read code deeply.
- **Subagents always run in the background** (never blocking), so the chat stays responsive;
  the main session relays the result when the agent completes.
- `planner` (opus): writes `tasks/NNN-name.md` — goal, spec sections, files, checks to write,
  acceptance criteria, out of scope, open questions.
- `implementer` (sonnet): reads CLAUDE.md + the task file (+ referenced spec sections); checks first;
  returns a one-line status.
- `reviewer` (opus, fresh context): checks the diff against the task file, runs lint and tests,
  writes `tasks/NNN-review.md` with verdict `APPROVE` / `CHANGES_REQUESTED`.
- Max 2 review iterations, then escalate to the human.
- **Light path:** trivial changes (typos, version bumps, one-line config) skip planner/reviewer, but
  still go through a PR — every change to `master` goes through a PR.
