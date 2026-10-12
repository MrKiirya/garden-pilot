# 023 — Review (round 1)

Verdict: APPROVE

Range reviewed: `git diff origin/master HEAD` on `task/023-examples-and-boards` (7 commits, 685b6af..a5ecbaf).

## Checks run
All in the devcontainer `gp-dev-014`, pinned ESPHome:
- `script/lint` → exit 0 (yamllint strict over the repo incl. `examples/`, `esphome config OK: garden-pilot.yaml`).
- `script/test` → `826 passed in 540.00s (0:08:59)` (4 xdist workers). The 6 new config rows are part of it, so `checks`
  stays well under the 15-min budget.
- `git status --porcelain` after the run → no `examples/secrets.yaml`, no build output (only an unrelated untracked
  `tasks/024-*.md` that is not part of this branch).
- Extra, by hand: `examples/beds-with-pump.yaml` with `hardware:` swapped to `../hardware/lilygo-t-relay-s3.yaml`, staged
  in a temp dir outside the checkout with `secrets.example.yaml`, `script/_esphome compile` → `Successfully compiled
  program` (Flash 67.3 %, RAM 35.8 %, 125 s). So `sn74hc595` + esp-idf + the strapping-pin display lines + the pump
  build for ESP32-S3, not only validate. Temp dir removed.
- Vendor facts: fetched `docs/RELAY_ESP32S3.MD`, `ESPHome/T-Relay-ESP32S3-Chain.yaml` and
  `Schematic/T-Relay6-ESP32S3-Rev1.1.pdf` from Xinyuan-LilyGO/LilyGo-T-Relay (main) and read the net labels next to
  H1 by position: IO8-TFT_CS, IO11-TFT_MOSI, IO13-TFT_CLK, IO12-TFT_MISO, IO10-TFT_TP_CS, IO14-TFT_TP_INT,
  IO3-TFT_RST, IO46-TFT_DC, IO9-TFT_BL. H1 order: CS, RST, DC, MOSI, CLK, BL, MISO, CLK, TP_CS, MOSI, MISO, TP_INT,
  i.e. the standard 14-pin ILI9341/XPT2046 order. Shift register DATA 7 / CLOCK 5 / LATCH 6 / nOE 4, RTC 16/17/18,
  CH1-6 = SR1-6, CH7/CH8 = LEDs: these match the profile. (The W5500 table in the vendor doc uses 9/11/13/3/8/12 for a
  different variant; that does not contradict the TFT header.)
