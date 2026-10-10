# 019 — Watering schedules on the device (slots per group, HA-editable, next run)

Status: planned
Roadmap: SPEC §9 item 11 "Schedules (WATER tab) with the now/next + day timeline widget" — **schedules part 1 of 2**
(019: engine, entities, HA editing, next-run data; the WATER tab editor and the now/next + timeline widget are stage 9
screen tasks). Bed heating and alerts are separate tasks.
Spec sections: SPEC §3, §4 (Schedules, garden_zones Safety / Soil moisture), §4.1 (`gp_*`), §4.1a (time sources, task
016), §7 items 3-4, §8 + §10.2 (screens decisions, task 017), §9 item 11, §9.1 (multiplier, rain delay, history), §10.1
("Schedules: on the device, HA optional"); CLAUDE.md core principles 1, 2, 3, 4, 7
Hardware check: light. Schedules fire through the same `gp_*` path as a manual queue start, so the actuator side is
already covered by 014. On the breadboard device: one scheduled run fires on time with Home Assistant **off** (SNTP time,
task 016), and a power cut inside / outside the catch-up window behaves as specified. Real valves and water stay
unverified. The PC emulator is the main verification bar.

**Stacked on 014 (garden_zones on the device), 016 (SNTP + `timezone`) and 018 (`gp_*` layer).** Branch
`task/019-schedules` from the 018 branch (or `master` once 014/016/018 are merged; rebase before review). 018 is being
specified in parallel (`tasks/018-gp-layer.md`): this file assumes the `gp_*` contract in "Dependencies" below.
**Where 018 shipped other names or semantics, 018 wins**; mark each adapted spot "to verify by the implementer" in
Implementation notes. If 018 lacks an item marked *(add here if missing)*, add it in this task (it is in the budget).

## Goal
Each irrigation group gets up to 8 **schedule slots** stored on the device: start time, days of week, which zones
(`all` = full cycle in zone order, or a list), a run-time multiplier (%) and an enabled flag, plus one "schedules on"
master switch per group. Slots fire from the device clock (Home Assistant time **or** SNTP), so watering runs with HA
and Wi-Fi gone after the clock was set once. A fired slot enqueues its zones through `gp_*` and starts the queue, so
the existing safety (watchdog lockouts, soil skip, disabled zones, service mode) applies unchanged. Slots are edited
today through Home Assistant entities (and `script/sim-ctl` in the emulator); the on-device editor comes with the WATER
tab (stage 9) and uses the same entities. The schedule publishes a **next run** value (HA timestamp + short text) and
C++ accessors for the now/next widget and the day timeline. Behaviour on an invalid clock, clock jumps (SNTP sync after
boot), DST changes and missed runs after a power cut is defined and covered by C++ unit tests with a fake clock.

## Context

### What exists / is assumed (read the files as merged; do not re-plan)
- 014: one group `gh_zones` ("Greenhouse") in `packages/greenhouse/irrigation.yaml`; each `bed.yaml` include adds a
  `garden_zone:` list item (zone number = include order, 0-based; UI and entities say "Bed N" = zone N-1). Zone
  run-duration numbers `gh_bed<N>_run_duration` (minutes, max `${gh_bed_run_max}` = 55, chosen so the longest run fits
  `max_on_time` 60 min). Main switch ON = full cycle. 014 "Human decisions": `gh_max_parallel` default 1; soil skip not
  wired yet (follow-up); watchdog default 60 min, can be `never`.
- 012/013 group API (`components/garden_zones/group.h`): `queue_zone(zone, run_duration)` (never starts),
  `is_zone_queued`, `queued_zones()`, `start_queue()` (starts every lane that has something queued), `start_cycle()`,
  `active_zones()`, `run_zone` refuses a watchdog-locked zone; the lanes' skip check (`skip_reason`) skips locked zones
  and wet soil **when the zone's turn comes in a queue or cycle** — so scheduled runs get the soil and watchdog
  behaviour for free as long as they go through the queue. The queue persists across reboot and never starts by itself
  (`queue-persist`); duplicates are allowed in a lane queue.
