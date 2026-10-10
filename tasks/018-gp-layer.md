# 018 — The `gp_*` layer: one read model and action set for screens, widgets and Home Assistant

Status: planned
Roadmap: SPEC §9 item 8 "`gp_*` layer on top of `garden_zones`, screens switched to it"
Spec sections: SPEC §4, §4.1, §8 (valve test, screensaver, "Screens: slots and widgets"), §9 items 8-9, §10.2
(from branch `task/017-screens-decision`); CLAUDE.md core principles 1, 2, 4, 5, 7 and the LVGL gotchas
Hardware check: optional smoke only (flash, greenhouse page RUN/STOP, valve test on one relay, HA sees the new actions
and entities). The PC emulator and the host scenario are the verification bar; nothing new touches a GPIO.

**Stacked on task 014** (device and emulator on `garden_zones`). Branch `task/018-gp-layer` from
`task/014-switch-to-garden-zones`; the PR targets that branch (or `master` after 013/014 merge, then rebase). 013 and 014
are not merged while this is written: **re-read `components/garden_zones/group.h`, `groups.py`, README and
`packages/greenhouse/*.yaml` as 014 shipped them** and use the real names (group id `gh_zones`, accessors
`time_remaining_zone()`, `queue_time()`, `auto_advance()`, `clear_queue()`, `zone_locked()`; action
`garden_zones.reset_watchdog`; the watchdog `never` option). Where this file guesses a 013/014 name, 013/014 win —
mark such spots "to verify by the implementer" in Implementation notes.

