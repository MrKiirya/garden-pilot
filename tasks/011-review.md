# 011 — Review (round 1)

Verdict: CHANGES_REQUESTED

Reviewed: working tree of `task/011-screensaver` against `cd501d9` (tip of `task/010-boot-and-valve-test`).

## Checks run
- `script/lint` (stub `sdl2-config` in PATH) → `esphome config OK: garden-pilot.yaml` (yamllint clean)
- `GP_REQUIRE_SDL=1 script/test` → `430 passed in 56.21s`
- `uv run --offline pytest -m unit -q` → `413 passed, 17 deselected`
- `GP_VERBOSE=1 GP_SECRETS=example script/config garden-pilot.yaml` and `garden-pilot-sim.yaml` → both OK (ESPHome 2026.9.1)
- Normalized device config, base commit (via `git archive` + `esphome config`) vs. working tree → only the screensaver
  top-layer widgets, `on_idle`, two `interval`s and `font: gp_font_clock` are added (plus a key reorder of
  `long_press_time`); no entity added, renamed or removed.
- `sha256sum packages/lvgl/fonts/Montserrat-Bold.ttf` → `bc6e8549...dec61`, equals the header and the notes.
- `grep -rn 'gfonts://\|https://.*\.ttf' packages` → **1 hit** (header comment of `screensaver.yaml`, line 12).
- Minimum ESPHome 2026.6.3: **not verified** (not in the offline uv cache); CI `compile (minimum)` must cover it.

## Acceptance criteria
- [ ] Step 0 a-e recorded for 2026.9.1 and 2026.6.3 — not met: a and b are implied by `esphome config` on 2026.9.1
      only; c, d, e (idle firing, swallowed press, flash delta) and the 2026.6.3 run are not recorded. I verified
      from the 2026.9.1 source that `IdleTrigger` fires once per idle period and re-arms only after input (c, by code).
      d is actually broken in the emulator (Required 1).
- [x] `pytest -m unit`, `script/lint`, `script/test` (`GP_REQUIRE_SDL=1`, stub sdl2-config) → all pass.
- [ ] CI green — not verifiable here (no push); minimum ESPHome rests on CI.
- [ ] `git grep -n 'gfonts://\|https://.*\.ttf' -- packages` → no output — not met: the header comment matches
      (Required 3). No build-time download exists, though.
- [x] Normalized device config diff vs. 010: only font, top-layer widgets, `on_idle`, intervals; no entity changes.
- [x] `design/tokens.json`, `design/README.md`, SPEC §8, CLAUDE.md updated; `OFL.txt` present next to the TTF.
- [ ] Emulator (author) — pending; note Required 1 will make the "click did not press anything" item fail.
- [ ] Device (author) — pending.
- [x] Implementer states that no emulator/device item was checked.

Principles: no actuator touched (status package only reads `gh_sprinkler`/sensors; tested); no `lvgl.*` in
`on_value`; lambdas are short; token colours only (`test_page_uses_only_token_colors` covers both files, checked by
hand too: `bg`, `border`, `text`, `text-dim`, `green-fill`, `green`); ASCII texts; `gp_font_clock` restricted to the
screensaver file; `meta.synced` unchanged; no secrets or personal data in the diff. Guards: boot (`gp_boot_done` +
`boot_page`), confirm dialog (`gp_confirm_open`), service mode (`gp_service_mode`; the valve test page and service
mode coincide because `gp_service_exit` navigates to Setup). Same page on wake: overlay, no `lvgl.page.show`.

## Findings
### Required
1. `garden-pilot-sim.yaml` (package order) + `packages/lvgl/screensaver.yaml:59` — in the emulator the SIM button
   (`nav_btn_sim`, `packages/sim/page_board.yaml`, also on `top_layer`) is merged **after** the screensaver (verified
   in the merged sim config: `gp_confirm_layer` → `gp_screensaver_layer` → `nav_btn_sim`), so it is drawn above the
   screensaver and stays clickable. A wake tap at x200..244 y1..21 opens `sim_board_page` underneath (and, from the
   valve-test path, would run `gp_service_leave`) while the screensaver stays up. This violates "the waking touch
   does not press anything underneath / same page is back" in the emulator acceptance item. Fix direction: bring the
   layer to the front when showing it (e.g. a one-line `lambda: lv_obj_move_foreground(id(gp_screensaver_layer));`
   before `lvgl.widget.show`), or order the packages so the screensaver is the last top-layer contributor; add a test
   that the screensaver is the last top-layer widget in the merged sim and device configs (or that the show path
   moves it to the foreground).