- 016 (SPEC §4.1a on branch `task/016-time-fallback`): `ha_time` is the only clock id features use; SNTP writes the
  same system clock; `timezone: ${timezone}` (default `UTC`) on both; an SNTP sync does **not** fire
  `ha_time.on_time_sync` (poll instead); emulator uses `time: host` with the PC zone. No RTC chip yet.
- 017 (SPEC §8 / §10.2 on branch `task/017-screens-decision`): Home is a stack of widgets; "now/next + day timeline"
  is a first widget ("until schedules: now + queue"); WATER tab hosts schedules. Widgets read data through `gp_*`
  / accessors, never engine ids. The schedule editor drafts live in the claude.ai canvas (boards W0-W6), not in the
  repo — 019 adds no screen.
- Known UI defect (SPEC §8): the Home "NEXT" label shows the queue time. Fixing it belongs to the widget task
  (stage 9); 019 provides the data.

### Dependencies on 018 (`gp_*` contract assumed here)
Per group (names illustrative, 018 wins):
- D1 `gp_<group>_enqueue_zones(mask, multiplier_pct, source)` — *(add here if missing)*: for every zone in the bit
  mask, in zone order, `queue_zone` with `run_duration = min(base × pct / 100, zone number max)` where base is the zone's
  run-duration number; a zone that is already queued or active is **not** queued again (INFO log). Needs one new group
  method `queue_zones(mask, pct)` in `group.h` (+ action `garden_zones.queue_zones` in `groups.py`) because YAML has no
  loop and the clamp needs each zone's number. The clamp to the number's `max_value` keeps every scheduled run under
  the 013 config rule (`max_value × 60 + 2 s <= max_on_time`), so a multiplier can never push a valve into a watchdog
  trip.
- D2 `gp_<group>_start_queue` — starts lanes that have queued zones; lanes already running keep running (their queue
  is picked up by auto-advance / queue mode). **To verify by the implementer** against the stock
  `start_from_queue()` on a busy lane: if it interrupts the running zone, D2 must only start idle lanes (018 or here).
- D3 `gp_service_mode` (existing switch, valve test) — read by the schedule's `skip_if` (below).
- D4 018's group "next run" model: if 018 defines a `gp_*` next-run entity or accessor per group, 019 feeds it from the
  schedule hub; otherwise 019's hub entities are the source and 018's layer re-exports them in a follow-up.

