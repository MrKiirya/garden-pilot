# 011 — Generic screens, part 3: screensaver with a 40 px clock font token

Status: implemented (awaiting review; emulator/device checks pending)
Roadmap: SPEC §9 stage "Screens on the design system" (stage 9 after task 006's renumbering), slice 3 of 3
(009 confirm + Setup + Network, 010 boot + valve test, **011 screensaver**).
Spec sections: SPEC §8; CLAUDE.md core principles 3, 5, 7; `design/README.md` Type
Hardware check: yes — readability of the 40 px clock on the panel, wake by touch, flash size delta. No actuators.

## Goal
After N minutes without a touch (substitution `screensaver_timeout`, default 5 min) a **screensaver** (draft D23)
covers the screen: a big clock, one status line (greenhouse air temperature and soil moisture), a running-bed
indicator ("Bed 2" with a green dot, hidden when idle) and "Touch to wake". Any touch hides it and the previously
shown page is exactly as it was (the waking touch does not press anything underneath). It never appears while the
boot screen is shown, while a confirm dialog is open or in service mode (valve test). The clock uses a **new design
token** `clock` (40 px / 44 px line height, weight 700) authorised by the author (2026-10-02): a custom font with
only the glyphs `0123456789:-`, documented in `design/README.md` and checked against `tokens.json` by tests. Works in
the PC emulator.

## Context
- Built on 010 (stacked on `task/010-boot-and-valve-test`): globals `gp_boot_done`, `gp_confirm_open` (009),
  `gp_service_mode` (010); `boot_page`; `test_design_tokens.py` font check allowing only `montserrat_8/10/12/14`;
  `test_screens.py`. Sensor ids `gh_air_temperature` (`sensors_air_dht.yaml`), `gh_soil_moisture_pct`
  (`sensors_soil.yaml`); in the emulator task 007 provides template sensors with the same ids (verify in 007; if it
  chose other ids, use those and note it).
- Draft D23: clock 40/44 px weight 700 `text`, centred at y70; status "24C · soil 58% · next 18:00" (label,
  `text-dim`) at x96 y124; 8×8 `green-fill` dot (radius 4) at x132 y146 + "Bed 2" (caption, `green`) at x146 y145;
  "Touch to wake" (caption, `text-dim`) at x98 y220; `bg` ground, 1px `border` frame.
- LVGL ([esphome.io/components/lvgl](https://esphome.io/components/lvgl/), checked 2026-10-02): `on_idle` trigger
  (fires when there was no input for `timeout`), `lvgl.is_idle` and `lvgl.page.is_showing` conditions,
  `top_layer` (always above pages; `hidden` flag + `lvgl.widget.show/hide`). Built-in `montserrat_*` fonts have no
  restricted glyph set; custom fonts come from the `font:` component.
- Font component ([esphome.io/components/font](https://esphome.io/components/font/)): sources are local files
  (`.ttf`, …), `gfonts://` (downloaded and cached) or web URLs; `glyphs:` restricts the baked characters; `bpp` 1–8
  (anti-aliasing). Fonts are usable by LVGL. A `gfonts://` source would need network during `esphome config` /
  compile and in every temp-dir config test → rejected; the TTF is vendored (Decision 2).
- Montserrat is under the SIL Open Font License 1.1 (redistribution allowed with the licence text).

## Decisions
1. **Token.** `design/tokens.json` → `type.groups[Device].styles` gets
   `{"name": "clock", "fontSize": "40px", "lineHeight": "44px", "fontWeight": 700, "sample": "14:32",
   "glyphs": "0123456789:-", "usage": "Screensaver clock only; custom font gp_font_clock (digits, colon, dash)."}`;
   `meta.synced` unchanged, and `design/README.md` Type section: "five sizes: … `clock` 40px/700, screensaver only,
   digits/colon/dash only (custom font, ~10 KB); don't use it elsewhere". Syncing the token back to the claude.ai
   design system is the author's follow-up.
2. **Font file vendored:** `packages/lvgl/fonts/Montserrat-Bold.ttf` (static Bold from the upstream Montserrat
   repository, github.com/JulietaUla/Montserrat, pinned tag; SHA-256 recorded in the font package header and in
   Implementation notes) + `packages/lvgl/fonts/OFL.txt` (licence text). Inside `packages/` so the existing staging
   scripts (`script/config`, `script/compile`, `script/sim`) copy it with no script change.
3. **Screensaver `packages/lvgl/screensaver.yaml`** (generic, device + sim):
   - `substitutions: screensaver_timeout: 5min` (entry file wins).
   - `font: - id: gp_font_clock, file: packages/lvgl/fonts/Montserrat-Bold.ttf, size: 40, glyphs: "0123456789:-",
     bpp: 4` (path relative to the entry file — step 0 b).
   - `lvgl: top_layer: widgets:` root `obj` `gp_screensaver_layer` (0,0 320×240, `bg` COVER, 1px `border`, `hidden:
     true`, clickable) with `gp_screensaver_clock` (`gp_font_clock`, `text`, `align: TOP_MID`, y70, initial
     "--:--"), `gp_screensaver_status` (`montserrat_10`, `text-dim`, `align: TOP_MID`, y124, initial ""),
     `gp_screensaver_bed_dot` (8×8 `obj`, `green-fill`, radius = half its height as for the pill, hidden),
     `gp_screensaver_bed_label` (`montserrat_8`, `green`, hidden), "Touch to wake" (`montserrat_8`, `text-dim`,
     `align: TOP_MID`, y220). Layer `on_press` → `lvgl.widget.hide: gp_screensaver_layer` (the press is consumed by
     the layer, so nothing underneath fires).
   - `lvgl: on_idle: - timeout: ${screensaver_timeout}` → `if` all of: `gp_boot_done`, not `gp_confirm_open`, not
     `gp_service_mode`, not `lvgl.page.is_showing: boot_page` → update the clock (`time_format: "%H:%M"`, `ha_time`)
     and `lvgl.widget.show: gp_screensaver_layer`.
   - `interval: 10s` → clock label update (no lambda). Header: generic; status line comes from zone packages.
4. **Greenhouse status `packages/greenhouse/screensaver_status.yaml`:** a 2 s `interval` writing
   `gp_screensaver_status` = "<t>C - soil <s>%" (ASCII; "--" parts when a sensor has no state; short `snprintf`
   lambda like `sprinkler_lvgl_status.yaml`) and showing/hiding the dot + "Bed N" from `gh_sprinkler.active_valve()`.
   No "next 18:00" part (no schedules; Assumption 3). Device and sim (sim needs 007's sensors).
5. **Entry files:** `lvgl_screensaver` after `lvgl_dialog_confirm`; `gh_screensaver_status` after
   `gh_sprinkler_lvgl`, in both. `garden-pilot-sim.yaml` sets `screensaver_timeout: 1min` (quick manual check);
   the device keeps 5 min.
6. **Top-layer merge.** 009's dialog and this screensaver both add `lvgl: top_layer: widgets:` from different
   packages. Step 0 a checks the lists are concatenated; if not, stop and ask (fallback idea: one
   `packages/lvgl/overlays.yaml` holding both) — don't restructure 009 on your own.

## Files
12 paths.
- create: `packages/lvgl/screensaver.yaml` — Decision 3.
- create: `packages/greenhouse/screensaver_status.yaml` — Decision 4.
- create: `packages/lvgl/fonts/Montserrat-Bold.ttf`, `packages/lvgl/fonts/OFL.txt` — Decision 2.
- create: `tests/test_screensaver.py` — checks below.
- modify: `design/tokens.json`, `design/README.md` — Decision 1.
- modify: `garden-pilot.yaml`, `garden-pilot-sim.yaml` — Decision 5.
- modify: `tests/test_design_tokens.py` — allowed fonts derived from tokens; tokenized list.
- modify: `tests/test_config_matrix.py` — row below; `tests/test_public_hygiene.py` only if it trips on the `.ttf`
  (exclude binaries by suffix, not by path).
- modify: `docs/SPEC.md` §8, `CLAUDE.md` (layout: `packages/lvgl/fonts/`; packages order; gotcha "custom fonts:
  vendored TTF, glyph-limited, one per token").

## Checks to write first
**Step 0 — spike (not committed), both versions, SDL devcontainer:** a: two packages each adding `top_layer:
widgets:` → both widgets exist (concatenated); b: `font: file:` with a repo-relative path inside an included package
resolves from the staged entry file, config + compile; c: `on_idle` with a substitution timeout (`1min`) fires once
per idle period in the emulator and not again until the next input; d: `on_press` on the layer hides it and a button
under it does not fire; e: flash/RAM delta of the font (compile size line, device build). Gate: if a or b fails,
`blocked` with the error.

| Level | Test | Asserts |
|---|---|---|
| unit | `tests/test_design_tokens.py::test_clock_token` | `tokens.json` has style `clock`: 40px / 44px / 700 / glyphs `0123456789:-`. |
| unit | `tests/test_screensaver.py::test_font_matches_token` | `gp_font_clock` `size` = 40, `glyphs` = token glyphs, `file` exists under `packages/lvgl/fonts/`, `OFL.txt` exists next to it, the TTF's SHA-256 equals the one in the header comment; it is the only `font:` in `packages/`. |
| unit | `tests/test_design_tokens.py::test_page_uses_only_token_fonts` (changed) | Allowed fonts = `montserrat_<n>` for the four built-in token sizes + `gp_font_clock`; `gp_font_clock` used only in `screensaver.yaml`. |
| unit | `tests/test_design_tokens.py::test_page_uses_only_token_colors` (extended) | `screensaver.yaml`, `greenhouse/screensaver_status.yaml` added. |
| unit | `tests/test_screensaver.py::test_idle_guards` | `on_idle` timeout is `${screensaver_timeout}`; its `if` checks `gp_boot_done`, `gp_confirm_open`, `gp_service_mode` and `boot_page`; layer starts `hidden: true` and hides itself `on_press`; no actuator or `lvgl.page.show` action in the file. |
| unit | `tests/test_screensaver.py::test_entry_files` | Both entry files include `lvgl_screensaver` and `gh_screensaver_status`; default timeout ≥ 1 min; sim overrides only `screensaver_timeout`. |
| unit | `tests/test_screens.py::test_screen_text_is_ascii` (009, extended) | New texts ASCII; clock initial text within the glyph set. |
| config | existing rows | Validate (fonts staged with `packages/`). |
| config | `…[no_screensaver]` | Device without `lvgl_screensaver` **and** `gh_screensaver_status` validates. |

## Acceptance criteria
- [ ] Step 0 a–e recorded for 2026.9.1 and 2026.6.3 (incl. font flash delta).
- [ ] `uv run pytest -m unit`, `script/lint`, `script/test` (SDL devcontainer, `GP_REQUIRE_SDL=1`) → all pass.
- [ ] CI green: `checks`, `compile (pinned)`, `compile (minimum)`.
- [ ] `git grep -n 'gfonts://\|https://.*\.ttf' -- packages` → no output (no build-time download).
- [ ] Normalized device config diff vs. the 010 branch: only the font, the top-layer widgets, `on_idle`, intervals;
      no entity changes.
- [ ] `design/tokens.json`, `design/README.md`, SPEC §8, CLAUDE.md updated; licence file present.
- [ ] **Emulator (author):** no input for 1 min → screensaver with the PC time; with a bed running (Greenhouse RUN)
      the dot and "Bed N" show, otherwise hidden; status line shows the sim values; a click hides it and the same
      page/state is back, and the click did not press anything; it never appears on the boot screen, with the
      confirm dialog open or on the valve test page.
- [ ] **Device (author):** after 5 min idle the screensaver shows; the clock is crisp and readable at a distance;
      touch wakes; flash usage delta noted.
- [ ] Implementer states that no emulator/device item was checked by it.

## Out of scope
- Backlight dimming / display off (needs a backlight output in the board profile — hardware decision), lowering
  LVGL refresh while idle (`lvgl.pause`), burn-in shifting.
- "next 18:00" in the status line (schedules, stage 11), lawn part of the status line.
- D16 standby, D19 calibration, alerts, history.

## Assumptions (author asleep)
1. **Overlay, not a page:** the screensaver is a top-layer overlay so "back to the previous page" needs no page
   history (ESPHome has only `lvgl.page.next/previous` in list order).
2. **Vendored TTF** (OFL) instead of `gfonts://`: tests and builds stay offline and deterministic; glyphs
   `0123456789:-` (the dash for `--:--` before the clock is set), `bpp: 4`.
3. **Status line without "next"** until schedules exist.
4. **Timeouts:** 5 min on the device (author's example), 1 min in the emulator.
5. **Not in service mode** either (valve state must stay visible during a test).

## Open questions
1. Should the screensaver also turn the backlight down/off (needs a dimmable backlight pin in the board profile)?
2. Weight 700 at 40 px as in D23 — confirm after seeing it on the panel.

<!-- Filled in by implementer -->
## Implementation notes
- Font: `packages/lvgl/fonts/Montserrat-Bold.ttf` + `OFL.txt` vendored by the main session (author-approved download) from
  https://github.com/JulietaUla/Montserrat (`fonts/ttf/`, master, not a pinned tag), SHA-256
  `bc6e854971cea46b463be6f9eef4d9cd52f51cfc1fc0dd90c9d3e6483dc0ec61` (also in the `screensaver.yaml` header; the test checks it).
- Implemented Decisions 1-5 as written. `lvgl: on_idle` is a list with one `timeout: ${screensaver_timeout}` item; the
  clock label uses `text: {time_format: "%H:%M", time: ha_time}` in `lvgl.label.update` (accepted by `esphome config`).
  A 10 s `interval` refreshes the clock while the overlay is up. Sensor ids `gh_air_temperature` / `gh_soil_moisture_pct`
  exist in the emulator's `packages/sim/sensors.yaml` too.
- `screensaver.yaml` depends on globals from `page_boot` (`gp_boot_done`), `dialog_confirm` and `lvgl_valve_test`
  (`gp_service_mode`): documented in its header; it cannot be used without them.
- Tests: `test_screensaver.py` (font/token, idle guards, status package, entry files, ASCII/glyphs), `test_clock_token`,
  fonts check updated in `test_design_tokens.py`, `no_screensaver` config row, new files in the tokenized/ASCII lists.
  Binary suffix change in `test_public_hygiene.py` was not needed (the TTF passes the scan).
- Results: `script/lint` ok, `script/test` 430 passed (stub `sdl2-config` in PATH, so the sim rows ran);
  `GP_REQUIRE_SDL=1` matrix rows pass; sim config OK.
- NOT done / not verified: Step 0 spike a-e as a separate recorded run (a, b are covered by `esphome config` passing for
  device + sim with both top-layer packages and the repo-relative font path; c, d, e - `on_idle` firing once per idle
  period, press swallowed by the layer, flash/RAM delta - need a compile/emulator/device); minimum ESPHome (2026.6.3)
  config check (not in the offline uv cache); no compile; no emulator or device item was checked by the implementer.
- Assumption: font source is master (not a tag) as vendored by the main session; pin a commit if reproducibility matters.
- Review round 1 fixes: overlay moved to the foreground (`lv_obj_move_foreground`) before showing, so the sim SIM button
  cannot cover it (lambda not compiled here); clock shows `--:--` until `ha_time.now().is_valid()` (script
  `gp_screensaver_update_clock`, used by on_idle and the 10 s interval); source comment no longer matches the `.ttf` grep;
  font provenance = JulietaUla/Montserrat master commit 555facfb2a18c72c3c0380f0d9c0f060453a9058 (fetched 2026-10-02,
  latest tag v9.000); OFL note in both READMEs; `*.ttf binary`; NaN readings show `--`; guard test checks structure.
## Follow-ups
- Pin the vendored font to an upstream commit/tag in the notes; sync the `clock` token back to the claude.ai design system.
