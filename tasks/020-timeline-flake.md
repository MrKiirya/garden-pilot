# 020 — Host scenario timeline flake

Status: in-review
Roadmap: maintenance
Spec sections: none
Hardware check: none

## Goal
Host scenario tests stop flaking (about 1 run in 50) because windows between marks are cut by log order instead of by millisecond timestamp.

## Context
`test_safety_host_scenario` failed in CI with `tl.intervals(_V4, "s6_b", "s6_c") == []` getting `[(409945, 409945)]`.
Step 6 ends with a delay; in the same scheduler pass and the same millisecond the scenario logs `mark s6_c`, then switches the next valve on.
When the 50 ms state poll runs in that millisecond, its state line (logged after the mark) has `t == marks["s6_c"]` and the old inclusive time comparison counted it, giving a zero-length interval.
The same pattern exists in `_Timeline.trips_between`, in the greenhouse `_Timeline.window` and in the gp layer test `between`.
A line belongs to a window now iff its message index lies strictly between the two mark indexes; `t` is kept for the returned spans.

## Files
- modify: `tests/test_garden_zones.py` — `_Timeline.intervals`, `trips_between`, unit test
- modify: `tests/test_greenhouse_zones.py` — `_Timeline.window`, unit test
- modify: `tests/test_gp_layer.py` — `between` helper, unit test

## Checks to write first
| Level | Test | Asserts |
|---|---|---|
| unit | `tests/test_garden_zones.py::test_safety_timeline_cuts_windows_by_log_order` | same-ms lines after the end mark or before the start mark are not counted |
| unit | `tests/test_greenhouse_zones.py::test_greenhouse_timeline_window_cuts_by_log_order` | same for `window` / `spans` |
| unit | `tests/test_gp_layer.py::test_gp_layer_between_cuts_by_log_order` | same for `between` |

## Acceptance criteria
- [x] unit tests above fail on the old helpers and pass on the new ones
- [x] `uv run pytest -m unit` passes
- [x] host scenarios of garden_zones, greenhouse_zones and gp layer pass
- [x] `script/lint` passes

## Out of scope
- Changing scenario timing or the firmware.

<!-- Filled in by implementer -->
## Implementation notes
The schedule host test has no mark-window helper (it reads `rel` lines by value), so it is unchanged.
## Follow-ups
