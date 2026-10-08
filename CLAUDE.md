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
   `gp_*` scripts and entities, never to `sprinkler:` / `garden_zones` directly, so the engine can be swapped.
3. **Modules are packages.** A feature (bed, lawn, heating, …) is a package that can be enabled by uncommenting
   one line in the entry file; hardware pins live in `hardware/<board>.yaml` substitutions, not in feature files.
4. **Safety first for actuators.** Raw GPIO switches are `internal: true`; valves and heaters default OFF on boot
   (`restore_mode: RESTORE_DEFAULT_OFF` or `ALWAYS_OFF`); every actuator has a maximum on-time guard.
5. **Design tokens are the source of truth for the UI.** Colours, font sizes and geometry in LVGL YAML come from
   `design/tokens.json`; don't invent new colours or font sizes (each font size is baked into flash).
6. **Secrets only via `!secret`.** Never in tracked YAML; remote packages must not use `!secret`.
7. **Tests first** where code is testable (Python checks now, C++ core of `garden_zones` later).

These principles apply to **new and changed code**. Existing greenhouse packages predate them (the greenhouse
page calls `sprinkler.*` directly, valves have no on-time guard beyond `run_duration_number`); they migrate in
roadmap stages 7-9. Don't "fix" legacy code outside a
task's scope, and don't block a review on it — list it as a follow-up.

## Repository layout
| Path | Role |
|---|---|
| `garden-pilot.yaml` | Device entry point only: secret substitutions, `esphome:`, `logger:`, ordered `packages:`. |
| `garden-pilot-sim.yaml` | PC emulator entry point (ESPHome `host` + SDL window), same packages as the device; run with `script/sim`, never flash. |
| `hardware/<board>.yaml` | Board profile: `esp32:` block, every GPIO pin (relays `relay_N_pin`, analog `adc_N_pin`, ...) plus display/touch orientation and calibration as substitutions, and the raw relay drivers as internal switches `board_relay_N`. |
| `hardware/sim.yaml` | Emulator profile (`host:` + template relays that log state changes) for irrigation + beds; no Wi-Fi, OTA, display or sensors. |
| `packages/greenhouse/bed.yaml` | One bed per `!include` with `vars` (`bed`, `bed_name`, `relay`): adds a valve to `gh_sprinkler` via `!extend`. |
| `packages/greenhouse/bed_soil.yaml` | Optional per-bed soil moisture sensor (reports only), second include with `vars`. |
| `packages/core/api.yaml`, `ota.yaml` | `api` (encryption) and `ota`; secrets arrive as substitutions. |
| `packages/core/network.yaml` | `wifi` (`min_auth_mode`, fallback `ap`), `captive_portal`; device only. |
| `packages/core/time.yaml`, `time_host.yaml` | `time: homeassistant` (device) or `time: host` (emulator), both id `ha_time`, no triggers. |
| `packages/display_touch.yaml` | SPI, `mipi_spi` ILI9341 display, XPT2046 touch, `touch_ui` / `touch_dot_overlay` scripts. |
| `packages/display_sdl.yaml` | Emulator only: SDL display + mouse touch with the same ids and scripts as `display_touch.yaml` (keep in sync). |
| `packages/lvgl/base.yaml` | LVGL `displays` / `touchscreens` / `buffer_size` — no `pages`. |
| `packages/lvgl/page_*.yaml` | One LVGL page per file under `lvgl: pages:`. |
| `packages/lvgl/screensaver.yaml` | Idle screensaver overlay on the top layer + the `clock` font token (`gp_font_clock`); status line from `packages/greenhouse/screensaver_status.yaml`. |
| `packages/lvgl/fonts/` | Vendored TTF (Montserrat Bold) + `OFL.txt` for the glyph-limited custom font. |
| `packages/lvgl/dialog_confirm.yaml` | Confirm dialog on the LVGL top layer + `gp_confirm` script (pattern in its header). |
| `packages/core/diagnostics.yaml` | Internal version / uptime / restart button for the Network page (no new HA entities). |
| `packages/greenhouse/*.yaml` | Greenhouse domain: substitutions, sensors, irrigation (`sprinkler`), LVGL page. |
| `packages/sim/*.yaml` | Emulator only (never included by `garden-pilot.yaml`): simulated sensors as settable template numbers (`sensors.yaml`, `bed_soil.yaml`), "Sim auto drift" (`drift.yaml`), polled Home/Greenhouse labels (`sensors_lvgl.yaml`) and the SIM board page (`page_board.yaml`). |
| `packages/touch_dot_test.yaml` | Optional touch debug overlay (`!extend touch_dot_overlay`). |
| `secrets.example.yaml` | Template with obvious dummy values; copy to git-ignored `secrets.yaml`. |
| `.devcontainer/` | Reference dev environment: shared `Dockerfile`, default config, opt-in `sdl/` config (host display). |
| `design/` | Snapshot of the design system (rules, tokens, icons); the live design lives in claude.ai artifacts. |
| `docs/SPEC.md` | Product spec, architecture, roadmap, open questions. |
| `.github/` | CI (`workflows/ci.yml`, weekly `canary.yml`) and `dependabot.yml`. |
| `components/garden_zones/` | Fork of the stock `sprinkler`, GPLv3; patches listed in `PATCHES.md`, marked `GZ-PATCH` in the code. Not used by the device yet. |
| `tasks/` | Task specs and reviews (see `tasks/README.md`). |
| `tests/` | pytest repo checks; `script/*` wraps all commands. |

