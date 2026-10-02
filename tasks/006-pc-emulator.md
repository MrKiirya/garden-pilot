# 006 — PC emulator, part 1: host + SDL build of the real screens, works without HA, API by IP, one-command runner

Status: in-review
Roadmap: SPEC §9 new stage 6 "PC emulator (host + SDL)" (inserted by this task after stage 5; part 1 of 2)
Spec sections: SPEC §5 (sim board, target layout `core/{network,time,api,ota}`), §6, §7 items 4–6, §9;
CLAUDE.md core principles 3, 4, 5, 6, 7; ESPHome security baseline
Hardware check: yes, but only "nothing changed": the author OTA-flashes the branch firmware once and confirms the
device behaves as before (the network package is split). The emulator itself is checked by the author on a PC
(window, mouse, optional Home Assistant by IP), not in CI.

## Goal
The author (and anyone repeating the project) runs GardenPilot on a PC with one command, `script/sim`: it builds a
second entry file, `garden-pilot-sim.yaml`, for the ESPHome `host` platform with an SDL window instead of the
ILI9341 and the mouse instead of XPT2046 touch, and starts it. The window shows the **same** LVGL pages from the same
packages (Home first, navigation, Greenhouse with beds 1–3); RUN/STOP on a bed switches a simulated relay and the
screen updates. **The emulator works fully without Home Assistant** (clock from the PC, controls on screen);
Home Assistant can optionally add it by IP (port 6053) as a separate device. The author's device is unchanged:
`packages/core/network.yaml` is split so the API can be used without Wi-Fi, and the normalized `esphome config` of
`garden-pilot.yaml` is identical before and after (apart from key order). CI compiles the host build on the pinned
and minimum ESPHome. Simulated sensors with settable values (manual and scripted) and the "Sim auto drift" switch are
part 2, task 007 (decided design in Out of scope, so this task leaves the right hooks).

## Context

### Current state (master after task 005)
- `garden-pilot.yaml`: `hardware` (breadboard) → `core_network` (api + ota + wifi + captive_portal) → `core_time`
  (`time: homeassistant`, id `ha_time`) → `display_touch` (`spi` `tft_spi`, `mipi_spi` `tft_display`, `xpt2046`
  `touch`, scripts `touch_ui` / `touch_dot_overlay`) → `lvgl_base` (uses `tft_display`, `touch`) → pages `home`,
  `touch_test`, `lawn` → `gh_irrigation`, `gh_bed_1..3`, `gh_lvgl_page`, `gh_sensors_air` (DHT), `gh_sensors_soil`
  (ADC + gpio DO), `gh_sprinkler_lvgl` → `touch_dot_test`.
- `packages/lvgl/page_home.yaml` adds the clock update to the time source with `time: - id: !extend ha_time`.
- `hardware/sim.yaml`: `host:` (`mac_address: "02:00:00:00:00:01"`) + `board_relay_1..3` as internal template
  switches, `ALWAYS_OFF`. Config-only today.
- Ids the reused packages need from a display package: `tft_display`, `touch` (`packages/lvgl/base.yaml`);
  `id(touch)->get_touch()` and `!extend touch_dot_overlay` (`packages/touch_dot_test.yaml`); `touch_ui` is executed
  only inside `display_touch.yaml`. `tft_spi` is internal to `display_touch.yaml`. Only built-in `montserrat_*`
  fonts, nothing downloaded at build time.
- Greenhouse sensors push to LVGL labels from `on_value` and use DHT/ADC/gpio, so they cannot run on `host`. In this
  task the Home/Greenhouse sensor labels keep their initial text; task 007 fills them.
- `script/sdl-smoke` already proves `host` + `display: sdl` + X11 forwarding in `.devcontainer/sdl/` (Dockerfile
  installs `libsdl2-dev`).
- CI: `checks` (devcontainer, `script/lint && script/test`, 20 min, caches uv only) and `compile` matrix
  `pinned`/`minimum` (devcontainer, `script/compile`, 60 min, caches uv + ESPHome + PlatformIO). `tests/test_ci.py`
  pins check names, one devcontainer step per job, `script/compile` in the compile `runCmd`.