- ESPHome source (pinned): `SN74HC595Component` setup priority is `IO` (runs before `GPIOSwitch`'s `HARDWARE`).
  `setup()` drives OE high, clocks out zeros, latches, then drives OE low, so after setup the relays start OFF and
  `ALWAYS_OFF` then holds them OFF. Before setup the state depends on the board's nOE pull-up; the profile lists that
  under "verify on the board", which is right.

## Acceptance criteria
- [x] `uv run pytest -m unit` green incl. the new unit checks: covered by the full `script/test` run (826 passed).
- [x] `script/lint` green: verified, exit 0; `.yamllint` does not exclude `examples/`.
- [x] `script/test` green, 5 new config rows (+ `test_script_config_subdir`) pass, under 15 min: verified (8m59s locally
      with 4 workers).
- [x] `GP_SECRETS=example script/config examples/<file>.yaml` OK for all four: `test_example_validates[*]` runs exactly
      this command and passed.
- [~] Example 1 + LilyGO on `GP_ESPHOME=minimum`: not re-run by me (taken from the implementation notes). I ran a stronger
      pinned check instead (LilyGO + pump example compiles). Acceptable.
- [x] Root compile still builds: not re-run here; CI `compile (pinned)` covers it, and the LilyGO compile above went
      through the same `components/` and packages with `gp_root: ".."`.
- [x] No `examples/secrets.yaml` / build output after the checks: verified with `git status`. `secrets.yaml` and
      `.esphome/` in `.gitignore` match at any depth (`git check-ignore` confirms for `examples/`).
- [x] `grep -rn "source: components" packages/` outside comments: none; `test_gp_root_default` enforces it (5 files).
- [x] CLAUDE.md, README.md, README.ru.md, SPEC §2.2/§4.2/§5/§7/§9/§9.1 updated; both READMEs have the same 8 headings
      and the new "Examples" / "Примеры" section and the layout line match sentence for sentence.
- [ ] Hardware verification: open, as the implementation notes say explicitly (nothing flashed). That is the author's
      checkbox, not a merge blocker.

## Focus points
- **Actuator safety.** Breadboard relays 4-12: `platform: gpio`, `internal: true`, `RESTORE_DEFAULT_OFF`, no `inverted`.
  LilyGO relays 1-12: `internal: true`, `ALWAYS_OFF`, `sn74hc595` pins without `inverted`. `test_board_relays_are_safe`
  (contiguous 1..N, counts 12/12/3) and `test_lilygo_profile` (numbers 0-5/8-13, `ALWAYS_OFF`, no inversion, OE pin
  wired) guard them. The pump in `irrigation_pump.yaml` keeps the component guards (`pump_max_on_time` 2h,
  `pump_idle_timeout` 10s; 2h >= 60 min zone limit), and `test_irrigation_pump_matches` keeps the file equal to
  `irrigation.yaml` apart from those keys and rejects a pump relay that is also a bed relay. The active-low warning is in
  both profiles, all four examples, `examples/README.md`, the README pair, CLAUDE.md and SPEC.
- **Breadboard pins.** 14, 16, 17, 38, 39-42, 5, plus ADC 1/2: none in flash/PSRAM/USB/UART0/strapping, none collide
  with SPI 8/9/10, display 11/12/13, touch 15/18, DHT 4, adc_1 6, soil DO 7 or relays 1-3. `test_breadboard_relay_pins_safe`
  checks the avoid list and that every `*_pin` value is unique. The GPIO38 (RGB LED on v1.1) and JTAG notes are in the table.
- **gp_root.** Works for both roots: the root config uses the package default `"."` (the `full` matrix row and lint),
  the examples use `".."` (4 config rows + my compile). `test_gp_root_default` also asserts the root entry does not
  override it.
- **script/config / script/compile.** The config is staged at its relative path with the secrets next to it. Real
  `examples/secrets.yaml` is used in place; otherwise the root `secrets.yaml` (or the example one) is copied into the
  temp dir (config) or the git-ignored `.esphome/example-build/` (compile). Nothing is written into the checkout. No
  real secrets, paths or IPs in the diff.

## Implementer deviations (judged)
1. **TFT_RST on GPIO3, TFT_DC on GPIO46:** accepted. The vendor schematic wires them that way, and the board cannot be
   used otherwise. GPIO3 only matters for the JTAG-source eFuse. GPIO46 only matters together with GPIO0 low (download
   mode), and the DC line is not driven at reset. The test allows exactly these two keys on 3/46 and still forbids 45/0.
   It is listed under "verify". The compile shows ESPHome accepts them.
2. **`board_backlight` (ALWAYS_ON) on the LilyGO:** accepted. TFT_BL is a real board line and no package handles a
   backlight. It is internal, the exemption in the safety tests is bound to this id and to the LilyGO file, and it is
   asserted as `internal` + `ALWAYS_ON`. See suggestion 4 for a cleaner long-term form.
3. **`lvgl_page_touch_test` kept:** accepted. `page_setup.yaml` navigates to `touch_test_page`, so leaving it out fails
   config. `touch_dot_test` stays out, and `test_examples_exist` asserts that.
4. **Examples drop `gh_screensaver_status` and sensors:** accepted. The status package hard-depends on
   `gh_air_temperature` / `gh_soil_moisture_pct`, the LilyGO profile has no DHT/ADC, and the soil example uses `adc_1`
   per bed. It is documented in every example and in `examples/README.md`, and noted as a follow-up.
5. **Soil example not on LilyGO:** accepted. The board has no analog pins in the profile. This is said in the example
   header and in `examples/README.md`.

## Findings
### Required
None.

### Suggestions
1. `script/config:20,42`, `script/compile:20,44` — `CONFIG` is used as a relative path under the staging dir without a
   check. An absolute path or one with `..` (e.g. `../private/x.yaml`, which the roadmap's private-config stage makes
   likely) gives `cp` to `$TMP_DIR/../private/`, outside the temp dir. That copy is not removed by the trap, and with a
   root `secrets.yaml` present the real secrets are copied there too. An absolute path, which worked before via
   `basename`, now fails confusingly. Direction: reject absolute paths and paths containing `..` with a clear message
   (or normalise to a repo-relative path first), and add a unit-level test of the rejection.
2. `script/compile:36` — the cleanup removes every top-level entry of the stage except `.esphome`, including
   `examples/` and so its nested build dir `examples/.esphome/build/<name>`. Every compile of an example through the
   staged path therefore starts from scratch, against the "reruns are incremental" comment. Direction: keep `.esphome`
   at any depth (e.g. delete only `packages hardware components` and the config file), or point `build_path` at a
   fixed location.
3. `tests/test_examples.py:202` — `test_script_config_subdir` runs the same command as
   `test_example_validates[minimal_1_bed]` and only covers the `GP_SECRETS=example` branch. The two new branches, "real
   `examples/secrets.yaml` used in place" and "root `secrets.yaml` staged next to the config", have no check. Direction:
   a test that runs `script/config` with a fake root `secrets.yaml` in a copied tree (or with `GP_SECRETS` unset and
   `examples/secrets.yaml` absent) and asserts it passes and leaves the tree unchanged. Or drop the duplicate row to
   save ~one LVGL config in CI.
4. `hardware/lilygo-t-relay-s3.yaml` `board_backlight` — a `switch` that is ALWAYS_ON is exempted by id in two tests.
   Longer term, an `output: gpio` + `light: monochromatic`/`binary` or a `display_touch` backlight hook would avoid
   special-casing ids in the actuator safety tests (stage 9/10 follow-up, not for this task).
5. `examples/README.md:23` — "Two things differ" is followed by three bullets. `examples/README.md:55` — "The examples
   have no air and soil sensors of their own" is not true of `soil-sensors.yaml` (it has per-bed probes; it lacks the
   greenhouse-wide ones).
6. `CLAUDE.md:168` — the commands note says subdirectory configs use `secrets.example.yaml` or `examples/secrets.yaml`.
   It omits the third case (root `secrets.yaml` staged next to the config), which the script headers do describe.
7. Breadboard table: GPIO39-42 power up as JTAG pads. The "all 12 LEDs dark at power-on" hardware step already covers
   this, but a one-word "check at reset" note on rows 8-11 (like the GPIO38 one) would point the author at it.

## Follow-ups (not blocking)
- Hardware verification steps 1-6, including the LilyGO nOE pull-up / no-click check and the 0-5/8-13 bit map.
- Sensor-less variant of `screensaver_status.yaml` so the examples get the running-bed indicator back (already listed
  by the implementer).