The target layout (`components/garden_zones/`, `lawn.yaml`, `heating.yaml`, ...) is in SPEC §5; it is
introduced by roadmap tasks, not ad hoc.

### `packages:` order in `garden-pilot.yaml` (do not reorder lightly)
1. `hardware` (board profile; exactly one), then `core_api`, `core_ota`, `core_network`, `core_time`, `core_diagnostics` — connectivity first.
2. `display_touch` — creates `tft_spi`, `tft_display`, `touch` (required by LVGL).
3. `lvgl_base` — LVGL wiring to those ids.
4. `lvgl_page_boot` — first page = boot screen (shows Home on Wi-Fi connect or after `boot_offline_timeout`; needs
   `core_diagnostics` and the home page); then `lvgl_page_home`, other `lvgl_page_*`, `lvgl_dialog_confirm`,
   `lvgl_screensaver`,
   `lvgl_page_setup`, `lvgl_page_network` and (device only) `lvgl_network_wifi`, `lvgl_boot_wifi`.
5. `gh_irrigation` (before the greenhouse page: its buttons call `gh_sprinkler`) → `gh_bed_N` (+ optional
   `gh_bed_N_soil` after its bed) in valve order, at least 2 beds → `gh_lvgl_page` → `gh_sensors_air` →
   `gh_sensors_soil` → `gh_sprinkler_lvgl` → `gh_screensaver_status` → `gh_valve_test` (Setup > SERVICE valve test).
6. `touch_dot_test` last (extends `touch_dot_overlay` from `display_touch`).

`garden-pilot-sim.yaml` uses the same order with `hardware/sim.yaml`, `core_api`, `core_time_host`, `core_diagnostics`, `display_sdl` and
without `core_ota`, `core_network`, `lvgl_network_wifi`, the greenhouse sensors and bed soil sensors.

### ESPHome YAML conventions
- **Pins only in `hardware/`, secrets only as entry-file substitutions** (`substitutions: x: !secret x`);
  packages use `${x}`. `tests/test_layout.py` enforces both.
- **Add a bed** = one `!include` block with `vars` in the entry file; features reference relays as `board_relay_N`
  and analog inputs as `${adc_N_pin}`, never GPIO numbers. With the stock sprinkler at least 2 beds are needed.
- **Board:** match the `esp32:` board declared in the `hardware/` profile until a migration task changes it.
- **Secrets files:** `secrets.yaml` / `secrets.example.yaml` are substitution files only (no `esphome:` block);
  `.vscode/settings.json` maps them to plain YAML so the ESPHome extension doesn't validate them as devices.
- **Remote packages** must not use `!secret`: expose `substitutions` and assign secrets from the entry file or a
  local include.
