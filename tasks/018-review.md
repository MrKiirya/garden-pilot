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

---

# 018 — Review (round 2)

Verdict: APPROVE

Reviewed: `git diff 82b1e0b 5f9d326` (round-1 fixes) against the round-1 findings above, and the whole range
`6a514f2..5f9d326` for regressions.

## Checks run
- `podman exec gp-dev-014 script/lint` → `esphome config OK: garden-pilot.yaml` (yamllint clean)
- `podman exec gp-dev-014 script/test-cpp` → `39 test cases, 0 failed checks`
- `podman exec -e UV_OFFLINE=1 -e GP_REQUIRE_CXX=1 gp-dev-014 script/test` → `697 passed in 865.29s (0:14:25)`, no
  skips and no failures (the 014 and gp host scenarios and `test_sim_ui` included).
- ESP32 pinned compile after the fixes: run by the main session (OK), not repeated here.

## Round-1 required items
1. **GpZoneSwitch has no behavioural check: resolved.** `bed.yaml` gives the switch the id `gh_bed${bed}_switch`
   (`test_bed_shape` updated). The gp host scenario now checks: OFF after boot (`sw_boot_off`); refused and back to OFF
   with the relay off while the watchdog is tripped (`locked_switch`); ON runs the zone and the switch follows the model
   (`sw_on`); OFF stops within 1 s (`sw_off`); OFF right after ON and OFF 1 s into the switching delay leave the valve
   closed (`quick_off`, `delay_off`); refused under inhibit while `source: service` is still accepted
   (`inhibit_refused`, `inhibit_service_ok`). These would fail without the change. With the old OFF logic the
   `delay_off` case would leave relay 3 open at the check, because the model is not yet RUNNING during the switching
   delay.
2. **CLAUDE.md stale lines: resolved.** The `packages:` order item 5 now lists `core_gp` → `core_gp_api` → `gh_gp`.
   The greenhouse layout row names `gp.yaml` for the watchdog sensor, reset button and status, and says which packages
   a bed needs. The valve-test gotcha now says "`duration` of `gp.run_zone`".
3. **Flaky 014 host scenario: resolved for this round.** The implementer ran the base `6a514f2` 5/5 green, the
   current tree 5/5 green, and my full run is green. The step-4 assertion now prints the step 3-4 timeline on failure,
   so a repeat can be diagnosed. See Suggestion R2-3 on what the added waits hide.

## Safety additions (focus of this round)
- **Service-mode inhibit (`gp.inhibit`): cannot stay on, but does not cover every HA path.**
  - Coverage: `GpGroup::set_inhibit` refuses `run_zone` unless `source: service`, plus `enqueue_zone`,
    `start_queue` and `full_cycle`. `stop_all` is always allowed.
  - Persistence: the flag is a plain RAM member (`inhibited_{false}`), so a reboot always clears it. Nothing persists
    it and no API action sets it. `gp_api.yaml` exposes no `source` parameter, so HA cannot pass `source: service`.
  - Set and clear: the flag is set only in `gp_service_enter` (page `on_load`). It is cleared in both
    `gp_service_exit` (EXIT SERVICE and the 10 min `gp_service_session` timeout) and `gp_service_leave` (page
    `on_unload`, any route). `test_service.py` asserts both.
  - Screensaver: it cannot leave the page in service mode, because `screensaver.yaml:39` blocks `on_idle` while
    `gp_service_mode` is on. It is also only a top-layer overlay, not a page change.
  - Result: the inhibit cannot get stuck ON. It and `gp_service_mode` are set and cleared together, with no delay in
    between.
  - Gap: one HA start path bypasses it, see R2-1.
- **Switch OFF always stops: OK.** `write_state(false)` calls `stop_all(false)` when the switch state is ON or the zone
  is RUNNING/PAUSED. Stopping the whole lane is the intended semantics. Stops are never inhibited, so an HA OFF also
  ends a valve test, which is safe.
- **Minutes cap: OK in code, no check.**
  - The cap: `gp_api.yaml` caps at 1440 min / 86400 s before multiplying, so `int` cannot overflow; negative
    values give 0 (the configured duration). `GpGroup::clamp_` then cuts the run to
    `Engine::max_run_seconds(zone)`.
  - Where the maximum comes from: `groups.py` takes the fixed `run_duration`, or the number's `max_value` converted
    by `rules.longest_run_ms` (unit-aware). This value already must fit under the watchdog `max_on_time`, so a long
    HA request now ends normally instead of tripping the watchdog.
  - Gap: neither cap has a test (R2-2).
