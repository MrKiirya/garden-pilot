# GardenPilot

[Русская версия](README.ru.md)

ESPHome controller for a garden plot: irrigation of greenhouse beds and lawn, bed heating, soil and air
sensors, a 320×240 touch screen (LVGL) and full Home Assistant integration through the native ESPHome API.
Built to be repeated: features are packages you switch on by uncommenting a line.

> **Status:** work in progress, not ready for use yet. Today: a prototype on an ESP32-S3 with an ILI9341 touch
> display, three greenhouse bed valves on the ESPHome `sprinkler` controller, soil moisture and air sensors.
> Plans and open questions: [docs/SPEC.md](docs/SPEC.md).

## Quick start (development)
Requires [uv](https://docs.astral.sh/uv/getting-started/installation/) (a devcontainer is planned).

```sh
script/setup                          # installs the pinned ESPHome, pytest, yamllint
cp secrets.example.yaml secrets.yaml  # then put your real Wi-Fi, API key and OTA password in it
script/lint                           # yamllint + esphome config
script/test                           # repo checks
uv run esphome run garden-pilot.yaml  # build and flash (USB the first time, then OTA)
```

## Repository
- `garden-pilot.yaml` — device entry file: a list of packages.
- `packages/` — network, display and touch, LVGL pages, greenhouse (irrigation, sensors).
- `design/` — design system: rules, colour/type tokens, icons.
- `docs/SPEC.md` — specification, architecture, roadmap.
- `CLAUDE.md`, `.claude/`, `tasks/` — how the project is developed with Claude Code agents.

## License
[MIT](LICENSE)
