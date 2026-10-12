# 014 — Review (round 1)

Verdict: APPROVE

Reviewed `git diff 2e9a6ea 56a647b` (6 commits after the 013 merge) against `tasks/014-switch-to-garden-zones.md`,
including its "Human decisions (2026-10-10)" section and the Implementation notes.

## Checks run
All in the dev container `gp-dev-014`:
- `script/lint` → `esphome config OK: garden-pilot.yaml` (yamllint clean)
- `script/test-cpp` → `26 test cases, 0 failed checks`
- `UV_OFFLINE=1 GP_REQUIRE_CXX=1 script/test` → `636 passed in 728.08s (0:12:08)`, 0 skipped (incl. the
  `test_greenhouse_zones.py` host scenario, the new config-matrix rows and `test_sim_ui.py`)
- `git grep -n -e gh_sprinkler -e 'sprinkler\.' -e '^sprinkler:' -- packages hardware garden-pilot.yaml garden-pilot-sim.yaml`
  → only `gh_sprinkler_lvgl` (package key kept on purpose, Decision 5)
- `git grep 'GZ-PATCH-BEGIN' -- components` → 013's ids plus `number-clamp`; `PATCHES.md` has the section;
  `test_patch_ids_documented` enforces the set.
- **Emulator number-clamp check (E2 equivalent, not done by the implementer):** `script/sim-ui start` (defaults), set
  "Greenhouse bed 3 run duration" = 50 and bed 2 = 7, stop; restart with `GP_SIM_SUBST="gh_bed_run_max=10"` → bed 3 = 10,
  bed 2 = 7, bed 1 = 5, log: `[W][garden_zones:038]: Restored value 50.0 of 'Greenhouse bed 3 run duration' is outside
  1.0..10.0, clamped to 10.0`. A further restart on the default build reads 10 (clamped value persisted). Prefs restored
  to 5/5 afterwards; `sim-ui` stopped. This also exercises `GP_SIM_SUBST` and same-name preference restore.

## Acceptance criteria
- [x] `uv run pytest -m unit` → all pass — part of the full run above.
- [x] `script/lint` clean, `esphome config OK` — verified.
- [x] `script/test` all pass, no skips — verified (636 passed, 12m08 here; implementer: 11m42 vs 6m25 on 013).
- [~] ESP32 compiles — pinned compile + flash/RAM numbers reported by the implementer (+15 364 B, +0.8 % of the app
  partition, under the 5 % Gate); minimum ESP32 compile not run locally (offline penv). Not re-run by me. The required
  CI job `compile (minimum)` covers it before merge; codegen on minimum passes (`test_greenhouse_zones_codegen[minimum]`).
- [x] `git grep` for stock sprinkler usage → no hits — verified.
- [x] `GZ-PATCH-BEGIN` ids incl. `number-clamp` with a `PATCHES.md` section — verified.
- [~] Emulator scenarios — E3/E4/E5/E6 reported PASS by the implementer; E2 now verified by this review (above); E1
  before-list missing, but object ids are derived from unchanged names and `test_entity_names_kept` pins the exact set
  of irrigation entity names from `esphome config` output, so continuity is covered.
- [ ] CI green — not verifiable here; required before merge.
- [x] Docs (SPEC §3/§4.1/§5/§7/§8/§9, CLAUDE.md, README.md / README.ru.md in sync, component README) — verified.
- [x] Implementation notes say clearly that nothing ran on a real device and list the breadboard checks.

## Safety review (strict items from the brief)
- Raw relays: unchanged, `internal: true`, breadboard `RESTORE_DEFAULT_OFF`, sim `ALWAYS_OFF`. Only `fault.yaml`
  (sim entry only, `test_sim_fault_is_sim_only`) turns a raw relay on, by design.
