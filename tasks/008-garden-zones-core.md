# 008 — `garden_zones` core: fork of the stock `sprinkler` with an open, persistent queue

Status: implemented, review round 1 fixes applied; C++ parts unverified (no C++ compiler on the implementer machine)
Roadmap: SPEC §9 item 6 "`garden_zones` component" (part 1 of 4, see "Stage plan" below)
Spec sections: SPEC §3, §4 (garden_zones, licence, cost), §4.2, §6, §7 (items 1, 3, 4), §9, §9.1, §10.1;
CLAUDE.md core principles 1, 2, 4, 7
Hardware check: none. The author's device does not change in this task (`garden-pilot.yaml` keeps the stock
`sprinkler`). The new component runs only in a host (Linux) test build with simulated relays.

## Goal
The repository gets its own irrigation engine, `components/garden_zones/`: a copy of ESPHome's
`esphome/components/sprinkler/` at tag **2026.9.1**, renamed so it can coexist with the stock component, with a
small, documented patch set on the queue only:
1. an **open queue API** (list in run order, "is zone N queued", remove one zone);
2. the queue **survives a reboot** (restored as a list; it never starts by itself);
3. a **manual single-zone run that does not switch off auto-advance or the queue** (stock `start_single_valve`
   does, SPEC §3);
4. **disabled zones are skipped** when the queue reaches them (stock runs them anyway).

New logic lives in a header-only, ESPHome-free C++ helper with host-compiled unit tests (`script/test-cpp`). A test
configuration on the sim board (3 zones) loads the component through `external_components`, passes `esphome config`
on the pinned and minimum ESPHome, is compiled for the `host` platform and runs a scripted scenario whose log lines
are asserted by pytest. Everything runs inside the existing `checks` CI job through `script/test`; no workflow,
ruleset or required-check name changes. The fork's difference to upstream is enforced mechanically: a unit test
diffs every forked file against the `sprinkler` sources shipped in the installed ESPHome package and fails on any
change that is not inside a documented patch region.

## Context

### Stage plan (roadmap stage 6 split)
- **008 (this task)** — fork + queue patches + C++ unit tests + host scenario on the sim board. Top-level YAML schema
  is still the stock one (a list of controllers under the key `garden_zones:`).
