# 002 — Devcontainer: reference environment (Docker + rootless Podman, USB on Linux, SDL window)

Status: done (Windows, Docker Engine, macOS deferred)
Roadmap: SPEC §9 stage 2
Spec sections: SPEC §6 (pinned / minimum ESPHome), §7 (host + SDL), §9 (roadmap, edited by this task)
Hardware check: USB flashing of the ESP32-S3 prototype from the container (Linux + rootless Podman) and an OTA
upload from the container. Both need the real board and cannot run in CI. The SDL window check needs a desktop
session but no hardware.

## Goal
A contributor opens the repo in VS Code, runs "Reopen in Container", and gets the same toolchain on Linux,
Windows and macOS: Python 3.13, uv, the ESPHome version pinned in `uv.lock`, the ESP-IDF / PlatformIO caches in
named volumes so they survive rebuilds, SDL2 for the later host + SDL work, and the recommended VS Code
extensions. Docker (Desktop or Engine) and rootless Podman both work. Linux users can optionally pass a USB
serial port into the container. Windows and macOS users do the first flash from the host and OTA from the
container. A second, opt-in config also forwards the host display, so an SDL window started in the container
opens on the Linux desktop. Claude Code is not part of the image. Users who want the Claude Code VS Code
extension can turn it on with a documented user setting, and it stays signed in across rebuilds.

## Context

### Decisions already made with the human (fixed)
1. **Engines:** Docker (Docker Desktop on Windows/macOS, Docker Engine on Linux) and **rootless Podman on Linux**.
   The author runs Bazzite (Fedora atomic, Wayland, SELinux enforcing) with Podman and no Docker, so Podman is
   the required verification target.
2. **Base image:** `mcr.microsoft.com/devcontainers/python` for Python 3.13 (`.python-version`), plus uv.
   ESPHome is installed only by `script/setup` from `uv.lock`. Do **not** use the `esphome/esphome` image and do
   not `pip install esphome` in the Dockerfile.
3. **Caches:** toolchain caches go in named volumes. `.esphome/` stays the in-repo build dir (git-ignored).
4. **USB:** optional serial passthrough on Linux only. When no device is plugged in, the container must still
   start. Windows/macOS: first flash from the host (web.esphome.io in Chrome/Edge, or esptool on the host), then
   OTA from the container. Mention usbipd-win only as a pointer.
5. **SDL, variant A:** install SDL2 dev libraries in the image and forward the host display. Two configs that
   share one Dockerfile: the default config has no display mounts, and an opt-in SDL config adds them. A
   `unit` check keeps the two in sync. 002 only proves that a window opens. The real `host` + `sdl` harness is
   roadmap task "Host + SDL" (stage 11 after the renumbering below).
6. **Editor:** VS Code + Dev Containers extension. `@devcontainers/cli` is for scripted verification only.
   Claude Code is opt-in and not installed in the image.
7. **CI is out of scope** (task 003 builds the devcontainer in CI).
8. **Lightweight end-user path:** out of scope. Record it as a new roadmap item after stage 4 and mention it in
   the READMEs as "planned".

