# garden_zones — patches on top of the stock `sprinkler`

Upstream base: ESPHome tag `2026.9.1`, commit `0b2b16e664ecfc0add37f3435db1c2140b8a687e`,
directory `esphome/components/sprinkler/` (`__init__.py`, `automation.h`, `sprinkler.h`, `sprinkler.cpp`).

Besides the patches below there are only renames (not marked in code): C++ namespace `esphome::garden_zones`,
Python namespace `garden_zones`, component key `garden_zones:`, action prefix `garden_zones.<name>`, log tag
`garden_zones`, and the fork header at the top of each file. `tests/test_garden_zones.py` diffs every forked file
against the `sprinkler` sources of the installed ESPHome package and fails on any change outside the regions
`GZ-PATCH-BEGIN(<id>)` ... `GZ-PATCH-END(<id>)` (blank lines are ignored). Regions do not nest.

## includes
- Purpose: pull the new helper and the preferences API into `sprinkler.h`.
- Files: `sprinkler.h` (include block).
- Behaviour change: none.
- Re-port notes: re-add the two `#include` lines after upstream's include block.

## queue-api
- Purpose: open queue API.
- Files: `sprinkler.h` (`queued_valves()`, `is_valve_queued()`, `remove_queued_valve()`), `sprinkler.cpp`
  (`Sprinkler::remove_queued_valve`, saves the queue after a removal), `automation.h` (`RemoveQueuedValveAction`,
  `IsValveQueuedCondition`), `__init__.py` (action `garden_zones.remove_queued_valve`, condition
  `garden_zones.is_valve_queued`).
- Behaviour change: new API only; the queue storage (reversed vector, next = `back()`) is unchanged. Removing a valve
  removes every duplicate of it and never touches the active valve.
- Re-port notes: independent of the upstream logic; re-add the blocks next to `clear_queued_valves`.

## queue-persist
- Purpose: the queue survives a reboot.
- Files: `sprinkler.h` (setters, members, `restore_queue_()` / `save_queue_()`), `sprinkler.cpp` (`setup()`, the two
  `pop_back()` sites of `load_next_valve_run_request_`, `queue_valve`, `clear_queued_valves`, implementations),
  `__init__.py` (`persist_queue` option, preference key from the controller id).
- Behaviour change: after every queue mutation a fixed-size snapshot (`queue_ops::QueueSnapshot`, max 32 entries,
  run order) is saved to a preference; `setup()` restores it. A snapshot with another format version, another valve
  count or an out-of-range valve is ignored. A restored queue never starts by itself.
- Re-port notes: re-add `save_queue_()` after every place upstream mutates `queued_valves_`.

## queue-skip-disabled
- Purpose: disabled zones are skipped when the queue reaches them.
- Files: `sprinkler.cpp` (start of `load_next_valve_run_request_`).
- Behaviour change: disabled valves at the head of the queue are dropped (INFO log) before the queue is read; the
  first enabled entry stays queued and is then taken by the unchanged upstream branch. If nothing is left, the
  upstream cycle branch runs as for an empty queue. Queuing a disabled zone is still accepted.
- Re-port notes: keep the block before the `next_req_.has_request()` check.

## manual-run
- Purpose: a manual single-zone run that keeps auto-advance and the queue (`start_single_valve` does not).
- Files: `sprinkler.h` (`run_valve()`, two flags), `sprinkler.cpp` (`Sprinkler::run_valve`, one extra branch in
  `load_next_valve_run_request_`, flag resets in `shutdown`, `resume`, `start_from_queue`, `start_full_cycle`,
  `start_single_valve`), `automation.h` (`RunValveAction`), `__init__.py` (action `garden_zones.run_valve`).
- Behaviour change: see the README; idle -> returns to idle afterwards; busy -> the running valve is paused with the
  stock `pause()` and resumed with its remaining time afterwards; paused by the user (nothing running) -> the pause
  is left alone; a stale user pause plus a running valve -> the running valve takes the pause slot (the stale pause
  is dropped). While the controller is stopping nothing is paused. A manual run is flagged `USER`, so during a full
  cycle it marks that zone as done for the cycle (it is not watered again by that cycle).
  `next_valve` / `previous_valve` do not clear the flags (they only select a valve with a delay).
- Re-port notes: the extra branch sits between the `next_req_` branch and the queue branch of
  `load_next_valve_run_request_`.
