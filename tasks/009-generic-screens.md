# 009 — Generic screens, part 1: confirm dialog, Setup tab, Setup → Network

Status: implemented (emulator/device checks pending, author)
Roadmap: SPEC §9 stage "Screens on the design system" (stage 9 after task 006's renumbering), slice 1 of 3, pulled
forward: only screens that do not depend on `garden_zones` / `gp_*`. Slices: **009 confirm + Setup + Network**,
010 boot + valve test (`tasks/010-boot-and-valve-test.md`), 011 screensaver + clock font token
(`tasks/011-screensaver.md`); one stacked branch and PR each.
Spec sections: SPEC §4.1, §5, §7 items 4–5, §8; CLAUDE.md core principles 1, 2, 4, 5, 7; `design/README.md`
Hardware check: yes — the author checks the new pages, the STOP confirmation and RESTART on the real device after
the emulator check. Nothing in CI can see the screen.

## Goal
The SETUP button in the Home nav opens a real **Setup** page (draft D10) instead of the touch test: a 2×3 tile grid
whose NETWORK tile opens **Setup → Network** (D11: Wi-Fi SSID/RSSI, IP, Home Assistant API state, ESPHome version,
uptime, BACK, RESTART), whose DISPLAY tile opens the existing touch test page, and whose other tiles are shown as
"soon". A reusable **confirm dialog** (D14: dim layer + card + CANCEL / action button) can be opened from any page
by one script call; its first two users are STOP on the Greenhouse page ("Stop all watering?") and RESTART on the
Network page. All new pages follow `design/tokens.json`; Wi-Fi-only data lives in a device-only package so the same
pages run in the PC emulator (`script/sim`, task 006). No Home Assistant entity is renamed or added (new sensors are
`internal: true`), valves keep their current safety behaviour.

## Context

### Stacking
Implemented on top of task 006 (`garden-pilot-sim.yaml`, `packages/display_sdl.yaml`, `packages/core/{api,ota,network,
time,time_host}.yaml`, `script/sim`, sim rows in `tests/test_config_matrix.py`, `test_sim_entry_file`) and task 007
(simulated sensors, SIM board page with a sim-only nav button). **`tasks/007-*.md` did not exist when this was
written** — before starting, the implementer reads it (if present) and checks Assumption 9 (where 007's nav button
lives). If 006 or 007 are not merged into the branch base yet, set Status `blocked` and say so.

### What exists (master after 005, plus 006 as planned)
- `packages/lvgl/page_home.yaml` follows the tokens (only colours from `tokens.json`, fonts `montserrat_8/10/12/14`).
  Its nav bar: `nav_btn_dash` (→ `home_page`), `nav_btn_zones` (→ `greenhouse_page`), `nav_btn_water`
  (→ `lawn_page`), `nav_btn_setup` (→ `touch_test_page`), geometry x = 4/84/164/244, y 204, 76/76/76/72 × 32, icons
  `   ` in `montserrat_14`, labels in `montserrat_8`.
- `packages/greenhouse/lvgl_page.yaml`: default LVGL theme, `gh_btn_stop` calls `sprinkler.shutdown: gh_sprinkler`
  directly (legacy; stage 8 `gp_*`). `gh_btn_home` → `home_page`. No nav bar on greenhouse/lawn/touch test.
- `tests/test_design_tokens.py`: `TOKENIZED_PAGES` + colour-literal check (`0xRRGGBB` must be a token).
- `packages/core/*` must stay display-independent (`tests/test_layout.py::test_core_is_display_independent`).
- Pollers, not `on_value`, push to LVGL (CLAUDE.md gotcha; pattern `packages/greenhouse/sprinkler_lvgl_status.yaml`).

### Drafts used (`.design-drafts/`, git-ignored; design data only, coordinates = LVGL x/y)
- **D14 Confirm stop:** full-screen dim layer `rgba(0,0,0,.65)`; card x30 y60 260×120; title (value, `text`) at
  x42 y74; two body lines (label, `text-dim`) at y96/y112; CANCEL ghost x42 y140 104×26; STOP ALL danger x154 y140
  124×26.
- **D10 Setup:** header "Setup"; six cards 150×52 at x 8/162, y 26/82/138; caption (8px, `text-dim`) at +6/+6,
  value line (10px) at +6/+20, chevron at +132/+20; tiles NETWORK ("Wi-Fi · HA online", green), TIME ("NTP · 14:32"),
  DISPLAY ("Brightness 70%"), CYCLE ("×100% · repeat 1"), SENSORS ("Calibrate soil"), SERVICE ("Valve test", amber);
  NavBar at y201 with SETUP active.
- **D11 Network:** header "Setup · Network"; wifi icon + "Connected" (value, green) at x30 y30; rows caption at x8,
  value at x120, y = 55/73/91/109/127/145/163 (WI-FI, HOME ASSISTANT, IP, MQTT, FIRMWARE, ESPHOME, UPTIME); BACK ghost
  x8 y210 92×26; RESTART ghost x104 y210 208×26.

### ESPHome behaviour checked (pinned 2026.9.1; minimum 2026.6.3 — confirm in step 0)
- LVGL ([esphome.io/components/lvgl](https://esphome.io/components/lvgl/)): `top_layer` is an always-on-top page
  that takes widgets and style properties like a page; widgets have the `hidden` flag and are toggled with
  `lvgl.widget.show` / `lvgl.widget.hide`; `bg_opa` accepts `TRANSP`, `COVER`, 0.0–1.0 or a percentage. So the
  dialog lives in `lvgl: top_layer: widgets:` hidden by default, above every page, with no page switch (the page
  underneath keeps its state and pollers). A full-screen clickable `obj` on the top layer swallows touches meant
  for the page underneath (verify in step 0 b). `msgboxes:` also exist but are drawn with the default theme; not
  used (no token control). Task 011 adds a second top-layer widget (screensaver) from another package.
- Sprinkler ([esphome.io/components/sprinkler](https://esphome.io/components/sprinkler/)): `sprinkler.shutdown`
  and `sprinkler.clear_queued_valves` are separate actions; this task keeps STOP's effect **exactly** as today
  (`sprinkler.shutdown` only) and only puts the confirmation in front of it.
- ESPHome scripts take typed `parameters:` (string/int/bool/float) usable in lambdas; `script.wait` waits for a
  script to finish; automations of any trigger (incl. LVGL `on_click`) may contain waits. The `gp_confirm` design
  below relies on this (step 0 c).
- `wifi_info` (ssid, ip_address) and `wifi_signal` need the `wifi` component, which the `host` platform does not
  have (task 006 Context). `version` text sensor, `uptime` (text sensor platform) and `button: platform: restart`
  are platform-independent in source, but **host behaviour is not verified** — step 0 d/e. The `api.connected`
  condition works wherever `api:` is present (device and sim).
- **Built-in LVGL Montserrat fonts contain only ASCII 0x20–0x7E plus the LVGL symbol set** (`LV_SYMBOL_*`, e.g.
  ``, `` right chevron, `` wifi). The drafts' `·`, `‑` (U+2011), `…`, `−`, `×` would render as
  missing glyphs: use ASCII (`-`, `/`, `...`) in all new texts. Step 0 f confirms with one glyph.

## Decisions
1. **Confirm dialog = `packages/lvgl/dialog_confirm.yaml`** (needs `lvgl_base`; no page):
   - `globals:` `gp_confirm_open` (bool, false) and `gp_confirm_result` (bool, false), `restore_value: false`.
   - `lvgl: top_layer: widgets:` one root `obj` `gp_confirm_layer` (x0 y0 320×240, `bg_color` = token `bg`,
     `bg_opa: 65%`, border 0, `hidden: true`, `scrollable: false`, clickable so it blocks the page) containing the D14
     card (`card` fill, 1px `border`, `radius-card`), `gp_confirm_title` (montserrat_12, `text`), `gp_confirm_body`
     (montserrat_10, `text-dim`, `long_mode: WRAP`, width 236, two lines max), `gp_confirm_cancel` (ghost: `TRANSP`
     fill, 1px `text-dim` border and text, `radius-control`, 104×26, label "CANCEL"), and **two** action buttons at
     the same place (124×26): `gp_confirm_ok_danger` (`error-fill` / `on-error`) and `gp_confirm_ok_primary`
     (`green-fill` / `on-green`), labels `gp_confirm_ok_danger_label` / `gp_confirm_ok_primary_label`; the script
     shows exactly one of them. Red stays reserved for stop actions (design rule), other confirmations use primary.
   - `script:` `gp_confirm` (`mode: single`), `parameters: {title: string, body: string, action: string,
     danger: bool}`: set the labels (one-line `return title;`-style lambdas), show the matching action button and
     hide the other, `gp_confirm_result := false`, `gp_confirm_open := true`, `lvgl.widget.show: gp_confirm_layer`,
     `wait_until` `gp_confirm_open` is false with `timeout: 30s` (auto-cancel = no action), then
     `gp_confirm_open := false` and `lvgl.widget.hide: gp_confirm_layer`.
   - CANCEL `on_click`: `gp_confirm_open := false`. Action buttons `on_click`: `gp_confirm_result := true`,
     `gp_confirm_open := false`.
   - **Calling pattern** (the action stays at the call site, so the dialog never references other packages):
     ```yaml
     on_click:
       - script.execute: {id: gp_confirm, title: "Stop all watering?", body: "...", action: "STOP ALL", danger: true}
       - script.wait: gp_confirm
       - if:
           condition: {lambda: "return id(gp_confirm_result);"}
           then: [<the action>]
     ```
     The header comment of `dialog_confirm.yaml` documents this snippet and "ASCII only". `gp_confirm_open` is also
     read by task 011 (no screensaver over an open dialog).
2. **STOP on the Greenhouse page asks first.** Only `gh_btn_stop`'s `on_click` changes: the pattern above with title
   "Stop all watering?", body "All greenhouse valves close.", action "STOP ALL", `danger: true`, then the unchanged
   `sprinkler.shutdown: gh_sprinkler`. The page keeps its default theme (restyling is stage 9 proper). The direct
   `sprinkler.*` call stays legacy (stage 8 moves it behind `gp_*`); not "fixed" here. Home Assistant's
   "Greenhouse irrigation" switch and the zone switches still stop immediately, without a dialog.
3. **Setup page = `packages/lvgl/page_setup.yaml`**, id `setup_page`, D10 geometry, tokens like `home_page`
   (`bg` ground, 1px `border` frame, header title "Setup" at x8 y4 `montserrat_10` `text`, divider at y22, no clock):
   - Tiles are `button`s with card styling (`card` fill, 1px `border`, `radius-card`, 150×52) holding a caption
     label (`montserrat_8`, `text-dim`), a value label (`montserrat_10`) and a chevron label ``
     (`montserrat_10`, `text-dim`). Ids `setup_tile_<name>`, value labels `setup_<name>_value`.
   - NETWORK → `lvgl.page.show: network_page`; value `setup_network_value` = "HA online" (`green`) / "HA offline"
     (`text-dim`) from `api.connected`, polled every 1 s by an `interval` in the same file (`if` + two
     `lvgl.label.update`, no lambda).
   - TIME: value `setup_time_value` = `%H:%M` from `ha_time` when the clock is valid, else "--:-- not set"; polled by
     the same interval (`time.has_time` condition). Not clickable, no chevron (no time settings yet).
   - DISPLAY → `touch_test_page`; value "Touch test" (`text`). Brightness is a follow-up (needs a backlight
     `light`/`output` in the board profile — hardware decision).
   - CYCLE, SENSORS, SERVICE: shown as disabled tiles (plain `obj`, not clickable, no chevron), value "Soon" in
     `text-dim` (design rule: no live data = `text-dim`). Task 010 turns SERVICE into "Valve test".
   - Bottom nav: a copy of the Home nav bar (same geometry, icons, targets) with **SETUP active** (`green-fill` /
     `on-green`) and DASH inactive (`status` / `text-dim`); widget ids prefixed `setup_nav_btn_*` (ids are global).
4. **Network page = `packages/lvgl/page_network.yaml`**, id `network_page`, D11 geometry, tokens:
   - Header "Setup - Network" (ASCII), divider. Status line: icon `` + `network_status_label` (`montserrat_12`)
     initial "--" (`text-dim`); only the device-only package below writes it ("Connected" `green` /
     "No Wi-Fi" `text-dim`).
   - Rows (caption `montserrat_8` `text-dim` at x8; value `montserrat_10` at x120; ids `network_<row>_value`):
     WI-FI (`network_wifi_value`, "SSID / -61 dBm"), HOME ASSISTANT (`network_api_value`), IP (`network_ip_value`),
     ESPHOME (`network_esphome_value`), UPTIME (`network_uptime_value`). Wi-Fi and IP start as "--"; on the
     emulator they stay "--" (accepted). MQTT and FIRMWARE rows of the draft are dropped (Assumption 4).
   - A 1 s `interval` in the same file updates `network_api_value` ("API connected" `green` / "Not connected"
     `text-dim`, `api.connected`), `network_esphome_value` from `gp_esphome_version`, `network_uptime_value` from
     `gp_uptime` (`lambda: return id(x).state;` one-liners, guarded by `has_state()` → "--").
   - BACK (ghost, x8 y210 92×26) → `setup_page`. RESTART (ghost, x104 y210 208×26) → `gp_confirm` with title
     "Restart the controller?", body "Running watering stops. Valves stay closed after boot.", action "RESTART",
     `danger: false`, then `button.press: gp_restart_button`.
5. **Diagnostics = `packages/core/diagnostics.yaml`** (display-independent, device and sim): `text_sensor:` `version`
   (`id: gp_esphome_version`, `hide_timestamp: true`) and `uptime` (`id: gp_uptime`, text platform), `button:`
   `restart` (`id: gp_restart_button`); **all `internal: true`**, so Home Assistant gets no new entities (Assumption
   3). Header: what it provides, no LVGL.
6. **Wi-Fi data = `packages/lvgl/network_wifi_status.yaml`**, **device only** (needs `wifi:` from `core_network`
   and `network_page`): `text_sensor: wifi_info` (`ssid` → `gp_wifi_ssid`, `ip_address` → `gp_wifi_ip`) and
   `sensor: wifi_signal` (`gp_wifi_rssi`, `update_interval: 10s`), all `internal: true`; a 2 s `interval` that writes
   `network_status_label` (`wifi.connected`), `network_wifi_value` ("<ssid> / <rssi> dBm", one short `snprintf`
   lambda like the existing poller) and `network_ip_value`; nothing from `on_value`. Header: "device only — the
   emulator has no Wi-Fi; comment out to drop Wi-Fi rows".
7. **Entry files.** `garden-pilot.yaml`: `core_diagnostics` right after `core_time`; after `lvgl_page_lawn`:
   `lvgl_dialog_confirm`, `lvgl_page_setup`, `lvgl_page_network`, `lvgl_network_wifi`. `garden-pilot-sim.yaml`: the
   same minus `lvgl_network_wifi`. Home stays the first page package (boot screen moves in task 010). CLAUDE.md
   `packages:` order section updated.
8. **Home nav:** only `nav_btn_setup`'s target changes to `setup_page`. ZONES/WATER unchanged.
9. **Token-only, ASCII-only.** New/changed tokenized files use only token colours and `montserrat_8/10/12/14`;
   geometry from D10/D11/D14 and the spacing/radius/size tokens. The dim layer uses token `bg` at 65 % opacity
   instead of the draft's pure black (no new colour; opacity is not a token yet — Open question 2).

## Files
13 paths (7 are small test/doc edits).
- create: `packages/lvgl/dialog_confirm.yaml` — Decision 1.
- create: `packages/lvgl/page_setup.yaml` — Decision 3.
- create: `packages/lvgl/page_network.yaml` — Decision 4.
- create: `packages/core/diagnostics.yaml` — Decision 5.
- create: `packages/lvgl/network_wifi_status.yaml` — Decision 6.
- create: `tests/test_screens.py` — checks below.
- modify: `packages/lvgl/page_home.yaml` — `nav_btn_setup` → `setup_page` (Decision 8).
- modify: `packages/greenhouse/lvgl_page.yaml` — `gh_btn_stop` through the dialog (Decision 2); header note.
- modify: `garden-pilot.yaml`, `garden-pilot-sim.yaml` — Decision 7.
- modify: `tests/test_design_tokens.py` — tokenized list + font check.
- modify: `tests/test_config_matrix.py` (rows), `tests/test_layout.py` (006's `test_sim_entry_file` allow-list, if it
  is a closed list).
- modify: `docs/SPEC.md` §8 (built pages, nav, confirm dialog, ASCII-only fonts), `CLAUDE.md` (layout table, packages
  order, gotchas "built-in fonts are ASCII + LVGL symbols" and "confirm dialog pattern"), `design/README.md` Pages
  (Setup, Network, Confirm dialog built; primary vs danger action).

## Checks to write first

**Step 0 — spike (not committed), scratch dir, pinned and `GP_ESPHOME=minimum`, SDL devcontainer** (extend 006's
spike config). Record results in Implementation notes:
- a: `lvgl: top_layer:` with a hidden obj validates and compiles on both versions.
- b: in the window, `lvgl.widget.show` makes the layer appear over a page; clicks on the dim area do **not** reach a
  button underneath (log line proves it).
- c: `script` with `parameters` + `script.wait` from an LVGL `on_click`, then `if` on a global, works (log line).
- d: `text_sensor: version`, `text_sensor: uptime`, `button: restart` validate and compile on host; what pressing the
  restart button does on host (restart / exit) — document it for the emulator.
- e: `wifi_info` / `wifi_signal` fail validation on host (confirms Decision 6 is needed).
- f: a label with `·` renders as a missing glyph with `montserrat_10` (confirms the ASCII rule).
Gate: if a or c fails, set Status `blocked` with the exact error; do not fall back to `msgboxes` or lambdas
without the author.

| Level | Test | Asserts |
|---|---|---|
| unit | `tests/test_screens.py::test_nav_targets_exist[<entry>]` | For `garden-pilot.yaml` and `garden-pilot-sim.yaml`: every `lvgl.page.show` target in the packages the entry file includes is a page id defined by an included package. |
| unit | `tests/test_screens.py::test_page_ids_unique` | No page id or widget id is defined twice across `packages/**/*.yaml` (ids are global). |
| unit | `tests/test_screens.py::test_setup_nav` | `nav_btn_setup` (Home) shows `setup_page`; `setup_page` has `setup_tile_network` → `network_page` and `setup_tile_display` → `touch_test_page`; `network_page` BACK → `setup_page`; the setup nav bar has the same four targets as Home. |
| unit | `tests/test_screens.py::test_confirm_dialog_shape` | `dialog_confirm.yaml` top level ⊆ {`globals`, `lvgl`, `script`}; `lvgl` has only `top_layer`; root `gp_confirm_layer` is `hidden: true`, 320×240; ids `gp_confirm_title`, `gp_confirm_body`, `gp_confirm_cancel`, `gp_confirm_ok_danger`, `gp_confirm_ok_primary` exist; script `gp_confirm` has parameters `title, body, action, danger` and a `wait_until` with a `timeout` ≤ 60 s; both globals `restore_value: false`; the file references no id outside itself and `lvgl_base`. |
| unit | `tests/test_screens.py::test_stop_asks_for_confirmation` | `gh_btn_stop.on_click` = `script.execute gp_confirm` (danger true) → `script.wait gp_confirm` → `if` on `gp_confirm_result` whose `then` contains `sprinkler.shutdown: gh_sprinkler`; no `sprinkler.*` action at the top level of that `on_click`. |
| unit | `tests/test_screens.py::test_restart_is_confirmed` | `button.press: gp_restart_button` appears only inside such an `if` (any file); `gp_restart_button` is `platform: restart`, `internal: true`. |
| unit | `tests/test_screens.py::test_new_diagnostics_are_internal` | Every `sensor`/`text_sensor`/`button` in `core/diagnostics.yaml` and `lvgl/network_wifi_status.yaml` is `internal: true` (no new HA entities). |
| unit | `tests/test_screens.py::test_device_only_packages_not_in_sim` | No package included by `garden-pilot-sim.yaml` uses `wifi_info`, `wifi_signal` or the `wifi.connected` condition; `network_wifi_status.yaml` is included by the device entry file only. |
| unit | `tests/test_screens.py::test_screen_text_is_ascii` | In the tokenized files, every `text:` literal is ASCII or an LVGL symbol (``–``). |
| unit | `tests/test_design_tokens.py::test_page_uses_only_token_colors` (extended) | `TOKENIZED_PAGES` += `page_setup.yaml`, `page_network.yaml`, `dialog_confirm.yaml`, `network_wifi_status.yaml`. |
| unit | `tests/test_design_tokens.py::test_page_uses_only_token_fonts` (new) | Tokenized files use only `montserrat_8/10/12/14` (the four sizes in `tokens.json`; task 011 adds the clock font). |
| unit | `tests/test_layout.py::test_core_is_display_independent` (existing) | Covers `core/diagnostics.yaml` (no `lvgl`, no widget ids). |
| config | `tests/test_config_matrix.py` existing rows (`full`, `sim_full`, …) | Still validate with the new packages; headless rows unchanged. |
| config | `…[no_wifi_status]` | Device entry file without `lvgl_network_wifi` validates (the package is optional). |
| config | `…[headless_diag]` | `CORE` + `core_diagnostics` validates without display/LVGL. |

## Acceptance criteria
- [ ] Step 0 a–f recorded for 2026.9.1 and 2026.6.3.
- [x] `uv run pytest -m unit` → all pass, including the new tests (written first, seen failing before the YAML).
- [x] `script/lint` → clean; `script/test` in the SDL devcontainer with `GP_REQUIRE_SDL=1` → all pass, none skipped.
- [x] `GP_ESPHOME=minimum GP_SECRETS=example sh script/config` and `… sh script/config garden-pilot-sim.yaml` → OK.
- [ ] CI green: `checks`, `compile (pinned)`, `compile (minimum)` (device and sim builds).
- [x] `git grep -nE '0x[0-9a-fA-F]{6}' -- packages/lvgl/page_setup.yaml packages/lvgl/page_network.yaml
      packages/lvgl/dialog_confirm.yaml packages/lvgl/network_wifi_status.yaml` → only token values (test enforces).
- [x] Normalized `esphome config` diff of `garden-pilot.yaml` master vs. branch (006's helper): only the added
      pages/scripts/globals/internal sensors, the `nav_btn_setup` target and `gh_btn_stop` actions; **no** changes to
      `switch`, `sprinkler`, `number` or any non-internal entity — pasted and explained.
- [x] `docs/SPEC.md` §8, `CLAUDE.md`, `design/README.md` updated as listed.
- [ ] **Emulator (author, not CI):** `script/sim`:
  - SETUP opens the Setup page; six tiles, NETWORK shows "HA offline" without HA (and "HA online" with HA by IP),
    TIME shows the PC time; CYCLE/SENSORS/SERVICE show "Soon" and do nothing; DISPLAY opens the touch test;
    the nav bar on Setup reaches Dash/Zones/Water;
  - NETWORK → Network page: ESPHome version and uptime filled, HA row matches the connection, Wi-Fi/IP "--"; BACK
    returns;
  - Greenhouse: RUN a bed, STOP → dialog over the page; CANCEL → dialog closes, bed keeps running; STOP again →
    STOP ALL → bed stops (log); dialog left open 30 s closes by itself and nothing stops; taps on the dim area do
    nothing;
  - RESTART → dialog with a green action button; CANCEL works; RESTART behaviour on host matches step 0 d.
- [ ] **Device (author, not CI):** OTA-flash; same walk-through; Network page shows SSID, RSSI, IP, "Connected";
      RESTART → device reboots, all valves off after boot, HA reconnects; HA device page shows **no new and no
      renamed entities**; readability of 8/10 px text on the panel noted.
- [x] Implementer states that no emulator/device item was checked by it.

## Out of scope
- Task 010: boot / connecting screen (D17) and Service → Valve test (D18) — full spec in
  `tasks/010-boot-and-valve-test.md`.
- Task 011: screensaver (D23) with the new 40 px `clock` font token (authorised by the author, 2026-10-02) — full
  spec in `tasks/011-screensaver.md`.
- Restyle of the Greenhouse/Lawn/Touch-test pages to tokens (stage 9 proper).
- D16 standby, D19 soil calibration (persisted calibration changes sensor behaviour — needs a decision), alerts,
  schedules (WATER tab), heating screens, history.
- Display brightness (needs backlight hardware in the board profile), CYCLE settings (needs a run-time multiplier /
  cycle-and-soak engine feature), MQTT row, firmware project version (`esphome: project:`).
- Moving STOP behind `gp_*` (stage 8); clearing the queue on STOP (behaviour change, not requested).
- A `scrim`/opacity token in the design system (Open question 2).

## Assumptions (author asleep — decided here, revisit in review)
1. **Split into three stacked tasks** (author's request): 009 here, 010 boot + valve test (the only actuator-facing
   slice, own hardware check), 011 screensaver + font token.
2. **STOP gets a confirmation** as drawn in D14, even though it adds one tap before stopping. Mitigations: the HA
   switches still stop instantly; the dialog auto-cancels after 30 s; RUN buttons are unchanged. If the author
   prefers "STOP immediate, confirm only when a queue would be lost", that is a one-condition change.
3. **No new HA entities:** version, uptime, Wi-Fi info/signal and the restart button are `internal: true`. Exposing
   them to HA is a one-line follow-up per entity if wanted.
4. **Network rows:** MQTT ("not used") and FIRMWARE ("GardenPilot [version]") dropped — there is no MQTT and no
   project version yet; ESPHOME row shows the ESPHome version.
5. **Setup tiles:** NETWORK and DISPLAY (→ touch test) are active, TIME is a read-only clock, CYCLE/SENSORS/SERVICE
   are visible "Soon" tiles (keeps the D10 grid so later tasks only flip a tile on). The touch test stays reachable
   via DISPLAY.
6. **Action button colours:** `error-fill` only for stop actions (STOP ALL), `green-fill` for other confirmations
   (RESTART) — keeps the "nothing else is red" rule.
7. **Dim layer** = token `bg` at 65 % instead of black (no new colour).
8. **ASCII-only texts** (built-in fonts); `·` → `-`, `‑` → `-`, `…` → `...`.
9. **007's sim-only nav button:** assumed to be added to Home's nav (or a gesture) by a sim-only package. This task
   only changes `nav_btn_setup`'s target and copies the four standard buttons onto Setup; it does not add 007's
   button to Setup. If 007 changed the Home nav geometry, copy that geometry instead and note it.
10. **Setup has no header clock** (the TIME tile shows it); a shared header clock is a follow-up together with the
    `ha_time` → neutral id rename.

## Open questions
1. STOP confirmation as drawn (Assumption 2) — keep, or only when something is queued?
2. Add an opacity token (e.g. `scrim-opa: 65%`) to the design system for dim layers?
3. Should the Network/diagnostic values also be visible in Home Assistant (non-internal entities)?

<!-- Filled in by implementer -->
## Implementation notes
- Checks first: `tests/test_screens.py` (13 tests), font test and token-file list in `tests/test_design_tokens.py`,
  matrix rows `no_wifi_status` / `headless_diag`, `test_sim_entry_file` required keys; seen failing, now green
  (`uv run pytest -m unit`: 360 passed; `script/test`: 375 passed, none skipped).
- **Step 0 spike (partial, no emulator/containers allowed):** a and d validated through `esphome config` on pinned
  2026.9.1 and minimum 2026.6.3 (offline, `UV_OFFLINE=1`) for both entry files (top layer widget with `hidden`,
  `lvgl.widget.show/hide`, `text_sensor: version/uptime`, `button: restart`, scripts with parameters + `script.wait`
  + `if` on a global all validate). **Not done:** compile; b (touch blocking in the window), c at runtime, d host
  restart behaviour, e (wifi_info on host), f (glyph rendering): all need the emulator. CI compile covers the
  compile part for pinned and minimum. The sim `esphome config` here ran with a fake `sdl2-config` stub on PATH
  (scratch dir only) because SDL2 dev files are not installed on this machine.
- Deviation: `time.has_time` is not a valid condition in 2026.9.1 (config error); the Setup poller uses
  `lambda: return id(ha_time).now().is_valid();`.
- `lvgl.label.update` accepts `text_color` (validated), so the status colours are set from the pollers.
- Sim entry order: `core_diagnostics` sits right after `core_time_host` (before `display_sdl`), so
  `test_sim_entry_file_is_a_package_list` now expects six leading keys.
- Dialog stacking on the emulator: the sim-only SIM button is a top-layer widget from a package listed later, so it is
  drawn above the dim layer and stays tappable over an open dialog (cosmetic, emulator only). Not fixed (would need
  the sim package ordered before the dialog; revisit with 010/011).
- Setup nav DASH/ZONES/WATER copies the Home targets; widget ids prefixed `setup_nav_btn_*`.
- **Device config difference vs task/007-sim-board** (normalized `esphome config`, by top-level key; sections compared
  as sets, order of keys/`args: []` placement ignored):
  - Device: added `globals` (gp_confirm_open/result), `text_sensor` (gp_esphome_version, gp_uptime, gp_wifi_ssid,
    gp_wifi_ip, all internal), `button` (gp_restart_button, internal), `sensor` gp_wifi_rssi (internal), `script`
    gp_confirm, `interval` pollers (setup/network/wifi), `lvgl` pages setup_page/network_page + top-layer dialog,
    `nav_btn_setup` target touch_test_page -> setup_page, `gh_btn_stop` actions now confirm-then-`sprinkler.shutdown`.
    `switch`, `sprinkler`, `number`, `binary_sensor`, and every non-internal entity: byte-identical (the `sprinkler:`
    block only moved in the dump because new component keys were inserted before it).
  - Sim: same, minus the Wi-Fi pieces (no `gp_wifi_*`, no wifi poller); its `switch` section differs only in
    `args: []` line placement.
  - No HA entity added, renamed or removed.
- **Not checked by the implementer:** nothing on the emulator or on a device (all author items remain open);
  the 8/10 px legibility; step 0 b/c-runtime/d-restart/e/f; CI compile jobs.

## Follow-ups
- Sim SIM button draws above the confirm dialog (see notes).
- Step 0 b/e/f should be confirmed by the author in the emulator (`script/sim`): dim area blocks touches, glyphs.
