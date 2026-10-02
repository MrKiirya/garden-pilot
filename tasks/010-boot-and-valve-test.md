# 010 — Generic screens, part 2: boot / connecting screen, Service → Valve test

Status: planned
Roadmap: SPEC §9 stage "Screens on the design system" (stage 9 after task 006's renumbering), slice 2 of 3
(009 confirm + Setup + Network, **010 boot + valve test**, 011 screensaver).
Spec sections: SPEC §3 (sprinkler limits), §4.1, §8; CLAUDE.md core principles 2, 4, 5, 7
Hardware check: **yes, actuator-facing** — the valve test opens real valves. The author verifies the 10 s limit, one
valve at a time, STOP and EXIT on the device with water connected (or relays only, valves unplugged, first).

## Goal
On power-up the display shows a **boot / connecting screen** (draft D17) instead of Home; it switches to Home as soon
as Wi-Fi connects, or after a timeout ("offline mode"), and never opens a valve. In Setup the SERVICE tile opens a
**Valve test** page (D18): for each greenhouse bed a TEST button opens that bed's valve for at most 10 s (hard limit,
enforced twice), one valve at a time; while the page is open the device is in **service mode**: anything else that
starts watering is shut down, the queue is cleared, and the mode ends by EXIT SERVICE, by a 10-minute session timeout
or by a reboot. Both pages follow the design tokens and run in the PC emulator. This file supersedes the outline in
`tasks/009-generic-screens.md` where they differ.

## Context
- Built on task 009 (branch stacked on `task/009-generic-screens`): `setup_page` with a disabled SERVICE tile
  ("Soon"), `gp_confirm` dialog, `test_screens.py`, `TOKENIZED_PAGES`, font/ASCII checks, `network_wifi_status.yaml`
  as the device-only pattern. Also on 006/007 (`garden-pilot-sim.yaml`, `script/sim`, sim matrix rows,
  `test_sim_entry_file` asserting Home is the first page package — this task changes that to `boot`).
