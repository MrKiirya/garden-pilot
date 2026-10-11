# 018 — Review (round 1)

Verdict: CHANGES_REQUESTED

Reviewed: `git diff 6a514f2 82b1e0b` (6 commits on `task/018-gp-layer`), against `tasks/018-gp-layer.md` with its
"Human decisions (2026-10-11)" section taking precedence over the planner text.

## Checks run
- `podman exec gp-dev-014 script/lint` → yamllint clean, `esphome config OK: garden-pilot.yaml`
- `podman exec gp-dev-014 script/test-cpp` → `39 test cases, 0 failed checks` (includes the 13 new gp cases:
  `alerts_*`, `state_precedence`, `skipped_expiry`, `last_watering_edges`, `summary_now_next`, `absent_zone`,
  `history_ring`, `persist_blob`, `format_lines`, `run_source`)
- `podman exec -e UV_OFFLINE=1 -e GP_REQUIRE_CXX=1 gp-dev-014 script/test` → `1 failed, 694 passed in 878.11s (0:14:38)`: `FAILED
  tests/test_greenhouse_zones.py::test_greenhouse_zones_host_scenario` (step 4, `line.rising("s4_a", "s4_b") == []`,
  expected `[0, 2]`). All new gp tests passed (`test_gp_layer.py` 17/17 incl. `test_gp_layer_host_scenario`).
- Re-run alone: `uv run pytest -q tests/test_greenhouse_zones.py -k host_scenario` → `1 passed, 11 deselected in
  247.93s` — so the failure is intermittent (see Required 3).
- Own greps: `git grep -n -e 'garden_zones\.' -e 'gh_zones' -- packages garden-pilot.yaml garden-pilot-sim.yaml
  hardware` → hits only in `irrigation.yaml`, `bed.yaml`, `packages/greenhouse/gp.yaml` (non-comment lines);
  `git grep sprinkler_lvgl -- . ':!tasks'` → none.
- Emulator not re-run by the reviewer (the full suite already runs `test_sim_ui`; port 6053 shared).

## Acceptance criteria
- [x] `script/test-cpp` → `test_gp_model`, `test_gp_alerts` pass — verified above.
- [x] `uv run pytest -m unit` → all pass — covered by the full `script/test` run.
- [x] `script/lint` → clean; `esphome config` OK — verified above (both entry files are also `config` rows in
      `script/test`).
- [ ] `script/test` → all pass incl. new config rows and the host scenario — not met in my run: the 014 host
      scenario failed once in the full suite and passed alone (Required 3). No skips with `GP_REQUIRE_CXX=1`.
- [ ] `GP_SECRETS=example script/compile` pinned + minimum for both entry files — only the pinned ESP32 build was
      done by the implementer (flash +15240 B, RAM +7192 B recorded); minimum ESP32 and the sim host compile are left
      to CI. Acceptable for this round, but the box stays open until CI is green.
- [x] `git grep` engine names → only the allowed files — verified by my own grep (fault.yaml is in the allowed set
      but has no hit, fine).
- [x] `git grep sprinkler_lvgl` → no hits — verified.
- [x] Emulator E1-E3 reported, E4 "not verified", E5 cut by human decision — read in Implementation notes, not
      re-run.
- [~] `components/gp/README.md` documents the contract; SPEC §4.1 links it; README.md / README.ru.md in sync — yes.
      CLAUDE.md partly stale: see Required 2.
- [ ] CI green — not run yet (no PR).
- [x] Implementation notes say nothing ran on a real device — yes.

## What holds (verified, not trusted)
- **Principle 2.** `test_no_engine_outside_adapter` is not trivially passing: it scans both entry files and every
  `packages/**/*.yaml` with comments stripped, and fails on `garden_zones.`, `id(gh_zones)` or the bare word
  `gh_zones` outside the four allowed files; `test_callers_use_gp` additionally restricts the four migrated callers to
  `gp.*` keys and `id(gp_*)` reads. My own grep agrees. The engine group is named only by `irrigation.yaml`, `bed.yaml`
  and `packages/greenhouse/gp.yaml` (`garden_zones_id: gh_zones`).
- **HA entity continuity.** `bed.yaml` makes the engine zone switch `internal: true` with the same name and adds a
  `gp_zone` switch named `${bed_name}` → same object id `greenhouse_bed_N`, so HA keeps the entity and there is no
  duplicate. "Greenhouse watchdog" / "Greenhouse watchdog reset" keep their ids and names (moved to
  `packages/greenhouse/gp.yaml`). Enable switches, run durations and auto advance are `entity_category: config` from
  the engine schema; `test_zone_switches_replace_engine_switches` and `test_entity_names_with_gp` cover it.
