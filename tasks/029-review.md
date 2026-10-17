# 029 — Review (round 1)

Verdict: APPROVE

Scope: `git diff origin/master...HEAD` (4 commits, spec + checks + feature + rig feedback fixes), checked against
`tasks/029-font-scale-c.md` including "Rig feedback (2026-10-17)".

## Checks run
- `script/lint` → yamllint ok, `esphome config OK: garden-pilot.yaml` (exit 0)
- `script/test` → `6 failed, 857 passed, 19 skipped in 169.76s`. The 6 failures are exactly the known Windows-only ones
  (`test_ci.py::test_esphome_selector_resolves`, 4 executable-bit tests in `test_devcontainer.py`,
  `test_sim_ui.py::test_start_xvfb_deadline_holds_when_xvfb_hangs`). Sim config row and Xvfb tests skipped (no
  `sdl2-config` / Xvfb on this host).
- `script/test-cpp` (zig c++ through a wrapper) → `82 test cases, 0 failed checks` (incl. `saver_date_*`,
  `version_short_strips_the_config_hash`).
- `rg montserrat_8` over all YAML → no match; `rg montserrat_16 packages` → only `page_boot.yaml:59`;
  `rg on_time_sync packages/lvgl` → no match; legacy pages (`greenhouse/lvgl_page.yaml`, `page_lawn.yaml`,
  `page_touch_test.yaml`) not in the diff.
- Nav icon PNGs: all four are 12x12 RGBA (colour type 6).
- Nav geometry, labels (DASH / ZONES / SCHEDULE / SETUP), icons and colours compared with the DS NavBar
  (`components/bundle.js` `NAV_DEFAULT`, `bundle.css` `.gp-nav`): match.

## Acceptance criteria
- [x] `uv run pytest -m unit` passes incl. the table tests — verified via `script/test` (only known Windows failures).
- [x] `script/test-cpp` passes — run here, 82 cases.
- [x] `script/lint` / `script/test` green — see above (device + four example config rows ran; sim row skipped locally,
  CI has `GP_REQUIRE_SDL=1`).
- [x] `montserrat_8` only in buttons — superseded by rig item 1: it is gone from the repo entirely.
- [x] `montserrat_16` only in `page_boot.yaml` — verified.
- [x] No `on_time_sync` in `packages/lvgl` — verified.
- [x] Legacy pages untouched — verified (`test_untouched_legacy_pages` guards it).
- [x] Valve test safety — the only script change is rig item 3 (conditional `gp.stop_all`); `valve_test_max_time`,
  `duration` of `gp.run_zone`, `gp_valve_test_guard` (started before `gp.run_zone`), `gp_service_enter` (stop + clear
  queue + `gp.inhibit`), the 1 s blocking poller and the exits are unchanged. `test_service.py` asserts the new order.
- [ ] `GP_SECRETS=example script/compile garden-pilot.yaml` + flash size delta — not run here (main session compiles on
  the rig). Implementer estimate: net about +1 KB after the rig fixes. Record the measured before/after in the task.
- [ ] `script/sim-ui` screenshots — not done (no Xvfb on Windows); still needed for the PR.
- [ ] Hardware legibility / ticking header clock / screensaver date — author, in progress.
- [x] Rig 1 (Bold button fonts) — `gp_font_button_md` / `_sm` in `base.yaml` from the vendored TTF, glyphs equal the
  tokens (`test_button_fonts_match_tokens`), every action-button label uses them, static button texts covered
  (`test_button_glyphs_cover_button_texts`).
- [x] Rig 2 (short ESPHome version) — `gp::fmt::version_short` + C++ test; Network value labels `height: 15`.
- [x] Rig 3 (valve test opens at once) — verified in code: from IDLE `fsm_transition_from_shutdown_()` sets
  `active_req_` immediately, so the old ~2 s came only from the idle `shutdown()`.
- [x] Rig 4 (design NavBar with PNG icons) — `test_nav_matches_design_navbar`, `test_nav_icons_are_vendored_images`;
  no `///` left in the navs.
- [x] Docs — `design/README.md`, `docs/SPEC.md` (§4.1a/§8/valve test), `CLAUDE.md` gotchas, `time_host` / `time_sntp`
  comments updated.

## Principles
- LVGL is written only from the 2 s `interval` (shared `gp_header_clock_update`, appended with `!extend` per page;
  `test_header_clock_merged` proves the merge in `esphome config`) and click handlers; screensaver date comes from the
  existing screensaver clock script. No `lvgl.*` from `on_value` / time triggers.
- Pure formatters (`saver_date`, `version_short`) in `components/gp/format.h`, unit tested; texts ASCII.
- Fonts: built-in 10/12/14/16 + `gp_font_clock` + two glyph-limited custom fonts, `montserrat_8` dropped; all mapped to
  tokens. `gp_root` used for the new font and image paths (`test_gp_root_default` counts `base.yaml`).
- No secrets, IPs or personal data in the diff.

## Findings
### Required
None.

### Suggestions
1. `packages/greenhouse/lvgl_valve_test.yaml:64` — "one valve at a time" can now be broken by a quick double tap when
   `gh_max_parallel` is not `"1"`. `summary()` is the gp model snapshot refreshed every 250 ms (`REFRESH_MS`,
   `components/gp/gp.h:531`). Tap bed 1 TEST, then bed 2 TEST within that window: `summary().running` is still false,
   so `gp.stop_all` is skipped. Each bed has its own lane, so `run_valve` opens bed 2 next to bed 1. With the default
   `max_parallel: 1` the second request just switches the valve on the same lane. Both valves stay limited by their
   `duration`, and the restarted guard stops both, so the 10 s limit holds. But the file header promises one valve at
   a time. Possible fix, with no engine change: also stop first while a test is in progress, i.e.
   `summary().running || script.is_running: gp_valve_test_guard` (the guard runs for 10 s after every TEST tap), and
   add the matching assert in `tests/test_service.py`.
2. `packages/lvgl/dialog_confirm.yaml:170,173` — the OK labels now use `gp_font_button_md` (upper case, digits,
   ` +-./:%`), but their text comes at run time from the caller's `action` argument. Today the callers pass `"STOP ALL"`
   and `"RESTART"`, which is fine. A future `action: "Stop"` would render with missing glyphs, and
   `test_button_glyphs_cover_button_texts` reads only static texts. Extend that check (or
   `test_confirm_call_texts_are_ascii`) so every `gp_confirm` `action:` must be a subset of the button glyphs.
3. `packages/lvgl/page_network.yaml:211-213` — the version lambda is three lines; rig item 2 asks for one line. Could be
   `return id(gp_esphome_version).has_state() ? gp::fmt::version_short(id(gp_esphome_version).state) : std::string("--");`.
4. `README.md:102` (and `README.ru.md`) still says "Home refreshes its labels every 30 s". That is about the sensor
   labels, not the clock, so it may still be correct. Check that it holds after the poller change.

### Follow-ups (not blocking)
- Record the measured flash delta from the rig compile in the task's Implementation notes (budget 40 KB).
- Attach the sim-ui screenshots (Home, Setup, Network, valve test, screensaver, SIM board) to the PR. Check the 8 px
  Bold nav labels and the thin icon strokes (RGB565 alpha edges) on the panel.
- Ask the designer to add `button-md` / `button-sm` (with `font` / `glyphs`) to the DS.