- **012 — groups and lanes.** Python codegen of controllers from `garden_zones: {groups: [...], zones: [...]}`
  (`max_parallel: 1 | all | N` with static lane assignment, SPEC §4); shared pump per group; a `garden_zone:`
  `MULTI_CONF` entry per zone so `bed.yaml` can add itself (SPEC §5, "verify with a first test build that lists from
  different packages merge"). Preliminary finding for the pump question (verify in 012): stock `sprinkler` already
  coordinates pumps across controllers — `Sprinkler::add_controller()` fills `other_controllers_`, and
  `pump_in_use()` asks the other controllers before switching a shared pump off; so all lanes must be generated as
  controllers of one `garden_zones` block and registered with each other. Lane-aware queue (which lane a queued zone
  goes to) belongs here too.
- **013 — safety and soil.** Maximum valve on-time watchdog (principle 4; must exist before any real device uses the
  component), optional per-zone soil-moisture skip (any ESPHome `sensor`, threshold), with C++ tests.
- **014 — switch the device.** `bed.yaml` / `irrigation.yaml` move to `garden_zones` (1-bed greenhouse allowed),
  ESP32 compile of the device with the component (pinned + minimum), HA entity names and saved run durations kept,
  greenhouse page and poller keep working; prerequisites for the `gp_*` layer (stage 7: `gp_run_bed` → manual run
  without breaking the queue, `gp_queue_text` from the open queue API). Hardware check by the author.

### Upstream sources checked (tag 2026.9.1)
Files in `esphome/components/sprinkler/`: `__init__.py` (~1100 lines incl. schema), `automation.h`, `sprinkler.h`
(~650 lines), `sprinkler.cpp` (~1450 lines). Sources:
<https://github.com/esphome/esphome/tree/2026.9.1/esphome/components/sprinkler>, docs
<https://esphome.io/components/sprinkler/>, external components <https://esphome.io/components/external_components/>.
- **No per-file licence headers** upstream (`sprinkler.cpp` starts with `#include "automation.h"`). The licence is
  in ESPHome's top-level `LICENSE`: C++ runtime (`.c/.cpp/.h/.hpp/.tcc/.ino`) GPLv3, Python code MIT. So "keep the
  headers" means: add a fork header to each copied file (see Licence below); there is nothing to preserve.
- Python: `sprinkler_ns = cg.esphome_ns.namespace("sprinkler")`; `AUTO_LOAD = ["number", "switch"]`; no
  `MULTI_CONF`; `CONFIG_SCHEMA = cv.All(cv.ensure_list(SPRINKLER_CONTROLLER_SCHEMA), validate_sprinkler)`;
  15 actions registered as `sprinkler.<name>` (`set_divider`, `set_multiplier`, `queue_valve`, `set_repeat`,
  `set_valve_run_duration`, `start_from_queue`, `start_full_cycle`, `start_single_valve`, `clear_queued_valves`,
  `next_valve`, `previous_valve`, `pause`, `resume`, `resume_or_start_full_cycle`, `shutdown`).
- C++: `namespace esphome::sprinkler`; classes `SprinklerControllerNumber final`, `SprinklerControllerSwitch final`,
  `SprinklerValveOperator`, `SprinklerValveRunRequest`, `Sprinkler final : public Component`.
- Queue storage: `std::vector<SprinklerQueueItem> queued_valves_` (`{size_t valve_number; uint32_t run_duration;}`),
  **stored reversed**: `queue_valve()` inserts at `begin()`, the next item is `back()`. `queue_valve()` checks
  `is_a_valid_valve()` and `max_queue_size_`, allows duplicates. `run_duration == 0` means "use the valve's
  (adjusted) run duration when it starts".
- `load_next_valve_run_request_(first_valve)`: order of precedence is `next_req_` (explicit request) → queue (if
  `queue_enabled()`, pops `back()`, **no `valve_is_enabled_()` check**) → full cycle (if `auto_advance()`; the cycle
  path does skip disabled valves). It is called from `fsm_transition_from_valve_run_()` when a valve finishes.
- `start_single_valve()`: checks standby/multiplier, then `set_auto_advance(false)`, `set_queue_enable(false)`,
  `reset_cycle_states_()`, `repeat_count_ = 0`, `fsm_request_(valve, duration)`.
- `start_from_queue()`: sets `auto_advance` off and `queue_enable` on, then kicks the FSM.
- `pause()`: stores `paused_valve_` and `resume_duration_ = time_remaining_active_valve()`, then `shutdown(false)`
  (queue kept). `resume()`: `fsm_request_(paused_valve, resume_duration)` unless `valve_cycle_complete_()`, then
  `reset_resume()`. These are reused for the manual run (Decision 4).
- `valve_is_enabled_(n)`: `enable_switch->state`, or `true` when the valve has no enable switch.
- `Sprinkler::setup()`: `all_valves_off_(true); disable_loop();` — no preferences in the controller (only
  `SprinklerControllerNumber` uses them).

### Minimum supported version (2026.6.3) vs. pinned (2026.9.1)
Commits to `esphome/components/sprinkler/` after 2026.6.3
(<https://github.com/esphome/esphome/commits/2026.9.1/esphome/components/sprinkler>): #16967 "Mark configurable
classes as final" (2026-07-06), #18636 "Inline the trivial Sprinkler accessors" (2026-08-23), #18907 "Keep
conditional log string literals in flash on ESP8266" (2026-08-31, wraps ternary log strings in `LOG_STR_LITERAL()`).
`LOG_STR_LITERAL` already exists in `esphome/core/log.h` at 2026.6.3, `final` is plain C++, and the core APIs the
Python side uses (`register_action(..., synchronous=)` #14606, `TemplatableFn` #15545) predate 2026.6. **Expected:**
the 2026.9.1 copy validates and compiles on 2026.6.3 too. This task proves it with `esphome config` and a host
compile on both versions (checks below). If the minimum fails, apply the Gate in Decisions. Preferences API for the
controller (`global_preferences->make_preference<T>(key)`) must be confirmed on both versions by the host compile.

### Constraints from other in-flight work
Tasks 006 (PC emulator) and 007 run on other branches. 006 modifies heavily: `.github/workflows/ci.yml`,
`tests/test_config_matrix.py`, `tests/test_layout.py`, `tests/test_ci.py`, `hardware/sim.yaml` (header),
`garden-pilot.yaml`, `packages/core/*`, `CLAUDE.md`, `README*.md`, `docs/SPEC.md`. This task therefore:
- does **not** touch `ci.yml`, `test_config_matrix.py`, `test_ci.py`, `hardware/sim.yaml`, `garden-pilot.yaml`,
  `packages/`, `script/test`;
- touches shared files only minimally (see Files: `pyproject.toml` markers, three short SPEC lines, one README
  paragraph each, two CLAUDE.md table rows + one sentence); expect trivial merge conflicts there, resolve by keeping
  both sides;
- `tests/test_layout.py` / `tests/test_public_hygiene.py` only if an existing check globs all YAML / all files and
  trips over `tests/configs/` or the vendored `doctest.h` (then the smallest possible exclusion, stated in
  Implementation notes).

## Decisions (planner; author asleep — see Assumptions)
1. **Fork layout = upstream layout.** `components/garden_zones/` contains `__init__.py`, `automation.h`,
   `sprinkler.h`, `sprinkler.cpp` copied from tag 2026.9.1 with the **same file and class names** (`Sprinkler`,
   `SprinklerControllerSwitch`, …). Renames are limited to what coexistence needs: C++ `namespace
   esphome::garden_zones`, Python `garden_zones_ns = cg.esphome_ns.namespace("garden_zones")`, component key
   `garden_zones:`, action prefixes `garden_zones.<name>`, log `TAG = "garden_zones"`, user-facing strings that name
   the component (error messages; `docs_url` keeps pointing at the upstream sprinkler docs, with a comment). Keeping
   class and file names keeps the upstream diff tiny; different namespaces avoid ODR clashes when both components are
   in one build.
2. **Patch regions are marked in code.** Every changed or added block in a forked file is wrapped in
   `// GZ-PATCH-BEGIN(<id>)` … `// GZ-PATCH-END(<id>)` (Python: `# GZ-PATCH-BEGIN(<id>)` …). Renames from Decision 1
   are not marked; the diff test normalises them. Patch ids: `queue-api`, `queue-persist`, `queue-skip-disabled`,
   `manual-run` (plus `includes` if a new `#include "queue_ops.h"` needs its own region). `PATCHES.md` lists every id
   with: purpose, files and functions touched, behaviour change, upstream base (tag `2026.9.1` + the commit SHA the
   tag points to), and a "re-port notes" line. A unit test keeps code markers and `PATCHES.md` in sync.
3. **Open queue API** (`queue-api`). The upstream `std::vector<SprinklerQueueItem> queued_valves_` and its reversed
   order stay (smallest diff). New public C++ methods on `Sprinkler`:
   - `std::vector<size_t> queued_valves() const` — valve numbers in **run order** (index 0 runs next);
   - `bool is_valve_queued(size_t valve_number) const`;
   - `size_t remove_queued_valve(size_t valve_number)` — removes **every** entry of that valve, returns the count,
     logs it; does not touch the active valve.
   YAML: action `garden_zones.remove_queued_valve` (`id`, `valve_number`, templatable) and condition
   `garden_zones.is_valve_queued` (`id`, `valve_number`). Duplicates stay allowed (upstream behaviour).
4. **Manual run that keeps the queue** (`manual-run`). New method `run_valve(optional<size_t> valve_number,
   optional<uint32_t> run_duration)` and action `garden_zones.run_valve` (same fields as `start_single_valve`).
   Stock `start_single_valve` stays **unchanged** (upstream semantics). Behaviour:
   - standby / multiplier 0 / invalid valve / valve already active → same early returns as `start_single_valve`;
   - **controller idle:** the valve runs for its duration; `auto_advance` and `queue_enable` switches are **not
     changed**; when it finishes the controller returns to idle — it does **not** pull the queue or start a cycle;
   - **controller busy** (a queue or cycle valve is running, not paused): the running valve is paused with the stock
     `pause()` (remaining time kept), the manual valve runs, and when it finishes the paused valve is resumed with the
     stock `resume()`; after that the controller continues exactly as before (queue, then cycle);
   - **already paused by the user** before `run_valve`: the manual valve runs, the user's pause is left as it was (no
     automatic resume);
   - `shutdown` / `pause` / another `run_valve` / `start_*` during a manual run clears the "resume after manual run"
     flag (no surprise resume later);
   - the enable switch is **not** checked for a manual run (same as upstream `start_single_valve`; explicit user
     intent).
   The decision "what happens when a manual run ends" is a pure function in the helper (Decision 7) so it is unit
   tested; `load_next_valve_run_request_` / `fsm_transition_from_valve_run_` call it in one patch region.
5. **Persistence** (`queue-persist`). New controller option `persist_queue` (boolean, default `true`). The queue is
   saved to a preference after every mutation (`queue_valve`, pop, `remove_queued_valve`, `clear_queued_valves`) and
   restored in `setup()`; ESPHome batches flash writes (`flash_write_interval`), so this is not a flash write per
   change. Snapshot = fixed-size POD from the helper: format version, valve count of the controller, entry count, up
   to **32** entries (`uint8_t` valve, `uint32_t` run duration), run order. Restore rejects (logs, starts empty) on
   version mismatch, different valve count or an out-of-range valve. A queue longer than 32 saves the first 32 (next
   to run) and logs a warning. The preference key is a hash of the controller `id` plus a fixed salt (computed in
   Python, passed by a setter), so two controllers never share a slot. **A restored queue never starts by itself**;
   the active valve at reboot is not part of the queue and is not restored (all valves boot OFF).
6. **Skip disabled zones** (`queue-skip-disabled`). When the queue is popped, entries whose valve is disabled
   (`valve_is_enabled_() == false`) are **dropped** with an `INFO` log line, and the next enabled entry runs; if none
   is left, the controller behaves as if the queue were empty (falls through to the cycle branch as upstream does).
   Queuing a disabled zone is still accepted (it may be re-enabled before its turn).
7. **Pure helper `components/garden_zones/queue_ops.h`** (header-only, includes only the C++ standard library, no
   ESPHome headers, namespace `esphome::garden_zones::queue_ops`, must compile as C++17 and later). Templated on the
   queue item type (anything with `valve_number` and `run_duration`) and operating on upstream's reversed vector, so
   the forked code changes only at call sites:
   - `run_order(items)` → `std::vector<size_t>`; `contains(items, n)`; `remove_all(items, n)` → count;
   - `pop_next_enabled(items, is_enabled)` → `{std::optional item, dropped valve numbers}`;
   - `QueueSnapshot` POD + `make_snapshot(items, valve_count)` and `restore_snapshot(snapshot, valve_count)` →
     optional vector (validation per Decision 5);
   - `after_manual_run(bool resume_pending, bool user_paused)` → enum `{RESUME_PAUSED, GO_IDLE}` (Decision 4).
   It is GPLv3 like the rest of the directory (it ships with the fork).
8. **C++ unit tests:** [doctest](https://github.com/doctest/doctest) single header (MIT), vendored at
   `tests/cpp/third_party/doctest/doctest.h` with its `LICENSE.txt`, pinned to the newest release tag at
   implementation time (record tag + SHA-256 in `tests/cpp/third_party/doctest/VERSION`). Reason: one header, no CMake,
   no network at test time, builds in seconds with the devcontainer's `build-essential` (`g++`). SPEC §7 item 3 is
   updated from "GoogleTest or Catch2" to doctest. Test sources stay in `tests/cpp/` (outside the component dir, so
   ESPHome never copies a `main()` into firmware).
9. **`script/test-cpp`** (POSIX sh, like the other scripts): builds `tests/cpp/*.cpp` with `${CXX:-g++}
   -std=c++17 -Wall -Wextra -Werror -I components` (`-isystem` for the vendored header) into the git-ignored
   `.esphome/cpp-tests/` and runs the binary; non-zero exit on failure. No CMake. It is hooked into `script/test`
   **through pytest** (`tests/test_garden_zones.py::test_cpp_unit_tests`, marker `cpp`), so `script/test` and the CI
   `checks` job pick it up without editing either.
10. **Test configuration, not a device config:** `tests/configs/garden_zones_sim.yaml` — `esphome:` (name
    `garden-zones-sim`), `logger:` (`level: DEBUG` is allowed here because it is a test harness that never runs on a
    device; say so in the header; if a hygiene/convention test forbids it, use `INFO` and log scenario lines at
    `INFO`), `packages: {hardware: !include hardware/sim.yaml}`, `external_components: [{source: components,
    components: [garden_zones]}]`, one `garden_zones:` controller `gz_sim` with `main_switch`,
    `auto_advance_switch`, `queue_enable_switch`, 3 valves (`valve_switch_id: board_relay_1..3`, `enable_switch` each,
    run durations in **seconds** so the scenario is fast), and the scenario (Decision 11). Paths are repo-root
    relative: the file is only used **staged at the repo root** (pytest copies it with `hardware/`, `components/` into
    a staging dir — the same way `script/config` / `script/compile` stage a config); its header says so. No
    `!secret`, no `api:`, no network.
11. **Host scenario** (one boot, then a second boot for persistence). An `esphome: on_boot` (late priority) script
    drives the controller with `delay:`s and logs machine-readable lines prefixed `GZTEST ` (e.g.
    `GZTEST queue=0,1,2`, `GZTEST active=2`, `GZTEST switches auto=0 queue=1`); a 250 ms `interval` logs
    `GZTEST active=<n|none>` on change. Small lambdas only for reading state into log lines (principle 1). Steps:
    1. log `GZTEST restored=<run order>` (first boot: empty; second boot: `0,1`), then clear the queue;
    2. queue 0, 1, 2 (2 s each) → `queue=0,1,2`, `queued(1)=1`; remove 2 → `queue=0,1`; queue 2 → `queue=0,1,2`;
       disable valve 1;
    3. `start_from_queue`; after ~1 s `run_valve` 2 for 2 s → active 2, then 0 resumes with its remaining time, then
       1 is skipped (disabled, dropped), then 2 runs from the queue, then idle. Expected active sequence:
       `0, 2, 0, 2, none`; the switches logged before and after `run_valve` are identical;
    4. idle (queue now empty): re-enable valve 1, queue 0 then 1 (run order `0,1`), log switches, `run_valve` 2 →
       active `2`, then `none`; queue still `0,1` (not started); switches unchanged;
    5. log `GZTEST done` and stay idle with `0,1` queued (this is what the second boot must restore) until pytest
       stops the program.
    pytest compiles the config for `host`, runs the program twice with a timeout, collects stdout, asserts the
    sequence and the restored queue on the second boot. If host preferences do **not** persist between runs (check
    where the host platform stores them; run both boots with the same working dir/home), the persistence assertion is
    `xfail` with the reason recorded, and persistence moves to the hardware check of task 014.
12. **Coexistence:** the stock `sprinkler` is untouched and the author's `garden-pilot.yaml` does not load
    `garden_zones` (no `external_components:` there either). A config with both components in one build is not part
    of this task (it would need `packages/greenhouse/*` on the sim board; config-only check in 012 or 014).

**Gates.**
- If the 2026.9.1 copy fails `esphome config` or the host compile on **2026.6.3**: do not fork from an older tag;
  record the exact error, keep the pinned checks, mark the `minimum` parametrisations `xfail(strict=True)` with the
  error, and add a Follow-up (the author decides between raising the minimum and a compatibility shim). The reviewer
  escalates.
- If the host compiles + scenario add more than **6 minutes** to `script/test` in CI (job timeout is 20 min), keep
  `test_host_compile[pinned]` and the scenario, reduce the `minimum` side to `config` only, and report timings.

## Licence (SPEC §4)
- `components/garden_zones/LICENSE` — full GPLv3 text, verbatim from <https://www.gnu.org/licenses/gpl-3.0.txt>.
- Fork header at the top of each copied file (C++ `//`, Python `#`), exactly one block, e.g.:
  ```
  // garden_zones — modified copy of ESPHome esphome/components/sprinkler (tag 2026.9.1).
  // Original: Copyright (c) ESPHome contributors. Modifications: Copyright (c) GardenPilot contributors.
  // Licensed under the GNU General Public License v3, like ESPHome's C++ runtime; see LICENSE in this directory.
  // MODIFIED: see PATCHES.md (regions marked GZ-PATCH-BEGIN/END).
  ```
  `__init__.py` derives from ESPHome's **MIT** Python code: its header says "Derived from ESPHome's MIT-licensed
  Python code (Copyright (c) 2019 ESPHome); distributed here as part of a GPLv3 component", and
  `components/garden_zones/README.md` reproduces the MIT notice from ESPHome's `LICENSE` at the tag (copy the exact
  text). New files (`queue_ops.h`) carry a short GPLv3 header without the "modified copy" line.
- `README.md` / `README.ru.md`: one paragraph "Licence": the repository is MIT except `components/garden_zones/`,
  which is a modified copy of ESPHome code under GPLv3 (see its `LICENSE` / `README.md`).
- `tests/cpp/` test code is ours (MIT, repo licence); the test binary is never distributed.

## Files
Component (new):
- create: `components/garden_zones/__init__.py` — fork (Decisions 1–5: `persist_queue`, new actions/condition,
  preference key setter).
- create: `components/garden_zones/automation.h` — fork; new action/condition classes for `run_valve`,
  `remove_queued_valve`, `is_valve_queued` inside `GZ-PATCH` regions.
- create: `components/garden_zones/sprinkler.h`, `components/garden_zones/sprinkler.cpp` — fork; patches per
  Decisions 3–6.
- create: `components/garden_zones/queue_ops.h` — Decision 7.
- create: `components/garden_zones/LICENSE` — GPLv3 text.
- create: `components/garden_zones/PATCHES.md` — Decision 2 (base tag + SHA; one section per patch id; "how to
  re-port on an ESPHome bump": copy upstream, re-apply regions, run `uv run pytest tests/test_garden_zones.py`).
- create: `components/garden_zones/README.md` — what it is, status ("not used by the device yet; stage 6 tasks
  012–014"), YAML example (stock schema under `garden_zones:` + new actions/condition/option), differences to stock
  (the four patches, one line each), licence section incl. the ESPHome MIT notice.

Tests and scripts (new):
- create: `tests/cpp/test_queue_ops.cpp` — doctest cases (table below).
- create: `tests/cpp/minitest.h` — the minimal header-only harness that replaced the vendored doctest (Decision 8 as changed by the author: no downloads).
- create: `script/test-cpp` — Decision 9 (executable bit set).
- create: `tests/configs/garden_zones_sim.yaml` — Decisions 10, 11.
- create: `tests/test_garden_zones.py` — Python checks (table below).

Shared files (minimal edits):
- modify: `pyproject.toml` — register pytest markers `cpp` ("builds and runs the C++ unit tests with the host
  compiler") and `host` ("compiles a test config for the host platform and runs it"). Nothing else.
- modify: `docs/SPEC.md` — §3: one line "Forked into `components/garden_zones/` from tag 2026.9.1 (task 008)"; §7
  item 3: "Unit tests of the `garden_zones` core (doctest, `script/test-cpp`)"; §9 item 6: append one status sentence
  ("Task 008: fork + open/persistent queue, manual run keeps the queue, disabled zones skipped; groups/lanes 012,
  watchdog + soil 013, device switch 014."). No other SPEC edits.
- modify: `README.md`, `README.ru.md` — the Licence paragraph (above) and one line about `components/garden_zones/`
  (status: in development, not used by the device yet); in sync.
- modify: `CLAUDE.md` — layout table: one row `components/garden_zones/` ("fork of stock `sprinkler`, GPLv3; patches
  in `PATCHES.md`, marked `GZ-PATCH`"); commands table: one row `C++ unit tests | script/test-cpp`; test levels: one
  sentence that `cpp` (doctest) and `host` (host compile + scenario of `tests/configs/`) exist now for `garden_zones`.
  Nothing else.

About 20 paths, above the ~10-file budget: 4 are upstream copies with small patch regions, 4 are licence/vendor
files, 4 are one-paragraph doc edits. The real work is the `sprinkler.h/.cpp` patch regions, `queue_ops.h`, the two
test files and the scenario config. No split proposed (the scope was fixed by the author's stage plan); if the
implementer runs out of budget, the cut is "host scenario (`test_host_scenario`) → follow-up", keeping everything
else.

## Checks to write first
| Level | Test | Asserts |
|---|---|---|
| cpp | `tests/cpp/test_queue_ops.cpp` "run_order" | Upstream reversed storage (`insert(begin)` / next = `back()`) maps to run order; empty → empty; duplicates kept. |
| cpp | "contains / remove_all" | `contains` true/false; `remove_all` removes every duplicate, returns count, keeps relative order of the rest, 0 for an absent valve. |
| cpp | "pop_next_enabled" | Skips and reports disabled entries, returns the first enabled one and removes exactly those entries; all disabled → empty optional, queue empty, all reported; predicate called with valve numbers. |
| cpp | "snapshot round trip" | `make_snapshot` → `restore_snapshot` gives the same run order and durations (incl. `0` = default duration); `QueueSnapshot` is trivially copyable (`static_assert`). |
| cpp | "snapshot validation" | Restore rejects wrong format version, different valve count, valve index ≥ count; > 32 entries saves the first 32 in run order and flags truncation. |
| cpp | "after_manual_run" | `resume_pending=true, user_paused=false` → `RESUME_PAUSED`; `resume_pending=false` → `GO_IDLE`; `user_paused=true` → `GO_IDLE`. |
| cpp | `tests/test_garden_zones.py::test_cpp_unit_tests` | `sh script/test-cpp` exits 0 (wraps the cases above into pytest; marker `cpp`). |
| unit | `test_fork_files_present` | The 8 component files exist; `LICENSE` starts with the GPLv3 title and contains "Version 3, 29 June 2007"; no source with `main(` under `components/`. |
| unit | `test_fork_headers` | Each forked file (`__init__.py`, `automation.h`, `sprinkler.h`, `sprinkler.cpp`) begins with the fork header naming `esphome/components/sprinkler`, tag `2026.9.1`, GPL v3 and `PATCHES.md`; `__init__.py` also mentions MIT; `queue_ops.h` has a GPLv3 header. |
| unit | `test_renamed_for_coexistence` | No `namespace esphome::sprinkler`, no `namespace("sprinkler")`, no `"sprinkler.` action string, no `TAG = "sprinkler"` under `components/garden_zones/`; Python namespace `garden_zones`. |
| unit | `test_fork_diff_is_documented` | For each forked file: upstream = the same file from the **installed** `esphome` package (`esphome/components/sprinkler/`, located via `importlib`); fork normalised = fork header removed, `garden_zones` → `sprinkler` rename map applied. `difflib` opcodes between them: every non-equal opcode touches only fork lines inside `GZ-PATCH-BEGIN/END` regions (a pure deletion must sit at a region boundary). Fails with the offending line numbers. If the installed ESPHome version ≠ the base tag in `PATCHES.md`, the failure message says so (re-port needed). |
| unit | `test_patch_ids_documented` | The set of `GZ-PATCH-BEGIN(<id>)` ids in code == the ids with a section in `PATCHES.md`; every BEGIN has a matching END in the same file, no nesting; `PATCHES.md` names the base tag `2026.9.1` and a 40-hex commit SHA. |
| unit | `test_queue_ops_is_esphome_free` | `queue_ops.h` includes only `<...>` standard headers (no `"esphome/` include). |
| unit | `test_device_unchanged` | `garden-pilot.yaml` and everything under `packages/` and `hardware/` contain no `garden_zones` / `external_components`. |
| unit | `test_sim_test_config_shape` | `tests/configs/garden_zones_sim.yaml`: includes `hardware/sim.yaml`; `external_components` source `components` with `[garden_zones]`; one controller with 3 valves on `board_relay_1..3`; no `!secret`, no `api:`/`wifi:`/`ota:`; no `GPIO\d+`. |
| config | `test_sim_config[pinned]`, `test_sim_config[minimum]` | The staged test config passes `esphome config` (`script/_esphome`, `GP_ESPHOME` per param). |
| host | `test_host_compile[pinned]`, `test_host_compile[minimum]` | The staged config compiles for `host` (staging dir under the git-ignored `.esphome/`, fixed per version for incremental rebuilds). |
| host | `test_host_scenario` (pinned) | Runs the compiled program twice (timeout each, e.g. 40 s, or until `GZTEST done` + grace); asserts the `GZTEST` lines of Decision 11: queue list/contains/remove, active sequence `0, 2, 0, 2, none`, disabled valve 1 never active, switches unchanged by `run_valve`, idle manual run returns to `none` with the queue untouched, `restored=` empty on boot 1 and `0,1` on boot 2 (or `xfail` per Decision 11). |

Unit tests use only the standard library + PyYAML (as the existing ones); `test_fork_diff_is_documented` reads the
installed package files but runs no ESPHome tooling, so it stays `unit`.

## Acceptance criteria
- [ ] `sh script/test-cpp` → builds with `-Wall -Wextra -Werror` and all doctest cases pass.
- [x] `uv run pytest -m unit` → all pass (existing + new).
- [ ] `uv run pytest tests/test_garden_zones.py` → all pass on pinned; the `minimum` parametrisations pass (or are
      `xfail(strict=True)` under the Gate, with the error in Implementation notes).
- [x] `script/lint` → clean (yamllint covers `tests/configs/`); `esphome config OK: garden-pilot.yaml`.
- [ ] `script/test` → all pass; wall time before/after recorded in Implementation notes (Gate: ≤ +6 min in CI).
- [x] `git diff master --stat -- garden-pilot.yaml packages hardware .github script/test tests/test_config_matrix.py
      tests/test_ci.py` → empty (device, CI and 006-owned files untouched).
- [x] `GP_SECRETS=example sh script/config` → `esphome config OK: garden-pilot.yaml` (device config unchanged).
- [x] `git grep -n 'GZ-PATCH-BEGIN' -- components` → only ids listed in `PATCHES.md`; `PATCHES.md` has base tag and
      SHA.
- [ ] `git grep -nE 'namespace esphome::sprinkler|"sprinkler\.([^h]|h[^"])' -- components` → no output (the file name `sprinkler.h` is kept).
- [x] `components/garden_zones/LICENSE` is the GPLv3 text; `README.md` and `README.ru.md` contain the licence
      paragraph (in sync).
- [x] `docs/SPEC.md` (§3 line, §7 item 3, §9 item 6 status) and `CLAUDE.md` (two table rows, test-levels sentence)
      updated as listed and nothing else in them.
- [ ] CI on the PR green for `checks`, `compile (pinned)`, `compile (minimum)` (the latter two unchanged: they still
      build the device without `garden_zones`).
- [ ] Implementation notes state: nothing was run on a real device; host scenario results (both boots), whether host
      preferences persisted, timings, and the 2026.6.3 result.

Needs real hardware: nothing in this task (the component is not on any device). Relay behaviour, flash persistence on
ESP32 and HA entities are checked in task 014.

## Out of scope
- Groups, lanes, `max_parallel`, `garden_zone:` MULTI_CONF, shared pump wiring (012).
- Max on-time watchdog and soil-moisture skip (013). Consequence: `garden_zones` must not drive a real valve before
  013; this is fine because no device config loads it (principle 4 is met by not shipping it to a device yet).
- Switching `bed.yaml` / `irrigation.yaml` / the greenhouse page to `garden_zones`, ESP32 compile with the component,
  1-bed greenhouse, the `gp_*` layer (014, stage 7).
- A queue text sensor / HA entity for the queue (stage 7 `gp_queue_text`), watering history (backlog §9.1).
- Changing stock `start_single_valve` semantics, renaming upstream classes or files, refactoring upstream code.
- Lane-aware or deduplicating queue; dynamic lanes (backlog).
- `aioesphomeapi` scenarios and SDL (stage 11 / task 006); the host scenario here needs no API.
- Changing the canary workflow: a re-port signal comes for free from `test_fork_diff_is_documented` on Dependabot
  ESPHome bump PRs.

## Assumptions (made by the planner while the author was unavailable; confirm or overturn at review)
1. Keep upstream file and class names; rename only namespace, component key, action prefix and log tag.
2. Stock `start_single_valve` keeps upstream behaviour; the queue-friendly manual run is a new action `run_valve`.
3. Manual run while busy pauses the running zone and resumes it afterwards (reusing stock `pause()`/`resume()`);
   while idle it does not start the queue afterwards. Manual runs ignore the enable switch (like upstream).
4. Disabled zones are **dropped** from the queue when reached (not kept for later); queuing a disabled zone is allowed.
5. `remove_queued_valve` removes all duplicates of the zone; duplicates in the queue remain allowed.
6. Persistence is on by default (`persist_queue: true`), capped at 32 entries, invalidated by a change in the number
   of valves; the restored queue never auto-starts and the zone that was running at reboot is not restored.
7. doctest (vendored single header, MIT) instead of GoogleTest/Catch2; SPEC §7 updated accordingly.
8. The whole `components/garden_zones/` directory is distributed under GPLv3, with ESPHome's MIT notice reproduced
   for the Python part; no SPDX "or later" claim (ESPHome's licence says GPLv3).
9. The test config lives in `tests/configs/` and is not a user example; a user-facing example arrives with 012/014.
10. CI integration through pytest markers inside the existing `checks` job (no workflow change) is acceptable,
    including a host compile on both versions, within the timing Gate.
11. Numbering: 006–007 (emulator) and 009–011 (generic screens) are taken by in-flight branches; the stage continues as 012–014.

## Open questions
- None blocking. For the author at review: Assumptions 2–4 are product behaviour (what a RUN button does while the
  queue runs; whether a disabled zone should stay queued) and are easy to flip before 014 wires the screens.

## Implementation notes
Nothing was run on a real device. The implementer machine (Bazzite, no network allowed, no C++ compiler) could not
build C++: `script/test-cpp`, `test_host_compile` and `test_host_scenario` were written but **never executed**
(they skip when no compiler is found, so CI must show them running in the devcontainer). The C++ in
`queue_ops.h`, `sprinkler.h/.cpp`, `automation.h` and `tests/cpp/` was only reviewed by eye; the Python side was
verified with `esphome compile --only-generate` (codegen OK on pinned 2026.9.1).

Verified here: `uv run pytest` all green (291 passed, 4 skipped = the cpp/host tests), `script/lint` clean,
`esphome config` of `tests/configs/garden_zones_sim.yaml` passes on pinned 2026.9.1 **and** minimum 2026.6.3
(minimum was run from the uv cache, offline). `script/test` took ~11 s locally (no host compile), so the timing
Gate is unmeasured: the host compiles on both versions are the open cost. Host preferences persistence between
two runs is unverified (the test asserts it strictly; if it fails the author decides to mark it xfail per
Decision 11). Host preference code notes: `ESPHOME_PREFDIR` selects the directory, file is written on `sync()`
only, entry length is a `uint8_t` (the 164-byte snapshot fits); the scenario calls `global_preferences->sync()`
before `done`.

Deviations and decisions:
- **No doctest** (author's order: no network downloads): a minimal header-only harness `tests/cpp/minitest.h`
  (`TEST_CASE`, `CHECK`, `CHECK_FALSE`, `REQUIRE`). SPEC §7 item 3 says "a minimal header-only harness". An earlier
  doctest download was removed again; nothing from it is left in the tree.
- `components/garden_zones/LICENSE` is the GPLv3 text fetched from gnu.org before the no-network rule arrived
  (verbatim). The ESPHome MIT notice in the component README was copied from ESPHome's LICENSE at 2026.9.1.
- `test_cpp_unit_tests`, `host_build` and `test_host_scenario` call `pytest.skip` when no compiler (`CXX`/`g++`)
  exists; the devcontainer has build-essential so CI runs them.
- `#include "sprinkler.h"` in `sprinkler.cpp` matches the acceptance grep `"sprinkler\.`; the test uses
  `"sprinkler\.(?!h")`. File names are kept on purpose (Decision 1).
- Diff test: blank-line differences are ignored; a removal or replacement must touch/lie in a region. Regions do not
  nest, so the `save_queue_()` call inside `remove_queued_valve` is part of `queue-api` (noted in PATCHES.md).
- `queue-skip-disabled` is implemented as a pre-pass at the start of `load_next_valve_run_request_` using
  `pop_next_enabled` and pushing the first enabled entry back, so the upstream queue branch stays untouched.
- `run_valve` also validates the valve number (stock `start_single_valve` does not). A second `run_valve` during a
  manual run clears the resume flag; the paused valve then stays paused (user can `resume`). `next_valve` /
  `previous_valve` do not clear the manual flags (they only select a valve after a delay).
- Preference key = `fnv1_hash("garden_zones_queue:<controller id>")`.
- Scenario: durations 4 s / 2 s; the active-valve log is polled every 250 ms and the test ignores transient `none`
  between valves, checking `0,2,0,2` then a final `none`. The config logs at INFO (not DEBUG).
- `next_prev` and the stock `sprinkler` are untouched; `CODEOWNERS` in the forked `__init__.py` still names the
  upstream author (harmless outside the ESPHome tree).

## Review round 1 fixes
- Scenario assertions now follow the real boot order (`restored=` by prefix; boot 2 asserts `restored=0,1`,
  `boot_queue=0,1` after a 1.5 s idle period, and no `active=<n>` before `step=2`).
- `GP_REQUIRE_CXX=1` (both devcontainer configs) turns the compiler skips into failures; the scenario depends on a
  pinned build fixture; `test_devcontainers_require_a_compiler` guards the setting.
- `run_valve`: pauses only when ACTIVE/STARTING (never while STOPPING); a stale user pause is dropped when a running
  valve is paused (Assumption 15); resume with 0 s remaining is skipped. New scenario step 3b covers it; step 3
  waits with `wait_until` instead of a fixed delay.
- `script/test-cpp` needs `chmod +x` by the main session (the implementer's chmod was denied).

## Assumptions (implementer)
12. doctest replaced by a self-written harness (reason above); SPEC §7 wording updated.
13. Skipping (not failing) the C++-dependent tests when no compiler exists is acceptable.
15. `run_valve` while a valve is running and an older user pause is still stored: the running valve is paused and
    resumed after the manual run, the older stale pause is dropped (not resumed). Alternative: refuse `run_valve`
    while paused; easy to flip.
14. A restored queue entry keeps its stored duration; `0` still means "default duration at start".

## Follow-ups
- Run `script/test-cpp` and the host tests in the devcontainer/CI and fix any compile error in the C++ (not built
  by the implementer); check the minimum 2026.6.3 host compile (the `Condition::check` signature and
  `make_preference<T>` are the likely spots).
- Decide whether `next_valve` / `previous_valve` should also cancel a pending manual-run resume.
