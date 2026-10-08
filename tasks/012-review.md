# 012 — Review (round 1)

Verdict: CHANGES_REQUESTED

Reviewed: uncommitted working tree on `task/012-groups-and-lanes` on top of `origin/master` (9bd5da2): `git diff` plus
the untracked files (`components/garden_zone/`, `groups.py`, `group.h`, `lanes.h`, `lane_plan.py`, the two test
configs, `tests/cpp/test_lanes.cpp`). Note: the local `master` ref is stale (d9dec56), so diff against `origin/master`.

## Checks run
All in the dev container `gp-dev-012` (`podman exec -w /workspaces/garden-pilot ...`).
- `script/test-cpp` → `13 test cases, 0 failed checks` (4 new lanes cases + the 008 cases).
- `script/lint` → `esphome config OK: garden-pilot.yaml`.
- `GP_REQUIRE_CXX=1 script/test` (online access unavailable) → `4 failed, 546 passed, 1 skipped, 1 error in 551.66s`.
  - `test_sim_config[minimum]`, `test_groups_config[minimum]`, `test_groups_codegen[minimum]`,
    `test_host_compile[minimum]` (error): `Failed to fetch https://pypi.org/simple/esphome/` (DNS in the container,
    environmental). Re-run with `UV_OFFLINE=1 GP_REQUIRE_CXX=1 uv run pytest tests/test_garden_zones.py -k minimum`
    → `4 passed, 33 deselected`.
  - **`test_groups_host_scenario` FAILED (real):** `assert 'done' in first` — the program never finishes the scenario
    (see Required 1).
- Ran the built groups host program by hand (90 s and 170 s, prefs under `.esphome/review-012-prefs*`): steps 2-5 log
  as expected, then the program sits idle after step 5 (`state=0000000 pump=0`) and never reaches step 6, also long
  after the 60 s `wait_until` timeout; the process idles at ~1 % CPU (no busy loop).
- `git diff origin/master --stat -- garden-pilot.yaml garden-pilot-sim.yaml packages hardware .github script
  tests/configs/garden_zones_sim.yaml` → empty.
- `git grep -n GZ-PATCH-BEGIN -- components` → ids `includes`, `queue-api`, `queue-persist`, `queue-skip-disabled`,
  `manual-run`, `groups`, `lanes`; each has a `PATCHES.md` section.
- Not run: `GP_SECRETS=example script/compile` (device firmware) — no device file is touched (diff above empty,
  `test_device_unchanged` passes); CI covers it.

## Acceptance criteria
- [x] `script/test-cpp` builds with `-Wall -Wextra -Werror`, all cases pass — verified in the devcontainer.
- [x] `uv run pytest -m unit` → all pass (part of the `script/test` run; every unit row green).
- [ ] `pytest tests/test_garden_zones.py` with `GP_REQUIRE_CXX=1` → not met: `test_groups_host_scenario` fails
      (Required 1). Minimum rows pass offline.
- [x] `script/lint` clean, `esphome config OK: garden-pilot.yaml`.
- [ ] `script/test` all pass, wall time recorded → not met: host scenario fails; no timings in Implementation notes.
- [x] Device / CI / script / 008-config diff is empty (against `origin/master`).
- [x] `GZ-PATCH-BEGIN` ids are exactly the seven listed, each documented.
- [x] Every `garden_zone:` in `tests/configs` is followed by a list item (`garden_zone_entry.yaml`; enforced by
      `test_garden_zone_entries_are_lists`).
- [x] `docs/SPEC.md` §4, §4.2, §5, §9 item 7 and `CLAUDE.md` (one layout row, one gotcha) updated as listed;
      component README documents dict form, lane limits, pump sharing, list-item rule and the actions.