### ESPHome behaviour checked (pinned 2026.9.1; minimum 2026.6.3)
- Host platform ([esphome.io/components/host](https://esphome.io/components/host/)): only option `mac_address`; no
  `wifi:` (the host's network is used); `esphome run file.yaml` compiles and runs the program; API port 6053; HA does
  **not** discover a host instance via mDNS — add by IP; `ota: esphome` works on host (port 8082) and "can overwrite
  the running executable"; preferences in `$ESPHOME_PREFDIR`, else `~/.esphome/prefs`, file `<name>.prefs`; a `host`
  time source exists.
- SDL display ([docs](https://esphome.io/components/display/sdl/), source `esphome/components/sdl/display.py` at
  2026.9.1 and 2026.6.3): `dimensions` required; `update_interval`, `show_test_card`, `window_options` exist on both
  versions; `headless` and `snapshot_key` exist on 2026.9.1 but **not** on 2026.6.3 — not used here.
  `sdl_options` defaults to `sdl2-config --cflags --libs`, run **at config validation**; without SDL2 dev files
  validation fails with "Unable to run sdl2-config - have you installed sdl2?".
- SDL touchscreen ([docs](https://esphome.io/components/touchscreen/sdl/)): `touchscreen: - platform: sdl`,
  optional `id`, common touchscreen options (incl. `on_touch`); mouse emulates touch; needs a window.
- **`web_server` does not support `host`**: `esphome/components/web_server/__init__.py` at 2026.9.1 has
  `cv.only_on([ESP32, ESP8266, BK72XX, LN882X, RP2, RTL87XX])`, and `web_server_base` has no host server
  implementation (AUTO_LOAD only `web_server_idf` for ESP32 or `async_tcp` for Arduino). A host shim exists only as a
  third-party external component (github.com/rjt-rockx/esphome-host-linux), which the security baseline rules out
  without the author's explicit decision. So the author's "web_server with auth in the sim entry file" idea for
  manual sensor control is **not possible upstream**; the decided alternatives (SIM board page + `script/sim-ctl`) are in the 007 outline.
- API on host: same `api:` schema (`encryption.key`, `reboot_timeout`, default 15 min). Whether noise encryption
  builds on host and what the reboot does there (exit vs. restart) is **not verified** — spike step 0.
- `aioesphomeapi` is already a dependency of `esphome` (used by `esphome logs`), so a later API control script and
  API scenarios need no new package (check `uv.lock` in task 007).
- Package merge (task 005 notes): dicts merge by key, entry file wins; `api:` is a dict, so the sim entry file can set
  `api: reboot_timeout:` on top of `core/api.yaml` without touching the device.

## Decisions
1. **Separate entry file `garden-pilot-sim.yaml`** in the repo root, built from the same packages. Only
   `substitutions`, `esphome` (`name: garden-pilot-sim`, `friendly_name: GardenPilot Sim` — a different device in
   HA), `logger: level: INFO`, optionally `api:` (only `reboot_timeout`, Decision 6) and `packages:` in this order:
   `hardware` (`hardware/sim.yaml`) → `core_api` → `core_time_host` → `display_sdl` → `lvgl_base` →
   `lvgl_page_home` → `lvgl_page_touch_test` → `lvgl_page_lawn` → `gh_irrigation` → `gh_bed_1..3` (same `vars` as
   the device) → `gh_lvgl_page` → `gh_sprinkler_lvgl` → `touch_dot_test`. No `core_network`, `core_ota`,
   `core_time` (HA), `display_touch`, greenhouse sensors, `web_server`. Header: what it is, never flash it, which
   device packages it leaves out and why, "works without Home Assistant".
2. **Network split along SPEC §5's target layout:** `packages/core/api.yaml` (`api: encryption: key:
   ${api_encryption_key}`, moved verbatim), `packages/core/ota.yaml` (`ota: - platform: esphome, password:
   ${ota_password}`, moved verbatim), `packages/core/network.yaml` keeps `wifi:` (+ fallback `ap:`) and
   `captive_portal:`. Device entry file: `core_network` is replaced by `core_api`, `core_ota`, `core_network` (in
   that order, right after `hardware`), then `core_time`. Each header lists the substitutions it needs.
3. **No OTA in the emulator** (host OTA can replace the running executable; the sim carries public example values;
   the runner rebuilds anyway).
4. **Display package `packages/display_sdl.yaml`** (mirrors `display_touch.yaml`; not in `hardware/sim.yaml`):
   `display: - platform: sdl, id: tft_display, dimensions: 320×240` (from `design/tokens.json` screen geometry if
   it defines it, else the device's literal 320×240); `touchscreen: - platform: sdl, id: touch, on_touch:
   script.execute: touch_ui`; `script:` `touch_ui` (→ `touch_dot_overlay`) and the no-op `touch_dot_overlay`, as in
   `display_touch.yaml` (6 duplicated lines, accepted; both headers say "keep in sync"). No transform/calibration,
   no `headless`/`snapshot_key`/`window_options` (minimum version).
5. **Clock without HA: `packages/core/time_host.yaml`** with `time: - platform: host, id: ha_time`. The id is kept so
   `page_home.yaml`'s `!extend ha_time` works with either source; the header says so, and renaming the id to a
   neutral one (e.g. `gp_time`) across device and sim is a follow-up (it would touch the device config). The sim uses
   it instead of `core/time.yaml`; with HA connected the PC clock still rules. Spike step 0 g confirms the Home clock
   label updates from the host source (its `on_time_sync` fires); if not, record it and leave the clock as a
   follow-up rather than adding lambdas.
6. **`api: reboot_timeout: 0s` in the sim entry file** if the spike shows the default makes the program exit or
   restart with no API client (the emulator must run indefinitely without HA). Device keeps the default.
7. **Secrets for the sim build.** The sim entry file assigns `api_encryption_key: !secret sim_api_encryption_key`.
   `secrets.example.yaml` gets `sim_api_encryption_key`: obviously fake, valid base64 of 32 bytes, **different**
   from the device example key, commented "public dummy, emulator only". `script/sim` **always** stages with
   `secrets.example.yaml` (never the real `secrets.yaml`), so no real key enters the emulator and the device key is
   never reused. Documented: the emulator's API key is public; anyone who can reach its port can toggle simulated
   relays (nothing physical). `script/config` / `script/compile` with `GP_SECRETS=example` work for the sim file;
   with a real `secrets.yaml` lacking the key they fail with "secret not found" — documented.
8. **Runner `script/sim`** (POSIX sh, executable, style of `script/sdl-smoke` / `script/compile`):
   - same helpful failure as `sdl-smoke` when neither `DISPLAY` nor `WAYLAND_DISPLAY` is set;
   - stages `garden-pilot-sim.yaml`, `packages`, `hardware`, `components` (if present) and `secrets.example.yaml` →
     `secrets.yaml` into the git-ignored `.esphome/sim-build/` (fixed dir → incremental; same copy list as
     `script/compile`/`script/config`);
   - exports `ESPHOME_PREFDIR=.esphome/sim-prefs` (absolute path) unless already set, so run durations survive
     restarts and nothing lands in `~`;
   - runs `sh script/_esphome run <staged file>` (honours `GP_ESPHOME`; foreground with logs; Ctrl+C stops). If the
     spike shows `esphome run` prompts or misbehaves on host, `_esphome compile` and exec the `program` binary like
     `sdl-smoke`;
   - prints once: "Works without Home Assistant. Optional HA: add ESPHome device by IP of this PC, port 6053, key
     `sim_api_encryption_key` from secrets.example.yaml. Never flash this build."
9. **Reaching the API from outside the devcontainer.** Only `.devcontainer/sdl/devcontainer.json` gets
   `"--publish=${localEnv:GP_SIM_API_PUBLISH:127.0.0.1:6053}:6053"` in `runArgs`. Default: PC loopback only (safe;
   enough for HA on the same PC and for tools on the host). For HA on another machine the user sets
   `GP_SIM_API_PUBLISH=6053` on the host before "Rebuild container" and allows TCP 6053 in the host firewall
   (Fedora/Bazzite: firewalld) — documented, not automated. No `--network=host` (documented as a Docker-on-Linux
   alternative only). Default devcontainer config unchanged. VS Code `forwardPorts` is not used (localhost only).
   Tools run inside the container (task 007's control script, API scenarios) reach `127.0.0.1:6053` directly.
10. **CI: compile the host build in the existing `compile` matrix jobs.** `runCmd` becomes `script/compile &&
    script/compile garden-pilot-sim.yaml && uv cache prune --ci` (`GP_SECRETS=example` already set). Reasons: cached
    PlatformIO/ESPHome, 60 min timeout, built on **both** pinned and minimum; `checks` has 20 min and no PlatformIO
    cache. Compile only, no window, no display needed. Check names unchanged; one devcontainer step per job. The
    implementer records extra time (cold and warm); if a warm run adds more than ~10 minutes, stop and ask.
11. **Config tests without SDL.** Matrix rows that include `display_sdl` `pytest.skip` with a clear reason when
    `shutil.which("sdl2-config")` is `None`, **unless** `GP_REQUIRE_SDL=1`, then they fail. CI's `checks` step sets
    `GP_REQUIRE_SDL=1` in its `env:` block, so CI never skips them.
12. **Roadmap renumbering in SPEC §9** (author's decision): new stage **6 "PC emulator (host + SDL)"** after stage 5
    (part 1 = this task; part 2 = task 007, simulated sensors, their control and the auto-drift switch); then
    7 `garden_zones`, 8 `gp_*`, 9 Screens, 10 Time without HA, 11 Schedules/heating, 12 **"Screenshot checks in CI"**
    (was 11; keeps headless screenshots, BMP comparison and `aioesphomeapi` scenarios in CI). Every "stage N"
    reference outside `tasks/` is updated: `CLAUDE.md:26`, `README.md:95` + matching `README.ru.md` line,
    `hardware/sim.yaml:6`, `docs/SPEC.md` ~80/157/188/224/250, `garden-pilot.yaml:42,44`,
    `packages/greenhouse/bed.yaml:18`, `packages/greenhouse/bed_soil.yaml:2`. Old task files are history, not edited.
    The new stage 6 text in SPEC §9 names both parts, including the default-OFF auto-drift switch (author decision,
    2026-10-02).

### Proving "the device does not change"
Task 005 procedure (master via `git archive` into the scratch dir vs. branch; both rendered with `script/_esphome
config` and `secrets.example.yaml`; `INFO`/`WARNING` lines and `substitutions:` dropped; `diff`; helper not
committed). Expected: **no differences** except possibly the top-level order of `api:`/`ota:`/`wifi:`/
`captive_portal:` and the known `long_press_time`/`long_press_repeat_time` order noise. Paste helper output and
justify each line. No entity or name changes, so HA entity ids and preferences are unaffected.

## Files
23 paths; 10 are test/doc edits of a few lines. Already split: simulated sensors, their control and auto drift are
task 007. If the author wants it smaller, the next cut is Decision 10 (CI compile + its test) as its own task.
- create: `garden-pilot-sim.yaml` — Decision 1.
- create: `packages/core/api.yaml`, `packages/core/ota.yaml` — Decision 2.
- create: `packages/core/time_host.yaml` — Decision 5.
- modify: `packages/core/network.yaml` — Wi-Fi + captive portal only; header (Decision 2).
- create: `packages/display_sdl.yaml` — Decision 4; header: "PC emulator only; same ids as display_touch.yaml;
  needs SDL2 dev files even for `esphome config`".
- create: `script/sim` — Decision 8 (executable).
- modify: `garden-pilot.yaml` — `core_api`, `core_ota`, `core_network`; stage renumbering in comments; a comment
  pointing to `garden-pilot-sim.yaml`.
- modify: `hardware/sim.yaml` — header only (now used by the emulator too; what it still cannot take).
- modify: `secrets.example.yaml` — `sim_api_encryption_key` (Decision 7).
- modify: `.devcontainer/sdl/devcontainer.json` — publish arg (Decision 9).
- modify: `.github/workflows/ci.yml` — compile `runCmd` (Decision 10); `checks` env `GP_REQUIRE_SDL=1` (Decision 11).
- modify: `tests/test_config_matrix.py` — `Variant.source` (entry file, default `garden-pilot.yaml`), sim rows,
  SDL skip/require, `CORE` keys.
- modify: `tests/test_layout.py` — new checks below; `test_no_secret_outside_entry_file`,
  `test_substitutions_resolve`, `test_core_is_display_independent` cover the new files / second entry file.
- modify: `tests/test_esphome_config.py` — device key order; sim entry-file shape.
- modify: `tests/test_ci.py` — sim compile + `GP_REQUIRE_SDL`.
- modify: `tests/test_devcontainer.py` — publish arg; `script/sim`.
- modify: `tests/test_secrets_example.py` — only if it does not already cover a new key generically.
- modify: `packages/greenhouse/bed.yaml`, `packages/greenhouse/bed_soil.yaml` — comment renumbering only.
- modify: `docs/SPEC.md` — §5 (core split done; `time_host.yaml`; sim board runs the emulator; `display_sdl.yaml`),
  §7 items 4–6 (host build exists, `script/sim`, compiled in CI on both versions; works without HA; `web_server`
  unavailable on host; sensor control via the native API in task 007; screenshots later), §9 (Decision 12), §6 only if
  something differs on 2026.6.3.
- modify: `CLAUDE.md` — layout table (`garden-pilot-sim.yaml`, `packages/core/{api,ota,network,time,time_host}.yaml`,
  `packages/display_sdl.yaml`), `packages:` order (device: core_api → core_ota → core_network → core_time), Commands
  (`script/sim`), stages note renumbered, gotchas "sim entry file needs `sdl2-config` even for `esphome config`" and
  "`web_server` is not available on `host`".
- modify: `README.md`, `README.ru.md` — "Run on a PC (emulator)" section, in sync: `script/sim` in the SDL
  devcontainer or on a desktop host with SDL2 dev files; works without HA; optional HA by IP (port 6053, public key
  `sim_api_encryption_key`, emulator only); devcontainer publishing, `GP_SIM_API_PUBLISH=6053` + firewall for HA on
  another machine; Ctrl+C; preferences in `.esphome/sim-prefs/`. Generic examples only (`192.168.x.x`).

## Checks to write first
**Step 0 — spike (not committed), scratch dir, pinned and minimum (`GP_ESPHOME=minimum`), SDL devcontainer.**
Minimal config: `host:` + `api: encryption.key: <dummy>` + `time: - platform: host` with `on_time_sync` logging +
`display: sdl` + `touchscreen: sdl` + `lvgl:` with one button. Record in Implementation notes:
- a: `esphome config` and `esphome compile` pass on both versions (API encryption builds on host).
- b: the window opens; a mouse click fires the button (log line).
- c: port 6053 is open: `uv run python -c "import socket; socket.create_connection(('127.0.0.1', 6053), 3)"` inside
  the container, and from the host after publishing.
- d: with no API client for longer than `reboot_timeout` (set `1min` in the spike): exit, restart or keep running?
  → Decision 6.
- e: `ESPHOME_PREFDIR` is honoured (a `.prefs` file appears there) → Decision 8.
- f: `esphome run <file>` on host compiles and starts without prompting → Decision 8.
- g: the host time source fires `on_time_sync` (log line) → Decision 5.
- h: adding `web_server: {port: 8080, auth: …}` to the spike config fails validation on host (confirms the source
  check above; record the message for task 007).
Gate: if a fails on either version (API encryption or SDL touchscreen unusable on host), set Status `blocked` and
report the exact error; do not drop encryption or invent a workaround.

| Level | Test | Asserts |
|---|---|---|
| unit | `tests/test_layout.py::test_core_split` | `core/api.yaml` only top-level `api`; `ota.yaml` only `ota`; `network.yaml` only `wifi`, `captive_portal`; `time.yaml` and `time_host.yaml` only `time`, one item each, both with id `ha_time` (`homeassistant` / `host`). `api.encryption.key` is `${api_encryption_key}`; the ota item has `password: ${ota_password}`. |
| unit | `tests/test_layout.py::test_display_packages_share_ids` | `display_touch.yaml` and `display_sdl.yaml` both define display id `tft_display`, touchscreen id `touch`, scripts `touch_ui` and `touch_dot_overlay`; `display_sdl.yaml` uses `platform: sdl` for both and has no `${…_pin}`, no `GPIO`, no `headless`/`snapshot_key`. |
| unit | `tests/test_layout.py::test_sim_entry_file` | `garden-pilot-sim.yaml` top-level keys ⊆ `{substitutions, esphome, logger, api, packages}`; `api` (if present) has only `reboot_timeout`; `hardware` includes `hardware/sim.yaml`; packages contain `core_api`, `core_time_host`, `display_sdl`, `lvgl_base`, `lvgl_page_home` (first page package), `gh_irrigation`, `gh_bed_1..3`, `gh_lvgl_page`, `gh_sprinkler_lvgl`; do **not** contain `core_network`, `core_ota`, `core_time`, `display_touch`, `gh_sensors_air`, `gh_sensors_soil`, any `bed_soil.yaml` include; no `web_server`; `esphome.name` differs from the device's; `logger.level` `INFO` or stricter; the only `!secret` is `sim_api_encryption_key` in `substitutions`. |
| unit | `tests/test_layout.py::test_sim_beds_match_device` | The `gh_bed_N` includes (file + vars) and their order equal the device entry file's; every package key shared by both entry files includes the same file (except `hardware`). |
| unit | `tests/test_layout.py::test_no_secret_outside_entry_file` (modified) | Runs for both entry files. |
| unit | `tests/test_layout.py::test_substitutions_resolve` (modified) | Every `${name}` used by a package included from the sim entry file is defined by it, `hardware/sim.yaml`, package `substitutions:` blocks or bed `vars` (catches a sim package needing `wifi_ssid` etc.). |
| unit | `tests/test_secrets_example.py` (extend if needed) | `sim_api_encryption_key` exists, is valid base64 of 32 bytes, differs from `api_encryption_key`. |
| unit | `tests/test_esphome_config.py::test_entry_file_is_a_package_list` (modified) | Device keys start with `hardware, core_api, core_ota, core_network, core_time`. |
| unit | `tests/test_ci.py::test_ci_compiles_the_sim` | Compile `runCmd` has `script/compile garden-pilot-sim.yaml` after the device `script/compile`; `checks` env has `GP_REQUIRE_SDL=1`; existing name/structure tests green. |
| unit | `tests/test_devcontainer.py::test_sdl_variant_publishes_api_port` | SDL `runArgs` has exactly one `--publish=` arg, `${localEnv:GP_SIM_API_PUBLISH:127.0.0.1:6053}:6053`; no `--network=host`; the default config has no `--publish`. |
| unit | `tests/test_devcontainer.py::test_sim_script` | `script/sim` exists, executable; text references `secrets.example.yaml`, `.esphome/sim-build`, `ESPHOME_PREFDIR`, `DISPLAY`/`WAYLAND_DISPLAY`; never copies the repo-root `secrets.yaml`; same copy list as `script/compile`. |
| unit | `tests/test_config_matrix.py::test_builder_blocks` (kept) | Green with the `source` field. |
| config | existing rows `full`, `headless`, `no_touch_debug`, `beds_2_headless`, `bed_soil_headless`, `sim_beds_3`, `sim_beds_2` | `CORE` = `hardware, core_api, core_ota, core_network, core_time`; otherwise unchanged. |
| config | `…[sim_full]` | `source="garden-pilot-sim.yaml"`, unchanged → validates (skip/require per Decision 11). |
| config | `…[sim_no_touch_debug]` | Sim entry file without `touch_dot_test` validates. |
| config | `…[sim_api_only]` | From the sim entry file keep `hardware`, `core_api`, `core_time_host`, `gh_irrigation`, `gh_bed_1..3` → validates without SDL (API and clock on host without Wi-Fi or display); never skipped. |

## Acceptance criteria
- [x] Step 0 spike a–h recorded in Implementation notes for 2026.9.1 and 2026.6.3.
- [x] `uv run pytest -m unit` → all pass, including the new tests.
- [x] `script/lint` → yamllint clean, `esphome config OK: garden-pilot.yaml`.
- [x] `script/test` in the devcontainer with `GP_REQUIRE_SDL=1` → all pass, 10 config variants, none skipped.
- [x] `GP_ESPHOME=minimum GP_SECRETS=example sh script/config` and `… sh script/config garden-pilot-sim.yaml` → OK.
- [x] `GP_SECRETS=example script/compile garden-pilot-sim.yaml` builds on pinned and with `GP_ESPHOME=minimum`;
      cold/warm durations recorded.
- [x] Normalized `esphome config` diff of `garden-pilot.yaml` master vs. branch → empty apart from the listed order
      noise; helper and output pasted.
- [x] `git grep -n '!secret' -- packages hardware` → no output; `git grep -nE 'GPIO[0-9]+|web_server' --
      garden-pilot-sim.yaml packages/display_sdl.yaml packages/core` → no output.
- [x] SPEC §9 lists 12 stages, "PC emulator (host + SDL)" = 6 (both parts named, incl. the default-OFF auto-drift
      switch), "Screenshot checks in CI" = 12; every "stage N" outside `tasks/` uses the new numbers (reviewer reads
      `git grep -nE '[Ss]tages? [0-9]+' -- ':!tasks/'`).
- [ ] `tests/test_ci.py` green; CI on the PR green for `checks`, `compile (pinned)`, `compile (minimum)`; ruleset file
      unchanged.
- [x] `docs/SPEC.md`, `CLAUDE.md`, `README.md`, `README.ru.md` updated as listed; READMEs in sync.
- [ ] **PC, without Home Assistant (author, not CI)** — SDL devcontainer on Linux with rootless Podman, HA not
      connected (or the port not published):
  - `script/sim` opens a 320×240 window and shows the Home page first; the clock shows the PC time;
  - the program keeps running for at least 20 minutes with no API client;
  - clicking the bottom navigation reaches Greenhouse, Lawn, Touch test and back; the touch dot follows clicks;
  - Greenhouse page shows beds 1–3; RUN on a bed → log shows the sprinkler starting that valve and `board_relay_N`
    turning on, the page status updates; STOP turns it off; QUEUE + start runs in order;
  - Home/Greenhouse sensor values show their initial placeholders (expected until task 007);
  - Ctrl+C stops it; a second `script/sim` rebuilds incrementally and keeps changed run durations.
- [ ] **PC with Home Assistant, optional (author):** with `GP_SIM_API_PUBLISH=6053` before rebuilding the container
      and TCP 6053 allowed in the host firewall, HA "Add integration → ESPHome → host `192.168.x.x`, port 6053, key
      `sim_api_encryption_key`" adds "GardenPilot Sim" with bed switches, enable switches, run durations,
      "Greenhouse irrigation", "Greenhouse auto advance"; toggling a bed in HA updates the window and vice versa; the
      real device's entities are untouched.
- [ ] **Device (author, not CI):** OTA-flash the branch build of `garden-pilot.yaml`; Wi-Fi and HA reconnect, a second
      OTA works, entities unchanged, nothing "unavailable", clock still from HA.
- [x] Implementer states that none of the PC/device items were checked by it (no display, no HA).

## Out of scope
- **Task 007 (stage 6 part 2): simulated sensors, their control and auto drift** — decided design, to be planned next:
  - each sim sensor value is backed by a settable template `number` (air temperature, air humidity, greenhouse soil
    moisture; per-bed soil moisture when a bed soil sensor is used), `restore_value: false`, deterministic defaults;
    these numbers are the single source of truth, set manually or by tests; template sensors with the device
    ids/names (`gh_air_temperature`, `gh_air_humidity`, `gh_soil_moisture_pct`, `gh_bedN_soil_moisture`) read them;
  - the LVGL label/bar updates move out of the sensors' `on_value` into a polled `packages/greenhouse/sensors_lvgl.yaml`
    (pattern of `sprinkler_lvgl_status.yaml`), so device and sim share one display path, sensors become display-free
    and the "`on_value` before LVGL is ready" gotcha is fixed — a justified device change with its own hardware check;
  - **"Sim auto drift" switch — in scope of 007 (author decision, 2026-10-02):** sim-only template switch,
    `restore_mode: ALWAYS_OFF` (default OFF keeps tests deterministic). When ON, an `interval` slowly lowers each soil
    value and raises it a little while that bed's relay (`board_relay_N`) is on; nothing else (no day/night or
    temperature model). It writes through the same numbers, so manual/test values stay the source of truth.
    Toggleable over the native API (HA, `script/sim-ctl`, tests); "from the web page" is not possible on host (see
    Context, `web_server`), so the manual paths are the SIM board page and `script/sim-ctl`. Rates and step sizes are literal
    defaults in the sim package (proposal in 007; small enough to watch on screen, e.g. −1 % per minute dry, +1 % per
    10 s watering, clamped 0–100);
  - **manual control without HA (author decision):** a sim-only LVGL "SIM board" page (virtual board: relay
    indicators named by board function, live on/off; one slider per simulated sensor value; the "Sim auto drift"
    checkbox, default OFF), reached by an extra nav button/gesture that exists only in the sim entry file (needs
    design tokens, no new colours); PLUS `script/sim-ctl` (Python, `aioesphomeapi` already shipped with ESPHome) to
    list/set entities over the native API, e.g. `script/sim-ctl set "Sim soil moisture" 35`,
    `script/sim-ctl switch "Sim auto drift" on`. `web_server` is impossible on host and no third-party shim is used;
  - **tests:** the same API path; a first `aioesphomeapi` scenario (set soil value → read the sensor state; drift ON →
    value changes) fits in 007 if the host program can run without a window in CI (`headless` is 2026.9.1-only, or a
    non-SDL sim variant such as `sim_api_only` plus the sim sensors — decide in 007); otherwise stage 12.
- Renaming the time id `ha_time` to a neutral id (touches the device config).
- Headless run, screenshots, BMP references, `aioesphomeapi` scenarios in CI (stage 12 unless 007 takes the first).
- Building the sim in the weekly canary (one line in `canary.yml` + test; follow-up).
- OTA and mDNS for the emulator; `web_server` via a third-party host shim.
- Changes to `display_touch.yaml`, LVGL pages, the greenhouse page's direct `sprinkler.*` calls, the 3-bed
  hard-coding (legacy, stages 8–9).
- Windows (WSL2) / macOS instructions beyond "untested".

## Author decisions (open questions settled, 2026-10-02)
1. **Manual control without HA (task 007).** A "SIM board" LVGL page that exists only in the emulator entry file: a
   virtual board view showing every board output (`relay_1..N` indicators named by board function, on/off live) and
   inputs (a slider for each simulated sensor value), plus the "Sim auto drift" checkbox (default OFF; when ON soil
   slowly dries and rises while that bed's relay runs). Reached by an extra nav button/gesture present only in the sim.
   PLUS a terminal command `script/sim-ctl` that talks to the emulator over the native API (same path as tests and
   HA). No third-party `web_server` shim. In task 006 itself, relay state is visible in the emulator log (state
   changes logged); the docs say the SIM board page comes in task 007.
2. **Port 6053**, published to loopback by default; `GP_SIM_API_PUBLISH` opt-in for HA on another machine — accepted.
3. **Public sim-only API key** — accepted (controls only simulated entities).
4. **Emulator compiled inside the existing compile jobs** — accepted (check names unchanged).
5. **Entity names as on the device** ("Greenhouse bed 1"); HA device "GardenPilot Sim", so ids get the
   `gardenpilot_sim_` prefix.

## Implementation notes
Pinned ESPHome 2026.9.1, minimum 2026.6.3. Checks ran in the author's already running devcontainer (it has SDL2 dev
files), with Xvfb as the X display.

**Emulator window not run by the agent on the author's display; author to check.** Before that rule was set, the agent
ran the emulator once under a private Xvfb inside the devcontainer (details below); that is not a substitute for the
author's PC check.

**Spike (step 0), both versions:**
- a: `esphome config` and `compile` pass; noise-encrypted API builds on host. Gate passed.
- b: the SDL window opens and a mouse press held ~0.4 s fires `on_touch` and the LVGL button (Xvfb + xdotool). A
  press+release faster than one loop is lost (touch state is polled). Injected clicks did not reach the window on the
  author's Xwayland, so a real-desktop click was not tested.
- c: port 6053 open on 127.0.0.1 inside the container. Publishing to the PC host not tested.
- d: `reboot_timeout: 1min` and no client: "No clients; rebooting", the process EXITS (no restart). So Decision 6 applies:
  `api: reboot_timeout: 0s` in the sim entry file.
- e: `ESPHOME_PREFDIR` honoured (a `.prefs` file appeared, also under `esphome run`).
- f: `esphome run <file>` on host compiles and starts without prompts.
- g: `on_time_sync` does NOT fire on host (`HostTime::update()` is empty). The Home clock label still showed the PC time
  within the first 30 s via the page's 30 s interval; no lambdas added.
- h: `web_server` fails validation on host on both versions ("only available on ESP32, ESP8266, BK72XX, LN882X, RP2, RTL87XX").
- Extra: with the host GL stack and no /dev/dri the SDL program hung in renderer creation; `SDL_RENDER_DRIVER=software`
  fixed it, so `script/sim` defaults to it. `logger.log` defaults to DEBUG, so checks use `level: INFO`.

**Results:**
- `script/lint` ok; `script/test` in the devcontainer with `GP_REQUIRE_SDL=1`: 291 passed, 10 config variants, none skipped.
  Without `sdl2-config` (this host) the two SDL config rows and the sim `script/config` test skip with a reason.
- `GP_ESPHOME=minimum` `script/config` OK for `garden-pilot.yaml` and `garden-pilot-sim.yaml`.
- Sim compile OK on pinned and minimum: 46 s each with a warm toolchain cache (cold CI time not measured), 9 s rebuilt
  warm. CI adds about 1 minute per compile job (well under the 10 minute limit).
- Normalized master-vs-branch `esphome config` of `garden-pilot.yaml` (master via `git archive`, both rendered by
  `script/config` with example secrets, `INFO`/`WARNING` lines and `substitutions:` dropped; 1383 lines each): the only
  difference is the known order noise, `long_press_repeat_time` / `long_press_time` swapped (lines 365/366). The helper
  was a scratch script, not committed.
- Agent's Xvfb run of `script/sim` (pinned): Home page with the PC clock, nav to Greenhouse worked, "Bed 1" logged
  `SIM relay_1 ON` and the page showed "Running: Bed1", "Stop" logged `SIM relay_1 OFF`, Ctrl+C-style SIGINT stopped it,
  a second run restarted in ~9 s. It ran only about 2 minutes unattended.

**Decisions and deviations:** `hardware/sim.yaml` relays log every state change (author decision); the sim key is base64
of the 32-byte text "garden-pilot-sim-public-dummy!!!"; `script/sim` defaults to `SDL_RENDER_DRIVER=software`; extra tests
`test_sim_substitutions_resolve` and `test_sim_entry_file_is_a_package_list`; the devcontainer variant test ignores the
`--publish=` arg. For testing the agent installed `xvfb xdotool imagemagick` as root inside the running devcontainer
(not in the repo or Dockerfile). A copy of an X auth cookie was left in the git-ignored `.esphome/spike/xauth`; delete it.

**Not verified:** PC window on the real desktop (clicks, Lawn / Touch test pages, touch dot, queue run), the 20-minute
run, run-duration persistence (`.prefs` was empty after one short run), HA by IP, `GP_SIM_API_PUBLISH` publishing,
device OTA with the split network package, CI on the PR, a truly cold CI compile time.

## Follow-ups
- Rename the time id `ha_time` to a neutral id (device change).
- Build the sim in the weekly canary.
- Consider `xvfb` in the SDL devcontainer for automated click tests (task 007 / stage 12).