## Goal
Screens, the screensaver, the valve test and Home Assistant read irrigation state and start/stop watering only through
one engine-neutral contract, `gp_*`: a per-zone read model addressed **by zone index** (what the stage-9 bed card slots
need), a group model (running, queue, now/next), an alert model (list + top alert for the Home alert strip), and a fixed
set of actions. The contract is implemented by a small C++ component `gp` (MIT) that talks to the engine through an
adapter interface; the only adapter today is `garden_zones` (GPLv3, lives in the fork's directory). After this task no
file outside `packages/greenhouse/irrigation.yaml`, `bed.yaml`, `packages/greenhouse/gp.yaml` and sim fault injection
mentions `garden_zones.*` or `id(gh_zones)`, and the migrated pollers have no multi-line lambdas. Visible texts on the
greenhouse page, Home, valve test and screensaver stay as 014 left them (no redesign; stage 9 builds the new screens).

## Context

### What exists (read, do not re-plan)
- After 014: group `gh_zones` ("Greenhouse") in `packages/greenhouse/irrigation.yaml` with main switch "Greenhouse
  irrigation", "Greenhouse auto advance", binary sensor "Greenhouse watchdog" (`condition:
  garden_zones.watchdog_tripped`), button "Greenhouse watchdog reset"; one `garden_zone:` list item per `bed.yaml`
  include (zone number = include order, 0-based; zone switch "${bed_name}", "... enable", number
  `gh_bed${bed}_run_duration`). Optional `bed_soil.yaml` adds sensor `gh_bed${bed}_soil_moisture` (reporting only;
  soil skip not wired, 014 decision 8).
- Callers that 014 adapted mechanically and this task migrates (CLAUDE.md "legacy, migrate in stages 7-9"):
  `packages/greenhouse/lvgl_page.yaml` (RUN, +Q, STOP via `gp_confirm`, Run Q), `sprinkler_lvgl_status.yaml` (1 s poller,
  ~130 lines of formatting lambdas, Home `gh_home_irr_status` / `gh_home_next_label`), `lvgl_valve_test.yaml`
  (`gp_service_*` scripts, `gp_valve_test_guard`, 1 s service poller + three copy-pasted row lambdas),
  `screensaver_status.yaml` ("Bed N" / "Bed N+").
- `GardenZonesGroup` (013 working tree, `group.h`): `zone_count()`, `queued_zones()` (round order), `active_zones()`,
  `is_zone_queued()`, `run_zone()` (refuses a watchdog-locked zone), `queue_zone()`, `remove_queued_zone()`,
  `start_queue()`, `start_cycle()`, `shutdown()`, `watchdog_tripped()`, `reset_watchdog()`, `skip_reason(lane, valve)`
  (the lanes' skip check: watchdog lock or soil verdict; reason text). Lanes (`Sprinkler`, fork) expose `valve_name()`,
  `enable_switch()`, `valve_run_duration()`, `paused_valve()`, `time_remaining_active_valve()`, `total_queue_time()`.
  The engine has **no** per-zone history and **no** start/stop triggers; a skip is only logged.
- Screens decision 2026-10-10 (branch `task/017-screens-decision`, SPEC §8 "Screens: slots and widgets", §10.2): bed
  card template included up to 6 times with `vars: slot: N`, slots >= the group's zone count hidden at boot, cards read
  **by zone index through `gp_*`**, never by bed ids; Home = widgets (zones with readings or last watering, alert strip
  always on top when active, now/next + day timeline = "now" + queue until schedules exist, weather from HA, heating).
  A C++ fit helper places widgets (stage 9, not here).
- Existing `gp_*` ids are UI/service glue (`gp_confirm*`, `gp_service_*`, `gp_valve_test_*`, `gp_screensaver_*`,
  `gp_boot_*`, diagnostics); they stay. SPEC §4.1 sketches YAML scripts `gp_run_bed` / `gp_queue_bed` / `gp_stop_all`
  and entities `gp_bed1_state`, `gp_queue_text`; this task replaces the sketch with the contract below.

### Sources checked
- ESPHome API docs (esphome.io/components/api, fetched 2026-10-10): user-defined `api: actions:` with typed
  variables (`int`, `float`, `string`, `bool`, arrays), `supports_response` modes; `api.connected` condition with
  optional `state_subscription_only`, lambda `id(api_id).is_connected()`; `on_client_connected/disconnected` triggers.
  **To verify by the implementer on 2026.6.3** (minimum): that `state_subscription_only` exists there; if not, use plain
  `is_connected()` (the device has no logger-only API clients in normal use). `actions:` (renamed from `services:`)
  predates the minimum.
- Package merge (CLAUDE.md gotcha): `api:` is a dict, `actions:` a list, so `packages/greenhouse/gp.yaml` can add
  actions next to `packages/core/api.yaml`; **proved by the `config` rows**, not assumed.
- `components/garden_zones/group.h`, `sprinkler.h` (013 working tree): accessors listed above.
- `garden_zone` precedent (task 012): `MULTI_CONF` list items from several packages concatenate; dict-form entries merge
  silently — the same rule applies to `gp_zone:` below.

## Decisions (planner; see Open questions)

### 1. C++ component, not YAML scripts + template entities
The read model has state that no engine entity holds: per-zone "skipped (+reason)", last watering start/duration,
paused vs queued vs locked precedence, now/next, an alert table with severity and a change counter. In YAML this is
globals + one lambda per field per zone (the 130-line `sprinkler_lvgl_status.yaml` is the preview, for 3 beds and no
history). Principle 1 ("C++ for stateful irrigation logic, never large logic in lambdas") and principle 7 (testable
core) point to C++. Principle 2 (swappable engine) is met by an **adapter interface**: the `gp` component never includes
an engine header; the `garden_zones` adapter does. The contract's names are `gp.*` actions/conditions and `gp_*` ids
(SPEC §4.1's "scripts" wording is updated accordingly).

Layout:
- `components/gp/` (MIT, like the repo): `__init__.py` (hub `gp:`, singleton, id `gp`), `zone_model.h` and
  `alerts.h` (**pure C++, no ESPHome includes**, unit-tested), `format.h` (pure: ASCII text helpers for labels), `gp.h`
  (ESPHome glue: `GpHub`, `GpGroup`, actions, conditions, triggers), `engine.h` (the abstract `Engine` interface),
  `README.md`.
- `components/gp_zone/__init__.py` (MIT): one `gp_zone:` list item per bed (`MULTI_CONF`, schema only; precedent
  `garden_zone`): attaches optional per-zone extras (soil sensor for display) to a gp group.
- `components/garden_zones/gp_engine.h` (GPLv3, new file in the fork dir, not a fork patch): `GardenZonesEngine :
  gp::Engine` over `GardenZonesGroup`. Swapping the engine = a new adapter + one schema option; screens, HA and
  `packages/*` keep working. Keeping the adapter on the GPL side keeps `components/gp/` MIT.
- Small additions to `group.h` (non-fork, GPL): thin read accessors the adapter needs if 014 did not add them
  (`zone_name(z)`, `zone_enabled(z)`, `zone_run_duration(z)`, `zone_paused(z)`), and a **last-skip record** per zone
  (`skip_reason()` stores reason + `millis()` when it returns non-null; accessor `last_skip(z)`). No state machine
  change, no `GZ-PATCH`.

### 2. The contract (normative; goes into `components/gp/README.md` and SPEC §4.1)
Zones are addressed by **0-based index within a gp group** (= engine zone number = bed include order). Times in
seconds. All reads are O(zones) and allocation-free after setup.

**Config** (hub in `packages/core/gp.yaml`, group in `packages/greenhouse/gp.yaml`, `gp_zone` in `bed_soil.yaml`):
```yaml
gp:                               # hub, once per device
  id: gp
  time_id: ha_time                # optional: wall-clock "last watering"; else uptime-relative only
  api_alert: {delay: 60s}         # optional: "Home Assistant disconnected" alert after this long without a client
  groups:
    - id: gp_greenhouse
      name: "Greenhouse"
      garden_zones_id: gh_zones   # engine adapter selector; exactly one engine key per group
gp_zone:                          # optional, list item per bed_soil include
  - group: gp_greenhouse
    position: ${bed}              # 1-based (bed vars are 1-based); stored as index position-1
    soil_moisture_id: gh_bed${bed}_soil_moisture
```
(If nested `groups:` lists under `gp:` do not merge across packages, the implementer moves groups to a top-level
`gp_group:` list item like `garden_zone`; record the choice. The hub stays in `packages/core/gp.yaml` because a future
lawn package adds a second group.)

**Per-zone read model** — `const gp::ZoneView &id(gp_greenhouse)->zone(i)`; out-of-range `i` returns a static
`ABSENT` view (`present == false`), so a hidden card slot polls safely:
| Field | Type | Meaning |
|---|---|---|
| `present` | bool | index < zone count |
| `name` / `short_name` | const char* | engine zone name ("Greenhouse bed 1") / "B1" |
| `state` | enum `ZoneState` | precedence **LOCKED > RUNNING > PAUSED > DISABLED > QUEUED > SKIPPED > IDLE** |
| `skip_reason` | const char* | set while `state == SKIPPED` (engine text, e.g. "soil moisture 72.0 > 60.0") |
| `time_left` | optional<uint32_t> | RUNNING / PAUSED only |
| `run_duration` | uint32_t | configured run (the zone's number or fixed duration) |
| `queue_position` | optional<uint8_t> | 0-based in `queued_zones()` order |
| `soil` | optional<float> | from `gp_zone.soil_moisture_id` when it has a non-NaN state |
| `last_start_epoch` / `last_start_uptime` | optional<uint32_t> | last observed RUNNING edge; epoch only if the clock was valid |
| `last_duration` | optional<uint32_t> | length of the last completed run (RAM only, see Open question 3) |
SKIPPED is shown from the engine's last-skip record until the zone next runs or is queued again, or 12 h pass.
LOCKED = `zone_locked(i)` of the watchdog. DISABLED = enable switch off. A run started but refused (LOCKED) does not
change the record.

**Group model** — `id(gp_greenhouse)->summary()`: `zone_count`, `running` (any RUNNING), `active[]` (indexes),
`queue_length`, `queue_time` (engine `queue_time()`), `auto_advance`, `watchdog_tripped`, `now` (first active zone +
its `time_left`, or none), `next` (first of `queued_zones()`, or none; until schedules exist "next" = queue only —
schedules extend this in stage 11, the field stays), `revision` (uint32, bumps on any visible change; countdowns bump it
once per second only while something runs).

**Actions** (YAML actions; every one logs at INFO with tag `gp`):
| Action | Args | Engine call |
|---|---|---|
| `gp.run_zone` | `id`, `zone` (templatable int), `duration` (optional; default the zone's run duration) | manual run (`run_zone`); refused + WARN when LOCKED or out of range |
| `gp.enqueue_zone` | `id`, `zone`, `duration` (optional) | `queue_zone` (never starts) |
| `gp.dequeue_zone` | `id`, `zone` | `remove_queued_zone` |
| `gp.start_queue` | `id` | `start_queue` |
| `gp.full_cycle` | `id` | `start_cycle` |
| `gp.stop_all` | `id`, `clear_queue` (bool, default false) | `shutdown` (+ `clear_queue`) |
| `gp.reset_watchdog` | `id` | `reset_watchdog` |
| `gp.alert_raise` / `gp.alert_clear` | `key` (string, <= 15 chars), `severity` (`error`/`warn`/`info`), `text` (ASCII, <= 40) | alert table only |
Conditions: `gp.zone_running {id, zone}`, `gp.any_running {id}`, `gp.watchdog_tripped {id}`, `gp.alert_active {key?}`.
Trigger: `gp: on_alert_change` (for logging / HA only, **never for LVGL**).

**Alert model** (`alerts.h`): fixed table (capacity 12, oldest INFO dropped first; a full table of ERRORs drops none
and logs WARN), entry = key, severity, text, since (uptime s), group index or -1. `top()` = highest severity, then newest.
`count()`, `at(i)` (sorted like `top`), `revision`. Built-in sources, evaluated in the hub `loop()` at 1 Hz:
- `wd:<group>` ERROR "Greenhouse: watchdog - B2 locked" while the group's watchdog is tripped (first locked zone, "+" if
  more);
- `soil:<group>:<i>` WARN "B2 soil sensor unavailable" when a `gp_zone` soil sensor has no state or NaN for > 10 min;
- `ha` WARN "Home Assistant disconnected" when `api_alert` is set and no API client for longer than `delay` (never
  raised during the first `delay` after boot);
- `clock` INFO "Clock not set" when `time_id` is set and the time is invalid 5 min after boot.
YAML packages add their own through `gp.alert_raise` / `gp.alert_clear` (e.g. the heating module later). Air-sensor
alerts are left to their packages (follow-up), not hard-wired.

**Home Assistant surface** (in `packages/greenhouse/gp.yaml` / `packages/core/gp.yaml`; names are part of the contract):
- API actions (`api: actions:`): `gp_greenhouse_run_zone(zone: int, minutes: int)`, `gp_greenhouse_enqueue_zone(zone:
  int, minutes: int)`, `gp_greenhouse_start_queue()`, `gp_greenhouse_full_cycle()`, `gp_greenhouse_stop_all()`,
  `gp_greenhouse_reset_watchdog()`. HA `zone` is **1-based** (matches "Greenhouse bed N"); `minutes: 0` = configured
  duration. Each body is one `gp.*` action (one-line lambdas for `zone - 1` / `minutes * 60`).
- Text sensor "Greenhouse status" (id `gp_greenhouse_status`): "Idle" / "Watering B1 B3" / "Locked" (same words as the
  Home status label), published on change only.
- Text sensor "Alert" (id `gp_alert_text`, hub): top alert text or empty.
- 014's "Greenhouse watchdog" binary sensor and "Greenhouse watchdog reset" button are **re-pointed** to
  `gp.watchdog_tripped` / `gp.reset_watchdog` (same names and object ids).
- Engine-owned entities (zone switches, enable switches, run-duration numbers, main / auto-advance switches) keep their
  names and remain the HA configuration surface; the contract says any future engine must provide the same names. HA
  automations that start watering should use the `gp_*` actions (documented in SPEC §4.1).

### 3. How LVGL reads it: polling, never callbacks
LVGL widgets are updated only from `interval:` pollers (1 s, as today), never from a `gp` trigger, `on_value` or engine
callback (CLAUDE.md gotcha: those can fire before LVGL is ready, e.g. on restore). Each poller starts with a cheap guard
`lambda: return id(gp_greenhouse)->changed_since(id(gp_gh_seen));` (`changed_since` stores the revision in the given
`globals`) so nothing is redrawn when nothing changed. Label texts come from `format.h` helpers so every label lambda is
one line, e.g. `text: !lambda "return gp::fmt::status_line(id(gp_greenhouse)->summary());"`. The hub refreshes its
snapshot in `loop()` (throttled to 4 Hz) so pollers read a consistent view. Callbacks were rejected: they would need a
"LVGL ready" gate in every widget and buy nothing at 1 s granularity.

### 4. Migration of callers (keep texts, change wiring)
- `lvgl_page.yaml`: Bed N → `gp.run_zone {id: gp_greenhouse, zone: N-1}`; `+Q BN` → `gp.enqueue_zone`; STOP (still via
  `gp_confirm`) → `gp.stop_all`; Run Q → `gp.start_queue`.
- `sprinkler_lvgl_status.yaml` → **renamed** `packages/greenhouse/gp_lvgl_status.yaml`, package key
  `gh_sprinkler_lvgl` → `gh_gp_lvgl` (both entry files, same position; `test_screensaver.py` order check follows).
  Same labels and the 014 texts, built by `format.h` (`status_line`, `modes_line`, `durations_line`, `zone_left_line`,
  `total_left_line`, `queue_line`, `home_status`, `home_next`). The run-duration hint reads `zone(i).run_duration`
  instead of the `gh_bedN_run_duration` ids.
- `lvgl_valve_test.yaml`: `gp_service_*` / `gp_valve_test_*` keep their ids and semantics (limit <= 10 s, guard script,
  service mode, 10 min session); engine calls become `gp.stop_all {clear_queue: true}` (enter, external-start block),
  `gp.stop_all` (guard, stop, exit, leave), `gp.run_zone {zone: valve, duration: ${valve_test_max_time}}`; the
  external-start check uses `gp.any_running` / `summary().queue_length`; the three row lambdas become one-line
  `gp::fmt::valve_test_row(id(gp_greenhouse)->zone(i))` (colours stay as today: OPEN `0x78dc77`, closed `0xbecab9`; a
  LOCKED row shows "locked" in the closed colour — new text, no new colour or font).
- `screensaver_status.yaml`: "Bed N" / "Bed N+" from `summary().active` via `gp::fmt::saver_bed()`; the air/soil line is
  untouched (sensor ids, not irrigation).
- `packages/sim/*` read only `board_relay_N` (no change); `packages/sim/fault.yaml` (014) keeps its raw relay on purpose.
- No new LVGL ids, design components, colours or font sizes (the greenhouse page still uses the default theme).

### 5. Package order
`core_gp` and `gh_gp` go after the last `gh_bed_N` / `gh_bed_N_soil` and before `gh_lvgl_page`:
`gh_irrigation` → beds → `core_gp` → `gh_gp` → `gh_lvgl_page` → `gh_sensors_air` → `gh_sensors_soil` → `gh_gp_lvgl` →
`gh_screensaver_status` → `gh_valve_test`. Sim entry: `core_gp` → `gh_gp` after `sim_bed_N_soil` of the last bed. ESPHome
resolves ids regardless of package order; the order is for readers and `test_layout.py`. CLAUDE.md's order list is
updated in the same commit.

### 6. Out of reach on purpose
Blocking an HA zone-switch start before the valve opens in service mode still needs the engine (a `gp` inhibit flag
would only cover `gp.*` callers): follow-up. Persisting last watering across reboots: Open question 3.

## Files
Component `components/gp/` (MIT) and `components/gp_zone/`:
- create: `components/gp/__init__.py` — hub + groups schema, codegen, actions/conditions/trigger registration.
- create: `components/gp/engine.h` — abstract `Engine` (zone count/name/enabled/locked/active/paused/queued order,
  time left, run duration, last skip, queue time, auto advance, watchdog; the action calls).
- create: `components/gp/zone_model.h` — pure: `ZoneState` precedence, `ZoneView`, `GroupSummary`, last-watering edge
  bookkeeping, revision.
- create: `components/gp/alerts.h` — pure alert table.
- create: `components/gp/format.h` — pure ASCII label helpers.
- create: `components/gp/gp.h` — `GpHub`, `GpGroup`, actions, conditions, trigger, built-in alert sources.
- create: `components/gp/README.md` — the contract (Decision 2), polling rule, how to write an adapter.
- create: `components/gp_zone/__init__.py` — `MULTI_CONF` list item schema.
- create: `components/garden_zones/gp_engine.h` — adapter; modify: `components/garden_zones/group.h` — accessors +
  last-skip record; `components/garden_zones/README.md` — one paragraph "gp adapter".

YAML:
- create: `packages/core/gp.yaml` — `external_components` for `gp`, `gp_zone`; hub, `gp_alert_text`.
- create: `packages/greenhouse/gp.yaml` — group `gp_greenhouse`, API actions, status text sensor.
- modify: `packages/greenhouse/irrigation.yaml` — re-point the watchdog sensor/button to `gp`.
- modify: `packages/greenhouse/bed_soil.yaml` — add the `gp_zone:` list item (cut 1).
- modify: `packages/greenhouse/lvgl_page.yaml`, `lvgl_valve_test.yaml`, `screensaver_status.yaml`; rename
  `sprinkler_lvgl_status.yaml` → `gp_lvgl_status.yaml`.
- modify: `garden-pilot.yaml`, `garden-pilot-sim.yaml` — Decision 5.

Tests:
- create: `tests/cpp/test_gp_model.cpp` (zone model + format), `tests/cpp/test_gp_alerts.cpp`.
- create: `tests/test_gp_layer.py`; create: `tests/configs/gp_layer_sim.yaml` (host scenario).
- modify: `tests/test_service.py`, `tests/test_screens.py`, `tests/test_screensaver.py`, `tests/test_layout.py` (package
  order), `tests/test_config_matrix.py` (rows), `tests/test_garden_zones.py` (allowed `garden_zones` locations).

Docs: `docs/SPEC.md` §4.1 (contract summary + link to `components/gp/README.md`), §5 (`gp_zone` in `bed_soil.yaml`),
§8 (valve test / screensaver "via gp"), §9 item 8 status; `CLAUDE.md` (layout rows `components/gp/`,
`components/gp_zone/`, `packages/core/gp.yaml`, `packages/greenhouse/gp.yaml`, `gp_lvgl_status.yaml`; package order;
principle 2 wording "`gp.*` actions and `gp_*` entities"; gotcha "LVGL reads gp only from pollers"); `README.md` /
`README.ru.md` one line on the HA actions, kept in sync.

About 32 paths — far over the ~10-file budget, like 014; the pure headers and tests are small, the YAML edits are
mechanical, and the migration cannot be split without leaving callers on two interfaces. **Cut order** if the run is
too long (each cut becomes a follow-up task, listed under Follow-ups):
1. `gp_zone` + soil reading + `soil:` alert (`components/gp_zone/`, `bed_soil.yaml` edit) — the `soil` field stays in
   the contract, always empty.
2. `clock` and `ha` built-in alerts (keep the table, `wd:` and `gp.alert_raise/clear`).
3. API actions and the two text sensors (HA keeps the engine entities meanwhile; principle 2 for HA is then partial).
4. Last-watering fields (contract keeps them, always empty).
Not cuttable: Decisions 1-5 for the zone/group model, actions, `wd:` alert, the four caller migrations, the cpp tests,
the host scenario, `test_gp_layer.py`, compiles.

## Checks to write first
| Level | Test | Asserts |
|---|---|---|
| cpp | `tests/cpp/test_gp_model.cpp::state_precedence` | Table-driven over (locked, active, paused, enabled, queued, skip record) combos: LOCKED > RUNNING > PAUSED > DISABLED > QUEUED > SKIPPED > IDLE. |
| cpp | `::skipped_expiry` | SKIPPED clears when the zone runs, is queued again, or after 12 h (uint32 millis wrap included). |
| cpp | `::last_watering_edges` | Run end records start and duration; a PAUSED gap within one run counts as one run (duration = open time without the pause; document the choice); epoch only when the fake clock is valid. |
| cpp | `::summary_now_next` | `now` = first active zone; `next` = first queued; empty queue → none; `revision` bumps on any visible change and not otherwise. |
| cpp | `::absent_zone` | `zone(i)` with `i >= count` returns `present == false`, no UB for `i` up to 255. |
| cpp | `::format_lines` | `status_line` / `modes_line` / `queue_line` / `home_status` / `home_next` / `valve_test_row` / `saver_bed` produce exactly the 014 strings for the same states (copy the 014 expectations); output is printable ASCII and fits the documented buffer. |
| cpp | `tests/cpp/test_gp_alerts.cpp` | raise/clear by key (idempotent; a text change bumps revision); `top()` = highest severity then newest; capacity 12 with INFO dropped first, ERROR never dropped; text truncated to 40 chars, non-ASCII bytes replaced by `?`. |
| unit | `tests/test_gp_layer.py::test_no_engine_outside_adapter` | `garden_zones.` actions and `id(gh_zones)` occur only in `packages/greenhouse/irrigation.yaml`, `bed.yaml`, `packages/greenhouse/gp.yaml`, `packages/sim/fault.yaml`; `sprinkler` nowhere under `packages/`. |
| unit | `::test_callers_use_gp` | `lvgl_page.yaml`, `gp_lvgl_status.yaml`, `lvgl_valve_test.yaml`, `screensaver_status.yaml` use only `gp.*` irrigation actions and `id(gp_greenhouse)` reads. |
| unit | `::test_lambdas_are_small` | Every `!lambda` / `lambda:` in those four files has <= 3 non-empty lines (principle 1). |
| unit | `::test_lvgl_only_from_pollers` | No `lvgl.*` action under a `gp:` trigger, `on_value`, `on_state` or `api: actions:` in any package. |
| unit | `::test_gp_yaml_shape` | `packages/greenhouse/gp.yaml`: group `gp_greenhouse` with `garden_zones_id: gh_zones`; API action names == the six of Decision 2, each body a single `gp.*` action; status text sensor id `gp_greenhouse_status`; no `!secret`, no `GPIO`. `packages/core/gp.yaml`: hub id `gp`, `external_components` lists `gp`, `gp_zone` with `source: components`. |
| unit | `::test_pure_headers` | `zone_model.h`, `alerts.h`, `format.h` include no `esphome/` header; `components/gp/*` and `components/gp_zone/*` carry an MIT notice; nothing under `components/gp/` includes from `garden_zones/`. |
| unit | `::test_gp_zone_entries_are_lists` (cut 1) | `gp_zone:` is always a list item. |
| unit | `tests/test_service.py` (adapted) | Allowed valve-test actions == `{gp.run_zone, gp.stop_all}` on `gp_greenhouse`; `run_zone` has `duration: ${valve_test_max_time}` and runs only inside the service-mode `if`; stop before guard before run; enter = `stop_all {clear_queue: true}`; limit <= 10 s; no raw relay, zone switch or engine id. |
| unit | `test_screens.py` STOP, `test_screensaver.py`, `test_layout.py` order (adapted) | STOP via `gp_confirm` then `gp.stop_all`; screensaver reads only `gp_greenhouse`; package order of Decision 5; ASCII texts. |
| config | `tests/test_config_matrix.py` rows | Existing rows pass; new: `gp_headless` (CORE + irrigation + bed 1 + `core_gp` + `gh_gp`, no LVGL), `gp_beds_3_soil` (beds with soil + `gp_zone`; cut 1), expected failure `gp_unknown_engine_group` (`garden_zones_id` of a missing id → error names the id), expected failure `gp_zone_position_out_of_range` (position 4 with 3 beds → error at final validation; cut 1). |
| config | `test_gp_codegen[pinned\|minimum]` | `compile --only-generate` of the device entry: one `gp::GpHub`, one `gp::GpGroup`, one `garden_zones::GardenZonesEngine`; API user actions registered for the six names. |
| host | `test_gp_layer_host_scenario` (pinned) | Scenario below passes (`GPTEST` lines). |
| compile | CI `compile (pinned)`, `compile (minimum)` | Device ESP32 + emulator host builds. Record flash/RAM delta vs 014. |

### Host scenario (`tests/configs/gp_layer_sim.yaml`)
Real `irrigation.yaml` + 3x `bed.yaml` + `core/gp.yaml` + `greenhouse/gp.yaml` on `hardware/sim.yaml`, short limits by
substitution (014 pattern: `gh_max_on_time: 90s`, `gh_bed_run_max: "1"`, `gh_bed_run_initial: "1"`), no LVGL, no API
(no `api_alert`, no API actions: include a variant of the group package or strip them by substitution; implementer's
choice). A 200 ms `interval` logs `GPTEST t=<ms> <id(gp_greenhouse)->debug_line()>` on revision change (`debug_line()` =
one stable line: per zone `B1:IDLE`, `B2:RUN(5)`, ..., queue, top alert key). Steps (`wait_until` with timeouts):
1. All zones IDLE, `queue_length 0`, no alert; `zone(3).present == false`.
2. `gp.enqueue_zone` 0 and 2 (3 s) → B1 and B3 QUEUED with positions 0/1, `next = 0`; `gp.start_queue` → B1 RUN then
   B3 RUN, never B2; afterwards `last_duration` of B1 is 3 s ± 1.
3. `gp.enqueue_zone` 0 (6 s), `gp.start_queue`, after 1 s `gp.run_zone` 1 (2 s) → B1 PAUSED, B2 RUN, then B1 RUN again
   (008 semantics).
4. Bed 2 enable switch off → B2 DISABLED (also when queued); back on.
5. Raw `switch.turn_on: board_relay_2` (fault, as 014 step 5) → after ~90 s B2 LOCKED, alert `wd:` ERROR is top,
   `gp.run_zone` 1 refused (WARN, relay 2 stays off), `gp.reset_watchdog` → alert cleared, B2 IDLE.
6. `gp.alert_raise {key: test, severity: info}` then `warn` with the same key → one entry, top changes; `gp.alert_clear`
   → gone.
7. `gp.stop_all {clear_queue: true}` during a run → all IDLE within 1 s, queue empty. Log `GPTEST done`.
(SKIPPED by soil needs the engine soil rule wired, which 014 left out: covered by the cpp tests with a fake engine, and
by a scenario step only if the soil follow-up has landed — to verify by the implementer.)

### Emulator verification (manual, record in Implementation notes; `script/sim-ui`, shots in `.esphome/shots/`)
- **E1 same screens:** with the 014 build and the 018 build take `gh_idle`, `gh_running` (after `script/sim-ctl switch
  "Greenhouse irrigation" on`), `home_running`, `valve_test_open`, `saver_running`; texts identical per state (list any
  intended difference, e.g. "locked" rows).
- **E2 actions from the screen:** tap Bed 2 → `SIM relay_2 ON`; `+Q B1` + Run Q → order in the log; STOP → confirm →
  all OFF; `script/sim-ctl get "Greenhouse status"` follows ("Watering B2" / "Idle"; to verify that `sim-ctl get` reads
  text sensors, else read the log).
- **E3 alert:** `GP_SIM_SUBST="gh_max_on_time=90s gh_bed_run_max=1 gh_bed_run_initial=1"`, `sim-ctl switch "Sim rogue
  relay 1" on` → after ~90 s "Alert" = "Greenhouse: watchdog - B1 locked", greenhouse page main line as in 014
  ("Watchdog: locked"), Home "Alarm"; reset by restarting the emulator (no `sim-ctl` button press) or from HA.
- **E4 HA actions (optional, needs HA connected to the emulator by IP):** call `esphome.<node>_gp_greenhouse_run_zone`
  with `zone: 3, minutes: 1` → relay_3 ON; stop with `..._stop_all`. Without HA: "not verified".
- **E5 HA alert (cut 2):** with `api_alert` delay shortened by substitution and no client → "Home Assistant
  disconnected" in the log after the delay (`sim-ctl` itself is an API client and would clear it).

## Acceptance criteria
- [ ] `script/test-cpp` → `test_gp_model`, `test_gp_alerts` pass (with the existing cpp tests).
- [ ] `uv run pytest -m unit` → all pass.
- [ ] `script/lint` → clean; `esphome config` OK for both entry files.
- [ ] `script/test` → all pass incl. new config rows and the host scenario (devcontainer with `GP_REQUIRE_SDL=1
      GP_REQUIRE_CXX=1`: no skips); wall time vs 014 recorded.
- [ ] `GP_SECRETS=example script/compile` and `GP_SECRETS=example GP_ESPHOME=minimum script/compile` → OK for both entry
      files; ESP32 flash/RAM delta vs 014 recorded.
- [ ] `git grep -n -e 'garden_zones\.' -e 'id(gh_zones)' -- packages garden-pilot.yaml garden-pilot-sim.yaml` → hits
      only in `irrigation.yaml`, `bed.yaml`, `packages/greenhouse/gp.yaml`, `packages/sim/fault.yaml`.
- [ ] `git grep -n sprinkler_lvgl -- . ':!tasks'` → no hits.
- [ ] Emulator E1-E3 done and reported; E4/E5 done or marked "not verified" / cut.
- [ ] `components/gp/README.md` documents the full contract of Decision 2; SPEC §4.1 links it; CLAUDE.md, README.md and
      README.ru.md updated and in sync.
- [ ] CI green (`checks`, `compile (pinned)`, `compile (minimum)`).
- [ ] Implementation notes say what (if anything) ran on the breadboard device.

**Needs real hardware (not CI):** optional smoke on the breadboard: RUN Bed 1 from the page clicks relay 1; STOP opens
all; valve test opens a relay <= 10 s; HA lists the six `gp_greenhouse_*` actions and the "Greenhouse status" / "Alert"
entities, and the existing entity names are unchanged.

## Out of scope
- New screens and widgets: bed card slots, Home widget stack and fit helper, alert strip UI, SETUP widget order
  (stage 9). This task only provides what they read.
- Schedules ("next" from a schedule, timeline), weather, heating model (stages 10-11); they extend the contract later.
- Service-mode inhibit for HA zone switches; watering history beyond "last" (SPEC §9.1); persisting last watering.
- Wiring soil skip into the engine (014 follow-up); air-sensor alerts.
- `sim-ctl` support for buttons and API actions (would make E3/E4 scriptable): follow-up.
- Page layouts for other bed counts (stage 9).

## Open questions
1. **[human]** HA API action names and the 1-based `zone` parameter (`gp_greenhouse_run_zone(zone, minutes)`), and the
   two new entities "Greenhouse status" / "Alert". Planner default as written. Renaming later breaks HA automations.
2. **[human]** Should HA keep using the engine's zone switches to start beds, or be steered to the `gp_*` actions only
   (engine zone switches then `internal: true`, which removes them from HA)? Default: keep them (014 entity
   continuity), document the actions as preferred.
3. **[human]** Persist "last watering" per zone across reboots (one preference write per run, a few a day) or RAM only?
   Default: RAM only; the Home zones widget shows "--" after a reboot.
4. **[human / designer]** Alert texts, severities and thresholds: HA disconnected after 60 s (WARN), soil sensor
   unavailable after 10 min (WARN), clock not set after 5 min (INFO), watchdog (ERROR). Is "HA disconnected" an alert at
   all on a device meant to work without HA (§4 "HA optional")? Default: only when `api_alert` is configured, which the
   public entry file does. Strip colour per severity must come from existing tokens (designer).
5. **[designer]** Zone state words for cards (IDLE / RUN / PAUSED / QUEUED / OFF / SKIPPED / LOCKED): `format.h` keeps
   them in one place; this task only uses them in `debug_line()` and the valve-test "locked".
6. SKIPPED visibility window (until next run/queue or 12 h): planner default, changeable without a contract change.
7. If nested `gp: groups:` does not merge across packages, groups become top-level `gp_group:` list items (implementer
   decides by the config row; contract fields unchanged).

<!-- Filled in by implementer -->
## Implementation notes
## Follow-ups