- [ ] CI green + host-build CI timings vs the 6-minute Gate → not met: no PR yet, nothing recorded.
- [ ] Implementation notes (nothing on a real device, both boots' scenario results, 2026.6.3 results) → not met:
      `## Implementation notes` and `## Follow-ups` are empty; `Status:` is still `planned`.

## Findings
### Required
1. `components/garden_zones/groups.py:333-337` — **codegen-time lane IDs corrupt the component count; components
   registered after the lanes are silently dropped.** ESPHome emits `#define ESPHOME_COMPONENT_COUNT
   len(CORE.component_ids)` in the core `to_code` (`esphome/core/config.py`, priority CORE), i.e. before
   `garden_zones` runs; `CORE.component_ids.add(lane_id.id)` comes too late, and `Application::components_` is a
   `StaticVector<Component *, ESPHOME_COMPONENT_COUNT>` whose `push_back` ignores items past capacity. In the staged
   groups build `defines.h` has `ESPHOME_COMPONENT_COUNT 36` while `main.cpp` has 40 `App.register_component_` calls
   (the 5 lanes are not counted): the last four registered components
   (`waituntilaction_id_7..10`) never get `setup()`/`loop()`. That is exactly why the scenario hangs at the step-5
   `wait_until` (and why step 4b's idle wait "did not resume", worked around with fixed delays in
   `tests/configs/garden_zones_groups_sim.yaml:248-250`). On a device it would drop whatever registers after
   `garden_zones` (LVGL, intervals, a future watchdog) without any error — a safety issue. This is the task's
   **Gate** ("codegen-time lane IDs ... do not work: stop, record the error, propose the fallback; the reviewer
   escalates") → **escalate to the human**. Directions to put in front of them: (a) the planned fallback — declare
   lane IDs at validation time from inline `zones:` only and defer `garden_zone:`; (b) declare the lane IDs during
   validation from the full config (e.g. in `FINAL_VALIDATE_SCHEMA`, which already sees the `garden_zone:` entries and
   runs before any `to_code`) so they enter `CORE.component_ids` before the count is emitted — a variant of (a) that
   keeps `garden_zone:`, but needs the human's OK under "do not invent a third mechanism". Whatever is chosen, verify
   on pinned **and** 2026.6.3.
2. `tests/test_garden_zones.py::test_groups_codegen` — add a check that would have caught 1: in the generated build,
   `ESPHOME_COMPONENT_COUNT` (`src/esphome/core/defines.h`) >= the number of `App.register_component_(` calls in
   `main.cpp` (ideally equal), on pinned and minimum.
3. `tests/configs/garden_zones_groups_sim.yaml:244-250` and `tests/test_garden_zones.py` step-4b assertions — once 1
   is fixed, restore the `wait_until` "solo idle" (queue empty and `active_zones()` empty) instead of the fixed
   `delay: 6s` + `delay: 8s`, and assert that step 4b ends with every valve off (today `_rising(step4b, 6) == 1` would
   also pass with v6 stuck on; the task requires "only v6 runs, then idle").
4. `tasks/012-groups-and-lanes.md` — fill `## Implementation notes` (where cpp/host checks ran, scenario results of
   both boots, 2026.6.3 results, the Gate outcome with the exact symptom from 1, local `script/test` wall time
   before/after, CI host-build timings once the PR runs, "nothing ran on a real device") and `## Follow-ups`; set
   `Status`.

### Suggestions
1. `components/garden_zones/groups.py:157-163` — the "list form cannot be mixed with `garden_zone:`" message is
   unreachable: a list-form config has no `GardenZonesGroup` id, so the `group:` `use_id` check always fails first
   (`test_groups_config_errors[list-form-plus-entry]` asserts that `doesn't inherit from ...GardenZonesGroup` error).
   Either drop the branch or make the message reachable (e.g. check in `garden_zone`'s own schema/final validation),
   and say which in the README.
2. `components/garden_zones/lane_plan.py:52` / `groups.py:32` — Decision 3 says a lane left without zones "is not
   generated (logged at config time)"; it is dropped silently and `_LOGGER` is unused. Log it (from `plan_group`) or
   remove the logger. Also note in the README that dropped pinned lanes are renumbered (`lane: 2` can become
   `<group>_lane_1`), which matters for the queue preference key.
3. `components/garden_zones/groups.py:96` — Decision 2 makes the group `id` required; `cv.GenerateID()` accepts a
   group without `id`, which then cannot be referenced by any zone (fails later as "group has no zones"). Use
   `cv.Required(CONF_ID)`.
4. `components/garden_zones/groups.py:333` — lane IDs are not in `declare_ids`, so a user id like `beds_lane_0`
   clashes only at C++ compile time. If the fix for Required 1 declares them at validation time, this goes away;
   otherwise validate it.
5. `components/garden_zones/sprinkler.cpp:551-556` — after `start_group_cycle` the lane's `lane_auto_advance_` stays
   `true` while idle (the stock switch would also stay on). Harmless today (`start_from_queue` / `start_single_valve`
   reset it), but worth one line in `PATCHES.md` for 013/014, which add the group auto-advance switch.
6. `components/garden_zones/group.h` — `lanes::LaneMap::valid()` is tested but never used at runtime; consider an
   `ESP_LOGE` in `dump_config()` when the table is invalid, or drop it from the header contract.
7. `docs/SPEC.md` §9 item 7 — "watchdog (valves and the pump, task 013's watchdog also covers the pump)" says the
   same thing twice; trim.
8. Scenario deviations from the task (step 5 lane-1 run 9 s instead of 4 s, step 6 runs 20 s instead of 6 s, 1.5 s
   instead of 1 s after `shutdown_group`) are reasonable; mention them in Implementation notes.

Housekeeping: the reviewer left scratch preference dirs `.esphome/review-012-prefs*` (git-ignored build cache);
nothing is left running.

---

# 012 — Review (round 2)

Verdict: APPROVE

Reviewed: the uncommitted working tree on `task/012-groups-and-lanes` on top of `origin/master` (9bd5da2) again
(`git diff` plus the untracked files), with the human's Gate decision of 2026-10-08: option (b), lane ids declared
from the full config in `FINAL_VALIDATE_SCHEMA`.

## Checks run
All in the dev container `gp-dev-012` (`podman exec -w /workspaces/garden-pilot ...`).
- `script/lint` → `esphome config OK: garden-pilot.yaml`.
- `script/test-cpp` → `13 test cases, 0 failed checks`.
- `UV_OFFLINE=1 GP_REQUIRE_CXX=1 script/test` → `558 passed, 1 skipped in 247.09s (0:04:07)` (the skip is in
  `tests/test_sim_ui.py`, needs a display; every `test_garden_zones.py` row incl. both host boots of the groups
  scenario and all `minimum` rows passed).
- Generated groups build of this run (`--only-generate`, pytest temp dir): `ESPHOME_COMPONENT_COUNT 42` vs 41
  `App.register_component_(` calls on **both** 2026.9.1 and 2026.6.3. The surplus of one is ESPHome's own baseline:
  the untouched 008 list-form host build shows the same `21` vs `20` on both versions. The registered ids include
  `beds_lane_0/1`, `lawn_lane_0/1`, `solo_lane_0` and all eleven `waituntilaction_id*` (in round 1 the last four
  never got `setup()`/`loop()`).
- `git diff origin/master --stat -- garden-pilot.yaml garden-pilot-sim.yaml packages hardware .github script
  tests/configs/garden_zones_sim.yaml` → empty. `GZ-PATCH-BEGIN` ids → exactly `includes`, `queue-api`,
  `queue-persist`, `queue-skip-disabled`, `manual-run`, `groups`, `lanes`.
- Hygiene grep (IPs, local paths) over the new and changed files → no hits.

## The Gate fix (option b), checked against the ESPHome sources
- `esphome/config.py` adds every declared `Component` id to `CORE.component_ids` during the id pass;
  `cpp_helpers.register_component` removes the id and raises if it is missing; `core/config.py` emits
  `ESPHOME_COMPONENT_COUNT = len(CORE.component_ids)` in the core `to_code`. `final_validate_groups`
  (`components/garden_zones/groups.py:165-216`) adds `<group>_lane_<n>` after the id pass and before any `to_code`,
  so the count includes the lanes and each lane's `register_component` consumes its id. The set makes a repeated
  final validation harmless. The final validation and `to_code_groups` compute the lane plan with the same
  `plan_group()` on the same zone list (inline zones + `garden_zone:` from the full config), so the ids match.
- Id clash: a lane name that equals any declared id (manual or generated) is rejected with a clear message
  (`groups.py:187-191`; error case `lane-id-clash`). A group id like `x_lane_0` next to a group `x` is caught the same
  way, because group ids are declared ids. Lane ids are not referencable from YAML (not in `declare_ids`), which is
  intended.
- `garden_zone:` entries from separate packages: `test_groups_config[pinned|minimum]` shows both entries from the
  two `garden_zone_entry.yaml` includes in include order, and the host scenario runs them as two parallel lanes
  (step 2).

## Round-1 items
### Required
1. Lane ids corrupt the component count → **resolved** (option b, see above; verified on pinned and minimum; the
   scenario now reaches every step, including step 5's `wait_until`).
2. Component-count check → **resolved**: `test_groups_component_count` (pinned + minimum, shared module-scoped
   `--only-generate` fixture) asserts `ESPHOME_COMPONENT_COUNT >= App.register_component_` calls; the round-1 code
   (36 vs 40) would fail it.
3. Step 4b fixed delays → **resolved**: `tests/configs/garden_zones_groups_sim.yaml:233-252` waits for "solo idle"
   (`queued_zones().empty() && active_zones().empty()`) in steps 4 and 4b. The remaining `delay: 8s` after step 4's
   idle wait is an observation window for "no extra cycle after the queue drains" (Decision 5), not a workaround.
   The test now asserts `step4b[-1][0] == "0000000"`.
4. Implementation notes / Follow-ups / Status → **resolved**: where checks ran, the Gate outcome with the symptom,
   the fix and its evidence, scenario deviations, the 2026.6.3 results and the `script/test` wall time (4m07s; the
   master baseline was not measured) are recorded; "nothing ran on a real device" is stated; CI timings are a
   Follow-up because no PR exists yet.

### Suggestions
1. Unreachable "cannot be mixed" branch → resolved (dropped; the README and test comment say where it fails).
2. Dropped pinned lanes → resolved (logged at info level, renumbering documented in the README).
3. Group `id` required → resolved (`cv.Required(CONF_ID)`, `groups.py:96`).
4. Lane id clash → resolved (validated, see above).
5. `lane_auto_advance_` after `start_group_cycle` → resolved (note in `PATCHES.md` `lanes`, and a Follow-up).
6. `LaneMap::valid()` unused → resolved (`ESP_LOGE` in `GardenZonesGroup::dump_config()`, `group.h:31-33`).
7. SPEC §9 item 7 repetition → resolved.
8. Scenario deviations → resolved (listed in the Implementation notes).

## Acceptance criteria (round 2)
- [x] `script/test-cpp`: all 13 cases pass with `-Wall -Wextra -Werror` (devcontainer).
- [x] `uv run pytest -m unit`: all pass (part of the `script/test` run).
- [x] `tests/test_garden_zones.py` with `GP_REQUIRE_CXX=1`: all pass, no skips, `minimum` rows pass (no xfail
      needed).
- [x] `script/lint`: clean.
- [x] `script/test`: all pass. Wall time is recorded (master baseline not measured, as the notes say).
- [x] Device / CI / script / 008-config diff is empty.
- [x] `GZ-PATCH-BEGIN` ids are exactly the seven, each with a `PATCHES.md` section.
- [x] `garden_zone:` in `tests/configs` is always a list (`test_garden_zone_entries_are_lists`).
- [x] SPEC §4, §4.2, §5, §9 item 7, the CLAUDE.md layout row and gotcha line, and the component README are updated
      as listed.
- [ ] CI green on the PR, with the host-build timings recorded against the 6-minute Gate. **Open: no PR yet.** The
      main session records this when the PR runs. It does not block approval of the code.
- [x] Implementation notes: no real device, both boots' results, 2026.6.3 results.

## Findings
### Required
None.

### Suggestions
1. `tests/test_garden_zones.py` `test_groups_component_count`: `>=` would not catch an overcount, for example a
   lane declared in final validation but not generated, which only wastes capacity. Consider comparing the surplus
   with the 008 baseline (`count - registered == 1` on both versions today) or with the 008 build's surplus, so
   final validation and codegen cannot drift apart unnoticed.
2. `components/garden_zones/groups.py:144-162`: `plan_group()` runs twice (final validation and `to_code_groups`),
   so the "pinned lanes ... not generated" info line is logged twice on `compile`. Cosmetic: log only from
   `final_validate_groups`, or pass a flag.
3. `tasks/013-watchdog-and-soil-skip.md` is untracked in this working tree but belongs to task 013. Keep it out of
   the 012 commits, or put it in its own `docs:` commit.

Follow-ups (not blocking): record the CI host-build timings against the Gate when the PR runs (already in the task's
Follow-ups).

Housekeeping: the test log `.esphome/review-012-r2-test.log` (git-ignored build cache) was written by this review.
Nothing is left running.
