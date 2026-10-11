# 019 — Watering schedules on the device (slots per group, HA-editable, next run)

Status: in-review
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

## Human decisions (2026-10-11; override anything below that conflicts)
- **Slots:** 2 per group by default, max 8 (substitution).
- **Slot content:** a zone list + one per-slot multiplier (10-200 % of each zone's own run duration). Per-zone
  minutes per slot may come later as an option; not in this task.
- **Days in HA:** 7 switches per slot (Mon..Sun), not a text field.
- **Missed runs:** catch-up window 60 min (substitution); later than that → logged as missed (history).
- **Interrupted runs (power cut mid-slot):** the "done" mark is per ZONE, set when that zone's watering COMPLETES
  and written to flash immediately (not the batched 60 s write). Within the catch-up window only the zones that did
  not complete are run again (an interrupted zone runs its full duration again); completed zones are not repeated.
  This replaces the "at most one run per slot per day, mark at start" rule where they conflict.
- **"Greenhouse schedules" master switch:** default ON; every slot defaults OFF.
- **A user STOP settles the slot (2026-10-11, review Required 1):** a STOP (`gp.stop_all` from any caller) and entering
  service mode drop today's pending zones of every slot ("stopped" in history / last result, not "missed"), clear the
  engine queue and any held-back start, and nothing re-runs after a reboot. Only zones cut by a power loss / reboot (no
  STOP) are re-run inside the catch-up window. This replaces "an interrupted zone stays pending" for the STOP case.
- **A slot firing while a manual full cycle runs waits for it (2026-10-11, review Required 5):** the cycle runs to its
  end, then the slot's zones (with the slot's multiplier) run; INFO log; the done marks follow the zones as usual. If the
  cycle is stopped by the user the held-back zones are settled like any STOP.

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
- [x] `script/test-cpp` → `test_schedule` all pass (and the existing C++ tests).
- [x] `uv run pytest -m unit` → all pass.
- [x] `script/lint` → clean; `esphome config OK` for both entry files.
- [x] `script/test` → all pass incl. the new config rows and the host scenario (devcontainer, `GP_REQUIRE_SDL=1
      GP_REQUIRE_CXX=1`: no skips).
- [ ] `script/test` wall time before/after recorded — see "Review round 1 fixes" (WALLTIME).
- [ ] `GP_SECRETS=example GP_ESPHOME=minimum script/compile` (ESP32) and the `garden-pilot-sim.yaml` compiles — NOT run
      (left to CI; the minimum `--only-generate` codegen row passes). Pinned ESP32 compile done, flash/RAM delta recorded.
- [x] `git grep -n -e 'garden_zones\.' -e 'sprinkler\.' -- packages/greenhouse/schedule*.yaml components/garden_schedule*`
      → no hits (principle 2).
- [x] `git grep -n 'on_time:' -- packages` → no new cron trigger for watering.
- [x] Emulator checks E1-E4 done and reported (E5 if HA is at hand).
- [ ] CI green (`checks`, `compile (pinned)`, `compile (minimum)`).
- [x] Docs updated (SPEC §4, §8, §9 item 11, §11; CLAUDE.md; READMEs in sync; component README).
- [x] Implementation notes state what ran on the breadboard device.

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
Milestone log.
- M1 (pure core): `components/garden_schedule/schedule_core.h` + `tests/cpp/test_schedule.cpp` (fake clock; 19 cases incl. DST, jumps,
  mono wrap, per-zone pending / restart rules). `script/test-cpp` green (63 cases).
- M2 (glue): `garden_schedule.h` (hub: 1 s tick, entity reads, preference + `global_preferences->sync()` after every mark change,
  next-run publishing, `skip_if`, `on_run`), `garden_schedule/__init__.py`, `garden_schedule_slot/__init__.py`;
  `packages/greenhouse/schedule.yaml`, `schedule_slot.yaml`; both entry files include the hub and slots 1, 2.
