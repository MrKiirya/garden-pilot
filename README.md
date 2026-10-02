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

## Run on a PC (emulator)
`script/sim` builds and starts `garden-pilot-sim.yaml`: the same LVGL screens and irrigation packages as the device,
on the ESPHome `host` platform, in a 320x240 SDL window with the mouse as the touchscreen. No hardware is needed
and it **works fully without Home Assistant**: the clock comes from the PC, and RUN/STOP on a bed switches a
simulated relay (every change is logged as `SIM relay_N ON/OFF`) and updates the screen. Sensor values are simulated:
air temperature, air humidity, greenhouse soil moisture and the soil of each bed are settable numbers, shown on Home
and Greenhouse like the real sensors.

- **SIM page:** the `SIM` button (top right of every page) opens a virtual board: live indicators for relay 1..3
  (bed 1..3 valves), one slider per simulated value and the **Sim auto drift** switch (default OFF; when ON soil dries
  1 % per minute and rises 1 % per 10 s while the bed's relay runs).
- **From a terminal:** `script/sim-ctl` talks to the running emulator over the native API (same path as Home
  Assistant): `script/sim-ctl list`, `script/sim-ctl get greenhouse_soil_moisture`,
  `script/sim-ctl set "Sim soil moisture" 35`, `script/sim-ctl switch "Sim auto drift" on`. Options `--host`,
  `--port` (6053), `--key`, `--timeout`; exit code 1 means the emulator is not reachable, 2 a usage or entity error.
  Run it in the same devcontainer, or on the PC against the published port.

- **Where:** in the SDL devcontainer config (above; on rootless Podman, X11 host) or on a desktop host with SDL2
  dev files (`sdl2-config` must exist, even for `esphome config`). Then run `script/sim`; Ctrl+C stops it.
- **Safe to run:** it always builds with `secrets.example.yaml`, never your real `secrets.yaml`. Its API key,
  `sim_api_encryption_key`, is a public dummy: anyone who can reach port 6053 can toggle the simulated relays
  (nothing physical). Never flash this build.
- **Home Assistant (optional):** add the ESPHome integration by the IP of this PC (for example `192.168.x.x`),
  port 6053, key `sim_api_encryption_key` from `secrets.example.yaml`. It appears as a separate device,
  "GardenPilot Sim" (ids get the `gardenpilot_sim_` prefix); there is no mDNS discovery on the host platform. The SDL
  devcontainer publishes port 6053 to the PC's loopback only, which is enough for HA on the same PC. For HA on
  another machine set `GP_SIM_API_BIND=0.0.0.0` on the host before **Rebuild Container** and allow TCP 6053 in the
  host firewall (firewalld on Fedora and Bazzite). Docker on Linux can use `--network=host` instead.
- **Checking the sim config by hand:** `script/config garden-pilot-sim.yaml` and `script/compile garden-pilot-sim.yaml`
  use your real `secrets.yaml` when it exists, which lacks the sim key and fails with "Secret
  'sim_api_encryption_key' not defined". Use `GP_SECRETS=example` or add the public dummy key from
  `secrets.example.yaml` to `secrets.yaml` (`script/sim` always uses the example file).
- If port 6053 is already in use (another emulator or an ESPHome device bridge on this PC), stop that program first.
- Run durations and other preferences are kept in `.esphome/sim-prefs/`. If the window does not appear, check the
  X11 access (`xhost`, above); the runner uses software rendering (`SDL_RENDER_DRIVER=software`) so a container
  without `/dev/dri` does not hang.

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
- `garden-pilot.yaml` — device entry file: a list of packages. `garden-pilot-sim.yaml` — the same packages for the PC emulator.
- `hardware/` — board profile (pins, relay drivers) and `sim.yaml` (PC emulator and config checks without a board); `packages/` — core (API, OTA, network, time), display and touch (device or SDL window), LVGL pages, greenhouse (irrigation, beds, optional bed soil sensor, sensors). One `!include` block per bed in the entry file; at least 2 beds until the own irrigation engine (roadmap stage 7).
- `design/` — design system: rules, colour/type tokens, icons.
- `docs/SPEC.md` — specification, architecture, roadmap.
- `CLAUDE.md`, `.claude/`, `tasks/` — how the project is developed with Claude Code agents.

## License
[MIT](LICENSE)
