# GardenPilot

[![CI](https://github.com/MrKiirya/garden-pilot/actions/workflows/ci.yml/badge.svg?branch=master)](https://github.com/MrKiirya/garden-pilot/actions/workflows/ci.yml)

[Русская версия](README.ru.md)

ESPHome controller for a garden plot: irrigation of greenhouse beds and lawn, bed heating, soil and air
sensors, a 320×240 touch screen (LVGL) and full Home Assistant integration through the native ESPHome API.
Built to be repeated: features are packages you switch on by uncommenting a line.

> **Status:** work in progress, not ready for use yet. Today: a prototype on an ESP32-S3 with an ILI9341 touch
> display, three greenhouse bed valves on the ESPHome `sprinkler` controller, soil moisture and air sensors.
> Plans and open questions: [docs/SPEC.md](docs/SPEC.md).

## Quick start (development)
Requires [uv](https://docs.astral.sh/uv/getting-started/installation/) (or use the devcontainer below).

```sh
script/setup                          # installs the pinned ESPHome, pytest, yamllint
cp secrets.example.yaml secrets.yaml  # then put your real Wi-Fi, API key and OTA password in it
script/lint                           # yamllint + esphome config
script/test                           # repo checks
uv run esphome run garden-pilot.yaml  # build and flash (USB the first time, then OTA)
```

## Development environment
The reference environment is a **devcontainer** (VS Code + the Dev Containers extension): Python 3.14, uv, the
ESPHome version pinned in `uv.lock`, SDL2, and the ESP-IDF / PlatformIO caches in named volumes. Plain `uv` on the
host (see Quick start) works too.

**Verification status:** verified by the author on Linux with rootless Podman (SELinux enforcing) in VS Code,
including USB flashing and OTA from the container. Windows (Docker Desktop + WSL2) is not verified yet; Docker
Engine on Linux and macOS are untested (reports welcome). Only the regular VS Code install is supported; Flatpak
VS Code needs the upstream workaround for talking to the host container engine, which this repo does not ship.

1. Install VS Code, the Dev Containers extension and Docker (Desktop, or Engine on Linux) or Podman.
2. Open the repo, run **Dev Containers: Reopen in Container** and pick a config:
   - **GardenPilot**: the default; works everywhere, no host display mounts.
   - **GardenPilot + SDL window (Linux host)**: also mounts the X11 socket so `script/sdl-smoke` can open a window.
     If the X server refuses the connection, run `xhost +SI:localuser:$(id -un)` on the host.
3. `script/setup` runs automatically. Then `script/lint`, `script/test`, `uv run esphome compile garden-pilot.yaml`.

**Windows:** clone the repo inside a WSL2 distro, open it from a "WSL:" window, then reopen in the container.
**macOS:** SDL needs XQuartz ("Allow connections from network clients") and VS Code started with `DISPLAY` set.

**Rootless Podman (Linux):** set the VS Code user setting `dev.containers.dockerPath` to `podman`, and give VS
Code the environment variable `PODMAN_USERNS=keep-id` (for example in `~/.config/environment.d/podman.conf`, then
log in again), so files created in the container belong to you. The configs use `--security-opt label=disable`
so SELinux does not block the checkout; the trade-off is that the container is not label-confined.

**USB on Linux (optional).** A UART bridge is not always `ttyUSB`: CH340 and CP210x show up as `/dev/ttyUSB*`,
CH343 and CH9102 as `/dev/ttyACM*` (cdc_acm). Identify the port with `ls -l /dev/serial/by-id/` (bridge vendor
name versus "Espressif USB JTAG") and prefer the board's UART-bridge connector. With the board plugged in, start
VS Code from a terminal with the variables set, for example:
`GP_SERIAL_DEVICE=/dev/ttyACM0 GP_SERIAL_GROUP=keep-groups code .` (`keep-groups` for Podman, your user must be in
`dialout`; use the host `dialout` GID for Docker). Without the variables the container starts with no serial
device. If `GP_SERIAL_DEVICE` is set but the board is unplugged, container creation fails, so set the variables
only when flashing over USB. After the first flash, OTA needs no USB. Using the native USB port (Espressif USB
JTAG) is best-effort: the port disappears and
reappears on reset, and the container may keep a stale node. If that happens, restart the container, or compile
in the container and flash the factory image from the host.

**Windows / macOS flashing:** the container cannot see USB. Flash the first time from the host (the factory image
path is printed by `esphome compile`; use https://web.esphome.io in Chrome/Edge or esptool on the host; for
Windows, usbipd-win can attach USB to WSL). After that, upload over the air from the container **by IP**:
`uv run esphome upload garden-pilot.yaml --device <device IP>`. mDNS (`.local`) often does not resolve in a
container, so use the IP for OTA and logs everywhere.

**Optional: Claude Code.** It is not installed in the image. To get the VS Code extension in every container, add
`"dev.containers.defaultExtensions": ["anthropic.claude-code"]` to your user settings; sign-in persists across
rebuilds in a named volume. Once installed, the extension stays in the extensions volume even if you remove
the setting; reset that volume (below) to drop it.

**Extensions volume:** VS Code server extensions live in the named volume `garden-pilot-vscode-extensions`, so they
are not reinstalled on every rebuild. If an extension breaks, remove the container and run
`podman volume rm garden-pilot-vscode-extensions` (`docker volume rm ...` for Docker), then rebuild.

**Updating the base image or uv:** Dependabot proposes tag and digest bumps for `.devcontainer/Dockerfile`; after merging one, rebuild the container.

A lightweight path for end users (ESPHome Device Builder + remote packages, no devcontainer) is planned.

## CI
Every pull request and every push to `master` runs, inside the devcontainer image: `script/lint` and `script/test`
(job `checks`), and a real ESP32 firmware compile with the pinned ESPHome and with the lowest supported one
(`compile (pinned)`, `compile (minimum)`; the minimum is `esphome-minimum` in `pyproject.toml`). A weekly canary
builds against the newest stable ESPHome and opens (or closes) a `canary-failure` issue. Dependabot proposes
updates for actions, Python dev dependencies (incl. ESPHome) and devcontainer images. CI covers Docker Engine on
Linux for the non-interactive path only.

Reproduce locally: `script/lint`, `script/test`, `GP_SECRETS=example script/compile`, and
`GP_ESPHOME=minimum GP_SECRETS=example script/compile` for the lowest supported ESPHome.

## Repository
- `garden-pilot.yaml` — device entry file: a list of packages.
- `packages/` — network, display and touch, LVGL pages, greenhouse (irrigation, sensors).
- `design/` — design system: rules, colour/type tokens, icons.
- `docs/SPEC.md` — specification, architecture, roadmap.
- `CLAUDE.md`, `.claude/`, `tasks/` — how the project is developed with Claude Code agents.

## License
[MIT](LICENSE)
