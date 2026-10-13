# Examples

Four complete device configs. Each is an entry file like `garden-pilot.yaml`: ESP32 + ILI9341 display + XPT2046
touch, the LVGL pages and the greenhouse page, Home Assistant API, one watering schedule slot. They use the shared
`packages/`, `hardware/` and `components/` of this repository through relative paths.

| File | What it is |
|---|---|
| [`minimal-1-bed.yaml`](minimal-1-bed.yaml) | The smallest working device: one bed on relay 1. No sensors, no pump. |
| [`beds-with-pump.yaml`](beds-with-pump.yaml) | Three beds one at a time (relays 1-3) and a shared pump on relay 4. |
| [`soil-sensors.yaml`](soil-sensors.yaml) | Three beds with a soil moisture probe each; a bed is skipped when its soil is wetter than 60 %. |
| [`relay-module-8ch.yaml`](relay-module-8ch.yaml) | A generic 8-channel relay module: eight beds one at a time. |

All of them use the breadboard board profile (`hardware/esp32-s3-devkitc1-breadboard.yaml`, up to 12 relay outputs).

## Use one

```sh
cp secrets.example.yaml examples/secrets.yaml     # git-ignored; fill in your values
uv run esphome run examples/minimal-1-bed.yaml
```

Two things differ from the root `garden-pilot.yaml`:

- **`!include` paths start with `../`** (`../packages/...`, `../hardware/...`): they resolve relative to the file
  that contains them.
- **`gp_root: ".."`** in `substitutions:` tells the packages where the repository root is. ESPHome resolves the
  `external_components` source (`components/`) and the screensaver font against the directory of the entry file, so
  the packages write `${gp_root}/components` and `${gp_root}/packages/lvgl/fonts/...` (default `"."`).
- **Secrets** (`!secret`) are read from `secrets.yaml` next to the config file: `examples/secrets.yaml`.

`script/config examples/<file>.yaml` and `script/compile examples/<file>.yaml` handle this (with
`GP_SECRETS=example` they stage a copy with the example secrets, nothing is written into the checkout).

## Relay modules: high-level trigger only

Active-low relay modules are **not supported**: they energise while the ESP32 resets and boots. Use a module with a
high-level trigger, or set its trigger jumper to H.

## Another board

Change the one `hardware:` include. Relay numbers stay 1..12 on both profiles:

```yaml
  hardware: !include ../hardware/lilygo-t-relay-s3.yaml
```

`hardware/lilygo-t-relay-s3.yaml` drives the LilyGO T-Relay-S3 (6 relays) and its 6-relay expansion through 74HC595
shift registers, with the display board on the soldered header. It has no analog pins, so it does not suit
`soil-sensors.yaml`. It is config-checked only (not run on a real board yet): read its header first.

## Limits until roadmap stage 9

The greenhouse page, the valve test and the screensaver show beds 1-3 only. `relay-module-8ch.yaml` has eight beds:
beds 4-8 work from Home Assistant and the schedule but not from the touch screen. The examples have no air and soil
sensors of their own, so they leave out `gh_screensaver_status` (its status line reads those sensors); add
`gh_sensors_air` / `gh_sensors_soil` / `gh_screensaver_status` as in `garden-pilot.yaml` if you wire them.
