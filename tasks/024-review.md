# 024 — Review (round 1)

Verdict: CHANGES_REQUESTED

Range reviewed: uncommitted working tree of `task/024-lawn-and-my-garden` against HEAD (`957da73`, master + task spec):
13 modified files plus the untracked `packages/lawn/{irrigation,zone,gp}.yaml`, `examples/my-garden.yaml`,
`tests/test_lawn.py`.

## Checks run
Windows host, Git Bash + uv, pinned ESPHome 2026.9.1 unless noted:
- `script/lint` → exit 0 (`esphome config OK: garden-pilot.yaml`).
- `script/test` → `6 failed, 851 passed, 19 skipped in 117.33s`. The 6 failures are the known Windows-only ones:
  `test_ci.py::test_esphome_selector_resolves`, `test_devcontainer.py::{test_sdl_smoke_script_is_executable,
  test_sim_script, test_sim_ctl_script, test_sim_ui_script}`, `test_sim_ui.py::test_start_xvfb_deadline_holds_when_xvfb_hangs`.
  None of those files (or the scripts they check) is touched by the diff, so they are unrelated.
- `uv run pytest -p no:xdist tests/test_lawn.py tests/test_config_matrix.py -k lawn` → `12 passed` (the 4 lawn matrix
  rows ran, not skipped). `tests/test_examples.py -k my_garden` → `2 passed`.
- `GP_SECRETS=example script/config examples/my-garden.yaml` → `esphome config OK`.
- `GP_SECRETS=example GP_ESPHOME=minimum script/config examples/my-garden.yaml` → `esphome config OK`.
- `script/compile` not possible on this host (no ESP-IDF toolchain, no host C++ compiler).
- `git status --short --ignored` → no `secrets.yaml`, only the ignored `.esphome/` cache.

## Acceptance criteria
- [x] `uv run pytest -m unit` all pass incl. the new tests — verified (part of the `script/test` run above).
- [x] `script/lint` passes — verified.
- [x] `script/test` passes apart from the known Windows-only failures; the 4 lawn rows and `my_garden` row are present
      and pass — verified. CI `checks` time still to be noted after push.
- [x] `script/config` of `examples/my-garden.yaml` OK at pinned and minimum — verified independently.
- [ ] `GP_SECRETS=example script/compile examples/my-garden.yaml` — **not met** (see Required 1).
- [ ] `script/compile` of `garden-pilot.yaml` — not run locally; acceptable to leave to CI (`compile` jobs build the
      root entry). The device config is unchanged: the diff to `garden-pilot.yaml` is comments only.
- [x] engine names only in engine-side files — verified by reading `test_no_engine_outside_adapter` (regex now includes
      `\blawn_zones\b`, `ENGINE_FILES` += the three lawn files) and the lawn files; `gp.yaml` uses only `gp.*` actions on
      `gp_lawn`.
- [x] `examples/my-garden.yaml` hygiene — verified: generic names (`gp-my-garden`, "Lawn", "Flowers", "Greenhouse bed N"),
      secrets only as `!secret` substitutions with keys from `secrets.example.yaml`, no SSID / IP / hostname / entity id /
      local path.
- [x] Docs — verified: SPEC §4, §4.1, §5, §8, §9 stage 13, §9.1; CLAUDE.md layout row, order step 5, "Add a lawn zone";
      README.md / README.ru.md (same content, see Suggestion 1); examples/README.md; design/README.md.
- [ ] Hardware checklist — optional, author only; not blocking.

## Principles
- Actuators: zone valves and the pump are `board_relay_N` from `hardware/lilygo-t-relay-s3.yaml` (`internal: true`,
  `restore_mode: ALWAYS_OFF`); the engine valve switch in `zone.yaml` is `internal: true`. Watchdog limits default on
  (60min / 2h / 10s), none `never`; the session rule is a repo check. Main switch `restore_mode: DISABLED`, not
  optimistic, so no STOP at boot.
- gp-only: Home Assistant gets the `gp_zone` switches, "Lawn irrigation" (gp), status / watchdog / reset via `gp_lawn`;
  the engine auto-advance switch is the same pattern as the greenhouse group.
- No pins outside `hardware/` (relays by var number), no `lvgl.*` anywhere in the lawn files, lambdas one line.
- `packages:` order: lawn appended after the schedule slots, before `touch_dot_test`; documented in CLAUDE.md step 5.
- gp history preference is keyed per group (`fnv1_hash("gp_history:" + key)`), so the second group does not collide
  with the greenhouse history.

## Findings
### Required
1. Acceptance criterion "`GP_SECRETS=example script/compile examples/my-garden.yaml` builds once locally" is unmet
   (`tasks/024-lawn-and-my-garden.md` Implementation notes, "NOT done"). This is the only planned coverage of the new
   codegen path: two `gp:` groups on one hub, two `garden_zones` groups (one with a pump) on one hub, two engine adapters.
   No host config in `tests/configs/` has two gp groups (`gp_layer_sim.yaml` has only `gp_greenhouse`), the root entry
   keeps the lawn commented out, and CI does not compile `examples/`, so after merge nothing would ever compile this
   combination. Reading `components/gp/__init__.py::to_code` the per-group loop looks safe, but `esphome config` does
   not exercise C++. Fix: run the compile once in the devcontainer (as the 023 review did for the LilyGO profile:
   `devcontainer exec --workspace-folder . sh -c 'GP_SECRETS=example script/compile examples/my-garden.yaml'`), note
   the result and flash/RAM usage in the Implementation notes and tick the box. Alternatively the human may accept
   moving it to CI, but then the task must say so (e.g. a one-off CI compile of the example), not leave the box open.

### Suggestions
1. `README.ru.md:129` — missing comma before `` `relay-module-8ch.yaml` `` ("...пропускаются) `relay-module-8ch.yaml`"
   should be "...пропускаются), `relay-module-8ch.yaml`"), so the list reads wrong; README.md has the comma.
2. `examples/README.md:3-4` — the intro still says every example has "one watering schedule slot"; `my-garden.yaml`
   has two. Reword to "one or two watering schedule slots" (or drop the count).
3. `tests/test_lawn.py::test_lawn_session_fits_pump_limit` / `_lawn_entries` — the header of `packages/lawn/irrigation.yaml`
   says `lawn_max_parallel` must stay `"1"`, but only the package default is checked (`test_lawn_defaults`). Add an
   assert that no lawn entry overrides `lawn_max_parallel` (cheap, keeps the session rule honest).
4. The session check bounds one full cycle; a queue built from Home Assistant (`gp_enqueue_zone` of the same zone twice)
   can still exceed `lawn_pump_max_on_time` and lock the group. Fail safe, but worth one sentence in the
   `irrigation.yaml` header next to the session rule.
5. Follow-up (already listed, worth stressing in the next screen task): the device screen has no way to STOP the lawn
   (Greenhouse STOP and the valve-test service mode act only on `gp_greenhouse`); until the Lawn page is wired, the lawn
   is stoppable only from Home Assistant or by its watchdog.
6. Cosmetic: with `lawn_name: "Lawn"` and a zone named "Lawn", HA shows "Lawn" (zone switch) next to "Lawn irrigation"
   (group main switch). Valid, but a zone name like "Lawn zone" in `garden-pilot.yaml` / `my-garden.yaml` would read
   clearer. Author's call (open question 10).