2. `packages/lvgl/screensaver.yaml:46-50, 128-135` — the clock is written with `time_format` regardless of time
   validity. Before `ha_time` is synced (device offline from HA — exactly the boot offline path) `now()` is not
   valid and the label shows a bogus time from the unsynced system clock (e.g. "00:07") instead of `--:--`, every
   10 s. Assumption 2 says the dash glyph exists for `--:--` "before the clock is set", so the intended behaviour is
   not implemented. Fix direction: wrap both updates in `if: condition: lambda: "return id(ha_time).now().is_valid();"`
   with an `else` writing `"--:--"` (CLAUDE.md gotcha: `time.has_time` is not a condition); extend
   `test_idle_guards` to require the validity check in both places.
3. `packages/lvgl/screensaver.yaml:12` — the acceptance grep `git grep -n 'gfonts://\|https://.*\.ttf' -- packages`
   must print nothing; the source comment `https://github.com/JulietaUla/Montserrat (fonts/ttf/Montserrat-Bold.ttf`
   matches. Fix direction: reword (e.g. "Source: github.com/JulietaUla/Montserrat, file fonts/ttf/Montserrat-Bold.ttf")
   and optionally make the grep a unit test.

### Suggestions
1. Font provenance: Decision 2 asked for a pinned tag; the notes say `master`. Record the upstream commit (or
   release tag) and the font version next to the SHA-256 in the header so the file can be re-fetched and verified.
2. Licence visibility: the repo is MIT (`README.md`/`README.ru.md` "License" section) while the TTF is OFL 1.1. Add a
   one-line third-party note to both READMEs' License section ("Montserrat Bold font in `packages/lvgl/fonts/`:
   SIL OFL 1.1, see `OFL.txt`"). `OFL.txt` itself is complete (copyright line + full licence text); the font is
   unmodified, so no Reserved Font Name issue.
3. `.gitattributes` — add `*.ttf binary`. Git's `text=auto` autodetects the TTF as binary today, but an explicit
   rule protects the checksum test from any EOL conversion on Windows.
4. `packages/greenhouse/screensaver_status.yaml:13-16` — `has_state()` is true for a NaN reading (DHT read failure
   publishes NaN), giving "nanC"; use `!std::isnan(...)` alongside `has_state()` to fall back to "--".
5. `tests/test_screensaver.py::test_idle_guards` — `str(guard["condition"])` only checks the names appear; it would
   still pass if `gp_boot_done` were negated or a guard moved under `or:`. Assert the structure (`and` list, one
   positive `gp_boot_done` lambda, three `not:` entries).
6. Record Step 0 c-e (emulator idle/wake, flash/RAM delta from a device compile) in the Implementation notes when the
   author runs them, and the 2026.6.3 config/compile result from CI.

Follow-ups (not blocking): sync the `clock` token back to the claude.ai design system; backlight dimming (Open
question 1).

# 011 — Review (round 2)

Verdict: APPROVE

## Checks run
- `script/lint` → `esphome config OK: garden-pilot.yaml`
- `GP_REQUIRE_SDL=1 script/test` (stub `sdl2-config`) → `434 passed in 78.62s`
- `grep -rn 'gfonts://\|https://.*\.ttf' packages` → no output
- `GP_SECRETS=example script/compile garden-pilot.yaml` (ESPHome 2026.9.1, offline cache) → `Successfully compiled
  program.`, RAM 33.8 % (115635 B), Flash 65.3 % (1198235 B). The `lv_obj_move_foreground` lambda builds (LVGL 9.5.0
  ships it in `lv_api_map_v8.h`, which `lvgl.h` includes). Font flash delta not measured (no base build to compare).
- Minimum ESPHome 2026.6.3: still not verified locally; it depends on CI `compile (minimum)`.

## Round 1 required items
1. Fixed. The SIM button sat above the overlay. `on_idle` now runs `lv_obj_move_foreground(id(gp_screensaver_layer))`
   before `lvgl.widget.show`. `test_screensaver_is_the_top_layer_foreground_in_the_emulator` checks the order and
   that the emulator has other top-layer contributors.
2. Fixed. The clock showed a wrong time before sync. Script `gp_screensaver_update_clock` writes `--:--` unless
   `id(ha_time).now().is_valid()`, and both `on_idle` and the 10 s interval use it. `test_idle_guards` asserts this.
3. Fixed. The header comment is reworded, and `test_no_font_download_urls` now runs the acceptance grep.

All round 1 suggestions are done: upstream commit `555facf` recorded, OFL note in both READMEs, `*.ttf binary`,
NaN shown as `--`, guard test now checks the structure. One point is still open: Step 0 c-e and the emulator/device
items are the author's manual checks, so they remain unchecked in the task file.