- Sprinkler ([esphome.io/components/sprinkler](https://esphome.io/components/sprinkler/), checked 2026-10-02):
  `sprinkler.start_single_valve` takes `valve_number` and optional `run_duration` (overrides the configured duration
  for this run); `sprinkler.shutdown`; `sprinkler.clear_queued_valves` (separate from shutdown). SPEC §3:
  `start_single_valve` turns off auto-advance and the queue; one valve at a time per controller. C++ accessors used
  by the existing poller: `active_valve()`, `time_remaining_active_valve()`, `queued_valve()`.
- LVGL ([esphome.io/components/lvgl](https://esphome.io/components/lvgl/)): the first page in the merged `pages:`
  list is shown at start; `lvgl.page.show`; condition `lvgl.page.is_showing`; `spinner` widget. Whether
  `run_duration` accepts a substitution string such as `10s` on both versions and whether `spinner` styling takes
  `arc_color` on 2026.6.3 → step 0.
- `wifi: on_connect:` is a `wifi` trigger (device only; the `host` platform has no `wifi`). `esphome: on_boot:` in a
  package merges with the entry file's (list).
- Existing safety: board relays are `internal: true`, `ALWAYS_OFF` / `RESTORE_DEFAULT_OFF` (tests
  `test_board_relays_are_safe`, `test_gpio_actuators_are_safe`). Boot code here never touches actuators.

## Decisions
1. **Boot page `packages/lvgl/page_boot.yaml`**, id `boot_page`, D17 layout with tokens, ASCII text: "GardenPilot"
   (`montserrat_14`, `green`, centred at y84), `boot_status_label` "Connecting to Wi-Fi..." (`montserrat_10`,
   `text-dim`, y108), a `spinner` (32×32 at x144 y124, arc `green-fill`, track `track`) **instead of the draft's
   static 40 % bar** (no fake progress), caption "Valves closed - offline mode in ${boot_offline_timeout}"
   (`montserrat_8`, `text-dim`, y162), and `boot_version_label` (`montserrat_8`, `text-dim`, x8 y224) filled from
   `gp_esphome_version` (009) by the sequence.
   - `substitutions: boot_offline_timeout: 30s` (package default; entry file wins).
   - `globals:` `gp_boot_net_ready` and `gp_boot_done` (bool, false, `restore_value: false`).
   - `esphome: on_boot: priority: -100` → `script.execute: gp_boot_sequence`.
   - `script:` `gp_boot_sequence` (`mode: single`): `wait_until` `gp_boot_net_ready` with `timeout:
     ${boot_offline_timeout}`; then `gp_boot_done := true` and `lvgl.page.show: home_page`. On timeout the status
     label is not needed (the page is left immediately). No actuator actions anywhere in the file.
2. **Device-only `packages/lvgl/boot_wifi.yaml`:** `wifi: on_connect: - globals.set: {id: gp_boot_net_ready,
   value: "true"}` only. Header: device only; without it the boot screen always waits for the timeout. The emulator
   has no Wi-Fi and takes the timeout path; `garden-pilot-sim.yaml` sets `boot_offline_timeout: 3s`.
3. **Package order:** `lvgl_page_boot` becomes the first page package, right after `lvgl_base` (before
   `lvgl_page_home`) in both entry files; `lvgl_boot_wifi` after `lvgl_network_wifi` in the device file only. CLAUDE.md
   rule "first page package = boot screen (home)" becomes "(boot)"; 006's `test_sim_entry_file` / 009 checks updated.
4. **Valve test page `packages/greenhouse/lvgl_valve_test.yaml`** (greenhouse-specific: uses `gh_sprinkler`), id
   `valve_test_page`, D18 tokens and geometry:
   - Header "Service - Valves" + right text "SERVICE" (`amber`, `montserrat_10`), caption "Opens one valve, max ${valve_test_max_time}.
     Other watering is stopped." (`amber`, `montserrat_8`, y28).
   - **Rows for beds 1–3 only** (cards 150×44 at (8,44), (162,44), (8,94)); no Lawn/Pump rows (no hardware). The page
     has the same fixed 3-bed limit as the greenhouse page until stage 8; header says so.
   - Per row: name label, `valve_test_bed<N>_status` (`montserrat_8`) and `valve_test_bed<N>_btn` TEST (`green-fill`
     / `on-green`, `btn-h-sm` 20 px, 42 wide). No per-row CLOSE (the draft's ghost CLOSE): STOP closes (Assumption 3).
   - Transport row: STOP (`error-fill`, x8 y210 92×26) → `script.execute: gp_valve_test_stop`; EXIT SERVICE (ghost,
     x104 y210 208×26) → `script.execute: gp_service_exit`.
   - `substitutions: valve_test_max_time: 10s` — **must not exceed 10 s** (test). Header: safety limit, human's call.
5. **Service-mode logic (same file, scripts only, one-line lambdas):**
   - Page `on_load` → `script.execute: gp_service_enter`: `sprinkler.shutdown: gh_sprinkler`,
     `sprinkler.clear_queued_valves: gh_sprinkler`, `gp_service_mode := true`, start `gp_service_session`.
   - `valve_test_bed<N>_btn.on_click`: `script.execute: {id: gp_valve_test_start, valve: N-1}` where
     `gp_valve_test_start` (`mode: restart`, parameter `valve: int`): only if `gp_service_mode`; `sprinkler.shutdown`
     (closes any open valve first: one at a time), `sprinkler.start_single_valve` with `valve_number: !lambda return
     valve;` and `run_duration: ${valve_test_max_time}`, then `script.execute: gp_valve_test_guard` and restart
     `gp_service_session`.
   - `gp_valve_test_guard` (`mode: restart`): `delay: ${valve_test_max_time}` → `sprinkler.shutdown: gh_sprinkler`.
     Second, independent enforcement of the limit (holds even if `run_duration` were ignored).
   - `gp_valve_test_stop`: `script.stop: gp_valve_test_guard`, `sprinkler.shutdown: gh_sprinkler`.
   - `gp_service_exit`: `script.stop` guard and session, `sprinkler.shutdown`, `gp_service_mode := false`,
     `lvgl.page.show: setup_page`.
   - `gp_service_session` (`mode: restart`): `delay: 10min` → `script.execute: gp_service_exit` (a forgotten service
     page does not block watering forever).
   - **Block other watering:** a 1 s `interval` in the same file: if `gp_service_mode` and the sprinkler has an
     active or queued valve while `gp_valve_test_guard` is **not** running → `sprinkler.shutdown` +
     `clear_queued_valves` + log WARN "service mode: external start blocked". This stops runs started by Home
     Assistant or the queue during service; there are no on-device schedules yet. The same interval updates the
     three status labels: "closed" (`text-dim`) / "OPEN - N s" (`green`) from `active_valve()` and
     `time_remaining_active_valve()` (short `snprintf` lambda as in `sprinkler_lvgl_status.yaml`).
   - `globals: gp_service_mode` (bool, false, `restore_value: false`) — reboot always leaves service mode.
   - Only `sprinkler.*` actions on `gh_sprinkler`; **no** `switch.turn_on` of zone or raw relay switches. Header note:
     moves to `gp_*` scripts in stage 8 (principle 2; legacy pattern kept consistent with the greenhouse page).
6. **Setup SERVICE tile** (009's `page_setup.yaml`): becomes a clickable tile `setup_tile_service`, value "Valve test"
   (`amber`, as in D10), chevron, `on_click` → `lvgl.page.show: valve_test_page`. Because the valve test page is a
   greenhouse package, the tile references it: acceptable while the greenhouse is the only zone (both entry files
   include it); headless rows don't include Setup. Note in the tile's comment.

## Files
10 paths.
- create: `packages/lvgl/page_boot.yaml` — Decision 1.
- create: `packages/lvgl/boot_wifi.yaml` — Decision 2.
- create: `packages/greenhouse/lvgl_valve_test.yaml` — Decisions 4–5.
- create: `tests/test_service.py` — valve test / service-mode checks below.
- modify: `packages/lvgl/page_setup.yaml` — SERVICE tile (Decision 6).
- modify: `garden-pilot.yaml`, `garden-pilot-sim.yaml` — packages (Decision 3), sim `boot_offline_timeout: 3s`.
- modify: `tests/test_screens.py`, `tests/test_design_tokens.py` — boot checks, tokenized list; `tests/test_layout.py`
  first-page assertion; `tests/test_config_matrix.py` rows.
- modify: `docs/SPEC.md` §8 (boot screen, service mode and its limits), `CLAUDE.md` (packages order, boot rule,
  gotcha "valve test limit"), `design/README.md` Pages.

## Checks to write first
**Step 0 — spike (not committed), both versions, SDL devcontainer:** a: `run_duration: 10s` via substitution in
`sprinkler.start_single_valve` validates and the valve closes after 10 s in the emulator (log timestamps); b:
`spinner` with token colours validates on 2026.6.3; c: page `on_load` fires on every `lvgl.page.show` of that page;
d: an `on_boot` priority −100 script with `lvgl.page.show` works on host (boot page visible, then Home after 3 s).
Gate: if a fails, keep the guard script as the only limit and record it — do not raise the limit.

| Level | Test | Asserts |
|---|---|---|
| unit | `tests/test_service.py::test_valve_test_limit` | `valve_test_max_time` parses to ≤ 10 s; `start_single_valve` uses `run_duration: ${valve_test_max_time}`; `gp_valve_test_guard` delay is `${valve_test_max_time}` and ends in `sprinkler.shutdown`. |
| unit | `tests/test_service.py::test_valve_test_actions_are_safe` | The file uses only `sprinkler.{start_single_valve,shutdown,clear_queued_valves}` on `gh_sprinkler`; no `switch.turn_on`/`switch.toggle`, no `board_relay_*` reference. |
| unit | `tests/test_service.py::test_service_mode_lifecycle` | `gp_service_mode` `restore_value: false`; page `on_load` runs `gp_service_enter` (shutdown + clear queue); `gp_service_exit` sets it false and shuts down; `gp_service_session` delay ≤ 10 min → exit; the 1 s interval blocks external runs when the guard is not running. |
| unit | `tests/test_service.py::test_valve_rows_match_beds` | Rows 1..3 ↔ `valve_number` 0..2; no row for lawn/pump. |
| unit | `tests/test_screens.py::test_boot_page_first[<entry>]` | In both entry files `lvgl_page_boot` is the first page package; `boot_page` has no actuator action; `gp_boot_sequence` ends in `lvgl.page.show: home_page` and its `wait_until` has `timeout: ${boot_offline_timeout}`. |
| unit | `tests/test_screens.py::test_boot_wifi_device_only` | `boot_wifi.yaml` only `wifi: on_connect` setting `gp_boot_net_ready`; included by the device entry file only; sim sets `boot_offline_timeout`. |
| unit | `tests/test_screens.py::test_nav_targets_exist` (009, extended) | SERVICE tile → `valve_test_page` exists in both entry files. |
| unit | `tests/test_design_tokens.py` (extended) | `page_boot.yaml`, `lvgl_valve_test.yaml` token colours/fonts, ASCII text. |
| unit | `tests/test_layout.py::test_gpio_actuators_are_safe` / `test_board_relays_are_safe` (existing) | Still green. |
| config | existing rows (`full`, `sim_full`, `no_wifi_status`, …) | Validate with the new packages. |
| config | `…[no_boot_wifi]` | Device without `lvgl_boot_wifi` validates. |

## Acceptance criteria
- [ ] Step 0 a–d recorded for 2026.9.1 and 2026.6.3.
- [x] `uv run pytest -m unit`, `script/lint`, `script/test` (host with a stub `sdl2-config`, `GP_REQUIRE_SDL=1`) → all pass (404 passed).
- [ ] CI green: `checks`, `compile (pinned)`, `compile (minimum)`.
- [x] Normalized `esphome config` diff of the device vs. the 009 branch: only the new pages/scripts/globals/interval,
      `wifi.on_connect`, `on_boot`, the SERVICE tile; no change to `switch`, `sprinkler`, `number` or entity names.
- [x] Docs updated (SPEC §8, CLAUDE.md, design/README.md).
- [ ] **Emulator (author):** boot screen with spinner for ~3 s, then Home; Setup → SERVICE → Valve test: TEST bed 2
      → log shows valve 2 on, status "OPEN - N s" counting down (stops near 2 s), closed ~10 s after the tap (valve open ~8 s: sprinkler start delay); TEST bed 1 while bed 2 is open →
      bed 2 closes first, only bed 1 open; STOP closes at once; starting a bed from HA (if connected) or the
      Greenhouse page is impossible while in service (page unreachable) and an HA start is shut down within ~1 s with
      the WARN log; EXIT SERVICE → Setup, watering from the Greenhouse page works again; leaving the page open
      10 min exits service by itself.
- [ ] **Device (author):** boot screen shows until Wi-Fi connects (then Home); with the router off → Home after
      30 s, all relays off throughout; valve test as above with relays (valves unplugged first), then once with water:
      each bed's valve is open ~8 s (never more than 10 s from the tap), never two at once; reboot during a test → all valves off after boot.
- [x] Implementer states that no emulator/device item was checked by it.

## Out of scope
- Task 011: screensaver + the 40 px clock font token.
- Lawn / pump rows (no hardware), per-row CLOSE button, a valve test for other zone groups (stage 8 `gp_*`).
- Blocking Home Assistant *before* it starts a valve (needs the `gp_*` layer to honour `gp_service_mode`; here it is
  shut down within one poll).
- Boot progress based on real connection steps; SNTP/offline clock (stage 10).

## Assumptions (author asleep)
1. **Limit 10 s** (as requested) via substitution, enforced by `run_duration` **and** a guard script; tests forbid
   more. Raising it is the author's call.
2. **Service mode actively stops external watering** (HA, queue) within 1 s instead of only "pausing" — the simplest
   enforceable meaning today. Auto-exit after 10 min.
3. **No per-row CLOSE** (draft shows one on the open bed): STOP does the same; avoids per-row button swapping.
4. **Spinner instead of the static progress bar** of D17 (a fake percentage would mislead).
5. **Boot timeout 30 s** on the device (from D17), 3 s in the emulator.
6. **Wi-Fi connect = ready**; Home Assistant is not awaited (the device works without HA).

## Open questions
1. Is 10 s the right test limit for your valves (opening time of motorised valves can be several seconds)?
2. Should service mode also be visible/settable in Home Assistant (e.g. a switch that blocks automations)?

## Implementation notes
Checks first: `tests/test_service.py` (8 tests: limit <= 10 s and `run_duration` + guard, only allowed sprinkler actions
and no raw relay/switch, service-mode lifecycle, leave-page, STOP/EXIT buttons, rows 1-3 <-> valves 0-2, page only
reachable from Setup), `test_boot_page_first[*]`, `test_boot_wifi_device_only`, extended nav / token / ASCII / layout /
matrix (`no_boot_wifi`) checks. They failed first (missing files). Final: `uv run pytest -m unit` 388 passed,
`GP_REQUIRE_SDL=1 script/test` 404 passed, `script/lint` ok, `esphome config` also OK with the minimum ESPHome
(2026.6.3, `UV_OFFLINE=1`) for both entry files.

Device config differences vs `task/009-generic-screens` (normalized `esphome config` dump, compared section by section;
`switch`, `sprinkler`, `number`, `sensor`, `text_sensor`, `binary_sensor`, `api`, `ota`, `time`, `display`,
`touchscreen` are byte-identical; no Home Assistant entity added, renamed or removed):
1. `substitutions`: `boot_offline_timeout: 30s`, `valve_test_max_time: 10s` (package defaults).
2. `esphome.on_boot` priority -100 -> `gp_boot_sequence` (flag wait + `lvgl.page.show: home_page`; no actuator).
3. `wifi.on_connect` sets `gp_boot_net_ready` (the only change to the `wifi` section).
4. `globals`: `gp_boot_net_ready`, `gp_boot_done`, `gp_service_mode` (none restored).
5. `script`: `gp_boot_sequence`, `gp_service_enter`, `gp_valve_test_start`, `gp_valve_test_guard`,
   `gp_valve_test_stop`, `gp_service_session`, `gp_service_exit`, `gp_service_leave`.
6. `interval`: one new 1 s poller (service-mode blocker + three status labels).
7. `lvgl`: new pages `boot_page` (first) and `valve_test_page`; Setup SERVICE tile became a button ("Valve test",
   chevron). The sim differs the same way minus item 3 plus `boot_offline_timeout: 3s`.

Decisions / deviations:
- Added `on_unload` -> `gp_service_leave` (shutdown, stop guard/session, `gp_service_mode := false`, no navigation) so
  that leaving the page by any route (e.g. the sim SIM button on the top layer) also ends service mode. Not in the
  outline; strictly safer.
- In `gp_valve_test_start` the guard script is started before `start_single_valve` (outline: after), so the open time
  can only be shorter than the limit. Both actions run in one tick, so there is no behavioural gap either way.
- `gp_valve_test_start` checks `gp_service_mode` itself: a TEST tap outside service mode does nothing.
- The boot caption interpolates `${boot_offline_timeout}` ("30s"), the draft says "30 s".
- Status label colours: "closed" `text-dim`, "OPEN - N s" `green`; the poller also runs while the page is hidden
  (the existing LVGL pollers do the same).
- Step 0 spikes (a-d) were NOT run: no emulator/device/devcontainer allowed in this session. Only `esphome config`
  validation covers: `run_duration: ${valve_test_max_time}` and `spinner` with `arc_color` / `indicator`, `on_load`
  and `on_unload` on 2026.9.1 and 2026.6.3. Runtime behaviour (does `run_duration` really close the valve after 10 s,
  does `on_load` fire on every show, does the boot page show before Home) is unverified; the guard script is the
  independent limit if `run_duration` misbehaves.

Not verified by the implementer (no emulator, device, compile or CI run): everything under the two "Emulator" /
"Device" acceptance items and CI `compile (pinned|minimum)`; real valve timing; boot-screen visibility on hardware.
`.esphome/work010/` holds the scratch config dumps (git-ignored).

Review suggestions applied: the ~8 s real open time is documented (YAML header, CLAUDE.md, SPEC §8, design/README.md,
acceptance wording above); the caption uses `${valve_test_max_time}`; the poller test asserts the `and` condition
structure incl. `not: script.is_running: gp_valve_test_guard`; the leave test asserts `gp_service_session` is stopped.

## Follow-ups
- Stage 8: move the valve test to the `gp_*` layer and let it honour `gp_service_mode` before HA starts a valve.
- Consider a boot status text change on timeout and a per-row CLOSE (Assumption 3) if the author wants them.
- Open questions 1 and 2 of this task remain for the author (is 10 s right for motorised valves; service mode in HA).
