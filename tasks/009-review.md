# 009 — Review (round 1)

Verdict: APPROVE

Reviewed: the working tree of `task/009-generic-screens` against `task/007-sim-board` (both at `b0317a6`; all changes
are uncommitted). Untracked `tasks/010-*`, `tasks/011-*` and git-ignored dirs were ignored.

## Checks run
- `script/lint` (SDL stub on PATH, offline) → `esphome config OK: garden-pilot.yaml`, exit 0.
- `script/test` (SDL stub on PATH, offline) → `375 passed in 23.42s`, none skipped (sim rows included).
- `GP_ESPHOME=minimum GP_SECRETS=example sh script/config` → `esphome config OK: garden-pilot.yaml`.
- `GP_ESPHOME=minimum GP_SECRETS=example sh script/config garden-pilot-sim.yaml` → `esphome config OK: garden-pilot-sim.yaml`.
- Manual reading of the diff, the five new packages and `tests/test_screens.py`; token values checked against
  `design/tokens.json`; Setup nav geometry diffed against the Home nav (identical x/y/size/fonts/radius).

## Acceptance criteria
- [ ] Step 0 a–f for both versions — partial: a and d checked at the `esphome config` level on 2026.9.1 and 2026.6.3
  (reproduced above); b, c at runtime, d host restart behaviour, e, f not done (they need the emulator). Left to the
  author; not blocking, the gate items (a, c) validate.
- [x] `uv run pytest -m unit` passes, new tests present — verified via `script/test` (13 tests in `test_screens.py`,
  font test, matrix rows). Reading the tests: each would fail on master (no `setup_page`, `gh_btn_stop` calls
  `sprinkler.shutdown` at the top level, no dialog/diagnostics files).
- [x] `script/lint` clean, `script/test` all pass, none skipped — verified (SDL rows ran with the stub).
- [x] Minimum-version `script/config` for both entry files → OK — verified.
- [ ] CI green (checks, compile pinned/minimum) — not verifiable here; pending the PR.
- [x] Colour literals in the four new tokenized files are tokens only — enforced by
  `test_page_uses_only_token_colors`, and the semantic mapping checked by hand: `bg` dim layer, `card`/`border`
  card, `text`/`text-dim` labels, `error-fill`/`on-error` danger, `green-fill`/`on-green` primary, `green` status,
  `status` inactive nav; radii 2 (`radius-card`) and 3 (`radius-control`); fonts only `montserrat_8/10/12/14`.
- [x] Config diff vs base: only additions plus `nav_btn_setup` target and `gh_btn_stop` actions — verified at the
  source level: no file with `switch:`, `sprinkler:`, `number:` or a non-internal entity is touched; the only
  greenhouse change is `gh_btn_stop.on_click`. All new `sensor` / `text_sensor` / `button` entries are
  `internal: true` (including the nested `wifi_info` sub-sensors). No HA entity added, renamed or removed.
- [x] `docs/SPEC.md` §8, `CLAUDE.md` (layout table, package order, gotchas), `design/README.md` (Pages) updated and
  consistent with the YAML.
- [ ] Emulator walk-through (author) — open.
- [ ] Device walk-through (author) — open.
- [x] Implementer states nothing was checked on the emulator or a device — yes, in Implementation notes.

## Focus points verified
- **Confirm dialog:** STOP (`packages/greenhouse/lvgl_page.yaml`) and RESTART (`packages/lvgl/page_network.yaml`)
  act only inside `if: gp_confirm_result`; `gp_confirm_result` is reset to `false` before the layer is shown, set
  `true` only by the two action buttons; CANCEL only clears `gp_confirm_open`. `wait_until` has `timeout: 30s`
  and the script always ends with `gp_confirm_open := false` + `lvgl.widget.hide` (no stuck modal on timeout,
  cancel or confirm). Globals `restore_value: false`, layer `hidden: true` at boot. The full-screen clickable layer
  blocks the page underneath, so the dialog cannot be re-opened from the page while it is up; `mode: single` is the
  second line of defence (see Suggestion 1).
- **Device-only Wi-Fi:** `network_wifi_status.yaml` is included only by `garden-pilot.yaml`; no sim package uses
  `wifi_info`/`wifi_signal`/`wifi.connected` (test-enforced). `core/diagnostics.yaml` is display-independent.
- **ASCII:** all new screen texts ASCII or LVGL symbols (``, ``, nav icons).
- **Nav targets:** every `lvgl.page.show` target exists in both builds (test-enforced, parametrized per entry).
- **Lambdas:** one-liners plus the short `snprintf` (5 lines) in the Wi-Fi poller, matching the existing poller
  pattern; no `lvgl.*` from `on_value`, only `interval` pollers.
- **Deviation `time.has_time` → `id(ha_time).now().is_valid()`:** reasonable; `ha_time` exists in both builds
  (`core_time` / `core_time_host`).

## Findings
### Required
None.

### Suggestions
1. `packages/lvgl/dialog_confirm.yaml:151` — with `mode: single`, a second `script.execute: gp_confirm` while a dialog
   is open is dropped with a warning, but that caller's `script.wait` + `if gp_confirm_result` then reads the
   **first** dialog's answer, so confirming dialog A would also run caller B's action. Not reachable on the device
   today (the dim layer swallows every touch), but on the emulator the sim-only `nav_btn_sim` (top layer, drawn
   above the dialog) stays tappable, and future callers (task 010 valve test, HA-triggered flows) could hit it.
   Direction: have callers skip when `script.is_running: gp_confirm` (or document "only from touch while the layer
   is hidden" in the header), and add that to the documented calling pattern.
2. `tests/test_screens.py:130` (`test_confirm_dialog_shape`) — the key safety properties of the dialog are not
   asserted: `gp_confirm_result := false` before `wait_until`, CANCEL never sets `gp_confirm_result`, and the
   script ends by clearing `gp_confirm_open` and hiding the layer. Removing the reset would let a stale `true` from a
   previous confirmation fire STOP/RESTART after a timeout, and no test would fail. Add a few structural asserts.
3. `tests/test_screens.py:218` — the ASCII check does not cover the dialog texts passed from
   `packages/greenhouse/lvgl_page.yaml` (title/body/action of STOP); extend the walk to every `script.execute:
   gp_confirm` argument in `packages/**` (and include the `action` key).
4. `design/tokens.json:94` — `error-fill` usage still says "STOP button only"; the dialog's STOP ALL button now uses
   it too (consistent with Assumption 6 and design/README). Update the usage text when tokens are next synced.
5. `CLAUDE.md:100` — the `time.has_time` note is appended to the confirm-dialog bullet; a separate gotcha bullet
   would be easier to find.
6. Follow-ups already noted by the implementer stay valid: emulator `nav_btn_sim` drawn above the dim layer (order
   the sim package before `lvgl_dialog_confirm`, or move the dialog to the end); step 0 b/e/f and host RESTART
   behaviour to be confirmed in `script/sim`. Open questions 1–3 of the task still need the author's answer.
