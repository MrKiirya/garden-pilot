# 015 — Headless emulator screenshots and taps (`script/sim-ui`)

Status: in-review
Roadmap: SPEC §9 stage 12 (first slice, pulled forward): headless SDL screenshots; no reference-image comparison yet
Spec sections: SPEC §7 (items 4-6), §9 stage 12, §6 (minimum version)
Hardware check: none (emulator only; the device config and firmware do not change)

## Goal
An agent or a developer can run the PC emulator without a desktop, take PNG screenshots of its 320x240 screen and
tap it in display coordinates, from the shell: `script/sim-ui start`, `script/sim-ui shot home`,
`script/sim-ui tap 280 220`, `script/sim-ui stop`. Combined with `script/sim-ctl` (set sensor values / switches
over the native API) this lets anyone see what a change does to a screen without hardware and without an SDL window
on the desktop. A `host`-level pytest boots the emulator under Xvfb, takes a shot of Home, taps SETUP and asserts
the screen changed; it runs in a separate, non-required CI job `sim-ui` because the devcontainer image gains Xvfb and xdotool.

## Context
- **Recipe proven by hand** (devcontainer image, ESPHome 2026.9.1): `Xvfb :99 -screen 0 640x480x24`, then
  `DISPLAY=:99 script/sim` (SDL software renderer, already forced by `script/sim` via `SDL_RENDER_DRIVER=software`).
  With no window manager the 320x240 window lands centred, at (160,120)-(480,360) on a 640x480 screen — do not
  hardcode this: get the geometry from `xdotool search ... getwindowgeometry --shell`.
  Screenshot: `PIL.ImageGrab.grab(xdisplay=":99").crop(box)`. Tap: `xdotool mousemove X Y`, 0.3 s,
  `mousedown 1`, 0.3 s, `mousemove X+1 Y+1`, 0.3 s, `mouseup 1`. A plain `xdotool click 1` is **not** registered by
  LVGL (press too short) — the press/move/release sequence is required.
