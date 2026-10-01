# 004 — Review (round 1)

Verdict: APPROVE

Scope reviewed: working tree on `task/004-modular-layout` (staged deletions, unstaged edits, untracked `hardware/`,
`packages/core/`, `tests/test_layout.py`, `tests/test_config_matrix.py`, task file) against
`tasks/004-modular-layout.md`, including the "Decisions" section (decision 3: display orientation and touch
calibration move into the board profile).

## Checks run
- `script/lint` → `esphome config OK: garden-pilot.yaml` (yamllint strict silent, exit 0).
- `script/test` → `227 passed in 11.40s` (includes `test_config_matrix.py ...` 3 variants, `test_layout.py`
  8 tests, `test_ci.py` 28 tests).
- `GP_ESPHOME=minimum GP_SECRETS=example sh script/config` → `esphome config OK: garden-pilot.yaml` (2026.6.3
  accepts `!secret` as substitution values and `time: - id: !extend ha_time`).
- **Normalized config diff, independently re-run.** `git archive master` into a scratch dir vs a scratch copy of
  the working tree, both with `secrets.example.yaml` as `secrets.yaml`, `esphome config` (pinned 2026.9.1).
  The scratch helper took the YAML *before* the trailing `INFO Configuration is valid!` line (in 2026.9.1 that
  line comes after the dump), dropped `INFO`/`WARNING` lines and `substitutions`, and loaded `!tags` as strings.
  Each top-level value became a sorted list of canonical JSON items. Output: `sections: 19 19`,
  `differences: 0`. As a sanity check, changing `x_min: 201` to `202` in the branch dump gives exactly one
  `DIFF touchscreen`. Pins, `restore_mode`, `internal`, entity names and ids, display/touch transforms and
  calibration (now string substitutions `"true"`/`"201"`, rendered as `true`/`201`) and the soil calibration are
  identical.
- Optional `main.cpp` comparison: `esphome compile --only-generate` on master vs the branch build. The only
  differences are renumbered generated automation ids, the component registration order and the config-dump
  comment (new substitutions). This is the expected package-order effect.
- `uv run esphome compile` (pinned 2026.9.1) on a scratch copy of the working tree with example secrets →
  `Successfully compiled program.` The minimum-version compile was not run locally; CI `compile (minimum)` covers
  it.
- New tests against the old layout: `tests/test_layout.py`, `tests/test_config_matrix.py` and the modified
  `tests/test_esphome_config.py` were copied into the master scratch tree, which got a throwaway `git init`. Result:
  `6 failed, 7 passed`. The failures are the expected ones: `test_pins_only_in_hardware`,
  `test_hardware_profiles_shape`, `test_no_secret_outside_entry_file`, `test_core_is_display_independent`,
  `test_entry_file_is_a_package_list` and `test_variant_validates[headless]` (headless fails because master's
  network package needs `home_clock_label`). The 7 that pass do so for legitimate reasons:
  `gpio_actuators_are_safe` and `substitutions_resolve` already hold on master, `full`/`no_touch_debug` were
  already valid, and `define_every_pin_used` / `board_settings_are_used` have no profile to check.
- Printed the three matrix variants from `build_variant`: `headless` keeps exactly `hardware`, `core_network`,
  `core_time`, and `no_touch_debug` drops only the `touch_dot_test` line.
- `git diff master --stat -- .github tests/test_ci.py` → empty (required check names `checks`,
  `compile (pinned)`, `compile (minimum)` unchanged in the workflow, ruleset and test).

## Acceptance criteria
- [x] `uv run pytest -m unit` all pass, incl. 7+1 `test_layout.py` tests and the modified entry test. Verified
      through `script/test`, where all 227 pass.
- [x] `script/lint` clean. Verified above.
- [x] `script/test` all pass incl. 3 matrix variants. Verified above.
- [x] Minimum `script/config` OK. Verified above.
- [x] `GPIO\d+` outside `hardware/` appears only in comments or not at all. `test_pins_only_in_hardware` passes,
      and a manual grep of the YAML outside `hardware/` finds none.
- [x] No `!secret` under `packages/` or `hardware/`. Verified by test and by reading the files.
- [x] `packages/network.yaml` and `packages/greenhouse/substitutions.yaml` deleted (staged `D`).
- [x] Normalized config diff shows no differences. Independently re-run, 0 differences (see above).
- [ ] CI on the PR is green. Pending, no PR yet. Workflow, ruleset and `test_ci.py` are unchanged (verified).
- [x] SPEC, CLAUDE.md, README.md and README.ru.md updated as listed in Files. The two READMEs are in sync. Minor
      stale SPEC wording remains (suggestion 1).