### ESPHome options checked (pinned 2026.9.1 in `.venv`; minimum 2026.6.3 proven by the config / compile rows)
- **`time:` `on_time` cron triggers** ([docs](https://esphome.io/components/time/#on-time-trigger); source
  `esphome/components/time/automation.cpp` at tag 2026.9.1): fields are **fixed at compile time**, so slots editable at
  run time are impossible with them. Behaviour worth copying: `CronTrigger` checks once per second
  (`set_interval(1000)`), does nothing while `!now().is_valid()`, catches up second by second for normal progress, and
  treats a jump of more than `MAX_TIMESTAMP_DRIFT = 900 s` as a sync: **forward jump → the skipped interval never
  fires**, backward jump → logged, no re-fire. It knows nothing about DST (it compares local fields, so the 02:00-03:00
  spring gap is skipped and a fall-back hour can match twice). → **Rejected** for slots; a C++ scheduler is needed.
- **Runtime-editable entities** (all restore to flash, all visible and settable in HA, all settable over the native API):
  - `datetime: platform: template, type: time` (`esphome/components/template/datetime/__init__.py`, 2026.9.1):
    `optimistic`, `restore_value` (default false), `initial_value`; lambda excludes both. C++ `datetime::TimeEntity`
    (`hour`, `minute`, `second` fields). HA shows a time picker. Exists since 2024.5 (well below the minimum).
  - `text: platform: template` (`.../template/text/__init__.py`, 2026.9.1): `max_length` <= 255, `pattern` (regex
    shown to HA), `restore_value` (saved with a `TextSaver<max_length>`), `optimistic`. Used for days and zones.
  - `switch: platform: template` with `restore_mode`, `number: platform: template` with `restore_value` (as the bed
    run-duration numbers today).
- **Preferences / flash** (`esphome/components/esp32/preferences.cpp`, `components/preferences/__init__.py`,
  `esp32/__init__.py`, 2026.9.1): ESP32 preferences are NVS blobs keyed by a 32-bit hash; writes are batched every
  `flash_write_interval` (default **60 s**) and skipped when the value did not change; the generated ESP-IDF partition
  table reserves `IDF_NVS_SIZE = 0x70000` for NVS. 8 slots × 5 entities + one 40-byte hub record is far below that; wear
  is a few writes per user edit plus one per fired slot per day. Consequence of the 60 s batching: a slot that fired less
  than 60 s before a power cut may not have its "fired" mark on flash → covered by the catch-up rule (it would fire
  again only inside the catch-up window, and D1's duplicate rule only protects within one boot). Documented, Open
  question 3.
- **`ESPTime`** (`esphome/core/time.h`): `is_valid()` = year >= 2019 and fields in range; `from_epoch_local`,
  `recalc_timestamp_local()`, `day_of_week` 1 = Sunday. ESP-IDF keeps the system time across a **software** reset
  (OTA, restart button) but not across a power cut, so after an OTA reboot the clock is valid at once; after a power
  cut it becomes valid at the first HA or SNTP sync. **To verify on the device** (one log line after OTA).
- **Floats:** a `sensor` publishes `float` (24-bit mantissa → an epoch would be off by up to ~2 min). The next-run
  timestamp therefore goes out as a `text_sensor` with `device_class: timestamp` (ISO 8601 with offset), not a sensor.
  **To verify by the implementer** that HA renders it (it does for template text sensors with that device class).

### Design decisions (planner; see Open questions for the human's calls)
1. **Engine-agnostic scheduler component, separate from the fork.** New `components/garden_schedule/` (hub, MIT, no
   forked code) and `components/garden_schedule_slot/` (one `garden_schedule_slot:` list item per slot, `MULTI_CONF`,
   schema only — same pattern as `garden_zones` / `garden_zone`). The hub never calls `garden_zones`: when a slot is
   due it fires `on_run` with `(uint32_t zone_mask, uint8_t multiplier_pct, uint8_t slot)` and the package routes that to
   `gp_*` (D1, D2). This keeps principle 2 (schedules → `gp_*` only) and lets a future engine swap keep the scheduler.
   Principle 1: the stateful logic (due evaluation, fired marks, next run) is C++; the YAML automation is two
   `script.execute` calls with three `!lambda 'return x;'` parameters, nothing more.
2. **Pure core `schedule_core.h`** (no ESPHome includes, unit-tested like `queue_ops.h` / `watchdog_core.h`). Input per
   tick: `Tick{bool valid; int64_t epoch_utc; uint32_t mono_ms; LocalTime local{days_since_epoch_local, weekday 0=Mon,
   minute_of_day, second}}`. Slot: `{bool enabled; uint16_t start_minute; uint8_t days_mask; uint32_t zone_mask; uint8_t
   pct}`. State per slot: `last_fired_day` (local day number, persisted). Output: list of `Fire{slot, zone_mask, pct}`
   and `Missed{slot, minutes_late}`, plus `next_run()` and `day_runs(day)`. The ESPHome wrapper builds `Tick` from
   `ha_time->now()` and `millis()` every 1 s (like `CronTrigger`).
3. **Due rules (the heart; all unit-tested):**
   - Clock invalid → nothing fires, nothing is marked, `next_run()` empty; the hub logs once (INFO) when the clock
     becomes valid.
   - A tick is **continuous** when `|Δepoch_utc − Δmono| <= 5 s` relative to the previous tick (uint32 wrap-safe
     `Δmono`). On a continuous tick every enabled slot whose start was **crossed** in local time (`prev_local <
     start <= cur_local`, also across midnight) on a matching weekday and not yet fired that local day **fires**. This
     makes DST correct: on spring-forward local time jumps 02:00 → 03:00 while UTC is continuous, so a 02:30 slot fires
     once at 03:00; on fall-back the 02:00-03:00 hour repeats, the fired mark for the day prevents a second run.
   - A **discontinuous** tick (first valid tick after boot, SNTP/HA sync that moved the clock, manual clock change)
     never fires by crossing. Instead every enabled slot of **today** (local) with `start <= now`, matching weekday and
     not fired today is either **caught up** (fires now) when `now − start <= catch_up_window` or recorded as **missed**
     (WARN log, marked as handled for the day, `last_result` text). Slots of earlier days are never caught up.
     `catch_up_window` is a hub option, default **60 min**, range 0-6 h (Open question 2); 0 = never catch up.
   - One run per slot per local day: `last_fired_day == today` blocks. Editing a slot's start time after it fired today
     does not make it fire again today (documented). A stored `last_fired_day` more than 1 day in the future (clock was
     wrong when it fired) is cleared with a WARN on the first valid tick.
   - Master switch off or slot disabled → not due, not missed, not marked.
   - Several slots due in the same tick fire in slot order (one `on_run` each; D1 skips zones already queued).
4. **`skip_if` hook (rain skip, service mode).** Hub option `skip_if:` = list of `{condition: <ESPHome condition>,
   reason: "<text>"}`, evaluated at fire time; the first true one turns the fire into a skip (INFO log, `last_result`
   "skipped: <reason>", slot marked fired for the day). The greenhouse package uses it for `gp_service_mode`
   ("service mode"). A future rain sensor / HA rain-delay just adds an item — no code change. **To verify by the
   implementer** that `automation.build_condition` in a component's config works as in other components (e.g.
   `wait_until`); if not, fall back to an optional `skip_switch_ids` list (switch ON = skip).
5. **What a slot runs.** `zones` text: `all` (every zone of the group, zone order = full cycle) or bed numbers
   `1 3` (1-based, as the UI names them). Durations = each zone's run-duration number × `multiplier` %, clamped (D1).
   Per-slot per-zone durations are **not** in this task (entity explosion; Open question 4). Disabled zones, locked
   zones and wet soil are skipped by the engine when their turn comes, unchanged.
6. **Multiplier hook.** Per-slot `multiplier` number 10-200 %, step 10, default 100. The core multiplies by a hub-level
   `global_pct` (fixed 100 now, setter `set_global_pct()` for the backlog "global run-time multiplier", §9.1) and clamps
   the product to 10-200 %. No HA entity for the global factor yet.
7. **Entities (HA edits them today; the stage 9 editor writes the same entities).** Per slot N of group `gh`
   (include `packages/greenhouse/schedule_slot.yaml` with `vars: {slot: N}`), all `entity_category: config`, restore on:
   | id | type | name | default |
   |---|---|---|---|
   | `gh_sched<N>_enabled` | template switch, `RESTORE_DEFAULT_OFF` | "Greenhouse schedule N" | off |
   | `gh_sched<N>_start` | template datetime `type: time` | "Greenhouse schedule N start" | 06:00 + (N−1) h |
   | `gh_sched<N>_days` | template text, `pattern` `^(daily|(mon|tue|wed|thu|fri|sat|sun)( (mon|tue|wed|thu|fri|sat|sun))*)$`, max 27 | "Greenhouse schedule N days" | `daily` |
   | `gh_sched<N>_zones` | template text, `pattern` `^(all|[1-9][0-9]?( [1-9][0-9]?)*)$`, max 47 | "Greenhouse schedule N zones" | `all` |
   | `gh_sched<N>_multiplier` | template number 10-200 %, step 10 | "Greenhouse schedule N multiplier" | 100 |
   Per group (`packages/greenhouse/schedule.yaml`): switch "Greenhouse schedules" (`gh_schedules_on`, restore, default
   **on** — slots themselves default off, so nothing waters until a slot is enabled), text sensor "Greenhouse next run"
   (`device_class: timestamp`, empty when none), text sensor "Greenhouse next run text" (`Tue 06:00` / `--:--`, for
   the screens and the 26 px widget row), text sensor "Greenhouse last schedule" (`06:00 #1 ran`, `06:00 #1 missed
   (clock)`, `06:00 #1 skipped: service mode`). An invalid days/zones value (bypassing the HA pattern, e.g. over the
   API) disables the slot at evaluation with one WARN; zone numbers above the group's zone count are dropped with a WARN.
   Package default: 2 slot includes in the entry files (cheap to add more; max 8 per hub, validated).
8. **Next run and timeline data.** Hub accessors (C++, for LVGL lambdas in stage 9 and for D4):
   `optional<NextRun> next_run()` → `{slot, local day, start_minute, epoch_utc}` over the next 8 days, ignoring
   disabled slots, the master switch off, and slots already fired today; `std::vector<DayRun> day_runs(int day_offset)`
   → today's (or another day's) slots sorted by start with `fired | missed | skipped | pending`. Durations for the
   timeline bar are **not** computed here (needs the engine's per-zone durations and lanes; widget task). Epoch for the
   HA timestamp is built from the local day + minute with `ESPTime` + `recalc_timestamp_local()` in the wrapper, so
   the DST offset of that day is used; the core stays timezone-free. Republished on every change and every minute.
9. **Persistence.** One hub preference (key from the hub id, format version byte, `last_fired_day[8]` as `int32`),
   written only when a slot is marked. The 014 queue persistence stays as is: a run that was cut by a power loss is not
   resumed by the schedule (its queue is restored but not started, 008) — the catch-up rule only concerns slots whose
   start was missed while the device was off.

## Files
Component (MIT, new; no forked file touched):
- create: `components/garden_schedule/__init__.py` — hub schema (`id`, `time_id`, `catch_up_window`, `master_switch_id`,
  `skip_if`, `next_run` / `next_run_text` / `last_result` text sensor ids, `on_run` trigger), slot collection at final
  validation (max 8 per hub, unique slot numbers), codegen.
- create: `components/garden_schedule/schedule_core.h` — pure core (Decisions 2, 3, 6, 8) + parsers for days / zones.
- create: `components/garden_schedule/garden_schedule.h` — ESPHome wrapper `GardenSchedule : Component` (1 s interval,
  entity reads, preference, publishing, `skip_if` evaluation, `on_run` trigger).
- create: `components/garden_schedule_slot/__init__.py` — `garden_schedule_slot:` list item schema (`schedule`, `slot`,
  `enabled_id`, `start_id`, `days_id`, `zones_id`, `multiplier_id`).
Engine side (only if 018 lacks D1):
- modify: `components/garden_zones/group.h`, `groups.py` — `queue_zones(mask, pct)` + action `garden_zones.queue_zones`
  (non-forked files, no `GZ-PATCH`).
YAML:
- create: `packages/greenhouse/schedule.yaml` — hub `gh_schedule`, master switch, text sensors, `on_run` → `gp_*`
  (D1, D2), `skip_if` service mode.
- create: `packages/greenhouse/schedule_slot.yaml` — one slot's five entities + its `garden_schedule_slot:` list item.
- modify: `garden-pilot.yaml`, `garden-pilot-sim.yaml` — `gh_schedule` after `gh_screensaver_status` / the `gp_*`
  package, then `gh_schedule_slot_1`, `gh_schedule_slot_2` (`!include` with `vars`), commented hint for more slots.
Tests:
- create: `tests/cpp/test_schedule.cpp` — fake-clock unit tests (below).
- create: `tests/test_schedule.py` — shape checks, codegen and host rows.
- create: `tests/configs/schedule_sim.yaml` — host scenario.
- modify: `tests/test_config_matrix.py` — rows below.
- modify (cuttable): `script/sim-ctl` + its unit test — `set` for `text`, `datetime` time (`HH:MM`) entities.
Docs: `docs/SPEC.md` (§4 Schedules paragraph → real behaviour; §8 next-run data; §9 item 11 status; §11 sources),
`CLAUDE.md` (layout rows for the two components and two packages, package order, gotcha "schedules: one run per slot
per local day, catch-up window"), `README.md` + `README.ru.md` (one feature line each, kept in sync),
`components/garden_schedule/README.md` (create: options, rules, entity table).

About 18 paths (≈ 11 code/test files + docs) — over the ~10-file budget because a new component needs both the hub and
the slot directory. **Cut order** if the run gets long: (1) `script/sim-ctl` text/time support (the emulator check then
uses HA by IP or a sim-only template button that sets slot 1 to now + 2 min); (2) `day_runs()` accessor (keep
`next_run()`); (3) `last_result` text sensor; (4) `skip_if` as a generic condition list → fixed `skip_switch_ids`
(keep service mode); (5) README wording beyond one line. **Not cuttable:** core rules (Decision 3) with their unit
tests, persistence, next-run entities, D1/D2 routing through `gp_*`, the host scenario, config rows on pinned and
minimum.

## Checks to write first
| Level | Test | Asserts |
|---|---|---|
| cpp | `test_schedule.cpp::parse_days` | `daily` → 0x7F; `mon wed fri` → Mon/Wed/Fri bits; empty, `mo`, `mon,wed`, duplicates handled (`mon mon` ok = Mon) ; invalid → nullopt. |
| cpp | `parse_zones` | `all` → all bits of `zone_count`; `1 3` → bits 0 and 2; `0`, `17` with 3 zones → dropped (flag set for the WARN); garbage → nullopt. |
| cpp | `fires_once_on_crossing` | Fake clock 05:59:59 → 06:00:00 continuous on a matching weekday → one `Fire{slot 0, mask, pct}`; next ticks to 06:05 → nothing; same time next day → fires again. |
| cpp | `weekday_mask_respected` | `mon wed fri` slot: Tue crossing → nothing; Wed → fires. `next_run()` on Tue 07:00 → Wed 06:00. |
| cpp | `disabled_and_master_off` | Disabled slot or master off: crossing → no fire, no mark, no missed; `next_run()` skips it / empty. |
| cpp | `same_minute_slots_fire_in_order` | Two slots at 06:00 → two fires, slot order. |
| cpp | `midnight_crossing` | Slot 00:00: tick 23:59:59 → 00:00:00 of the next local day (weekday of the new day) fires. |
| cpp | `dst_spring_gap` | Local 01:59:59 → 03:00:00 with UTC +1 s (continuous) → a 02:30 slot fires once at 03:00; a 03:30 slot fires later as normal. |
| cpp | `dst_fall_back_no_double` | Local 02:59:59 → 02:00:00 with UTC +1 s → a 02:30 slot that fired before fires no second time. |
| cpp | `boot_catch_up_inside_window` | First valid tick (no previous) at 06:20, slot 06:00, window 60 min, not fired today → fires (catch-up); `last_fired_day` = today. |
| cpp | `boot_missed_outside_window` | First valid tick at 07:30 → `Missed{slot, 90}`, no fire, marked; later ticks today → nothing; tomorrow fires normally. Window 0 → 06:01 is missed. |
| cpp | `boot_already_fired_today` | Persisted `last_fired_day` = today → first valid tick at 06:20 → nothing. |
| cpp | `sync_jump_forward` | Clock jumps 05:00 → 06:30 (UTC +5400 s, mono +1 s, discontinuous): slot 06:00 → catch-up (window 60); slot 05:10 → missed (80 min). |
| cpp | `sync_jump_backward` | After a 06:00 fire, clock jumps back to 05:50 → crossing 06:00 again → no fire (fired today). |
| cpp | `future_mark_cleared` | `last_fired_day` = today + 30 on the first valid tick → cleared, flag for the WARN, slot fires at its time today. |
| cpp | `invalid_clock` | `valid=false` ticks → no fire, no mark, `next_run()` empty; valid again (discontinuous) → boot rules apply. |
| cpp | `mono_wraps` | `mono_ms` wrapping past 2^32 between ticks stays continuous. |
| cpp | `edit_after_fire` | Fired at 06:00, start changed to 08:00 → no fire today; tomorrow 08:00. |
| cpp | `multiplier_hook` | Slot 150 % × global 100 → pct 150; global 200 → clamped 200; slot 10 % × global 50 → clamped 10. |
| cpp | `next_run_and_day_runs` | `next_run()` = earliest pending over 8 days (today later, tomorrow, week wrap, none); `day_runs(0)` sorted with fired / missed / pending states. |
| unit | `tests/test_schedule.py::test_slot_package_shape` | `schedule_slot.yaml`: exactly the five entities with ids `gh_sched${slot}_*`, `entity_category: config`, restore (`restore_value: true` / `RESTORE_DEFAULT_OFF`), the two `pattern`s and defaults of Decision 7, one `garden_schedule_slot:` **list** item; no `lambda`, no `!secret`, no `GPIO\d+`. |
| unit | `test_schedule_package_shape` | `schedule.yaml`: one hub `gh_schedule` with `time_id: ha_time`, `catch_up_window` default from a substitution, `skip_if` containing `gp_service_mode`; `on_run` contains only `script.execute` of `gp_*` scripts (no `garden_zones.`, `sprinkler.`, `switch.`, `board_relay`); each `!lambda` in it is a single `return x;`-style line. |
| unit | `test_entry_includes_schedule` | Both entry files include `gh_schedule` after the `gp_*` / greenhouse packages and slots 1, 2 after it, in order; slot numbers unique. |
| unit | `test_schedule_component_python` | Importing `garden_schedule/__init__.py` by path: final validation rejects 9 slots, a duplicate slot number, `catch_up_window` > 6 h, a slot pointing to an unknown hub. |
| unit | ASCII UI text check (existing) | Texts produced for the screens (`--:--`, `Tue 06:00`) are ASCII (assert on the C++ format strings in `garden_schedule.h`). |
| config | `tests/test_config_matrix.py` rows | Device and sim entry files with the schedule (pinned + minimum); `schedule_no_slots` (hub without slots: config OK, warns); `schedule_bad_slot` **expected failure** (slot number 9). |
| config | `test_schedule_codegen[pinned\|minimum]` | `compile --only-generate` of the device entry: one `GardenSchedule`, two slot registrations, the `on_run` automation, no `garden_zones` symbol referenced by `garden_schedule.h`. |
| host | `test_schedule_host_compile` (pinned) | `tests/configs/schedule_sim.yaml` compiles for `host`. |
| host | `test_schedule_host_scenario` (pinned) | One run, `GSTEST` log lines (below). |

### Host scenario (`tests/configs/schedule_sim.yaml`)
Real `irrigation.yaml` + 2× `bed.yaml` + the 018 `gp_*` package + `schedule.yaml` + 2× `schedule_slot.yaml` on
`hardware/sim.yaml`, bed numbers 1 min, `time: host` (PC clock). `on_boot` (late priority) sets via `datetime.time.set`
/ `text.set` / `switch.turn_on`: slot 1 = next whole minute + 1, `daily`, zones `2`, enabled; slot 2 = same minute,
`daily`, zones `1`, **disabled**. A 100 ms `interval` logs `GSTEST t=<ms> r1=<0/1> r2=<0/1>` on change; `wait_until`
with timeouts:
1. Before the start minute: both relays 0; "Greenhouse next run text" = slot 1's time.
2. Within 3 s after the start minute: `r2 = 1`, `r1` stays 0 (slot 2 disabled); "Greenhouse last schedule" ends with
   `ran`; next run text = tomorrow's time.
3. `switch.turn_on: gp_service_mode`-equivalent (018's way to enter service mode) is **not** used; instead a second
   boot is not possible in one run, so persistence is left to the emulator check.
4. `GSTEST done` within 3 min. Global: `r1` never 1.
(Keep it to one firing; DST, jumps and catch-up are proven in `test_schedule.cpp`.)

### Emulator check (manual, `script/sim-ui` or `script/sim`, results in Implementation notes)
- E1: `script/sim-ctl set "Greenhouse schedule 1 start" HH:MM` (now + 2 min), `set "... days" daily`,
  `set "... zones" "1 3"`, `switch "Greenhouse schedule 1" on` → `get "Greenhouse next run text"` shows it; at the
  minute the log shows `SIM relay_1 ON` then `relay_3` (relay_2 never), "last schedule" = ran.
- E2 restart within the window: stop the emulator 1 min after the start, restart → **no** second run (mark persisted;
  `.esphome/sim-prefs/`). Note: with the 60 s flash batching, stop at least 61 s after the fire.
- E3 catch-up: set slot 1 start to now − 10 min while the emulator is stopped is not possible → instead set start =
  now + 1 min, stop the emulator before it fires, wait 2 min, restart → catch-up fires once (window 60); repeat with
  `-s catch_up_window 0s` (via `GP_SIM_SUBST` from 014) → "missed (...)" logged, nothing runs.
- E4 service mode: enter SETUP > SERVICE, let a slot fire → "skipped: service mode", no relay.
- E5 editing in HA (optional, HA connected by IP): the five slot entities appear under Configuration, time picker and
  text patterns work.

## Acceptance criteria
- [ ] `script/test-cpp` → `test_schedule` all pass (and the existing C++ tests).
- [ ] `uv run pytest -m unit` → all pass.
- [ ] `script/lint` → clean; `esphome config OK` for both entry files.
- [ ] `script/test` → all pass incl. the new config rows and the host scenario (devcontainer, `GP_REQUIRE_SDL=1
      GP_REQUIRE_CXX=1`: no skips); wall time before/after recorded.
- [ ] `GP_SECRETS=example script/compile` and `GP_SECRETS=example GP_ESPHOME=minimum script/compile` → ESP32 OK; same
      for `garden-pilot-sim.yaml`; flash/RAM delta recorded.
- [ ] `git grep -n -e 'garden_zones\.' -e 'sprinkler\.' -- packages/greenhouse/schedule*.yaml components/garden_schedule*`
      → no hits (principle 2).
- [ ] `git grep -n 'on_time:' -- packages` → no new cron trigger for watering.
- [ ] Emulator checks E1-E4 done and reported (E5 if HA is at hand).
- [ ] CI green (`checks`, `compile (pinned)`, `compile (minimum)`).
- [ ] Docs updated (SPEC §4, §8, §9 item 11, §11; CLAUDE.md; READMEs in sync; component README).
- [ ] Implementation notes state what ran on the breadboard device.

**Needs real hardware (not CI):** a slot fires on time with HA stopped and SNTP as the only clock source (016); power
cut 10 min after a missed start → catch-up once; power cut 2 h after → "missed", no run; after an OTA reboot the clock is
valid immediately (log line). Unverifiable here: DST change on the device (covered by unit tests only), real valves.

## Out of scope
- WATER tab, on-device schedule editor (canvas W0-W6), now/next + day timeline widget, Home "NEXT" label fix (stage 9;
  they consume `next_run()` / `day_runs()` and the slot entities).
- Per-slot per-zone durations; interval modes ("every N days", odd/even days); cycle and soak; seasonal adjust.
- Rain sensor / HA rain delay entity (only the `skip_if` hook exists); global multiplier entity (only the setter).
- Watering history (§9.1), alerts, bed heating schedules.
- Lawn group schedules (same package pattern once a lawn package exists).
- Timeline duration estimates (need engine + lane data).
- RTC chip (016 follow-up).

## Open questions
1. **[human]** Slot count default in the entry files: 2 per group (max 8)? Each slot = 5 HA entities.
2. **[human]** Missed-run policy: catch up a slot missed by a power cut / late clock if the device is back within
   **60 min** (default), else skip with a WARN. Alternatives: 0 (never catch up — safest against watering at a wrong
   time) or "always run once late the same day". Watering at an unexpected time can matter (sun on wet leaves, a pump
   on shared supply).
3. **[human]** Accept that a slot fired less than 60 s (ESPHome `flash_write_interval`) before a power cut can run
   again on restart if the device is back within the catch-up window? Alternative: force a preference sync right after
   marking (`global_preferences->sync()`; a few extra flash writes per day).
4. **[human]** Slot content: zones list + one multiplier (planned) vs per-zone minutes per slot (N_zones more entities
   per slot).
5. **[human]** Days format in HA: text `daily` / `mon wed fri` (planned, one entity) vs seven switches per slot vs a
   select of presets.
6. **[human]** Default for the "Greenhouse schedules" master switch: on (planned; slots default off) or off.
7. Clock jumps under 5 s are treated as continuous; a manual clock change on the device is not possible today, so a
   discontinuity is only a boot or an HA / SNTP sync.
8. Edited start time after today's run: no second run today (planned). Tell me if a re-run on edit is expected.

<!-- Filled in by implementer -->
## Implementation notes
## Follow-ups