- **Raw relays** untouched (`hardware/` not in the diff, still `internal: true`).
- **Valve test safety unchanged.** Limit 10 s, `gp.run_zone {duration: ${valve_test_max_time}, source: service}` inside
  the service-mode `if`, guard started before the run, independent `gp_valve_test_guard` stop, enter =
  `gp.stop_all {clear_queue: true}`; `tests/test_service.py` was adapted one-to-one (no assertion dropped; new ones
  added: `source: service`, no engine id in the file).
- **Service mode vs HA zone switches — not a regression.** In 014 an HA zone switch hit the engine's
  `start_single_valve` directly and the 1 s service poller shut it down; in 018 it goes `GpZoneSwitch` →
  `GpGroup::run_zone` → engine, and the same poller (`summary().running || queue_length > 0`, refreshed at 4 Hz) stops
  it. Same window, same guard. See Suggestion 1: the follow-up is now cheap.
- **Boot state.** `gp_zone` uses `default_restore_mode: ALWAYS_OFF`, `setup()` only publishes `false` and never
  calls `write_state`, so no valve opens on boot.
- **Flash writes.** `PersistBlob` is ~1.3 KB (magic + 100 x 12 B entries + 16 x 8 B last runs); `pref_.save()` is
  called at most once per hub refresh and only when a run completed; ESPHome's `flash_write_interval` (default 60 s,
  not overridden in the repo) batches NVS commits. A few writes a day is negligible.
- **LVGL only from pollers.** `gp_lvgl_status.yaml` and the valve-test rows are `interval:` pollers guarded by
  `changed_since` (revision starts at 1, `seen` at 0, so the first poll draws); `on_alert_change` only logs; API
  actions contain no `lvgl.*` (`test_lvgl_only_from_pollers`).
- **MIT/GPL boundary (C++).** No fork code in `components/gp/`; the pure headers include nothing from `esphome/` or
  `garden_zones/`; the adapter `components/garden_zones/gp_engine.h` is GPL-marked. See Suggestion 2 for the Python side.
- **Texts.** `format_lines` reproduces the 014 strings; the deleted 130-line lambda file is replaced by one-line
  lambdas (`test_lambdas_are_small`).

## Findings
### Required
1. `components/gp/gp.h:566-601` (`GpZoneSwitch`) — the per-zone HA switch is a new actuator entry point (human
   decision) and has **no behavioural check**: the codegen test only counts three `GpZoneSwitch(` instances, and the
   host scenario `tests/configs/gp_layer_sim.yaml` never turns a `gp_zone` switch on or off. Nothing would fail if
   `write_state(true)` ignored the watchdog lock, if `write_state(false)` did not stop the valve, or if the state never
   followed the model. Fix direction: give the bed switches ids in the scenario (or address them by the generated
   id) and add a step: `switch.turn_on` bed 2 → B2 RUN and `relay2` on; `switch.turn_off` → all IDLE within 1 s and
   relay off; with the watchdog tripped, `switch.turn_on` → refused, switch state back to OFF, relay stays off; after
   boot all three switches report OFF. (Principle 7 / checklist 2: every behaviour of the task needs a check that
   would fail without it.)