- [ ] Hardware checklist (author). Not verified on a device; the implementer says so explicitly. Merging does not
      depend on it, but the author must run it before relying on the firmware.

## Principles and ESPHome correctness
- Pins exist only in `hardware/esp32-s3-devkitc1-breadboard.yaml`, which has the 14 `*_pin` keys exactly as named
  in the task, plus the decision-3 orientation and calibration keys. Its header comment explains how to add a
  board and keeps the MISO/strapping wiring note.
- Raw valve switches are unchanged: `internal: true`, `restore_mode: RESTORE_DEFAULT_OFF`, now guarded by
  `test_gpio_actuators_are_safe`. The max on-time guard is still missing; it is a known legacy gap (stage 6) and
  outside this task.
- `packages/core/*` has no `!secret`, no defaults for the secret substitutions and no LVGL. The headless variant
  proves the core validates alone. The packages are ready to be used as remote packages.
- The clock trigger moved verbatim into `page_home.yaml` through `!extend ha_time`. The "LVGL from
  `on_time_sync`" risk is unchanged (out of scope, SPEC §8).
- Package order follows CLAUDE.md: `hardware` → `core_network` → `core_time` → `display_touch` → LVGL → greenhouse
  → `touch_dot_test`. `gh_substitutions` is removed.
- Public hygiene: no SSIDs, IPs, entity ids, local paths or personal data in the new or changed files.
  `secrets.example.yaml` is untouched. The scratch runs created no `secrets.yaml` in the checkout.
- The `tracked_files` helper in `tests/test_layout.py` (`git ls-files --cached --others --exclude-standard`) also
  works in CI. The checkout is a clean git work tree with no untracked YAML, `.venv/`, `.esphome/` and caches are
  git-ignored, and `conftest.tracked_files` already relies on `git` in the same container.

## Findings
### Required
None.

### Suggestions
1. `docs/SPEC.md:193` — the §8 bullet still starts "`packages/network.yaml` updates `home_clock_label` …", so it
   names a deleted file in the present tense. The following sentence corrects it. Reword it to start from
   `packages/lvgl/page_home.yaml` (`!extend ha_time`). `docs/SPEC.md:209` (§9 item 3) still says "The `config`
   matrix over module combinations waits for stage 4". Point it to `tests/test_config_matrix.py` instead.
2. `tests/test_config_matrix.py:28-50,54` — a `"without"` row silently becomes the full config if the key it
   removes is renamed in `garden-pilot.yaml` (e.g. `touch_dot_test` → `touch_debug`). The row then still passes,
   so the CLAUDE.md promise "comment it out to disable" is no longer tested. The same applies to a `"keep"` row
   whose key disappears. Fix direction: in `build_variant` or the test, parse the variant's `packages:` keys and
   assert they equal the expected set (all keys minus the removed ones, or exactly the kept ones). This matters more
   in task 005, when more rows arrive.
3. `tests/test_layout.py:18` — `--others` makes local runs stricter than CI. Any untracked, non-ignored `*.yaml` in
   the checkout (for example a personal second entry file with real GPIO numbers) fails
   `test_pins_only_in_hardware` locally but not in CI. This is fine for the stated purpose. Mention it in the
   docstring or in CLAUDE.md "Test levels" so a confusing local failure is easy to explain.
4. `tests/test_layout.py:102` — `"'secret'" not in repr(value)` also matches a plain string value `secret`.
   Walking the loaded tree for `{"__tag__": "secret"}` would be exact. This is cosmetic.
5. `tests/test_layout.py:78` — `test_hardware_profiles_define_every_pin_used` and
   `test_hardware_board_settings_are_used` pass when no profile exists. `test_hardware_profiles_shape` covers that
   case today. A one-line `assert _hardware_profiles()` would make each test stand on its own.

## Follow-ups (not blocking)
- Legacy, unchanged by this task: valves still have no max on-time guard (stage 6), the greenhouse page still calls
  `sprinkler.*` (stage 7), and `on_time_sync` still updates LVGL (SPEC §8).
- Author: run the hardware checklist from the task after flashing. Check in particular that HA entity ids and the
  restored bed run durations survive the OTA. The config diff predicts they will (same names and ids).