- **`sprinkler`** ([docs](https://esphome.io/components/sprinkler/)): every valve has `valve_switch_id`
  pointing at a real switch; with more than one valve `main_switch` and `auto_advance_switch` are required. Home
  Assistant and automations use the controller's zone switches and actions (`sprinkler.start_full_cycle`,
  `start_single_valve`, `shutdown`, queue actions) — never the raw GPIO switches, which stay `internal: true`.
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
- Actions extended into a `script` run outside the `on_touch` trigger: don't use the trigger-only `touch`
  variable there; use `id(touch)->get_touch()`.
- Don't call `lvgl.*` from a `number`'s `on_value` that can fire on restore/HA before LVGL is ready; poll from
  an `interval` instead (see `packages/greenhouse/sprinkler_lvgl_status.yaml`).
- Package merge: substitutions in the entry file win; dicts merge by key; component lists merge by `id`.
  Prefer small includes over deep `!extend` / `!remove` chains.
- The sim entry file needs `sdl2-config` (SDL2 dev files) even for `esphome config`; `web_server` is not available on
  the `host` platform, and `on_time_sync` does not fire on `host` (poll the clock from an `interval`).
- `xdotool click` is too short for LVGL to register a touch: use press, move, release with pauses (`script/sim-ui tap`). SDL `headless: true` disables the SDL touchscreen, so screenshots are X-level grabs under Xvfb instead.
- Logger actions (`logger.log`) default to DEBUG: pass `level: INFO` to see them at the committed log level.
- **Valve test limit:** `valve_test_max_time` in `packages/greenhouse/lvgl_valve_test.yaml` must stay <= 10 s
  (`tests/test_service.py`); it is enforced by `run_duration` and by the separate `gp_valve_test_guard` script. Service
  mode (`gp_service_mode`, never restored) stops other watering within 1 s. The limit counts from the tap and the sprinkler opens the valve ~2 s later, so a valve is open ~8 s. Raising the limit is the human's call.
- `sprinkler` limitations (one valve at a time, closed queue, `start_single_valve` disables auto-advance and the
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
| All checks | `script/test` (pytest, includes `esphome config`) |
| Fast checks only | `uv run pytest -m unit` |
| Validate config by hand | `script/config` (uses `secrets.yaml`, or `secrets.example.yaml` if absent). For `garden-pilot-sim.yaml` a real `secrets.yaml` without `sim_api_encryption_key` fails with "Secret not defined": use `GP_SECRETS=example` (same for `script/compile`; `script/sim` always does) |
| Compile firmware | `script/compile` (real `secrets.yaml`, or `GP_SECRETS=example` to stage example secrets under `.esphome/example-build/`) |
| Other ESPHome version | `GP_ESPHOME=pinned\|minimum\|latest\|YYYY.M.P` with `script/config` / `script/compile` |
| PC emulator (host + SDL window) | `script/sim` (needs a display; always builds with `secrets.example.yaml`; Ctrl+C stops) |
| Control the running emulator | `script/sim-ctl list \| get NAME \| set NAME VALUE \| switch NAME on\|off` (native API, `127.0.0.1:6053`, key from `secrets.example.yaml`; exit 1 = unreachable, 2 = usage) |
| Headless emulator screenshots / taps | `script/sim-ui start \| shot [NAME] \| tap X Y \| status \| stop` (private Xvfb, PNGs in `.esphome/shots/`; needs Xvfb + xdotool, in the devcontainer image; exit 3 = already running / port 6053 busy) |
| SDL window smoke check | `script/sdl-smoke` (needs a display: SDL devcontainer config or a desktop host) |
| Devcontainer from CLI | `devcontainer up --workspace-folder .` then `devcontainer exec --workspace-folder . script/test` (add `--docker-path podman` and `PODMAN_USERNS=keep-id` for Podman; `--config .devcontainer/sdl/devcontainer.json` for SDL) |
| Reproduce CI | `devcontainer up --workspace-folder .` then `devcontainer exec --workspace-folder . sh -c 'GP_SECRETS=example GP_ESPHOME=minimum script/compile'` |
| C++ unit tests | `script/test-cpp` |
| Flash / logs | `uv run esphome run garden-pilot.yaml` / `uv run esphome logs garden-pilot.yaml` |

Always pass the config path explicitly; run from the repo root.

## Test levels
- `unit` — pytest repo checks with no ESPHome toolchain: secrets template, public hygiene, YAML shape.
- `config` — `esphome config` on the entry file with `secrets.example.yaml` (copied into a temp dir).
- `compile` — `script/compile`: ESP32 firmware build in CI with pinned + minimum ESPHome (the weekly canary builds the latest).
- Sim entry order after the beds: `sim_bed_N_soil` right after `gh_bed_N`, then `sim_sensors`, `sim_drift`, `sim_sensors_lvgl`, `sim_page_board` (the last two are optional and LVGL-only; `sim_*` ids stay out of device files).
- The emulator entry file is checked by `esphome config` rows (need `sdl2-config`; skipped without it unless `GP_REQUIRE_SDL=1`, set in CI) and compiled in the CI `compile` jobs.
- The `host` level also has the emulator screen test (`test_sim_ui.py`: Xvfb + `script/sim-ui` shot, tap, shot). CI runs it in the separate, non-required job `sim-ui` (`GP_REQUIRE_SIM_UI=1`, screenshots uploaded as an artifact); `checks` sets `GP_SKIP_SIM_UI=1`. Elsewhere it skips without Xvfb/xdotool.
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
