# 007 — PC emulator, part 2: simulated sensors, SIM board page, auto drift, `script/sim-ctl`

Status: in-review
Roadmap: SPEC §9 stage 6 "PC emulator (host + SDL)", part 2 of 2 (part 1 = task 006)
Spec sections: SPEC §5 (sim board, layout), §7 items 4–6, §9; CLAUDE.md core principles 2, 3, 4, 5, 7;
ESPHome security baseline; design/README.md (Colour, Type, Layout)
Hardware check: none on the device (the device config must not change, proven by a normalized config diff). The
emulator window, sliders and `script/sim-ctl` are checked by the author on a PC, not in CI.
Base: branch `task/007-sim-board` is stacked on `task/006-pc-emulator`. Plan against the 006 task file (its files may
still change); if a 006 file named below has a different final name, follow 006's final state and note it.

## Goal
In the emulator (`script/sim`), sensor values are no longer placeholders: air temperature, air humidity, greenhouse
soil moisture and the soil moisture of each bed come from **settable template numbers** (the single source of truth),
exposed over the native API with the same sensor ids and names as on the device. A sim-only **SIM board** LVGL page,
reached by a sim-only `SIM` button, shows the virtual board: relay 1..3 indicators named by board function with live
ON/OFF, one slider per simulated value, and a **Sim auto drift** switch (default OFF; when ON soil slowly dries and
rises while the bed's relay runs). `script/sim-ctl` lists, reads and sets entities of the running emulator over the
native API (the same path as Home Assistant and future scenario tests). `garden-pilot.yaml` and every package it
includes are byte-for-byte unchanged.

## Context

### State after task 006 (planned names)
- `garden-pilot-sim.yaml`: `hardware` (`hardware/sim.yaml`) → `core_api` → `core_time_host` → `display_sdl` →
  `lvgl_base` → `lvgl_page_home` → `lvgl_page_touch_test` → `lvgl_page_lawn` → `gh_irrigation` → `gh_bed_1..3` →
  `gh_lvgl_page` → `gh_sprinkler_lvgl` → `touch_dot_test`. No greenhouse sensors, no `bed_soil.yaml`, no `web_server`
  (not supported on `host`). Only secret: `sim_api_encryption_key` (public dummy in `secrets.example.yaml`).
- `hardware/sim.yaml`: `host:` + `board_relay_1..3` (template, internal, optimistic, `ALWAYS_OFF`).
- `tests/test_config_matrix.py`: `Variant.source`; rows `sim_full`, `sim_no_touch_debug` (SDL skip unless
  `GP_REQUIRE_SDL=1`), `sim_api_only` (never skipped). `tests/test_layout.py::test_sim_entry_file`,
  `test_sim_beds_match_device`.
- API: port 6053, published to PC loopback from the SDL devcontainer; tools inside the container use `127.0.0.1:6053`.

### Device sensors the sim mirrors (unchanged by this task)
- `packages/greenhouse/sensors_air_dht.yaml`: `gh_air_temperature` "Greenhouse air temperature" (1 decimal),
  `gh_air_humidity` "Greenhouse air humidity" (1 decimal); `on_value` updates `gh_home_air_t_label` (`"%.0f C"`),
  `gh_greenhouse_t_label` (`"Air: %.1f C"`), `gh_home_air_rh_label` (`"%.0f%%"`), `gh_greenhouse_rh_label`
  (`"RH: %.0f %%"`).
- `packages/greenhouse/sensors_soil.yaml`: `gh_soil_moisture_pct` "Greenhouse soil moisture" (`%`, 0 decimals,
  `device_class: moisture`); `on_value` updates `gh_home_soil_bar` (0–100) and `gh_greenhouse_soil_hint`
  (`"Soil: %.0f %%"`). Also `gh_soil_moisture_do` (gpio binary sensor) — **not** simulated (out of scope).
- `packages/greenhouse/bed_soil.yaml`: `gh_bed${bed}_soil_moisture` "${bed_name} soil moisture" (`%`, 0 decimals,
  moisture). Not shown on any LVGL page today.

### Decision vs. the 006 outline (author's newer constraint wins)
The 006 outline proposed moving the sensors' LVGL updates out of `on_value` into a shared polled
`packages/greenhouse/sensors_lvgl.yaml`, which changes the device. The author now requires **no device config
change**, so 007 does **not** touch device packages: the sim gets its own polled label updater
(`packages/sim/sensors_lvgl.yaml`, same text formats, header "keep in sync with sensors_air_dht.yaml /
sensors_soil.yaml"). The shared display path for device + sim (which also fixes the "`on_value` before LVGL is
ready" gotcha on the device) becomes a follow-up with its own hardware check.

### ESPHome behaviour checked (pinned 2026.9.1; minimum 2026.6.3 — re-verify the starred items on minimum in step 0)
- LVGL widgets ([esphome.io/components/lvgl/widgets](https://esphome.io/components/lvgl/widgets/)): `slider` has
  `on_value` (user or programmatic), `on_change` (user only, `x` = new value), `on_release`; `lvgl.slider.update`
  sets `value`. `switch` widget / `checkbox` have `on_change` with `x` = checked state; state set with
  `lvgl.widget.update: state: checked:`. LVGL also offers `number: platform: lvgl` / `switch: platform: lvgl`
  (widget-backed entities) — **not used**, because the source of truth must exist without LVGL (`sim_api_only`).
- `lvgl: top_layer:` (widgets drawn above every page) — not used by any package today, so no merge conflict. *
- Template number (`platform: template`): `optimistic`, `min_value`, `max_value`, `step`, `initial_value`,
  `restore_value`; actions `number.set`, `number.increment` / `number.decrement` with `cycle: false` (clamps at
  min/max — no lambda needed for drift). *
- `aioesphomeapi` **46.3.0** is in `uv.lock` (dependency of `esphome`; no new package). Source
  [client.py @ v46.3.0](https://github.com/esphome/aioesphomeapi/blob/v46.3.0/aioesphomeapi/client.py):
  `connect(on_stop=None, login=False, log_errors=True)`, `list_entities_services() -> (entities, services)`,
  `subscribe_states(on_state)`, `number_command(key, state, device_id=0)` and `switch_command(key, state,
  device_id=0)` (both synchronous, fire-and-forget), `disconnect(force=False)`. The constructor (`APIClientBase`,
  `address, port, password, *, noise_psk=…, client_info=…`) — implementer confirms the keyword names at 46.3.0.
  `sim-ctl` must not depend on another version: use only these calls and import from `aioesphomeapi` top level.
- `web_server` is unavailable on `host` (006 Context) — hence page + CLI.

## Decisions (made by the planner; the author was not available — see Assumptions)
1. **New sim-only directory `packages/sim/`** (never included by `garden-pilot.yaml`; header in each file: "PC
   emulator only (garden-pilot-sim.yaml); never include from the device entry file"). All display-free files work in
   `sim_api_only`; the two LVGL files are separate so the sim can drop the page.
2. **`packages/sim/sensors.yaml`** (display-free):
   - template numbers (`optimistic: true`, `restore_value: false`, `mode: slider`, deterministic `initial_value`):
     `sim_air_temperature` "Sim air temperature" (−10…50 °C, step 0.5, initial 22),
     `sim_air_humidity` "Sim air humidity" (0…100 %, step 1, initial 60),
     `sim_soil_moisture` "Sim soil moisture" (0…100 %, step 1, initial 50);
   - template sensors with **exactly the device ids, names, units, `device_class`, `accuracy_decimals`**:
     `gh_air_temperature`, `gh_air_humidity`, `gh_soil_moisture_pct`; each `lambda: return id(sim_…).state;`
     (one line), `update_interval: 5s` (as the device soil probe); each number has
     `on_value: - component.update: <sensor id>` so a set value is published at once (no LVGL calls here).
3. **`packages/sim/bed_soil.yaml`** — per-bed mirror of `bed_soil.yaml`, included once per bed right after that bed's
   `gh_bed_N` block, `vars: {bed, bed_name, relay}` (same values as the bed): number `sim_bed${bed}_soil_moisture`
   "${bed_name} sim soil moisture" (0…100, step 1, initial 50, `restore_value: false`); template sensor
   `gh_bed${bed}_soil_moisture` "${bed_name} soil moisture" (as `bed_soil.yaml`); and that bed's drift (Decision 4)
   gated on `board_relay_${relay}`. The sim entry file includes it for beds 1–3 (the demo shows all beds). The sim
   never includes the device `bed_soil.yaml` (ADC).
4. **Auto drift** — switch in `packages/sim/drift.yaml`: `sim_auto_drift` "Sim auto drift", template, optimistic,
   `restore_mode: ALWAYS_OFF`, **not** internal (settable over the API). Rates (literal defaults in the files,
   header explains): every **60 s** while drift is ON, each soil number `number.decrement` (step 1, `cycle: false`)
   → −1 %/min drying; every **10 s** while drift is ON **and** the soil's relay is ON, `number.increment` → +1 %/10 s
   watering. Bed soil N follows `board_relay_N` (in `bed_soil.yaml`); greenhouse-wide `sim_soil_moisture` (in
   `drift.yaml`) rises while **any** of `board_relay_1..3` is on (the sim board has exactly three relays). Conditions
   via `switch.is_on`; no lambdas, no other modelling (no day/night, no temperature). Writes go through the numbers,
   so a manual/API value is always the starting point.
5. **`packages/sim/sensors_lvgl.yaml`** — `interval: 1s` updating the six Home/Greenhouse widgets listed in Context
   from the sim sensors' states, with the device's exact text formats; skips a widget while its sensor has no state
   (keeps placeholders). Same polling pattern as `sprinkler_lvgl_status.yaml`; lambdas are format-only.
6. **`packages/sim/page_board.yaml`** — LVGL page `sim_board_page` + the sim-only nav entry + its own `interval:
   500ms` sync. Layout proposal (implementer may shift by a few px; tokens only):
   - header band (`header-h` 22): title `SIM BOARD` at x=8 (`label`/montserrat_10, `text`), divider at y=22 (`border`);
   - left card x=8, y=26, w=148 (`card`, `border`, `radius-card`): caption `OUTPUTS`; three rows, one per board relay,
     ids `sim_relay_N_led` (10×10 `obj`, fill `green-fill` when ON, `track` when OFF) + label `sim_relay_N_label`
     (`R1 BED 1 VALVE`, `R2 BED 2 VALVE`, `R3 BED 3 VALVE`, montserrat_8 `text-dim`) + state word `sim_relay_N_state`
     (`ON` in `green` / `OFF` in `text-dim`, montserrat_10) — state is fill **plus** a word (design rule). Below:
     caption `SIM AUTO DRIFT`, LVGL `switch` widget `sim_auto_drift_sw` (design `Switch`: 14 px tall,
     `radius-pill`, `green-fill` when on, `track` off) + word `ON`/`OFF`;
   - right card x=162, w=150: caption `INPUTS`; six rows (`AIR T`, `AIR RH`, `SOIL GH`, `SOIL B1`, `SOIL B2`,
     `SOIL B3`), each caption (montserrat_8 `text-dim`) + value label `sim_<name>_value` (montserrat_10 `text`,
     e.g. `22C`, `60%`) + slider `sim_<name>_slider` (track `track`, indicator/knob `green-fill`; soil and RH 0–100,
     air T −10…50; row ≥ 20 px with `ext_click_area` so nothing tappable is under 20 px);
   - transport row y=208: `HOME` ghost button `sim_btn_home` (`btn-h-md` 26, `status` fill, `text-dim` outline/text)
     → `lvgl.page.show: home_page`;
   - **sim-only nav:** `lvgl: top_layer: widgets:` one button `nav_btn_sim` (label `SIM`, montserrat_8, `status` fill,
     `text-dim` text, `radius-control`, `btn-h-sm` 20 tall at y=1 inside the header band, x chosen so it covers no
     header text on Home, Greenhouse, Lawn, Touch test — e.g. x=200, w=44; implementer checks every page header)
     → `lvgl.page.show: sim_board_page`. Visible on all pages, only in the sim. No device page is edited;
   - sync `interval: 500ms`: relay led/word from `id(board_relay_N).state`; sliders and value labels from the
     `sim_*` numbers; switch state from `sim_auto_drift`. Sliders write with `on_change` → `number.set` (continuous
     while dragging, so the poll never fights the knob); the switch writes with `on_change` → `switch.turn_on/off`.
     No `lvgl.*` in any number/switch `on_value` (gotcha).
   - **No new colours, no new font sizes** (montserrat_8/10/12/14 only; 14 only if needed). New on-device
     **components** without a design-system entry: `Slider` and the relay indicator row — flagged; the author adds
     them to the design artifact later (follow-up), tokens unchanged.
7. **Sim entry file order** (`garden-pilot-sim.yaml`): … `gh_bed_1`, `sim_bed_1_soil`, `gh_bed_2`, `sim_bed_2_soil`,
   `gh_bed_3`, `sim_bed_3_soil`, `gh_lvgl_page`, `gh_sprinkler_lvgl`, `sim_sensors`, `sim_drift`,
   `sim_sensors_lvgl`, `sim_page_board`, `touch_dot_test`. Header gains: what the SIM page is, how to drop it
   (comment `sim_sensors_lvgl` + `sim_page_board`), and "values are set on the SIM page, by `script/sim-ctl` or HA".
8. **`script/sim-ctl`** — POSIX sh wrapper (`exec uv run python "$(dirname "$0")/sim_ctl.py" "$@"`, executable) +
   `script/sim_ctl.py` (stdlib `argparse` + `asyncio` + `aioesphomeapi`; no new dependency; a module with pure
   functions so tests import it by path):
   - `sim-ctl [--host H] [--port P] [--key K] [--timeout S] list | get NAME | set NAME VALUE | switch NAME on|off`;
   - defaults: host `127.0.0.1`, port `6053`, timeout 10 s; key from `--key`, else env `GP_SIM_API_KEY`, else
     `sim_api_encryption_key` read from repo-root `secrets.example.yaml` (**never** `secrets.yaml`);
   - `NAME` matches an entity's `object_id` or its name, case-insensitive; ambiguous or missing → exit 2 with the
     candidates; `set` only on number entities (value checked against min/max before sending), `switch` only on
     switch entities; after a command it waits for the new state (or timeout) and prints `name = value`;
   - `list` prints `kind  object_id  name  state` sorted; `get` prints the state;
   - exit codes: 0 ok, 1 connection/timeout error (message suggests `script/sim` running and port 6053),
     2 usage/entity error. Documented in README (both languages) and CLAUDE.md Commands.
9. **API scenario test → follow-up (stage 12).** It needs a compiled host binary started headless; the `checks` job has
   no PlatformIO cache and 20 min, `headless` exists only on 2026.9.1, and a non-SDL host binary would be a third
   build. Not cheap; `sim-ctl` is unit-tested with a fake client instead.
10. **Device unchanged:** no edit to `garden-pilot.yaml`, `packages/core/*`, `packages/greenhouse/*`,
    `packages/lvgl/*`, `packages/display_*.yaml`, `hardware/esp32-*.yaml`. `hardware/sim.yaml` gets a header-only
    note (relay functions R1–R3 = bed 1–3 valves; shown on the SIM page).

## Assumptions (author asleep — reasonable defaults, easy to change)
1. Initial values 22 °C / 60 % / soil 50 % (all soils); ranges −10…50 °C, 0…100 %.
2. Drift rates −1 %/min and +1 %/10 s, clamped 0–100; greenhouse-wide soil wets while any relay runs.
3. The toggle on the SIM page is the design-system `Switch` (LVGL `switch` widget), not a `checkbox` — the design
   system has a Switch and no checkbox. Entity name stays "Sim auto drift".
4. The sim-only nav entry is a small `SIM` button on `top_layer` in the header band (visible on every page), because
   the Home nav bar is full (four 76 px buttons) and device pages must not change.
5. Sim numbers are visible entities ("Sim … " names) in HA's "GardenPilot Sim" device, next to the mirrored sensors.
6. All three beds get a simulated soil sensor in the sim, regardless of whether the device uses `bed_soil.yaml`.
7. `script/sim_ctl.py` lives in `script/` (no new top-level dir).
8. The soil DO binary sensor is not simulated.

## Files
16 paths (above the ~10 guideline because the author scoped sensors + page + CLI together; next cut if needed:
`script/sim-ctl` + its tests + docs as task 008).
- create: `packages/sim/sensors.yaml` — Decision 2.
- create: `packages/sim/bed_soil.yaml` — Decision 3 (+ bed drift).
- create: `packages/sim/drift.yaml` — Decision 4 (switch + greenhouse-wide drift).
- create: `packages/sim/sensors_lvgl.yaml` — Decision 5.
- create: `packages/sim/page_board.yaml` — Decision 6.
- create: `script/sim-ctl` (executable), `script/sim_ctl.py` — Decision 8.
- create: `tests/test_sim_ctl.py` — unit tests below.
- modify: `garden-pilot-sim.yaml` — Decision 7.
- modify: `hardware/sim.yaml` — header only (Decision 10).
- modify: `tests/test_layout.py`, `tests/test_config_matrix.py`, `tests/test_design_tokens.py`,
  `tests/test_devcontainer.py` (script shape) — checks below.
- modify: `docs/SPEC.md` — §5 (`packages/sim/`), §7 (sim sensors, SIM page, sim-ctl; API scenario still stage 12),
  §9 stage 6 part 2 marked done.
- modify: `CLAUDE.md` — layout table (`packages/sim/`), Commands (`script/sim-ctl`), sim entry order note.
- modify: `README.md`, `README.ru.md` — "Run on a PC" section: SIM page, auto drift, `sim-ctl` examples (in sync,
  generic only), e.g. `script/sim-ctl set "Sim soil moisture" 35`, `script/sim-ctl switch "Sim auto drift" on`.

## Checks to write first
**Step 0 (not committed, scratch dir):** with the minimum version (`GP_ESPHOME=minimum`) confirm `esphome config` of a
tiny host config accepts template number `number.increment`/`decrement` with `cycle: false`, LVGL `top_layer`,
`slider` `on_change`, `switch` widget `on_change`, `lvgl.widget.update` `state: checked`. Record results; if any is
missing on 2026.6.3, use the nearest equivalent available on both and note it (do not raise the minimum).

| Level | Test | Asserts |
|---|---|---|
| unit | `tests/test_layout.py::test_sim_packages_never_in_device` | `garden-pilot.yaml` includes nothing under `packages/sim/` and no package key starting with `sim_`; no file under `packages/` outside `packages/sim/`, and no `hardware/*.yaml`, references `packages/sim/` or an id starting with `sim_`. |
| unit | `tests/test_layout.py::test_sim_sensors_mirror_device` | Template sensors in `packages/sim/sensors.yaml` and `bed_soil.yaml` have the same `id`, `name`, `unit_of_measurement`, `device_class`, `accuracy_decimals` as the device sensors (`sensors_air_dht.yaml` temperature/humidity, `sensors_soil.yaml`, `bed_soil.yaml`) after substituting the same vars. |
| unit | `tests/test_layout.py::test_sim_numbers_are_deterministic` | Every `number` under `packages/sim/` is `platform: template`, `optimistic: true`, `restore_value: false`, has `initial_value` within `[min_value, max_value]`; soil/RH ranges 0–100. |
| unit | `tests/test_layout.py::test_sim_drift_defaults_off` | `sim_auto_drift` is a template switch, `restore_mode: ALWAYS_OFF`, not internal; every drift `interval` action is guarded by `switch.is_on: sim_auto_drift`; wetting also by a `board_relay_N`. |
| unit | `tests/test_layout.py::test_sim_display_free_packages` | `sensors.yaml`, `bed_soil.yaml`, `drift.yaml` contain no `lvgl` key or `lvgl.` action; no `GPIO`, no `${…_pin}`, no `!secret`. |
| unit | `tests/test_layout.py::test_sim_board_page` | `page_board.yaml` defines page `sim_board_page`; `sim_relay_N_led`/`_state` for every `board_relay_N` in `hardware/sim.yaml`; one `*_slider` per `sim_*` number id defined in `packages/sim/` (beds 1–3); `sim_auto_drift_sw`; `sim_btn_home` → `home_page`; `top_layer` button `nav_btn_sim` → `sim_board_page`; fonts only `montserrat_8/10/12/14`; no `lvgl.*` inside any `on_value` of a number/switch. |
| unit | `tests/test_layout.py::test_sim_entry_file` (modified) | Accepts the new `sim_*` keys in Decision 7 order (`sim_bed_N_soil` right after `gh_bed_N`, vars equal to the bed's); still rejects device sensors, `bed_soil.yaml`, `web_server`. |
| unit | `tests/test_design_tokens.py::test_page_uses_only_token_colors` (param extended) | `TOKENIZED_PAGES` also covers `packages/sim/page_board.yaml` and `packages/sim/sensors_lvgl.yaml`. |
| unit | `tests/test_devcontainer.py::test_sim_ctl_script` | `script/sim-ctl` exists, executable, runs `uv run python` on `script/sim_ctl.py`; `sim_ctl.py` never opens `secrets.yaml` (only `secrets.example.yaml`). |
| unit | `tests/test_sim_ctl.py::test_parse_args_*` | Defaults (`127.0.0.1`, 6053, 10 s); each subcommand; `switch` accepts only `on`/`off`; `set` requires a float; bad usage exits 2. |
| unit | `tests/test_sim_ctl.py::test_default_key_from_example` | Key is read from a temp `secrets.example.yaml`; `--key` and `GP_SIM_API_KEY` take precedence; a sibling `secrets.yaml` is ignored. |
| unit | `tests/test_sim_ctl.py::test_resolve_entity` | Built from real `aioesphomeapi` `NumberInfo`/`SwitchInfo`/`SensorInfo` objects: match by object_id and by name (case-insensitive); ambiguous and missing raise the usage error with candidates; `set` on a sensor and `switch` on a number are rejected; out-of-range `set` rejected. |
| unit | `tests/test_sim_ctl.py::test_commands_with_fake_client` | A fake client (same method names as 46.3.0) records `number_command(key, value)` / `switch_command(key, True)` and feeds a state back; `list` output is sorted and contains kind/object_id/name/state; connection failure → exit 1 with the hint. |
| config | `test_config_matrix.py[sim_full]`, `[sim_no_touch_debug]` (now with the sim packages) | Validate (SDL skip/require as in 006). |
| config | `…[sim_no_board_page]` | Sim entry file without `sim_sensors_lvgl` and `sim_page_board` validates (page is optional). |
| config | `…[sim_api_only]` (extended) | Adds `sim_sensors`, `sim_bed_1..3_soil`, `sim_drift` → validates without SDL/LVGL; never skipped. |
| config | existing device rows | Unchanged and green. |

## Acceptance criteria
- [x] Step 0 results recorded for 2026.6.3 (and any substitution made).
- [x] `uv run pytest -m unit` → all pass, including the new tests.
- [ ] `script/lint` → clean; `script/test` in the SDL devcontainer with `GP_REQUIRE_SDL=1` → all pass, no skips.
- [ ] `GP_SECRETS=example script/compile garden-pilot-sim.yaml` builds on pinned and `GP_ESPHOME=minimum`.
- [ ] `git diff --stat task/006-pc-emulator -- garden-pilot.yaml packages/core packages/greenhouse packages/lvgl
      packages/display_touch.yaml packages/display_sdl.yaml 'hardware/esp32-*'` → empty, and the normalized
      `esphome config` of `garden-pilot.yaml` (006 procedure) is identical to the 006 branch — output pasted.
- [x] `git grep -nE 'packages/sim|sim_' -- garden-pilot.yaml packages/core packages/greenhouse packages/lvgl` → no
      output; `git grep -n '!secret' -- packages hardware script/sim_ctl.py` → no output.
- [x] `git grep -nE '0x[0-9a-fA-F]{6}' -- packages/sim` lists only token colours (also enforced by the tokens test).
- [ ] CI green: `checks`, `compile (pinned)`, `compile (minimum)`.
- [x] `docs/SPEC.md`, `CLAUDE.md`, `README.md`, `README.ru.md` updated; READMEs in sync; generic examples only.
- [ ] **PC (author, not CI)** — `script/sim` in the SDL devcontainer, HA not connected:
  - Home shows 22C / 60% and the soil bar at 50; Greenhouse shows `Air: 22.0 C`, `RH: 60 %`, `Soil: 50 %`;
  - `SIM` button opens the SIM board; RUN bed 2 on Greenhouse → on the SIM page `R2` turns green with `ON`, others
    `OFF`; STOP → all `OFF`;
  - moving the AIR T / SOIL GH sliders changes Home and Greenhouse values within ~1 s; HOME returns;
  - Sim auto drift ON: soil values drop 1 % per minute; while a bed runs, its soil and SOIL GH rise ~1 % per 10 s;
    OFF stops changes; after restart it is OFF and values are back to defaults;
  - in a second terminal: `script/sim-ctl list` shows the sim entities; `script/sim-ctl set "Sim soil moisture" 35`
    moves the slider and Home bar; `script/sim-ctl switch "Sim auto drift" on` flips the switch on screen;
    `script/sim-ctl get greenhouse_soil_moisture` (object id as reported by `list`; derived from the entity name, not the YAML id) prints 35; with the sim stopped it
    exits 1 with the hint.
- [ ] **Optional, HA by IP (author):** "GardenPilot Sim" shows the sim numbers, "Sim auto drift" and the mirrored
      greenhouse sensors; changing a number in HA updates the window.
- [x] Implementer states that the PC/HA items were not checked by it.

## Out of scope
- Shared display path for device + sim sensors (move device LVGL updates out of `on_value` into a polled package) —
  device change with hardware check; follow-up.
- `aioesphomeapi` scenario tests against a running host binary, headless run, screenshots (stage 12).
- Simulating the soil DO binary sensor, day/night or temperature models, relay on-time guards in the sim.
- Adding `Slider` / relay indicator components to the design artifact (author, design follow-up).
- Bed count other than 3 on the SIM page (hard-coded like the greenhouse page until stages 8–9).
- Building the sim in the weekly canary; `web_server` shims; OTA for the emulator.

## Open questions
None blocking. The author may revisit Assumptions 1–4 (values, rates, Switch vs. checkbox, `SIM` button placement).

<!-- Filled in by implementer -->
## Implementation notes
Checks first: the new tests were written with the packages (all unit tests green: 319 passed with `-m unit`;
`script/lint` clean; `script/test` 328 passed, 4 skipped = the three SDL config rows and the sim `script/config`
test, because this host has no `sdl2-config`; CI/devcontainer with `GP_REQUIRE_SDL=1` must run them).

**Step 0 (scratch config under `.esphome/scratch/`, `esphome config` only, `sdl_options: "-lSDL2"` to bypass the
missing `sdl2-config`):** template number with `number.increment`/`decrement` `cycle: false`, LVGL `top_layer`, `slider`
`on_change`, `switch` widget `on_change`, `lvgl.widget.update: state: checked:` all validate on 2026.9.1 and on
2026.6.3 (`UV_OFFLINE=1 GP_ESPHOME=minimum`). No substitution needed.

**Validation of the sim entry file here:** the real `garden-pilot-sim.yaml` (staged copy in `.esphome/scratch/sim/`
with `sdl_options` added to the SDL display and the sim key inlined, since a secrets file could not be created there)
passes `esphome config` on pinned and minimum (offline). Not compiled: `script/compile` of the sim was not run by me
(needs the toolchain/SDL), CI `compile` jobs cover it.

**Device unchanged:** `git diff --stat task/006-pc-emulator -- garden-pilot.yaml packages/core packages/greenhouse
packages/lvgl packages/display_touch.yaml packages/display_sdl.yaml packages/touch_dot_test.yaml 'hardware/esp32-*'
secrets.example.yaml` is empty, so the device's normalized `esphome config` is identical by construction. A rendered
side-by-side was attempted (`git archive` into `.esphome/compare/006`) but the 006 tree could not be given a secrets
file in this session; the byte-identity above is the evidence. `script/lint` renders `garden-pilot.yaml` OK.

**Decisions / deviations:**
- `hardware/sim.yaml` header mentions the SIM page without the path `packages/sim/` (the new test forbids hardware
  files referencing it); its "NOT supported" note now says the emulator has simulated sensors.
- `sim_ctl.py`: `connect(login=False)` wrapped in `asyncio.wait_for`; every connect failure is exit 1 with the hint.
  Entities are matched on `object_id` or `name`; `get`/`list` wait up to 2 s for the initial state dump. In the
  aioesphomeapi 46.3.0 client the constructor keywords used are `noise_psk` and `client_info`.
- Switch widget colours: track `track`, indicator `green-fill`, knob `text` (token colours only). The Slider and the
  relay indicator row are not in the design system yet (as flagged in the task).
- `test_sim_sensors_mirror_device` fills the DHT platform defaults (unit, device class) into the device side, since
  `sensors_air_dht.yaml` leaves them implicit.
- The SIM nav button sits at x=200..244, y=1..21: clear of "GardenPilot" (x=6) and the Home clock (x=252); header
  texts on Greenhouse, Lawn and Touch test are at x<=140 / x=10. Checked by reading the YAML, not on screen.
- Scratch left behind (git-ignored): `.esphome/scratch/`, `.esphome/compare/` (incl. a `.venv` that uv created there).

**Not verified (needs a PC / CI):** the window itself (layout, slider feel, the SIM button, indicators, drift rates),
`script/sim-ctl` against a live emulator, HA by IP, the SDL config rows and `GP_REQUIRE_SDL=1` runs, compile on pinned
and minimum, CI. No hardware involved.
## Follow-ups
- Shared display path for device + sim sensors (polled `sensors_lvgl.yaml`, fixes the `on_value`-before-LVGL gotcha).
- Add `Slider` and the relay indicator row to the design artifact.
- `aioesphomeapi` scenario test against a headless host build (stage 12).
