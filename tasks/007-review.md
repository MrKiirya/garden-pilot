# 007 — Review (round 1)

Verdict: CHANGES_REQUESTED

Scope: working tree of `task/007-sim-board` against `task/006-pc-emulator` (HEAD == `task/006-pc-emulator`, so the
whole change is the uncommitted diff plus the untracked `packages/sim/`, `script/sim-ctl`, `script/sim_ctl.py`,
`tests/test_sim_ctl.py`, `tasks/007-sim-board.md`). Planning files for tasks 009–011 were ignored.

## Checks run
- `script/lint` → `esphome config OK: garden-pilot.yaml`, exit 0.
- `script/test` → `328 passed, 4 skipped in 15.26s` (skips: the three SDL config rows and the sim `script/config`
  test, because this host has no `sdl2-config`).
- `UV_OFFLINE=1 GP_ESPHOME=minimum uv run pytest tests/test_config_matrix.py -k sim_api_only` → `1 passed`
  (2026.6.3; the display-free sim packages validate without SDL/LVGL).
- Full `garden-pilot-sim.yaml` (scratch copy under `.esphome/review007/full/`, `sdl_options: "-lSDL2"` added to the
  copied `display_sdl.yaml` to bypass the missing `sdl2-config`, example secrets) → `INFO Configuration is valid!` on
  2026.9.1 and on 2026.6.3 (offline). The same entry file without `sim_sensors_lvgl` + `sim_page_board` → valid on
  2026.9.1. This covers the step-0 items (`number.increment`/`decrement` `cycle: false`, `top_layer`, slider and
  switch `on_change`, `lvgl.widget.update: state: checked`).
- `git diff --stat task/006-pc-emulator -- garden-pilot.yaml packages/core packages/greenhouse packages/lvgl
  packages/display_touch.yaml packages/display_sdl.yaml packages/touch_dot_test.yaml 'hardware/esp32-*'
  secrets.example.yaml` → empty; no untracked files in those paths.
- `git grep -nE 'packages/sim|sim_' -- garden-pilot.yaml packages/core packages/greenhouse packages/lvgl
  'hardware/esp32-*'` → no output; `!secret` in `packages`, `hardware`, `packages/sim`, `script/sim_ctl.py` → none.
- Hex colours in `packages/sim/` → only `bg`, `card`, `status`, `border`, `track`, `text`, `text-dim`, `green`,
  `green-fill`; fonts only `montserrat_8` / `montserrat_10`; radii 2 / 3 / 7 = `radius-card` / `radius-control` /
  `radius-pill`.
- Checked against the pinned sources in `.venv`: ESPHome 2026.x auto-authenticates on `HelloRequest` (password auth
  removed in 2026.1.0), so `connect(login=False)` is correct; `NumberCall` does not round to `step`; the API sends
  `object_id` derived from the entity **name** (`snake_case(sanitize(name))`), not from the YAML `id`.
- Not run: `script/compile` of the sim (pinned/minimum), `GP_REQUIRE_SDL=1` in the SDL devcontainer, CI, the PC
  window and `script/sim-ctl` against a live emulator (no containers, no window, no toolchain run in this review).

## Acceptance criteria
- [x] Step 0 results recorded for 2026.6.3 — implementer notes; independently confirmed by validating the full sim
  entry file on 2026.6.3 (offline) above.
- [x] `uv run pytest -m unit` → all pass — confirmed via `script/test` (all unit tests green, incl. 13 in
  `test_sim_ctl.py`).
- [ ] `script/lint` clean (yes) — `script/test` with `GP_REQUIRE_SDL=1` in the SDL devcontainer not run here; the SDL
  rows were validated by hand with `sdl_options` (see above). Left for CI.
- [ ] `GP_SECRETS=example script/compile garden-pilot-sim.yaml` pinned + minimum — not run; left for CI.
- [x] Device diff empty — verified (command above). HEAD equals `task/006-pc-emulator` and no file read by
  `garden-pilot.yaml` changed, so its normalized `esphome config` is identical by construction (`script/lint` renders
  it OK). No rendered side-by-side was pasted, but none is needed when the inputs are byte-identical.
- [x] `git grep` for `packages/sim|sim_` and `!secret` → no output — verified.
- [x] Hex colours in `packages/sim` are token colours only — verified by grep and by `test_page_uses_only_token_colors`.
- [ ] CI green — not available yet.
- [ ] Docs updated, READMEs in sync, generic only — updated and in sync (en/ru same content, no private data), **but
  the `sim-ctl get` example is wrong** (Required 1).
- [ ] PC (author) — not checked by implementer or reviewer; note that the `get gh_soil_moisture_pct` bullet will fail
  as written (Required 1).
- [ ] Optional HA by IP — author.
- [x] Implementer states the PC/HA items were not checked by it — yes.