- **Why not the native SDL options** (checked on [esphome.io SDL display](https://esphome.io/components/display/sdl/),
  [Snapshot display](https://esphome.io/components/display/snapshot/),
  [2026.9.0 changelog](https://esphome.io/changelog/2026.9.0/), PR
  [esphome#17917 / #19696](https://github.com/esphome/esphome/pull/19696)):
  - `headless: true` draws into memory, but "the SDL touchscreen and SDL binary sensor cannot be used with headless"
    — no taps, and `packages/display_sdl.yaml` has an SDL touchscreen with id `touch` that the UI relies on.
  - `snapshot` display / `snapshot.take` (BMP files) and `headless` arrived in **2026.9.0**; the minimum supported
    version is **2026.6.3** (SPEC §6) and the sim build is compiled with both in CI. Using them would mean raising
    the minimum or splitting the sim config per version — not this task.
  - `window_options` (`position`, `borderless`) from [esphome#16363](https://github.com/esphome/esphome/pull/16363):
    not needed (geometry is read from X) and avoids another version dependency.
  - Decision: X-level capture under Xvfb, so `garden-pilot-sim.yaml` and every package stay unchanged and the tool
    works on every supported ESPHome version. SPEC §7 item 5 must be reworded accordingly (BMP + `headless` stays a
    stage 12 option for reference images, not a dependency).
- **Dependencies:** Pillow 12.3 is already in `uv.lock` as an ESPHome dependency (same situation as
  `aioesphomeapi` for `sim-ctl`): no `uv add`. New apt packages in `.devcontainer/Dockerfile`: `xvfb`, `xdotool`
  (Debian trixie). Pillow's manylinux wheel includes XCB support needed by `ImageGrab.grab(xdisplay=...)`; if
  `ImageGrab` raises, report it — do not add a dependency.
- **SDL devcontainer pitfall:** `.devcontainer/sdl/devcontainer.json` bind-mounts the host `/tmp/.X11-unix`, so a
  fixed `Xvfb :99` there creates a socket in the **host's** X11 dir and may collide with a real display. Pick the
  display number with `Xvfb -displayfd <fd>` (Xvfb chooses a free one) unless `GP_SIM_UI_DISPLAY` is set, and
  start Xvfb with `-nolisten tcp`. On a Wayland desktop (Xwayland) root `GetImage` fails with BadMatch and needs
  `XAUTHORITY`, which is why `sim-ui` always uses its own Xvfb and never the desktop `DISPLAY`.
- **Emulator timing facts** (SPEC §8): the boot page shows Home after `boot_offline_timeout` = 3 s in the emulator;
  the screensaver covers the screen after 1 min without input (a tap wakes it and is swallowed); the Home clock
  changes every minute, so two shots taken a minute apart differ even without a tap. The SIM button (top layer) is
  visible in every shot.
- **Tap target for the test:** Home bottom nav `nav_btn_setup` (`packages/lvgl/page_home.yaml`: x 244, y 204,
  72x32) → centre (280, 220) → `setup_page`. Read the coordinates from the YAML in the test (or keep one constant
  with a comment pointing at the widget id) so a layout change fails with a clear message.
- **Ready signal:** wait until 127.0.0.1:6053 accepts a TCP connection AND the 320x240 window is found (xdotool); the log line `setup() finished` is not used (stdout is block-buffered into sim.log on 2026.6.3; `start` also runs the sim under `stdbuf -oL`). Original wording: (verify the exact
  wording against the 2026.9.1 and 2026.6.3 output; match a substring, strip ANSI codes like
  `tests/test_garden_zones.py::_run_program`), then wait the settle time (default 5 s: boot page gone), then
  confirm the window exists.
- **Process handling** (learned in `script/sdl-smoke`): the SDL program may ignore SIGTERM while its window is open —
  start `script/sim` in its own session/process group and stop with SIGTERM to the group, then SIGKILL after a few
  seconds. `script/sim` uses `esphome run`, which compiles first (1-2 min cold, incremental in
  `.esphome/sim-build/`).
- **Port 6053:** the sim's API port is fixed. `start` must fail with a clear message when 6053 is already in use
  (a developer's `script/sim` running), instead of starting a second emulator that cannot bind.
- **Prefs:** `script/sim` honours an existing `ESPHOME_PREFDIR`; the test sets it to a temp dir so saved run
  durations etc. from a developer session cannot change what the screen shows.

### Interface (decided; the implementer may refine names of internal helpers only)
`script/sim-ui` (POSIX sh wrapper: `exec uv run python "$(dirname "$0")/sim_ui.py" "$@"`, like `script/sim-ctl`)
and `script/sim_ui.py`:

| Command | Behaviour | Exit codes |
|---|---|---|
| `start [--timeout S] [--settle S]` | Refuse if a session is running or 6053 is busy; start Xvfb (640x480x24, `-displayfd`, `-nolisten tcp`) unless `GP_SIM_UI_DISPLAY` names an existing X display; run `script/sim` with that `DISPLAY` (and `WAYLAND_DISPLAY` unset) in a new process group, log to `.esphome/sim-ui/sim.log`; wait for port 6053 + the window (default timeout 900 s: first build), then `--settle` (default 5 s); find the window; write `.esphome/sim-ui/state.json` (display, pids, window box). Print the display and window box. | 0 ok; 1 build/start failure or timeout (tail of the log on stderr); 2 usage; 3 already running / port busy |
| `shot [NAME]` | Grab the window box from the session display, save `.esphome/shots/NAME.png` (default `shot-YYYYmmdd-HHMMSS`), print the path. NAME: `[A-Za-z0-9._-]+`, no path separators. | 0; 1 no session / grab failed; 2 bad name |
| `tap X Y [--settle S]` | X in 0..319, Y in 0..239 (display pixels); press/move/release sequence above at window origin + (X, Y); then sleep `--settle` (default 0.5 s) so LVGL redraws. | 0; 1 no session; 2 out of range / usage |
| `status` | Print whether a session runs (pids alive, display, window box). | 0 running; 1 not running |
| `stop` | SIGTERM the sim process group, SIGKILL after 5 s, stop Xvfb, remove `state.json`. Idempotent. | 0 |

Constants `WIDTH = 320`, `HEIGHT = 240` must match `packages/display_sdl.yaml` (checked by a unit test). Taps and
shots are only ever sent to the Xvfb display that `start` created (or `GP_SIM_UI_DISPLAY`), never to the desktop.
Everything written goes under the git-ignored `.esphome/` (`.esphome/sim-ui/`, `.esphome/shots/`). No secrets: the
emulator already builds only with `secrets.example.yaml`.

Keep the logic in small pure functions so it is unit-testable without X: display-to-screen mapping with bounds
checks, parsing `getwindowgeometry --shell` output, building the xdotool argv steps for a tap, shot-name
validation/path building, a `looks_blank(image)` helper (fewer than N distinct colours, e.g. `len(image.getcolors(256)
or []) ... ` — define it and test it), and ready-line detection on a log line.

## Files
- modify: `.devcontainer/Dockerfile` — add `xvfb` and `xdotool` to the apt list (with a one-line comment: headless
  screenshots/taps for `script/sim-ui`). One image for both configs; no devcontainer.json change.
- create: `script/sim-ui` — executable sh wrapper (header comment with usage examples, like `script/sim-ctl`).
- create: `script/sim_ui.py` — the tool (argparse subcommands above, stdlib + Pillow only).
- create: `tests/test_sim_ui.py` — unit checks of the pure helpers + the `host` scenario.
- modify: `tests/test_devcontainer.py` — Dockerfile installs `xvfb` and `xdotool`; `script/sim-ui` is executable and
  uses `uv run python ... sim_ui.py`.
- modify: `.github/workflows/ci.yml` — `checks` job env gains `GP_REQUIRE_SIM_UI=1` (a missing Xvfb/xdotool in the
  CI image fails instead of skipping). Job names unchanged; `timeout-minutes` unchanged unless the measured run
  needs more (then ask, see Open questions).
- modify: `CLAUDE.md` — Commands table row for `script/sim-ui`; Test levels: the `host` level now also covers the
  emulator screen test (skips without Xvfb/xdotool unless `GP_REQUIRE_SIM_UI=1`); ESPHome gotchas: "`xdotool click`
  is too short for LVGL; use press/move/release (`script/sim-ui tap`)" and "SDL `headless:` disables SDL touch".
- modify: `docs/SPEC.md` — §7 item 5 reworded (Xvfb + `script/sim-ui` done in task 015; `headless`/`snapshot` are
  2026.9.0+ and headless has no touch); §7 item 6 / §9 stage 12 note that screenshots and taps exist, reference-image
  comparison and `aioesphomeapi` scenarios remain.
- modify: `README.md` and `README.ru.md` — where `script/sim-ctl` is documented, add `script/sim-ui` usage (keep
  both in sync).

## Checks to write first
| Level | Test | Asserts |
|---|---|---|
| unit | `tests/test_sim_ui.py::test_display_size_matches_sdl_package` | `sim_ui.WIDTH, HEIGHT == 320, 240` and equal to `dimensions` in `packages/display_sdl.yaml` |
| unit | `tests/test_sim_ui.py::test_to_screen_maps_with_window_offset` | window at (160,120): (0,0)→(160,120), (319,239)→(479,359) |
| unit | `tests/test_sim_ui.py::test_to_screen_rejects_out_of_range` | -1, 320 (x) and 240 (y) raise `ValueError` (CLI → exit 2) |
| unit | `tests/test_sim_ui.py::test_parse_window_geometry` | parses `WINDOW=..\nX=160\nY=120\nWIDTH=320\nHEIGHT=240\nSCREEN=0` into a box (160,120,480,360); missing keys raise |
| unit | `tests/test_sim_ui.py::test_tap_steps_press_move_release` | argv steps are mousemove, mousedown 1, mousemove +1/+1, mouseup 1 with >= 0.2 s pauses; no `click` step |
| unit | `tests/test_sim_ui.py::test_shot_path` | default name matches `shot-\d{8}-\d{6}.png` under `.esphome/shots/`; `home` → `.esphome/shots/home.png`; `../x`, `a/b`, empty → rejected |
| unit | `tests/test_sim_ui.py::test_looks_blank` | a uniform 320x240 image is blank; one with a second-colour rectangle is not |
| unit | `tests/test_sim_ui.py::test_ready_line` | ANSI-coloured log line with `setup() finished` is detected; other lines are not |
| unit | `tests/test_sim_ui.py::test_outputs_stay_in_esphome_dir` | state, log and shot paths resolve under `REPO_ROOT/.esphome/` |
| unit | `tests/test_devcontainer.py::test_dockerfile_has_xvfb_and_xdotool` | both package names in the apt install list of `.devcontainer/Dockerfile` |
| unit | `tests/test_devcontainer.py::test_sim_ui_script` | `script/sim-ui` executable, contains `uv run python` and `sim_ui.py`; `sim_ui.py` never references `secrets.yaml` |
| unit | `tests/test_ci.py` (or existing CI test file) `::test_checks_requires_sim_ui` | `checks` job env has `GP_REQUIRE_SIM_UI=1`; required job names unchanged |
| host | `tests/test_sim_ui.py::test_sim_headless_shot_and_tap` | skip without `Xvfb`, `xdotool`, a C++ compiler or `sdl2-config` (fail instead when `GP_REQUIRE_SIM_UI=1`); skip if port 6053 is busy (fail with `GP_REQUIRE_SIM_UI=1`); with a temp `ESPHOME_PREFDIR`: `script/sim-ui start` exits 0; `shot home` → PNG 320x240, not `looks_blank`; `tap 280 220`; `shot setup` → 320x240, not blank, and pixel-different from `home` (e.g. > 2 % of pixels changed); `stop` always runs in a `finally`/fixture teardown and leaves no sim or Xvfb process |

## Acceptance criteria
- [x] `uv run pytest -m unit tests/test_sim_ui.py tests/test_devcontainer.py` → all pass (also on a machine without
      Xvfb or X).
- [ ] In the rebuilt devcontainer (default config, no host display): `which Xvfb xdotool` → both found.
- [x] Same container: `script/sim-ui start` → exit 0 and prints the display and a 320x240 window box;
      `script/sim-ui shot home` → prints `.esphome/shots/home.png`, a 320x240 PNG showing the Home page (open it
      and look); `script/sim-ui tap 280 220 && script/sim-ui shot setup` → the Setup page;
      `script/sim-ui stop` → exit 0, and `pgrep -f Xvfb` / `pgrep -f garden-pilot-sim` find nothing.
- [x] `script/sim-ctl set "Sim air temperature" 35` while a session runs, then a shot shows the new value on Home
      (manual check of the combined workflow; record the wait needed in Implementation notes).
- [x] `script/sim-ui start` while a session runs → exit 3 with a clear message; `script/sim-ui tap 320 0` → exit 2;
      `script/sim-ui shot ../x` → exit 2; `script/sim-ui shot` with no session → exit 1.
- [ ] In the SDL devcontainer config: `start` does not touch the desktop display (the display it prints differs from
      `$DISPLAY`) and no stray socket is left in `/tmp/.X11-unix` after `stop`.
- [x] `uv run pytest -m host -k sim_headless` → passes in the devcontainer; on a host without Xvfb it is skipped
      with a reason naming the missing tool.
- [x] `script/lint` and `script/test` green; `git status` shows no new tracked files under `.esphome/`.
- [x] `garden-pilot.yaml`, `garden-pilot-sim.yaml`, `packages/`, `hardware/` unchanged (`git diff --stat` on them is
      empty).
- [ ] CI `checks` is green with the host screen test executed (not skipped) — visible in the pytest summary of the
      job log; record the job duration before/after in Implementation notes. Required check names unchanged.
- [x] `CLAUDE.md` (Commands, Test levels, gotchas), `docs/SPEC.md` §7/§9, `README.md` + `README.ru.md` updated.

No criterion needs real hardware.

## Out of scope
- Reference images and pixel comparison against committed PNG/BMP files (stage 12; needs a decision on font
  rendering stability across ESPHome versions and a tolerance policy).
- `aioesphomeapi` integration scenarios (start a valve over the API, assert relay logs + screen) beyond the manual
  `sim-ctl` check above — next stage 12 task.
- Switching to SDL `headless: true` + `snapshot.take` (needs minimum ESPHome >= 2026.9.0 and has no touch).
- Swipes/long-press/drag gestures, keyboard input, multiple sim instances in parallel, a configurable API port.
- Screenshots on macOS/Windows hosts (Xvfb is Linux-only; the devcontainer covers them).
- Any change to screens, packages or the device firmware.

## Decisions (human, replaces the open questions)
- CI: the screen test runs in a separate, NON-required job `sim-ui` in `ci.yml`, parallel to `checks`, in the
  devcontainer like the other jobs. It is NOT added to `.github/rulesets/master.json` (it may become required later).
  `checks` sets `GP_SKIP_SIM_UI=1` so `script/test` there skips the host screen test (the image has Xvfb, so it would
  otherwise run twice). `tests/test_ci.py` allows non-required jobs: required names stay the ruleset's three.
- Shots (`.esphome/shots/`) are uploaded as a CI artifact on every run (`actions/upload-artifact`, pinned by SHA,
  `if: always()`).
- Display stays 320x240; fixed 640x480 Xvfb is fine.
- Where this contradicts the Files / Checks sections above (`checks` env `GP_REQUIRE_SIM_UI=1`, "CI `checks` green with the
  screen test executed"), the decisions win: `GP_REQUIRE_SIM_UI=1` is set on `sim-ui`, and the criterion applies to `sim-ui`.

## Implementation notes
- `script/sim_ui.py` follows the decided interface. Window found with `xdotool search --onlyvisible --name .` and
  matched by size 320x240; Xvfb picks its display with `-displayfd` (printed by `start`; `:0` in the test container).
- Measured in the container (build cached): host test ~17 s; cold build is 1-2 min more. A shot taken 35 s after
  `sim-ctl set "Sim air temperature" 35` showed `35 C` (Home refreshes every 30 s; wait >30 s).
- Deviations: `checks` sets `GP_SKIP_SIM_UI=1` (not `GP_REQUIRE_SIM_UI=1`) per the human decision; the new job `sim-ui`
  sets `GP_REQUIRE_SIM_UI=1`, 30 min timeout, uploads `.esphome/shots/` as artifact `sim-ui-shots` with
  `actions/upload-artifact` v7.0.1 (SHA from `git ls-remote`). `tests/test_ci.py` got `NOT_REQUIRED_JOBS = {"sim-ui"}`.
  Extra unit test `test_tap_target_is_the_setup_button` and `test_sim_ui_job_*` in test_ci.py.
- The host test ignores zombie processes when checking that nothing is left (a container without an init leaves
  defunct children of the stopped sim/Xvfb under PID 1).
- Verified in the `gp-sim-015` container (Podman): start/shot/tap/stop, exit codes 1/2/3, sim-ctl combination.
  Git-dependent tests (hygiene, parts of layout) cannot run inside that container (worktree `.git` points outside the
  mount); unit tests were run on the host instead.
- Not verified: the SDL devcontainer config criterion (stray socket in the host `/tmp/.X11-unix`), a rebuilt image from
  the changed Dockerfile (packages were installed by hand in the test container), the CI job itself (artifact upload,
  duration), ESPHome minimum version run.
## Follow-ups
- Consider making `sim-ui` required once it has been stable for a while (ruleset + `NOT_REQUIRED_JOBS` in test_ci.py).

## Implementation notes (round 3)
- Ready signal changed (review round 2, Required 1): `script/sim_ui.py::_wait_ready` polls until 127.0.0.1:6053 accepts a TCP
  connection AND the 320x240 window is found via xdotool; the `setup() finished` log line is no longer used (on 2026.6.3
  stdout is block-buffered into sim.log). The sim is also started under `stdbuf -oL -eL` (when available) so sim.log is
  useful while running. Unit tests: `test_wait_ready_needs_port_and_window_not_log`, `test_wait_ready_times_out_and_detects_exit`.
- Verified in gp-sim-015: pinned `GP_REQUIRE_SIM_UI=1 pytest tests/test_sim_ui.py` 19 passed; manual `GP_ESPHOME=minimum`
  (2026.6.3) `start` ready in seconds after build, `shot min_home` shows the Home page, `stop` clean.