- **Service runs keep the last watering: OK.** Both the RAM tracker (`zone_model.h`) and the persisted blob
  (`gp.h:186`) skip `Source::SERVICE`, and the history entry is still written. The C++ test covers the tracker. The
  blob path is only covered by reading the code.
- **Scenario waits: no safety race hidden.** See R2-3 for a non-safety behaviour they hide.

## Findings
### Required
None.

### Suggestions
1. **Main switch bypasses the inhibit.**
   - Where: `packages/greenhouse/lvgl_valve_test.yaml:18-19,43` and `packages/greenhouse/irrigation.yaml:37-39`.
   - The comment says the inhibit means "Home Assistant cannot open a valve in the window before the poller acts". The
     engine's HA-visible main switch "Greenhouse irrigation" goes straight to `GardenZonesGroup::start_cycle()`
     (`group.h:57-58`), bypassing `GpGroup`. My round-1 Suggestion 1 wrongly claimed that every HA start path goes
     through gp.
   - Why not blocking: the 1 s poller still stops it, and the lane's ~2 s switching delay comes before the valve
     opens. That is the same as 014, so it is not a regression.
   - Fix direction: reword the comment ("every gp start path"). As a follow-up, route the main switch through gp or
     make it `internal` with a gp-owned replacement; that also closes a remaining principle-2 hole.
2. **No checks for the minutes cap.** `GpGroup::clamp_`, `set_zone_max_run` / `zone_max_run` and the 24 h cap in
   `gp_api.yaml` are new behaviour without a check. A host-scenario step is enough: `gp.run_zone` with a duration
   above the zone maximum, then assert `time_remaining` <= max. A unit check on the generated `set_zone_max_run(...)`
   values (fixed `run_duration` and number `max_value` with unit `min`) would also do. Also add a scenario step that
   the inhibit refuses `gp.enqueue_zone`, `gp.start_queue` and `gp.full_cycle`; today only `run_zone` via the switch
   is exercised.
3. **Scenario waits hide an engine behaviour.**
   - Where: `tests/configs/greenhouse_zones_sim.yaml:120-125`, `tests/configs/gp_layer_sim.yaml:132-137`.
   - The waits make the scenarios deterministic, which is fine for these tests. But the round-1 failure shows real
     behaviour: `queue_zone` + `start_queue` issued within ~1 s of `shutdown_group`, while the lane is still in its
     switching delay, can be silently dropped. Nothing waters and there is no log. In gp, `queue_run_` is then set
     while nothing runs.
   - Why not blocking: it is fail-safe (nothing opens) and pre-existing in 014. On the device the confirm dialog
     makes STOP followed by Run Q within 1 s unlikely.
   - Fix direction: follow-up to pin the behaviour in a dedicated scenario step, then either make the engine defer
     the start until the shutdown finishes, or log a WARN when a start is dropped.
   - Also: `quick_off` / `delay_off` only check the end state after 5 s. `line.ever(_R3, ...)` over the window would
     prove the valve never opened at all.
4. Round-1 suggestions S6, S7 and S8 are deferred with reasons in the Implementation notes; that is acceptable.

## Acceptance criteria (round 2)
- [x] `script/test-cpp`, `pytest -m unit`, `script/lint`, `script/test` (697 passed, no skips with `GP_REQUIRE_CXX=1`):
      verified above.
- [x] `git grep sprinkler_lvgl` / engine names only in the allowed files: unchanged by the fixes.
      `components/gp/__init__.py` no longer imports the GPL Python, because the type is declared locally.
- [~] Compile pinned + minimum for both entry files: pinned ESP32 is OK (main session). Minimum ESP32 and the sim host
      build are left to CI.
- [ ] CI green: no PR yet.
- [x] Nothing verified on a real device; the notes say so.

## Follow-ups (not blocking)
- R2-1 main switch through gp; R2-2 cap/inhibit checks; R2-3 dropped start after shutdown; round-1 S6/S7/S8 and the
  round-1 follow-up list.