- Group switches: `SprinklerControllerSwitch::setup()` only sets `state` from the restore mode and never calls
  `write_state`, so neither the main switch (default `ALWAYS_OFF`) nor the auto-advance switch (`RESTORE_DEFAULT_OFF`)
  can start watering at boot; the auto-advance restore is pushed to the lanes in the group `setup()` (switch priority
  HARDWARE runs before the group's DATA). Host scenario step 1 asserts all relays/main/watchdog 0 after boot.
- Watchdog: active with `max_on_time: ${gh_max_on_time}` = `60min`, codegen check asserts `3600000` per zone; `never`
  only when a user sets it; the bed max 55 min fits (`test_bed_max_fits_watchdog`) and a too-short limit is rejected at
  config time (`max_on_time_too_short` row). Host step 5 proves a raw relay is cut at 125 s, the latch refuses
  `run_zone`, and the reset button clears it. Locked zones are also skipped in cycles/queues via 013's `skip_reason`.
- Number clamp: correct placement (restore branch only, before `publish_state`), saves the clamped value, WARN log;
  verified in the emulator above.
- Valve test: limit 10 s unchanged; `run_zone` with `run_duration: ${valve_test_max_time}` only inside the
  service-mode `if`, guard started before the run, shutdown first; poller uses `active_zones()`/`queued_zones()`;
  `test_service.py` adapted 1:1 (no weakening). Host step 6 shows a 10 s run closes in 9.0-10.4 s without a trip.
- Screensaver: read-only (`id(gh_zones)` only), `az.front()` only after the non-empty condition.
- 1 bed: `beds_1_headless` and `sim_beds_1` config rows pass.
- HA entity names: kept; two new ("Greenhouse watchdog", "Greenhouse watchdog reset") as approved by the human.

## CI-time Gate — recommendation
`script/test` grows by ~5m17 (6m25 → 11m42 locally; 12m08 in this run), over the 4 min Gate; ~4 min is the new host
scenario run, ~1 min its host build. **Recommendation: accept for this PR** (the Gate asks to report and propose, not to
block; the scenario is the only automated proof that the real bed packages are cut by the watchdog) **and open a
follow-up** to cut it: (a) overlap step 5 with step 3 (start the raw `board_relay_3` turn-on at the start of step 3 so
the 125 s watchdog wait runs during the 1 min auto-advance wait, saves ~60 s), (b) fold the scenario into the 013
safety host build so only one host binary is compiled (~1 min), (c) check the real CI `checks` job duration after the
PR run before deciding further.

## Findings
### Required
None.

### Suggestions
1. `script/sim:12` — the header example `GP_SIM_SUBST="gh_max_on_time=90s gh_bed_run_max=1 gh_bed_run_initial=1"` does
   not validate (`max_value` must be greater than `min_value: 1`, as the implementer found). Use the working values from
   `packages/sim/fault.yaml` / SPEC §7: `gh_max_on_time=125s gh_bed_run_max=2 gh_bed_run_initial=1`.
2. `tests/test_greenhouse_zones.py:340-341` — step 3 checks only state *changes* after `s3_b` (`after[1:]`); if bed 2
   had already been logged on at the mark and stayed on, the check would pass vacuously. In practice the mark and the
   relay-off happen in the same loop pass, so it does catch a failure today, but make it independent of timing:
   `assert not line.ever(_R2, "s3_a", "s3_c") and not line.ever(_R3, "s3_a", "s3_c")`.
3. Number-clamp has no automated check (verified only by hand in this review). A cheap option: a second run of the
   host program in the 013/014 host fixture with the same `ESPHOME` prefs dir and a lower `-s gh_bed_run_max`, or a
   C++ harness case if `SprinklerControllerNumber::setup()` can be isolated. Follow-up is fine.
4. `never` for `gh_max_on_time` is a human decision but has no config row; add `max_on_time_never` (`-s gh_max_on_time
   never -s gh_bed_run_max 240`) expecting success, so a later rule change cannot silently forbid it.
5. The restored auto-advance switch state being pushed to the lanes at boot (`components/garden_zones/group.h:79`) is
   untested; cover it with the clamp follow-up (second boot) or note it in the breadboard checklist.
6. `tests/test_garden_zones.py:179` — `"number-clamp",` is over-indented relative to the set literal (cosmetic).
7. Follow-ups already listed in the task stay valid: minimum ESP32 compile via CI, breadboard hardware checks
   (incl. the 120 → 55 min clamp on the real saved values), duplicated label in the 013 trip log, scratch under
   `.esphome/` (`baseline-build`, `baseline-tree`, `scratch`) to delete by hand.
8. Principle 2: the greenhouse page, Home status, valve test and screensaver call `garden_zones.*` / `id(gh_zones)`
   directly — accepted legacy path per the task (stage 8 `gp_*` layer), not a blocker.
