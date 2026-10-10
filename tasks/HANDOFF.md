# Handoff — 2026-10-10 (night run)

Where the work stands, what waits for the author, and how to continue on another machine. Delete this file once
everything below is resolved.

## Branches and PRs (merge order matters)

| Task | Branch | State |
|---|---|---|
| 012 groups and lanes | `task/012-groups-and-lanes` | draft PR #20, CI green, review APPROVE — **merge first** |
| 013 watchdog + soil skip | `task/013-watchdog-and-soil-skip` (on 012) | draft PR #22 (base: 012 branch), review round 3 APPROVE, CI started via workflow_dispatch |
| 014 device + emulator → `garden_zones` | `task/014-switch-to-garden-zones` (on 013) | implementation running (2026-10-11 night); emulator checks in a fresh dev container `gp-dev-014` (image with Xvfb) |
| 016 SNTP time fallback | `task/016-time-fallback` | draft PR #19, CI green, review APPROVE |
| 017 screen decisions (docs) | `task/017-screens-decision` | draft PR #21 |
| 018 `gp_*` layer, 019 schedules | this branch `handoff/2026-10-10` | **specs only, need the author's approval** |

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

## Open questions for the author

### 018 `gp_*` layer (`tasks/018-gp-layer.md`)
1. HA action names (`gp_greenhouse_*`), the 1-based `zone` parameter, new entity names "Greenhouse status" and
   "Alert" — renaming later breaks HA automations.
2. Keep the engine's zone switches in HA, or only `gp_*` actions? (default: keep)
3. Last watering: persist across reboots (a few flash writes a day) or RAM only? (default: RAM)
4. Alert texts, severities, thresholds; is "HA disconnected" an alert at all on a device meant to work without HA?
5. Card state words — for the designer.

### 019 schedules (`tasks/019-schedules.md`)
1. Slots per group: 2 by default (max 8)? Each slot adds 5 HA entities.
2. Missed runs: catch-up window 60 min, never water late, or always once late the same day?
3. A slot that fired < 60 s before a power cut may run again — accept, or force a flash save after each run?
4. A slot runs a zone list + one multiplier, or per-zone minutes (many more entities)?
5. Days in HA: one text (`daily` / `mon wed fri`), seven switches, or presets?
6. "Greenhouse schedules" master switch default on (slots default off) or off?
Known weak spots in the 019 spec to fix before implementation: host-scenario step 3, emulator check E3 wording,
the `parse_days` test row.

### Other
- Personal config: the public `garden-pilot.yaml` stays on defaults. Proposal: a git-ignored personal entry file
  that includes the shared packages, plus `examples/` (1 bed, 3 beds at once, lawn with pump). Separate task.
- Screens 009–011 still not checked by the author on the emulator/device.
- 014 for the author's own setup: greenhouse runs ~3 h → set `max_on_time` above the longest run (or `never`) and
  the bed run max accordingly in the personal config.

## Continue on another machine

```bash
git clone https://github.com/MrKiirya/garden-pilot && cd garden-pilot
git switch task/014-switch-to-garden-zones   # latest code (012 → 013 → 014 stack)
script/setup && script/test
```
Read `CLAUDE.md`, then the task file of the step you continue. Specs 018/019: `git switch handoff/2026-10-10`.
