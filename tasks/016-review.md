# 016 — Review (round 1)

Verdict: APPROVE

Scope reviewed: `git diff` on `task/016-time-fallback` (uncommitted, on top of master 9bd5da2) plus the untracked
`packages/core/time_sntp.yaml` and `tasks/016-time-fallback.md`. Files changed: `CLAUDE.md`, `docs/SPEC.md`,
`garden-pilot.yaml`, `packages/core/time.yaml` (comment only), `tests/test_config_matrix.py`,
`tests/test_esphome_config.py` and `tests/test_layout.py`, plus the new `packages/core/time_sntp.yaml`. This matches the
task's "Files" list. No README change was needed: neither README names the core packages.

## Checks run
All commands ran on the host from the worktree. `TMPDIR` and `--basetemp` pointed at a session scratch directory.
- `uv run --directory <worktree> pytest -m unit -q` → `495 passed, 27 deselected in 15.40s`
- `script/lint` → yamllint clean, `esphome config OK: garden-pilot.yaml`
- `script/test -q -rs` → `513 passed, 9 skipped in 52.91s`. The skips are: 4 sim `esphome config` rows (no
  `sdl2-config`), 4 `garden_zones` C++ checks (no compiler) and 1 `sim_ui` check (no Xvfb). None of them is caused by
  this change.
- `GP_SECRETS=example GP_VERBOSE=1 script/config garden-pilot.yaml` → OK. The validated `time:` has two items:
  - `platform: homeassistant`, `id: ha_time`, no `timezone`, `update_interval: 15min`, plus the existing Home
    `on_time_sync`.
  - `platform: sntp`, `id: sntp_time`, servers `0/1/2.pool.ntp.org`, `update_interval: 15min`.
- `UV_OFFLINE=1 GP_SECRETS=example GP_ESPHOME=minimum script/config garden-pilot.yaml` → `esphome config OK`. The
  2026.6.3 build is in the uv cache: `uvx --isolated --from esphome==2026.6.3 esphome version` → `Version: 2026.6.3`.
- `script/compile` was not run (no toolchain build here). The CI `compile (pinned)` and `compile (minimum)` jobs
  cover it.

## Design claim verified in the pinned source (esphome 2026.9.1, `.venv/.../esphome/components`)
- `time/real_time_clock.h:32`: `timestamp_now()` is `::time(nullptr)`, and `now()` (`real_time_clock.cpp:26-38`)
  converts it with `get_global_tz()`. Every `RealTimeClock` reads the same process-wide system clock, so
  `id(ha_time).now().is_valid()` turns true after an SNTP sync.
- `sntp/sntp_component.cpp` (ESP32): ESP-IDF `esp_sntp` sets the system time itself. The sync notification only
  calls `time_synced()`, which fires **this** component's `time_sync_callback_`. `ha_time.on_time_sync` therefore does
  not fire on an SNTP sync. This matches the CLAUDE.md gotcha and SPEC §4.1a, and it is why the Home clock can lag up
  to 30 s.
- `time/real_time_clock.cpp:59-108`: the HA source writes via `synchronize_epoch_()`, which skips `settimeofday` when
  the clock is valid and within ±1 s. Two agreeing sources do not cause jumps.
- `time/__init__.py:408-427` and `:121-136`: without `timezone:`, each item uses `detect_tz()`, cached in
  `CORE.data`, so both items emit the same zone. `homeassistant/time/__init__.py:25-26` keeps
  `USE_HOMEASSISTANT_TIMEZONE`, so the runtime push from HA still wins. The offline-timezone caveat in SPEC §4.1a is
  accurate.
- `sntp/time.py`: `servers` takes 1-3 domain names or hostnames, defaults to the pool, and is `cv.only_on` ESP32/…
  (no `host`). Several `sntp` items are merged by a final validator. All of this matches the task's Context section.

## Emulator unaffected
`garden-pilot-sim.yaml` includes `core_api`, `core_time_host` and `core_diagnostics` (lines 47-49) and no
`core_time`/`core_time_sntp`. The diff does not touch it, `time_host.yaml` or any `packages/sim/` file. No file in the sim
include graph changed: `time.yaml` changed in comments only, and the sim entry does not include it
anyway. `test_sim_entry_file` now forbids `core_time_sntp`. The sim `esphome config` rows were skipped locally
(no `sdl2-config`). CI runs them with `GP_REQUIRE_SDL=1`.

## Acceptance criteria
- [x] `uv run pytest -m unit` passes — verified (495 passed).
- [x] `script/lint` passes — verified.
- [x] `script/test` passes, including `no_sntp`, `headless_sntp_only` and `test_sntp_servers_override` — verified
      (513 passed; the new rows are among them, not skipped).
- [x] `GP_SECRETS=example script/config garden-pilot.yaml` → exit 0 with the expected two `time:` items — verified
      from the output above.
- [x] `GP_SECRETS=example GP_ESPHOME=minimum script/config garden-pilot.yaml` → exit 0 — verified offline here
      (2026.6.3). The implementer could not run it; it can be ticked now.
- [ ] `script/compile` / CI compile jobs — not run locally; left to CI on the PR.
- [x] Emulator config unchanged — verified structurally (no file in the sim include graph changed; see above). The
      literal before/after normalized diff was not run, because the sim config cannot be validated without SDL2 here.
      The CI sim config rows are the authoritative check.
- [x] `grep sntp_time` matches only `packages/core/time_sntp.yaml` — verified. A grep over `packages`, `hardware`,
      the entry files, `.github` and the READMEs finds `sntp` only in `time_sntp.yaml`, plus comments in `time.yaml`
      and `garden-pilot.yaml`.
- [x] No `!secret`, IPs or non-generic hostnames — verified (`*.pool.ntp.org`, `ntp.example.lan` in a test only).
- [x] SPEC/CLAUDE.md updated. The new SPEC §4.1a, §5 core list, §9 item 10 ("done, task 016 … RTC follow-up") and §11
      sources are present. In CLAUDE.md: the layout row, the `packages:` order item 1 and the gotcha line.
- [ ] Hardware verification matrix — not run (the implementer reports all rows "not verified"). This is the human's
      step. The PR description must say so. It does not block the merge under the task's own wording.

## Findings
### Required
None.

### Suggestions
1. `tests/test_layout.py:486`: the `defines_ha` regex only matches when `platform:` comes directly before
   `id: ha_time`. A future file written as `- id: ha_time` / `platform: homeassistant` would slip past
   `test_time_ids_single_source`. Parsing with `load_esphome_yaml` and checking `time:` items whose `id == "ha_time"`
   and that are not `!extend` would be more robust.
2. `tasks/016-time-fallback.md:3`: the status still reads `planned`, and the minimum-config checkbox (line 164) can
   now be ticked with the result above. Update both before the PR.
3. Follow-up, out of scope here because the task forbids touching the sim entry: the "Left out of the device's
   package list" header comment in `garden-pilot-sim.yaml:10-16` could also list `core_time_sntp` (no `sntp` on
   `host`) the next time that file is edited.
4. `docs/SPEC.md:126`: `### 4.1a` is a new numbering style in SPEC. It is acceptable, but `4.2` stays unchanged, so
   check that this is the intended convention rather than renumbering.
