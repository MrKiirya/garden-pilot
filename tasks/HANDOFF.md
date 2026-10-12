# Handoff — 2026-10-10 (night run)

Where the work stands, what waits for the author, and how to continue on another machine. Delete this file once
everything below is resolved.

## Branches and PRs (merge order matters)

| Task | Branch | State |
|---|---|---|
| 012 groups and lanes | `task/012-groups-and-lanes` | draft PR #20, CI green, review APPROVE — **merge first** |
| 013 watchdog + soil skip | `task/013-watchdog-and-soil-skip` (on 012) | draft PR #22 (base: 012 branch), review round 3 APPROVE, CI started via workflow_dispatch |
| 014 device + emulator → `garden_zones` | `task/014-switch-to-garden-zones` (on 013) | draft PR #23, review APPROVE; implemented and committed (2026-10-11 ~03:40): ESP32 pinned compile OK (+0.8 % flash), script/test 636 passed, emulator scenarios E3–E6 pass (screenshots in `.esphome/shots/` locally); review round 1 running; no PR yet. Found and fixed a 013 bug the host builds missed (watchdog trigger `int32_t`, fix committed on the 013 branch) |
| 016 SNTP time fallback | `task/016-time-fallback` | draft PR #19, CI green, review APPROVE |
| 017 screen decisions (docs) | `task/017-screens-decision` | draft PR #21 |
| 018 `gp_*` layer | `task/018-gp-layer` (on 014) | draft PR #25, review round 2 APPROVE, ESP32 pinned compile OK, CI started |
| 019 schedules | `task/019-schedules` (on 018) | PR #26 ready, review round 2 APPROVE, CI green (checks timeout raised to 40 min) |
| 020 timeline flake (test only) | `task/020-timeline-flake` (on 019) | PR #27 ready (base 019), CI green; also carries the schedule-scenario handover fix |
| 021 review follow-ups | `task/021-review-follow-ups` (on 020) | PR #28 (base 020), review APPROVE, CI green |
| 022 CI speed-up | `task/022-ci-speed` (on 021) | PR #29 (base 021), review round 2 APPROVE, CI green; `checks` 13.7 min (was ~25) |

Stacked branches: after #20 is squash-merged, 013 and 014 need to be brought up to date with `master` before their
PRs can merge (CI for a stacked branch: `gh workflow run ci.yml --ref <branch>`).

## Decisions already made by the author (recorded in the task files)

- 012 Gate: lane ids declared from the full config in `FINAL_VALIDATE_SCHEMA` (option b).
- 016: `timezone` substitution (default UTC), SNTP on by default, `pool.ntp.org`.
- 013: the brief stock handover overlap of two valves is accepted (pump protection first; `valve_overlap` for a
  deliberate overlap). Watchdog on by default (60 min / 2 h / 10 s), no 4 h cap, disable only explicitly with
  `never`; technical maximum 30 days.
- 014: `max_parallel` default 1 (the author will use `all` in his own config); "Greenhouse watchdog" /
  "Greenhouse watchdog reset" names OK; bed run max 55 min by default.
- Screens: bed card slots + Home widgets, YAML decides which widgets exist, SETUP chooses order; first widgets:
  zones + alerts, weather (HA), now/next + timeline, heating.

## Night results worth a look
- 014 deviations: watchdog sensor id `gh_zones_watchdog_problem`; scenario run times shortened (`gh_bed_run_max=2`).
- 014 not done: ESP32 compile on minimum ESPHome (needs network, CI covers it), clamp check E2, E1 before-list.
- CI time: local `script/test` grew 6m25 → 11m42 because of the new host scenario (~4 min) — decide whether to
  shorten it or move it out of `checks`.

## Open questions for the author

### 018 `gp_*` layer (`tasks/018-gp-layer.md`)
Answered 2026-10-11 (recorded at the top of the spec): one generic HA action set (`group`, 1-based `zone`);
`gp_*` owns the per-zone switches (engine switches hidden); last watering + 100 history entries in flash;
"HA disconnected" = quiet header icon. Still open: alert texts/severities/thresholds; card state words (designer).

### 019 schedules (`tasks/019-schedules.md`)
Answered 2026-10-11 (top of the spec): 2 slots (max 8); zone list + multiplier; 7 day switches; catch-up 60 min;
per-zone "done" mark at completion, written to flash at once, catch-up re-runs only unfinished zones; master switch
on, slots off. Spec weak spots still to fix before implementation: host-scenario step 3, E3 wording, `parse_days`
row (days are switches now, so that row changes anyway).

### 019 review round 2 — three non-blocking questions (asked 2026-10-11 ~23:55, denied by night mode)
- A. The hold-back (queue start waits until a manual run ends, +5 s) applies to every queue start during any
  non-queue run, not only to schedules during a cycle. Recommended: keep.