2. `CLAUDE.md:76-78` — the `packages:` order list was not updated although Decision 5 requires it "in the same
   commit": item 5 still reads `gh_irrigation (before the greenhouse page: its buttons call the group gh_zones) →
   gh_bed_N … → gh_lvgl_page` with no `core_gp` → `core_gp_api` → `gh_gp`. Two more stale lines in the same file:
   `CLAUDE.md:52` says `irrigation.yaml` holds the "watchdog sensor and reset button" (moved to
   `packages/greenhouse/gp.yaml`), and `CLAUDE.md:126` says the valve-test limit is enforced "by `run_duration`" (now
   `duration` of `gp.run_zone`). Fix: update the three lines; mention that every config with `bed.yaml` now needs
   `core_gp` + `gh_gp` (and `core_gp_api` when `api` is present).

3. `tests/test_greenhouse_zones.py:342` / `tests/configs/greenhouse_zones_sim.yaml` — the 014 host scenario, which
   this task changed (it now also loads `core_gp` + `gh_gp`, lines 33-35), failed in the full `script/test` run: in
   step 4 neither relay 1 nor relay 3 rose after `queue_zone 0, 2` + `start_group_queue` within the 12 s window. It
   passed when re-run alone, so it is intermittent; the implementer's run reported 695 passed. A flaky host job makes
   the "CI green" criterion unreliable. Fix direction: find out whether it is pre-existing (run the 014 scenario on
   `6a514f2` a few times) or introduced by the gp hub in the loop; then either fix the cause or make the step robust
   (e.g. `wait_until` the queue has started instead of a fixed delay, or print the step-4 timeline on failure so the
   next occurrence is diagnosable). Record the result in the Implementation notes.

### Suggestions
1. Service-mode inhibit (follow-up listed) — Decision 6's reason ("a gp inhibit flag would only cover `gp.*`
   callers") no longer holds: after the human decision every HA start path (zone switches and the generic actions)
   goes through `GpGroup::run_zone` / `enqueue_zone` / `start_queue` / `full_cycle`. A `GpGroup::set_inhibit()` that
   refuses non-`SERVICE` starts while `gp_service_mode` is on would close the ~1 s window before the poller acts.
   Worth pulling the follow-up forward; not a regression vs 014, so not blocking.
2. `components/gp/__init__.py:16-21` — the MIT file imports `esphome.components.garden_zones.groups`, which is marked
   GPLv3 (`components/garden_zones/groups.py:1-3`). No code is copied and the combined binary is GPL anyway, but the
   "gp never depends on garden_zones" boundary is cleaner without the import: declare the id type locally
   (`cg.esphome_ns.namespace("garden_zones").class_("GardenZonesGroup", cg.Component)`) and extend
   `test_pure_headers` to reject `garden_zones` imports in `components/gp/*.py`.
3. `components/gp/gp.h:595-597` — `write_state(false)` stops only when the 250 ms model already shows the zone
   RUNNING/PAUSED. An OFF sent right after ON (before the next refresh, or during the switching delay if the engine
   does not report the zone active yet) is a no-op and the valve opens anyway. The engine switch in 014 always shut
   the lane down on OFF. Consider stopping when the zone is running *or* was commanded within `OPTIMISTIC_MS`, or ask
   the engine directly.
4. `packages/core/gp_api.yaml:20,31` — `minutes * 60` has no upper bound (and overflows `int` for absurd inputs). The
   watchdog still caps the open time, but it then locks the zone and raises an ERROR. Clamp in `GpGroup::run_zone` /
   `enqueue_zone` to the zone's maximum (or refuse with WARN above it).
5. `components/gp/gp.h:161-164` — a valve test (`Source::SERVICE`) overwrites the zone's persisted "last watering"
   (and its history entry is fine). The Home zone widget would then show an 8 s test as the last watering; consider
   skipping `SERVICE` runs for `blob_.last[]`.
6. `components/gp/format.h:135` — `valve_test_color()` hard-codes `0x78dc77` / `0xbecab9` in C++. They match the
   tokens today, but token checks only look at YAML; returning a bool/enum and keeping the two colours in the YAML
   (two `if` branches or a substitution) keeps tokens in one place.
7. `packages/greenhouse/gp_lvgl_status.yaml:45-52` — the Home header HA icon (core concern) is driven from a greenhouse
   package and adds a hard dependency on `api` to it; a config without greenhouse would never update it. Consider a
   small core LVGL poller. Also `` is `LV_SYMBOL_WIFI`, which reads as "Wi-Fi" rather than "HA offline" — a
   designer call.
8. History persistence is only checked by string greps (`test_history_is_persisted`); the host scenario could run the
   program twice on the same preferences file and assert the restored entry count / last duration.
9. `tests/test_greenhouse_zones.py` dropped the assertion that the watchdog sensor id is not `gh_zones_watchdog` (the
   generated component id); re-add it in `test_gp_yaml_shape` for `packages/greenhouse/gp.yaml`.
10. Task file `Status:` still says `planned`.

### Follow-ups (not blocking, from the notes)
- Soil reading + soil alert + SKIPPED-by-soil scenario (cut 1); air-sensor alerts; legacy `on_value` LVGL updates in
  `sensors_air_dht.yaml` / `sensors_soil.yaml`; enable switches OFF on a fresh device; PAUSED time-left in the adapter;
  `sim-ctl` buttons/actions.