### What was checked (2026-10-01) and how it shapes the design
- **Dev Containers spec** ([containers.dev/implementors/spec](https://containers.dev/implementors/spec/)):
  configs live at `.devcontainer/devcontainer.json`, `.devcontainer.json` or
  `.devcontainer/<folder>/devcontainer.json`. Tools should let the user pick between several configs. VS Code
  shows a picker on "Reopen in Container". `updateRemoteUserUID` (Linux only, on by default) syncs the remote
  user's UID/GID with the host user. `${localEnv:VAR:default}` substitution works in `runArgs`, `mounts` and
  `containerEnv`.
- **VS Code built-in display forwarding:** when `DISPLAY` is set for the local VS Code, Dev Containers forwards
  X11 into the container through its own connection. Logs show "X11 forwarding: DISPLAY in container (:0)
  forwarded to local host". This can't be turned off ([vscode-remote-release#11098](https://github.com/microsoft/vscode-remote-release/issues/11098)).
  The `dev.containers.mountWaylandSocket` user setting (on by default) mounts the host Wayland socket.
  Consequences:
  - Inside VS Code, the **default** config may already be able to open a window. That is fine. The rule
    "no display mounts in the default config" is about the committed file only.
  - `@devcontainers/cli` does **not** forward displays, so the SDL config needs explicit mounts.
  - Some Dev Containers releases have set the wrong `DISPLAY` ([#7983](https://github.com/microsoft/vscode-remote-release/issues/7983)).
    Record which `DISPLAY` a VS Code terminal sees in the SDL config.
- **WSLg** ([microsoft/wslg Containers.md](https://github.com/microsoft/wslg/blob/main/samples/container/Containers.md)):
  containers need `/tmp/.X11-unix` (and `/mnt/wslg` for Wayland) plus `DISPLAY` / `WAYLAND_DISPLAY` /
  `XDG_RUNTIME_DIR`. Under Docker Desktop the WSLg directory is visible from the VM under a different path
  (reported as `/run/desktop/mnt/host/wslg`; unverified). Native WSLg support in Dev Containers was closed as
  "not planned" ([#9387](https://github.com/microsoft/vscode-remote-release/issues/9387)). So on Windows the
  **primary path** is: clone inside a WSL2 distro, open the folder in a "WSL:" window, then "Reopen in
  Container". VS Code forwards the WSLg `DISPLAY` with the default config, and no Windows-specific mounts are
  committed. Add a WSLg config only if someone can verify it on Windows (see Files).
- **macOS:** XQuartz only, best-effort and documented. Launch VS Code with `DISPLAY` set and XQuartz
  "Allow connections from network clients" enabled. No committed config.
- **Rootless Podman:**
  - VS Code needs the user setting `dev.containers.dockerPath: podman`. Do not commit it: it would break Docker
    users.
  - `--userns=keep-id` is needed for correct bind-mount ownership. Docker rejects that value, so it must **not**
    go in `runArgs`. Podman reads the default userns from the `PODMAN_USERNS` environment variable
    ([podman docs, `--userns`](https://docs.podman.io/en/latest/markdown/podman-run.1.html)) or from
    `containers.conf`. Docker ignores both. Making Dev Containers set `PODMAN_USERNS` itself is still backlog
    ([#10399](https://github.com/microsoft/vscode-remote-release/issues/10399)).
  - SELinux blocks a container from reading a home or bind-mounted checkout, the X11 socket, or a passed-in tty
    unless one of two things is done: relabel the files (`:z`/`:Z`, which is Podman/`-v` only and changes labels
    on the host checkout permanently) or use `--security-opt label=disable`. Docker and Podman both accept the
    latter, and hosts without SELinux ignore it. Preferred choice: `runArgs: ["--security-opt",
    "label=disable"]` in all configs, with the trade-off documented (open question 4).
  - `--device-cgroup-rule` is rejected in rootless mode
    ([wolf#477](https://github.com/games-on-whales/wolf/issues/477)). `--group-add keep-groups` is Podman + crun
    only, and Docker rejects it. Neither may appear verbatim in the committed `runArgs`.
- **Claude Code in a dev container** ([code.claude.com/docs/en/devcontainer](https://code.claude.com/docs/en/devcontainer),
  [/vs-code](https://code.claude.com/docs/en/vs-code)):
  - The extension panel runs inside the container (remote extension host) and **bundles its own copy of the
    CLI**. It needs neither Node nor the devcontainer feature. `claude` in the terminal would need a separate
    install, which is not part of this task.
  - Auth: browser sign-in. If the localhost callback doesn't reach the container, paste the code at the
    prompt.
  - State lives in `~/.claude` **and** `~/.claude.json`. To persist both, mount a named volume at `~/.claude`
    and set `CLAUDE_CONFIG_DIR` to that path. The reference config uses `claude-code-config-${devcontainerId}`.
  - The official feature `ghcr.io/anthropics/devcontainer-features/claude-code` installs the CLI and the
    extension for everyone, so it is **not** used.
  - Opt-in per user: the VS Code user setting `dev.containers.defaultExtensions: ["anthropic.claude-code"]`
    ([VS Code docs](https://code.visualstudio.com/docs/devcontainers/containers)) installs the extension in
    every container the user opens. Nothing changes for other users.
- **ESPHome 2026.9.1 toolchains:**
  - Since 2026.7 the ESP32 default toolchain is native ESP-IDF, installed in the machine-global
    `~/.cache/esphome/idf` ([2026.7 release notes](https://esphome.io/blog/2026/07/15/esphome-2026-7/),
    [ESP-IDF guide](https://esphome.io/guides/esp_idf/); override: `ESPHOME_ESP_IDF_PREFIX`).
  - PlatformIO (`~/.platformio`, override `PLATFORMIO_CORE_DIR`) is deprecated for ESP32 (removed in 2027.2).
    It is still what the **minimum supported** ESPHome (≥ 2026.2.3, SPEC §6) uses, and possibly what the
    `host` platform uses.
  - **Both** cache locations therefore get named volumes. The uv cache (`~/.cache/uv`) lands in the same
    `~/.cache` volume.
  - The decision text said `~/.platformio`; the ESP-IDF cache under `~/.cache` was added because of this
    finding.
- **ESPHome legacy dashboard was removed in 2026.7.** The ESPHome Device Builder ships in the HA add-on and in
  the `ghcr.io/esphome/esphome` container ([esphome/device-builder](https://github.com/esphome/device-builder)).
  `docker run esphome/esphome dashboard` from the decision text is outdated. The new roadmap item names the
  Device Builder instead.
- **ESPHome SDL** ([display/sdl](https://esphome.io/components/display/sdl/),
  [host](https://esphome.io/components/host/)):
  - Linux needs `libsdl2-dev build-essential git`. `sdl2-config --libs --cflags` verifies the install.
  - Minimal config: `host:` + `display: - platform: sdl` with `show_test_card: true` and `dimensions`.
  - `esphome run` on `host` compiles and runs the program.
- **uv in Docker** ([docs.astral.sh/uv/guides/integration/docker](https://docs.astral.sh/uv/guides/integration/docker/)):
  - Install with `COPY --from=ghcr.io/astral-sh/uv:<version> /uv /uvx /bin/`, which is pinnable by tag or
    digest. Use this instead of a third-party devcontainer feature.
  - `UV_LINK_MODE=copy` avoids hardlink warnings when the cache sits on a different filesystem (volume).
  - `UV_PROJECT_ENVIRONMENT` moves the venv. The docs advise keeping the platform-specific `.venv` out of a
    bind-mounted project.
- **ESPHome VS Code extension** (`ESPHome.esphome-vscode`): `esphome.validator: local` (default) runs `esphome`
  from `PATH`, so the venv's `bin` must be on `PATH` in the container.
- **devcontainers/python image** ([devcontainers/images](https://github.com/devcontainers/images/tree/main/src/python)):
  tags follow `<image-major>-<python>-<debian>` (e.g. `3-3.13-trixie`). Images are multi-arch (amd64/arm64),
  run as the non-root user `vscode` (UID 1000) with sudo, and include pipx. uv is not preinstalled.

### Design (implement this; deviations must be justified in Implementation notes)
1. **One Dockerfile**, `.devcontainer/Dockerfile`.
   - **Base:** `FROM mcr.microsoft.com/devcontainers/python:<image-major>-3.13-<debian>@sha256:<digest>`.
     The Python minor must equal `.python-version`.
   - **uv:** `COPY --from=ghcr.io/astral-sh/uv:<x.y.z> /uv /uvx /bin/`, using the latest uv release on the
     implementation day.
   - **apt:** `libsdl2-dev`, `build-essential`, `pkg-config`, plus whatever `esphome compile` of the entry file
     proves necessary for native ESP-IDF (e.g. `cmake`/`ninja-build` only if ESP-IDF doesn't fetch its own).
     Each package needs a short comment on why it is there.
   - **Cache dirs:** create `~/.cache` and `~/.platformio` owned by `vscode`, so named volumes copy up the right
     owner.
   - **Serial group:** add `vscode` to `dialout`.
   - **No COPY from the repo.**
   - **Build context:** `.devcontainer/` only, so `secrets.yaml` never enters the context.
2. **Default config `.devcontainer/devcontainer.json`** (strict JSON, no comments, so the test can parse it;
   comments go in the README section):
   - `name`: "GardenPilot".
   - `build`: the shared Dockerfile with `context: "."`.
   - `remoteUser`: `vscode`.
   - `containerEnv`:
     - `UV_PROJECT_ENVIRONMENT` = a venv under the vscode home, outside the workspace, so the host `.venv` is
       never touched.
     - `UV_LINK_MODE=copy`.
     - `UV_PYTHON_DOWNLOADS=never`: a Python mismatch fails loudly.
     - `PATH` with the venv `bin` prepended (via `remoteEnv` if `containerEnv` can't reference `PATH`).
     - `CLAUDE_CONFIG_DIR` = the Claude volume path.
   - `mounts`: named volumes only:
     - `garden-pilot-cache` → `~/.cache`
     - `garden-pilot-platformio` → `~/.platformio`
     - `garden-pilot-claude-${devcontainerId}` → `~/.claude` (inert unless the user enables the extension)
   - `runArgs`:
     - `--security-opt label=disable`.
     - Serial passthrough driven by host env vars with harmless defaults:
       `--device=${localEnv:GP_SERIAL_DEVICE:/dev/null}` and `--group-add=${localEnv:GP_SERIAL_GROUP:vscode}`.
     - Podman users set `GP_SERIAL_GROUP=keep-groups`; Docker-on-Fedora users set the host `dialout` GID.
     - Verify that the defaults don't break startup on any engine you can test. If `--device=/dev/null` turns
       out unreliable, document USB as a Linux-only manual `runArgs` edit instead and say so.
   - `postCreateCommand`: `script/setup`.
   - `customizations.vscode`:
     - `extensions`: `ESPHome.esphome-vscode`, `redhat.vscode-yaml`, `ms-python.python`. **Not**
       `anthropic.claude-code`.
     - `settings`: the `files.associations` from `.vscode/settings.json`, `python.defaultInterpreterPath`
       pointing at the venv, and `esphome.validator: local`.
   - No `features` (fewer moving parts under Podman). If one turns out to be unavoidable, it must be identical in
     every config.
3. **SDL config `.devcontainer/sdl/devcontainer.json`** (Linux host, X11 or Wayland + Xwayland). Identical to the
   default except:
   - `name`: "GardenPilot + SDL window (Linux host)".
   - `build.dockerfile`: `../Dockerfile`; `build.context`: `..`.
   - An extra bind mount `source=/tmp/.X11-unix,target=/tmp/.X11-unix,type=bind`.
   - `containerEnv.DISPLAY` = `${localEnv:DISPLAY::0}`.
   - **No Xauthority mount:** a missing file would break startup. If the X server rejects the client, the
     README documents `xhost +SI:localuser:$(id -un)` on the host. With `keep-id` (Podman) or
     `updateRemoteUserUID` (Docker), the container UID equals the host UID.
   - Native Wayland (`SDL_VIDEODRIVER=wayland`) is optional and documented only.
4. **`script/sdl-smoke`** (POSIX sh, executable). This is the lightest check that exercises the real chain:
   ESPHome `host` build + SDL2 + display forwarding.
   - Writes a ~10-line config into `.esphome/sdl-smoke/` (git-ignored, so builds are cached):
     `esphome: name: sdl-smoke`, `host:`, `display: platform: sdl, show_test_card: true, dimensions 320×240`.
   - Compiles it with `uv run --no-sync esphome compile` and runs the program for a few seconds
     (`GP_SDL_SECONDS`, default 10).
   - Pass = still running at timeout. Fail = early exit. The script fails fast with a clear message when neither
     `DISPLAY` nor `WAYLAND_DISPLAY` is set ("open the repo with the SDL config").
   - It runs on the host too.
   - A C test program was considered and rejected: it wouldn't prove the ESPHome `host` toolchain. The task 11
     harness may replace this script later.
5. **Hygiene check:** `tests/test_public_hygiene.py` flags every absolute path under a user's home in `/home`.
   The base image's `vscode` user home is a fixed, generic container path, not a local one. The devcontainer
   JSON must spell it out (mount targets, venv path), so the check must allow exactly that one user and keep
   flagging every other user name (matcher test below). Task and review files should write `~vscode` instead
   of the absolute path.

## Files
- create: `.devcontainer/Dockerfile` — shared image (base + uv + SDL2 + build deps + cache dirs + `dialout`).
- create: `.devcontainer/devcontainer.json` — default config (works everywhere, no host display mounts).
- create: `.devcontainer/sdl/devcontainer.json` — opt-in Linux SDL config (X11 socket + `DISPLAY`).
- create (only if verified on a real Windows machine): `.devcontainer/sdl-wslg/devcontainer.json`. Docker Desktop
  WSLg mounts for users who don't open the repo from a WSL window. Otherwise list it as a follow-up.
- create: `script/sdl-smoke` — SDL window smoke check (see Design 4).
- create: `tests/test_devcontainer.py` — checks below.
- modify: `tests/test_public_hygiene.py` — allow the `vscode` container user's home only (Design 5).
- modify: `.claude/settings.json` — allow `Bash(script/sdl-smoke)`. The script only builds and runs a local
  window.
- modify: `README.md`, `README.ru.md` — replace "a devcontainer is planned" with a **Development environment**
  section, kept in sync in both languages:
  - Prerequisites per OS.
  - Opening in a container; choosing the SDL config.
  - Podman setup: `dev.containers.dockerPath`, `PODMAN_USERNS=keep-id` and how to give it to a desktop-launched
    VS Code (e.g. `~/.config/environment.d/` or `containers.conf`), and the SELinux note.
  - USB on Linux (`GP_SERIAL_DEVICE` / `GP_SERIAL_GROUP`; prefer the board's UART-bridge port, see Risks).
  - First flash on Windows/macOS (web.esphome.io or host esptool, using the factory image path that `esphome
    compile` prints), then OTA. A usbipd-win pointer.
  - OTA by IP when `.local` doesn't resolve in the container.
  - Optional Claude Code (user setting + what persists).
  - One or two lines: lightweight end-user path is planned.
- modify: `CLAUDE.md`:
  - Layout table: add `.devcontainer/`.
  - Environment: the devcontainer is the reference; drop "roadmap task 002. Until then"; keep plain uv as the
    alternative.
  - Commands: add `script/sdl-smoke` and the `devcontainer up/exec` verification commands.
  - Legacy note: "roadmap stages 4–5" → "roadmap stages 4 and 6" after the renumbering.
- modify: `docs/SPEC.md`:
  - §9: item 2 rewritten to describe what exists (two configs, engines, USB/SDL scope, Windows/macOS flashing).
  - §9: new item **5. Lightweight end-user path** after item 4: ESPHome Device Builder (HA add-on or the
    `ghcr.io/esphome/esphome` container) + remote packages from this repo + first flash via web.esphome.io,
    then OTA; no devcontainer needed; depends on stage 4.
  - §9: renumber the old 5–10 to 6–11.
  - §11: add the sources checked here.

Count: 12 files, but four of them are small doc edits (one coherent goal). If the implementer can't finish
everything in one run, stop after the configs, tests and README section, and leave CLAUDE.md/SPEC edits for a
follow-up in the same PR.

## Checks to write first
All checks are `unit` (no toolchain, no container engine) and go in `tests/test_devcontainer.py` unless noted.
"Variant" means every `.devcontainer/*/devcontainer.json`.

| Level | Test | Asserts |
|---|---|---|
| unit | `test_configs_are_strict_json` | the default config and every variant parse with `json.loads` |
| unit | `test_variants_share_the_image` | `build.dockerfile` and `build.context` of each variant resolve to the same file / dir as the default; same `build.args` |
| unit | `test_build_context_is_devcontainer_dir` | resolved build context is `.devcontainer/` (repo root and `secrets.yaml` never enter it) |
| unit | `test_variants_differ_only_in_display_settings` | after removing `name`, display bind mounts and the display keys of `containerEnv` (`DISPLAY`, `WAYLAND_DISPLAY`, `XDG_RUNTIME_DIR`, `SDL_VIDEODRIVER`, `PULSE_SERVER`), each variant equals the default: same `features`, named-volume mounts, other env, `remoteUser`, `runArgs`, `postCreateCommand`, `customizations` |
| unit | `test_default_has_no_host_display` | default config: no `type=bind` mounts, no display keys in `containerEnv`/`remoteEnv`, no `X11-unix` / `wslg` / `XAUTHORITY` anywhere |
| unit | `test_caches_are_named_volumes` | default config mounts named volumes at `~/.cache` and `~/.platformio` of the remote user |
| unit | `test_run_args_are_engine_neutral` | no `--userns`, `keep-id`, `keep-groups` (literal), `--device-cgroup-rule`, `--privileged`, `--network=host` in `runArgs`; every `--device` / `--group-add` value comes from `${localEnv:…:default}` with a default |
| unit | `test_base_image_matches_python_version` | Dockerfile `FROM mcr.microsoft.com/devcontainers/python:` tag contains `.python-version`'s `3.13`, has an image-major prefix, and is pinned with `@sha256:` |
| unit | `test_uv_is_pinned` | Dockerfile copies uv from `ghcr.io/astral-sh/uv:<x.y.z>` (exact version or digest, not `latest`) |
| unit | `test_esphome_comes_only_from_uv_lock` | no `esphome/esphome` image and no `pip`/`pipx`/`uv pip install esphome` in `.devcontainer/`; `postCreateCommand` runs `script/setup` |
| unit | `test_venv_is_outside_workspace` | `UV_PROJECT_ENVIRONMENT` is absolute, not under the workspace folder; `python.defaultInterpreterPath` and the `PATH` entry point into it |
| unit | `test_claude_code_is_not_installed_by_default` | no `anthropics/devcontainer-features`, no `claude` install in the Dockerfile, no `anthropic.claude-code` in `extensions`; `CLAUDE_CONFIG_DIR` equals the `~/.claude` volume target |
| unit | `test_vscode_associations_are_carried_over` | `files.associations` in `customizations.vscode.settings` contains every entry of `.vscode/settings.json` |
| unit | `test_no_secrets_in_image` | Dockerfile has no `COPY`/`ADD` of repo files and no `secrets` / `!secret` / `.env` mention |
| unit | `tests/test_public_hygiene.py::test_local_path_matcher` (extend) | a path under the `vscode` user's home is **not** flagged; the same path for any other user name (e.g. `alice`, `vscodex`) still is |

Commit the checks before the configs (separate `test:` commit), so the PR shows them failing first.

## Acceptance criteria
Mechanical (any Linux shell with uv; these will move to CI in task 003):
- [x] `uv run pytest -m unit tests/test_devcontainer.py tests/test_public_hygiene.py` → all pass.
- [x] `script/lint` and `script/test` → green on the host.
- [x] `git ls-files --stage script/sdl-smoke` → mode `100755`.
- [x] `git grep -n "stages 4–5"` → no hits; SPEC §9 is numbered 1–11 without gaps; the Device Builder item
  is number 5.
- [x] `git grep -n -i "devcontainer is planned\|devcontainer в планах"` → no hits.

Manual, required: author's Linux machine, **rootless Podman**, SELinux enforcing. Record the OS, Podman,
VS Code and Dev Containers versions in the review.
- [x] With `PODMAN_USERNS=keep-id`, no serial device plugged in and `DISPLAY` unset:
  `devcontainer up --workspace-folder . --docker-path podman` (default config) starts.
- [x] `devcontainer exec --workspace-folder . --docker-path podman uv run esphome version` → `Version: 2026.9.1`.
  `command -v esphome` points into the venv outside the workspace. The host `.venv/pyvenv.cfg` is unchanged.
- [x] `devcontainer exec … script/lint` and `… script/test` → green inside the container.
- [x] A file the container creates in the workspace (e.g. under `.esphome/`) is owned by the host user
  (`stat -c %U` on the host).
- [x] `uv run esphome compile garden-pilot.yaml` (real `secrets.yaml` from the workspace) succeeds in the
  container. After `devcontainer up --remove-existing-container`, a second compile does not download ESP-IDF
  again. Record both durations and `podman volume ls`.
- [x] `podman image history` of the built image shows no repo files and no secrets.
- [x] SDL config: `devcontainer up --config .devcontainer/sdl/devcontainer.json …` then
  `devcontainer exec … script/sdl-smoke` → a 320×240 test-card window opens on the desktop and the script
  exits 0. The same works from a VS Code terminal; record the `DISPLAY` value there.
- [x] Default config via CLI: `script/sdl-smoke` exits non-zero with the "use the SDL config" message.
- [x] VS Code "Reopen in Container" offers both configs. The recommended extensions are installed, the ESPHome
  extension validates `garden-pilot.yaml` with the local validator, and `secrets.yaml` is not treated as a
  device.
- [x] Claude, opt-in:
  - Without the user setting: no Claude extension in the container and `command -v claude` fails.
  - With `dev.containers.defaultExtensions: ["anthropic.claude-code"]`: the panel works inside the container,
    sign-in succeeds (callback or pasted code), and the session is still signed in after a rebuild.
- [x] **Hardware:** with the board on the UART-bridge port (`/dev/ttyUSB*` or, for CH343/CH9102, `/dev/ttyACM*`;
  verified with a CH343 on `/dev/ttyACM0`), `GP_SERIAL_DEVICE=<port>` and `GP_SERIAL_GROUP=keep-groups` (host user
  in `dialout`): `uv run esphome run garden-pilot.yaml --device <port>` flashes and shows logs. Also try the native-USB `ttyACM` port and record the result (see Risks).
- [x] **Hardware:** OTA from the container: `uv run esphome upload garden-pilot.yaml --device <device IP>`
  succeeds. Record whether `garden-pilot.local` resolves inside the container.

Manual, author-verified (Linux + Docker Engine, Windows) or best-effort (macOS). Each item is checked or explicitly marked "not tested" in the review:
- [ ] (not tested, deferred) Linux + Docker Engine: default and SDL configs start; `script/test` green; USB with
  `GP_SERIAL_GROUP=<host dialout GID>`.
- [ ] (DEFERRED by the author, follow-up) Windows 11 + Docker Desktop (WSL2): repo cloned in a WSL distro, opened from a "WSL:" window, default
  config; `script/test` green; `script/sdl-smoke` window via WSLg; the container starts with no serial variables
  set.
- [ ] (not tested, deferred) macOS + Docker Desktop: default config starts (arm64 if Apple Silicon); `script/test` green; SDL via
  XQuartz attempted.

### Manual verification (author, 2026-10-02)
Linux (Bazzite), rootless Podman, SELinux enforcing, VS Code installed as a regular (layered) package:
- "Reopen in Container" with the SDL config: OK; the `script/sdl-smoke` window was seen by a person.
- ESP-IDF cache survives "Rebuild Container": first compile long, second near-instant.
- Claude Code via `dev.containers.defaultExtensions`: sign-in persists across "Rebuild Container".
- USB flash from the container: the board's UART bridge is a WCH CH343 (USB id 1a86), which appears as
  `/dev/ttyACM0` (cdc_acm), not `ttyUSB`. Launched with `GP_SERIAL_DEVICE=/dev/ttyACM0 GP_SERIAL_GROUP=keep-groups`: flashed OK.
- OTA by IP and `esphome logs --device <IP>` from the container: OK.
- The default (non-SDL) config was not reopened separately in the VS Code UI; it was built and started via the CLI
  (implementer and reviewer runs).
- Native-USB (Espressif USB JTAG) port: not tried separately (best-effort, documented).

### Explicit deferrals (the task closes with these)
- **Windows 11 + Docker Desktop (WSL2): DEFERRED** by the author to a follow-up task; not verified. No `sdl-wslg` config.
- **Linux + Docker Engine: not tested** (follow-up / reports welcome).
- **macOS: not tested** (ships documented as untested).

## Risks to watch
- **Native USB re-enumeration under rootless Podman:** `--device` bind-mounts the host node, and an ESP32-S3
  `ttyACM` port disappears and reappears on reset. The container may then hold a stale node. Recommend the
  UART-bridge port (`ttyUSB`). Fallback for everyone: compile in the container, flash the factory image from the
  host.
- **mDNS** doesn't cross Docker's NAT bridge or Podman's user-mode networking reliably. Document OTA/logs by IP.
  `--network=host` is not used: it's Linux-only and not engine-neutral.
- **VS Code's own X11 forwarding** may override `DISPLAY` in VS Code terminals. Both routes must open the
  window; record which one is in effect.
- **`updateRemoteUserUID` with `keep-id`** when the host UID ≠ 1000: volume contents may keep the old owner.
  Note it in the README if seen.
- **SDL renderer without GPU:** if the window fails with a GL error, add the minimal Mesa package or set
  `SDL_RENDER_DRIVER=software` in `script/sdl-smoke`, not globally.

## Out of scope
- CI that builds or uses the devcontainer, Dependabot for the base image and uv (task 003). Until then, bump
  the image by editing the tag + digest in `.devcontainer/Dockerfile` (`docker buildx imagetools inspect` /
  `skopeo inspect` for the digest) and uv by editing its tag, in a `chore(deps):` PR that reruns the manual
  Podman checks.
- The real `host` + `sdl` test harness, headless screenshots, `hardware/sim.yaml` (roadmap "Host + SDL", stage 11
  after renumbering).
- The lightweight end-user path itself (new roadmap stage 5).
- Installing the `claude` CLI in the image, the Claude devcontainer feature, an egress firewall.
- usbipd-win setup beyond a link; Codespaces; JetBrains / other editors.
- Native Wayland SDL by default; GPU passthrough.
- Legacy firmware YAML (unchanged).

## Decisions
Human decisions that resolve the open questions (recorded before implementation):
1. **VS Code:** only the regular install (native package or vendor download) is supported. Flatpak VS Code is not
   supported: the README has at most one sentence pointing to the upstream workaround, and the repo ships no
   `flatpak-spawn` wrapper.
2. **USB on Linux:** both UART-bridge (`/dev/ttyUSB*`) and native USB (`/dev/ttyACM*`) ports are supported. The
   UART bridge is the primary documented path; native USB is best-effort, with a short note on what to do if the
   port disappears after a reset. Windows/macOS: first flash from the browser (web.esphome.io) or the host, then
   OTA from the container (by IP).
3. **Platforms:** Linux (Docker and rootless Podman) and Windows (Docker Desktop + WSL2) are verified manually by
   the author; macOS ships documented as untested ("reports welcome"). The README states which platforms were
   verified. The manual Linux and Windows checks below are required acceptance criteria; the macOS one is not.
4. **Planner defaults accepted:** Claude config volume + `CLAUDE_CONFIG_DIR` stay in the shared config;
   `--security-opt label=disable` (no `:z` relabel); Debian trixie base pinned by tag + digest, bumped manually
   until Dependabot (task 003); `script/sdl-smoke` stays until the stage-11 host + SDL harness replaces it; one
   task for all 12 files.

Still open: none.

<!-- Filled in by implementer -->
## Implementation notes
- Checks written first (17 failed for missing files), then configs. `tests/test_devcontainer.py` also has two extra
  checks (SDL variant forwards X11 without Xauthority; `script/sdl-smoke` is executable).
- Base image `devcontainers/python:3-3.13-trixie` pinned to the multi-arch index digest (amd64 + arm64); uv 0.12.21.
  apt: `build-essential`, `git`, `libsdl2-dev`, `pkg-config` only: the ESP-IDF compile of the entry file was not
  run in the container, so `cmake`/`ninja` were not added (the sdl-smoke host build compiled fine).
- Mechanical items ticked above were verified on the host (lint, test, grep, mode). `git ls-files --stage` shows
  nothing until the file is committed: mode is `100755` on disk (`chmod +x`); the main session should confirm
  after `git add`.
- `PATH` is set in `remoteEnv` (`${containerEnv:PATH}`); the venv is `~vscode/.venv-garden-pilot`, outside the
  workspace.
- `script/sdl-smoke`: SDL programs ignore SIGTERM while a window is open (the script hung in `wait`), so it escalates
  to SIGKILL. ESPHome `host` keeps running when SDL cannot open a window, so the script also greps the log for
  display errors (X11 "Authorization required" gave a false pass before). `GP_SDL_SECONDS` is a variable of the
  exec'd shell, not forwarded by `devcontainer exec`: set it inside (`sh -c 'GP_SDL_SECONDS=5 ...'`).
- Verified in this run on the author's Bazzite machine, rootless Podman 5.8.7 + `@devcontainers/cli` via npx
  (`PODMAN_USERNS=keep-id`, SELinux enforcing, `DISPLAY` unset): default config `up` succeeds with no serial
  device (`--device=/dev/null`, `--group-add=vscode` defaults are harmless); `esphome version` = 2026.9.1,
  `command -v esphome` in the venv outside the workspace, host `.venv` untouched; `script/lint` and `script/test`
  green inside (159 passed); workspace files owned by the host user; no Claude binary, `~/.claude` volume owned by
  `vscode`; default config `script/sdl-smoke` exits non-zero with the SDL-config message; SDL config `up` succeeds
  and `script/sdl-smoke` compiled the host build and ran with a window after `xhost +SI:localuser:$(id -un)` (the
  program printed only GL driver warnings; a window was not looked at by me). Test containers, volumes and
  images were removed afterwards.
- **Verified later:** the reviewer compiled `garden-pilot.yaml` in the container (ESP-IDF downloads its own cmake;
  ninja comes from the venv, so neither is in the image) and checked `podman image history`; the author verified
  VS Code "Reopen in Container", the SDL window, cache reuse across a rebuild, Claude sign-in persistence, USB flash
  and OTA (see "Manual verification").
- **Not verified:** the native-USB (Espressif USB JTAG) port; extensions reuse from the extensions volume in VS
  Code; Docker Engine; Windows + Docker Desktop; macOS.
- The Windows `sdl-wslg` config was not created (no Windows machine here): follow-up.

## Follow-ups
- Windows (Docker Desktop + WSL2) verification, and Docker Engine on Linux (deferred by the author).
- Added after the first review: named volume `garden-pilot-vscode-extensions` (extensions survive rebuilds) in both
  configs, required by the sync test.
- `.devcontainer/sdl-wslg/devcontainer.json` only if verified on Windows.
- The base image bump process has no automation until task 003 (Dependabot).