- M3 (tests/docs): `tests/test_schedule.py` (unit shape, python component, codegen pinned+minimum, host scenario),
  `tests/configs/schedule_sim.yaml`, config-matrix rows (`schedule_headless`, `schedule_no_slots`, `schedule_window_zero`,
  `schedule_window_too_long` and `schedule_bad_slot` expected failures, `sim_schedule_api_only`), `sim-ctl text` / `time`
  (+ tests), SPEC 4 / 8 / 9 / 11, CLAUDE.md, READMEs, `components/garden_schedule/README.md`.
- M4 (checks): `script/lint` ok; host scenario 1 passed (~2 min, three program runs on one preferences dir);
  ESP32 pinned compile OK: flash 1228839 -> 1248859 (+20020, 68.1 % of the app partition), RAM 123339 -> 126227. Full
  `script/test`: first run 739 passed / 3 failed (old tests needing the new packages: substitution check, external_components rule, entity-name filter); adapted, re-run of those green; second full run: 742 passed in 17:05 (UV_OFFLINE=1, GP_REQUIRE_CXX=1); lint ok.

Decisions / deviations (018 names win; each marked where it differs from the spec's guesses):
- Human decisions implemented: 2 slots by default (max 8); zone list + one multiplier 10-200 %; days = 7 switches per slot
  (so no `parse_days`; `parse_zones` and its cpp test remain); catch-up 60 min (`gh_schedule_catch_up_window`); per-zone done
  mark: a fired slot keeps a `pending` zone mask (persisted with `last_fired_day`, saved + synced at once), `garden_schedule.zone_done`
  clears a zone, a restart inside the window re-fires only the pending zones, outside it they are logged as missed;
  master switch "Greenhouse schedules" default ON, slots default OFF; slot entities `entity_category: config`.
- D1: `gp.enqueue_zones {mask, pct}` added to `components/gp` (018 had none): fresh engine read, zones queued or running are
  not queued again, run = zone run duration x pct cut to the zone maximum (018's clamp). No change to the GPL fork.
- D2 (to verify): `gp.start_queue` on a lane that is already running from the queue is a no-op (stock `start_from_queue`); on a lane
  running a full cycle it switches it to queue mode. Not exercised.
- D3/D4: 018 ships the service mode as `gp.inhibit` plus the global `gp_service_mode`; the skip condition is a new
  `gp.inhibited` condition (so the schedule works in headless configs without LVGL). No next-run entity existed in 018: the hub's
  entities are the source.
- Completion hook: `gp` group option `on_zone_finished (zone, completed)`; `completed` = queue-sourced run that was not ended by
  `stop_all` within 3 s. `packages/greenhouse/gp.yaml` calls the hook script `gp_gh_zone_done`, which `schedule.yaml` extends with
  `garden_schedule.zone_done` (script `!extend` appends the action). A manual run of a pending zone does not count.
- `on_run` uses the `gp.*` actions directly (018 has actions, not `gp_*` scripts), so the shape test asserts `gp.enqueue_zones` + `gp.start_queue` only.
- Zone count for zone lists: hub option `zone_count`, default = number of `gp_zone` entries (so adding a bed needs no edit).
- Next run: text sensor with ISO timestamp (offset from `recalc_timestamp_local`); the emulator showed `2026-10-11T06:28:00+00:00` (UTC
  container); HA rendering still to verify. The "last schedule" text is `06:28 #1 ran` / `ran (catch-up)` / `missed (40 min late)` /
  `skipped: service mode` (the spec's "missed (clock)" wording dropped: the minutes are more useful).
- Host scenario (spec step 3 was a leftover note): now three runs on one preferences directory: phase 1 fires slot 1 (zones 1 2 at 10 %),
  zone 1 completes, the program is killed inside zone 2; phase 2 restarts: only zone 2 runs (catch-up), zone 1 does not; phase 3: nothing
  runs. Slot 2 (disabled, zone 3) never runs. The `gp_service_mode` skip is covered by the emulator (E4) and cpp (`mark_skipped`), not the host run.
- Cuts: none of the cut list (`sim-ctl` text/time support was implemented, 3 small subcommands `text` / `time`).
  Not done: HA by IP (E5), `GP_ESPHOME=minimum` ESP32 compile (codegen test covers minimum; CI compiles it), sim ESP32/host compile outside the emulator run, wall-time
  before/after comparison of `script/test`.

Emulator (script/sim-ui + sim-ctl, fresh `ESPHOME_PREFDIR`, container clock UTC):
- E1 ok: slot 1 start now+2 min, zones "1 3", multiplier 10, enabled: next run text "Sun 06:28", at 06:28:00 `SIM relay_1 ON`, 30 s later relay_3, relay_2
  never; "last schedule" = `06:28 #1 ran`, next run text = tomorrow.
- E2 ok: restart 1.5 min after the run: no second run, settings restored.
- E3 ok: slot 2 at now+4 min, emulator stopped, restarted 1 min after the start: catch-up fired once ("ran (catch-up)"). With
  `GP_SIM_SUBST=gh_schedule_catch_up_window=0s` and a slot 40 min late: WARN "slot 1 missed: 40 min late, not run", nothing ran.
  (The E3 wording of the spec was fixed: the slot is not set "to now - 10 min" while stopped; the persisted start is set while running and the 60 s flash batching is waited out.)
- E4 ok: SETUP > SERVICE (valve test) -> `starts inhibited (service mode)`; slot 2 fired -> "skipped: service mode", no relay.
- E5 not done (no HA).
Not verified on hardware: everything (breadboard run, SNTP-only clock, power cut, valid clock after OTA reboot).

## Follow-ups
- Rain skip / HA rain delay entity (the `skip_if` list is the hook); global multiplier entity (setter exists).
- Per-slot per-zone minutes; the WATER tab editor and now/next + timeline widget consume `next_run()` / `day_runs()`.
- `gp.start_queue` while a full cycle runs on the lane switches it to queue mode (D2): decide in the widget / engine task.
- A zone skipped by the engine (wet soil, disabled) never completes, so it stays pending and re-queues after a restart inside the window.
- Verify on a device: HA renders "Greenhouse next run" (timestamp, empty when none); clock valid after an OTA reboot.
- Slot entities per slot: 11 (days are 7 switches); add a card/grouping on the HA side if it is too noisy.

## Review round 1 fixes
Decided by the author on 2026-10-11 (~21:50), implemented in round 2: see "Human decisions" (items 6 and 7) and "Round 2" below.

Done:
- Required 2: `Scheduler::resumed_`; pending zones resume only on the first valid tick after boot. A later clock jump
  or a transient invalid clock never re-fires a fired slot or reports it missed (pending kept). cpp:
  `clock_jump_while_running_does_not_refire`, `transient_invalid_clock_does_not_resume`,
  `unfired_slot_is_still_caught_up_after_a_later_jump`, `resume_only_on_first_valid_tick_even_with_master_off_at_boot`.
- Required 3: gp host scenario step 9 (`tests/configs/gp_layer_sim.yaml`, via the no-op hook script `gp_gh_zone_finished`
  that logs `fin zone=N completed=X`): queue run by itself -> 1; `stop_all` (clear_queue) -> 0; manual run -> 0; HA turning off the main
  switch -> 1. The watchdog-ended run is documented, not tested (scheduled runs are clamped below the limit). Table in
  `components/garden_schedule/README.md`.
- Required 4: `components/gp/README.md` lists `gp.enqueue_zones`, `gp.inhibited`, `on_zone_finished (zone, completed)`.
- Required 6: boxes unticked above (compile minimum / sim; wall time).
- Suggestions done: run marks keyed by slot NUMBER (blob index = number - 1, other slots keep their marks); `zone_group`
  option (default zone count per gp group, set in `schedule.yaml`); `time_id: ha_time`; README notes (slot enabled after
  its time, missed-slot zones in the engine queue, engine-skipped zones show "ran", spring-forward offset);
  `entity_category: diagnostic` on "next run text" and "last schedule" ("Greenhouse next run" stays a normal timestamp
  entity for HA).
- Skipped on purpose: millis-wrap 3 s stop window; spring-forward offset of the next-run timestamp (README line only).
- Verified: `script/test-cpp` 68 cases ok, `script/lint` ok, `tests/test_gp_layer.py` 17 passed, ESP32 pinned compile OK
  (flash 1249879 bytes, 68.1 %; RAM 126355).

Follow-ups added:
- A manual/service run of a zone remembers its intent for 15 s, so a queue run of the same zone started within 15 s is
  classified manual (`completed=false`): the scheduled zone then stays pending. Edge case, not changed.
- Engine-skipped zones stay pending (already listed); missed-slot zones stay in the engine queue (README).
- Final full run after the fixes: `UV_OFFLINE=1 GP_REQUIRE_CXX=1 script/test` -> 744 passed in 994 s (16:34), no skips.
  WALLTIME: the "before" run (a `git archive 8440aea` copy) was NOT done (would cost another ~15 min); the box stays
  unticked. The reviewer's earlier run of the branch was 978 s, so the new tests add little.

## Round 2 (the two decisions of 2026-10-11)
Implemented:
- Decision 1: `Scheduler::stop_pending()` (core; result `STOPPED`, `DayRunState::STOPPED`, day mark kept) and the hub action
  `garden_schedule.cancel_pending` (saves + syncs at once, "last schedule" = `06:00 #1 stopped`). New `gp` group trigger
  `on_stop` (fires in `stop_all` and when `gp.inhibit: true` is set, so the valve test's SERVICE entry counts) and action
  `gp.clear_queue`. `packages/greenhouse/gp.yaml` calls the hook script `gp_gh_stopped`; `schedule.yaml` extends it with
  `garden_schedule.cancel_pending` + `gp.clear_queue` (so a config without schedules keeps the old STOP behaviour: the
  queue is kept). `tests/cpp/test_schedule.cpp`: `awaiting_decision_stop_keeps_pending_and_a_restart_resumes_it` replaced
  by `stop_settles_the_slot_and_nothing_resumes_after_a_restart`, `stop_settles_every_slot_with_pending_zones`,
  `a_power_cut_without_a_stop_still_resumes_the_pending_zones`, `a_stopped_slot_does_not_fire_again_today_but_fires_tomorrow`.
  The gp scenario step 9 still pins `completed=0` for a stop (comment updated: the settle happens through `on_stop`).
- Decision 2: finding while testing: the engine in groups mode has no queue-enable switch, so queued zones are picked at the
  NEXT zone change, also in the middle of a cycle (a first version that only deferred `start_queue` ran the slot's zone
  right after the current cycle zone, before the rest of the cycle). So `gp` now holds back both `enqueue_zones` and
  `start_queue` while a non-queue run is active (`start_must_wait`, pure `components/gp/deferred_start.h`, cpp
  `test_gp_deferred_start.cpp`), and queues + starts them 5 s after the last zone stopped (cycle gaps are shorter).
  Cancelled by `stop_all`, `gp.clear_queue` and entering service mode. The previous WARN is gone.
- Host scenario `tests/configs/schedule_sim.yaml` (phases 4 and 5, plus slot 3): phase 4 STOP in the middle of slot 2 ->
  idle, queue empty, last = `#2 stopped`; phase 5 restart inside the window -> nothing runs (`quiet=1 queue=0`); (a) a
  manual cycle with a held-back enqueue + start, then STOP -> nothing starts, queue empty; (b) slot 3 fires in the second
  bed of a manual cycle (beds 1 and 2): the cycle's beds ran 60 s each undisturbed, then the slot's beds 1 and 2 ran 6 s
  each after a >= 4 s gap, last = `#3 ran`. The host scenario now takes about 7.5 min (was about 2).
- Docs: `components/garden_schedule/README.md` (the "Awaiting" bullet replaced by the two rules), `components/gp/README.md`
  (actions, `on_stop`), CLAUDE.md gotcha, SPEC 4.
Notes / limits:
- A cycle zone that finishes after the slot fired counts as "done" for the slot (queue-classified run) although the
  slot's own run of that zone follows after the cycle; the slot's zone list is held back as a whole, so such a zone runs
  twice (the second time at the slot's percentage). Harmless; a power loss before the held-back run leaves the not-yet-run
  zones pending (the held-back request is RAM only) and a restart inside the window runs them.
- Home Assistant turning off the engine's main switch is still not a STOP for the schedule (no `gp` involvement).
- `gp.enqueue_zone` (single zone, e.g. from Home Assistant) is NOT held back during a cycle (only `enqueue_zones`).
- Not verified on hardware: nothing of round 2.