## Findings
### Required
1. `README.md:94`, `README.ru.md:94`, `script/sim-ctl:4` — the documented example `script/sim-ctl get
   gh_soil_moisture_pct` exits 2 ("no entity named …"). `sim_ctl.resolve_entity` matches the API `object_id` or name,
   and ESPHome derives `object_id` from the entity **name** ("Greenhouse soil moisture" → `greenhouse_soil_moisture`),
   not from the YAML `id`. It only works by coincidence for the `sim_*` entities, whose names snake-case to their ids.
   `tests/test_sim_ctl.py:23` already uses the correct `greenhouse_soil_moisture`, so docs and tests disagree. Fix:
   use `script/sim-ctl get greenhouse_soil_moisture` (or `get "Greenhouse soil moisture"`) in both READMEs and the
   wrapper header; optionally say in the README that `NAME` is the object id shown by `list` or the entity name, not the
   YAML id. The PC acceptance bullet in the task file needs the same correction (it already says "object id as reported
   by `list`").

### Suggestions
1. `script/sim_ctl.py:150` — `set` waits for `abs(state - value) < 1e-6`, but the device stores a float32. For
   non-integer values above 64 the float32 error is bigger than that (e.g. `set "Sim soil moisture" 99.3` → state
   99.30000305, diff 3e-6), so the command times out and exits 1 although the value was applied. Compare after float32
   rounding (`struct.unpack("f", struct.pack("f", v))[0]`) or with a tolerance tied to the step (e.g. `step / 2` or
   `1e-4 * max(1, abs(v))`). Since `NumberCall` does not round to `step`, consider also rejecting off-step values
   (35.3 on a step-1 number) with exit 2. Add a fake-client case that returns the float32-rounded value.
2. Add a unit test that the `sim-ctl` examples in the READMEs resolve: build `object_id`s from the `name`s in
   `packages/sim/*.yaml` with `esphome.helpers.snake_case`/`sanitize` and assert each `get`/`set`/`switch` example
   argument matches one. That would have caught Required 1.
3. `packages/sim/page_board.yaml:525` (and the other `lvgl.slider.update` lambdas) — `(int) state` truncates toward
   zero, so negative air temperatures are off by one step on the slider (−9.5 → −9) while the label (`%.0f`) rounds.
   Use `lroundf(...)` for consistency.
4. `packages/sim/page_board.yaml:418` — `sim_btn_home` is at x=8; design/README.md says "HOME is a ghost button at the
   right" of the transport row. Move it right (e.g. x=232, w=80) or note the deviation in the file header.
5. `packages/sim/page_board.yaml:15-31` — the top-layer `SIM` button also sits over the Touch test page and swallows
   taps in x=200..244, y=1..21 there. Harmless, but worth a line in the header so touch-test results near the top
   edge are not misread.
6. `docs/SPEC.md` §9 stage 6 says "Both parts done" — fine after merge, but the PC/CI items are still open; consider
   wording it as done only once the PR merges.

Follow-ups already listed in the task (shared polled display path for device + sim, `Slider` / relay indicator in the
design artifact, stage-12 API scenario test) are agreed and not blocking.

## Iteration 2

Verdict: APPROVE

### Checks run
- `script/lint` → `esphome config OK: garden-pilot.yaml`, exit 0.
- `script/test` → `333 passed, 4 skipped` (same SDL skips as round 1; this host has no `sdl2-config`).
- Full `garden-pilot-sim.yaml` with the updated `packages/sim/` (scratch copy, `sdl_options` stub as in round 1) →
  valid on 2026.9.1 and on 2026.6.3 (offline).

### Round-1 findings
- Required 1 — resolved: `README.md:94`, `README.ru.md:94`, `script/sim-ctl:4` and the task's PC bullet now use
  `get greenhouse_soil_moisture`; new `tests/test_sim_ctl.py::test_sim_ctl_examples_resolve` derives object ids from
  the sim entity names via ESPHome's `snake_case`/`sanitize` and fails on any README/wrapper example that does not
  resolve.
- Suggestion 1 — done: `as_float32` comparison with a relative tolerance and off-step rejection (exit 2), covered by
  `test_set_accepts_the_float32_state_the_device_reports` and `test_set_rejects_off_step_values`.
- Suggestion 2 — done (the test above).
- Suggestion 3 — done: slider updates use `lroundf`.
- Suggestion 4 — done: `sim_btn_home` at x=232 (right of the transport row).
- Suggestion 5 — documented in the `page_board.yaml` header instead of hidden (no per-page condition for top-layer
  widgets); acceptable.
- Suggestion 6 — done: SPEC §9 says "implemented (done once the PR merges …)".

### Still open (not blocking this review)
`script/compile` of the sim on pinned/minimum, `GP_REQUIRE_SDL=1` run, CI, and the author's PC/HA checks.