- B. With schedules on, every STOP clears the whole engine queue, including zones queued by hand. Recommended: keep.
- C. Turning off "Greenhouse irrigation" in HA is not a STOP (slot zones stay queued). Recommended: follow-up —
  route the main switch through gp (already a review follow-up).

### 019 review round 1 — two decisions (answered 2026-10-11: STOP settles the slot; slot after the cycle)
1. **STOP during a scheduled run.** Today the unfinished zones stay "pending" and a reboot within 60 min
   resumes watering. Recommended: STOP settles the slot (history "stopped", queue cleared); only zones cut by a
   power loss are re-run. Alternative: keep today's behaviour, document and test it.
2. **A slot fires while a manual full cycle runs.** Today the slot silently ends the rest of the cycle (now with a
   WARN). Recommended: queue the slot's zones after the cycle. Alternatives: skip the slot ("skipped: watering"),
   or interrupt with a WARN (today).
The other review items are being fixed (resume pending zones only after boot, "done" semantics tests, gp README,
marks keyed by slot number, ...).

### 021 review follow-ups (night 2026-10-12, planner decisions to confirm)
- Main switch "Greenhouse irrigation" becomes a gp-owned template switch (same name → same HA entity id): ON =
  `gp.full_cycle` (respects service mode), OFF = full STOP (`gp.stop_all`, settles schedule slots). Answers 019 C
  with the recommended option — confirm.
- "+Q" during a manual run/cycle: the added zone shows in the queue line only after the run ends — OK?
- With schedules on, main switch OFF while idle still settles today's slots and clears the manual queue — OK?
- Out of scope (later): soil in gp model + sensor alerts, legacy LVGL on_value pollers, 019 question B.

### 022 CI speed-up (planner decisions to confirm)
- No job split now (required check names unchanged); pytest-xdist inside `checks`, libfaketime in the devcontainer
  image to skip minute-boundary waits in the schedule scenario.
- Open: parallel `script/test` by default locally (8 workers), or opt-in? `checks` landed at 13.7 min: accept or split jobs next?
- Small follow-ups from review round 2: `check_shifted` should compare millis() modulo 2**32 (dev machine uptime
  > 49.7 days); `test_group_marks_reach_xdist` docstring; `_resolved_version` for labels other than pinned/minimum.

### Other
- Flaky test (found 2026-10-11, CI of #25): `test_safety_host_scenario` "a locked group refuses run_zone" fails ~1/50.
  Test artifact, not firmware: `_Timeline.intervals` in `tests/test_garden_zones.py` cuts windows by millisecond and
  includes the end mark, so a state line logged in the same ms as `s6_c` (step 7 turns valve 4 on) counts as `(X, X)`.
  Fix: cut windows by log order (index of the mark), same in `tests/test_greenhouse_zones.py` `_Timeline.window`.
  The author approved the stack as is: do it as a separate small task after the merge; on a failure just re-run CI.
- Personal config: the public `garden-pilot.yaml` stays on defaults. Proposal: a git-ignored personal entry file
  that includes the shared packages, plus `examples/` (1 bed, 3 beds at once, lawn with pump). Separate task.
- Screens 009–011 still not checked by the author on the emulator/device.
- 014 for the author's own setup: greenhouse runs ~3 h → set `max_on_time` above the longest run (or `never`) and
  the bed run max accordingly in the personal config.

## Next steps for whoever continues (another agent or machine)
1. 019: re-run the review (reviewer agent, `tasks/019-review.md` draft is a starting point; range
   `git diff 8440aea HEAD` on `task/019-schedules`), fix findings (max 2 rounds), push, open a draft PR with base
   `task/018-gp-layer`, run CI with `gh workflow run ci.yml --ref task/019-schedules`.
2. The author reviews and squash-merges the stack in order #20 → #22 → #23 → #25 → 019 (plus #19, #21 any time).
3. Then: personal config + `examples/`, shorten the host scenarios (CI time), roadmap stage 9 screens with the
   designer. Follow-ups of each task are at the end of its task file.

## Continue on another machine

```bash
git clone https://github.com/MrKiirya/garden-pilot && cd garden-pilot
git switch task/014-switch-to-garden-zones   # latest code (012 → 013 → 014 stack)
script/setup && script/test
```
Read `CLAUDE.md`, then the task file of the step you continue. Specs 018/019: `git switch handoff/2026-10-10`.

## Answered 2026-10-12 (morning)
All open questions above are answered; behaviour stays as implemented: main switch OFF = full STOP (also when idle);
queue hold-back for every manual run; STOP clears the whole queue; "+Q" shown as queued → stage 9 screens; `checks`
up to 15 min is fine (above → split jobs); local `script/test` 4 workers by default (pushed on #29).
