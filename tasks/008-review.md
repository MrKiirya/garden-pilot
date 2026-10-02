# 008 — Review (round 1)

Verdict: CHANGES_REQUESTED

Reviewed: working tree of `task/008-garden-zones-core` (untracked `components/`, `tests/cpp/`, `tests/configs/`,
`tests/test_garden_zones.py`, `script/test-cpp`; modified `CLAUDE.md`, `README*.md`, `docs/SPEC.md`, `pyproject.toml`).
The reviewer machine has no C++ compiler, the same as the implementer's. All C++ (helper, unit tests, forked patches,
host scenario) was reviewed by reading it, not by building it.

## Checks run
- `script/lint` → `esphome config OK: garden-pilot.yaml` (yamllint clean)
- `script/test -rs` → `291 passed, 4 skipped in 12.81s`. The 4 skips are `test_cpp_unit_tests`,
  `test_host_compile[pinned|minimum]` and `test_host_scenario` ("no C++ compiler").
- `uv run pytest tests/test_garden_zones.py -v` → the 8 unit tests and `test_sim_config[pinned|minimum]` pass.
- `GP_SECRETS=example sh script/config` → `esphome config OK: garden-pilot.yaml`
- Mutation check of `test_fork_diff_is_documented`, run on a scratch copy outside the repo: flipping
  `set_auto_advance(false)` and deleting an upstream `reset_resume()` line outside the regions were both reported.
  The test works.
- `diff` of the fork against the installed 2026.9.1 `sprinkler` sources: outside the marked regions there are only
  renames (namespace, TAG, `sprinkler::` qualifiers, include path) and the header.
- `diff` of upstream 2026.6.3 (uv cache) against 2026.9.1 `sprinkler`: only `final` and inlined accessors. The
  `Condition::check(const Ts &...)` signature, `TemplatableValue::optional_value`, `PreferencesMixin::make_preference<T>`
  and `esphome.helpers.fnv1_hash` exist in both versions, so compile errors on minimum are unlikely. This is not proven.
- `components/garden_zones/LICENSE` is byte-identical to `/usr/share/common-licenses/GPL-3`. The MIT notice in the
  component README matches ESPHome's `LICENSE` at 2026.9.1.

## Acceptance criteria
- [ ] `sh script/test-cpp` builds with `-Wall -Wextra -Werror` and passes. **Not verified** (no compiler). On reading,
      no warning-prone code was found (uint8/size_t comparisons are promoted from unsigned types, so GCC does not
      warn). Also, the script is not executable (see R4).
- [x] `uv run pytest -m unit`: all pass. Verified.
- [ ] `uv run pytest tests/test_garden_zones.py` passes on pinned and minimum. Config passes on both. Host compile and
      scenario **not verified**, and the scenario will fail as written (R1).
- [x] `script/lint` clean. Verified.
- [ ] `script/test` passes, with timings for the Gate. Passes only with skips; the host compile cost (Gate ≤ +6 min)
      is not measured.
- [x] Device, CI and 006-owned files untouched. `git diff master --stat -- …` is empty; `test_device_unchanged` passes.
- [x] `GP_SECRETS=example sh script/config` OK. Verified.
- [x] GZ-PATCH ids == `PATCHES.md` sections (`includes`, `queue-api`, `queue-persist`, `queue-skip-disabled`,
      `manual-run`). Base tag and a 40-hex SHA are present.
- [~] The `namespace esphome::sprinkler|"sprinkler\.` grep is not empty because of `#include "sprinkler.h"`. This is
      expected, because Decision 1 keeps the file names. The test uses `"sprinkler\.(?!h")`. Accepted; the criterion
      text should be corrected.
- [x] GPLv3 `LICENSE`, fork headers, README licence paragraph present in both languages.
- [x] SPEC and CLAUDE.md edits are limited to the listed lines.
- [ ] CI green. Pending.
- [~] Implementation notes say nothing ran on a device and give the 2026.6.3 config result. Host results, persistence
      and timings are missing because nothing could be run.

## Findings
### Required
1. **`tests/test_garden_zones.py:348` and `:378`: the host scenario asserts a boot log order that will not happen.**
   `on_boot` (priority -100) runs inside `App::setup()`. The scheduler is not ticked during setup
   (`core/application.cpp`: `scheduler_tick_` runs only while a component cannot proceed), so the 250 ms `interval`
   fires first during the 500 ms `delay`. The actual order is `restored=…`, `active=none`, `step=2`. So
   `first[first.index("step=2") - 1] == "restored="` fails on boot 1, and `second[0] == "active=none"` fails on boot 2.
   The two assertions also contradict each other. Also, `second[0]` does not check the property that matters, that a
   restored queue never starts by itself. Fix direction:
   - take the first `restored=` message by prefix;
   - on boot 2 assert `restored=0,1`;
   - on boot 2 assert that no `active=<n>` other than `none` appears before `step=3`.
2. **Skipped C++ tests are not enforced in CI (`tests/test_garden_zones.py:211, 276, 338, 341`).** Every C++
   dependent test calls `pytest.skip` when `shutil.which(CXX or g++)` is None. Nothing makes CI fail if the compiler
   is missing (for example after a base-image change). The required `checks` job would then go green with zero C++
   coverage, and that is exactly the failure mode this task cannot detect locally. In addition, `test_host_scenario`
   skips when the program file is absent instead of depending on the build, so with `-k`, a reorder or a stale build
   dir it silently skips too. Fix direction:
   - fail instead of skipping when an opt-in env var is set, for example `GP_REQUIRE_CXX=1` in
     `.devcontainer/devcontainer.json` `containerEnv` (`ci.yml` stays untouched). Guard it with a check in
     `tests/test_devcontainer.py`;
   - make the scenario use a pinned build fixture (or `host_build` filtered to pinned) instead of a file-exists skip.
3. **`components/garden_zones/sprinkler.cpp`, `Sprinkler::run_valve` (the `busy` / `this->pause()` lines): a stale
   user pause makes `run_valve` lose the running valve and resume a different one.** Upstream `pause()` is a no-op when
   `paused_valve_` is already set, and `start_from_queue` / `start_full_cycle` / `start_single_valve` never call
   `reset_resume()`. Sequence:
   1. The user pauses A.
   2. The user starts the queue, and B runs. `paused_valve_` is still A.
   3. `run_valve(C)` is called. `busy` is true, so `pause()` is called but returns early, and
      `manual_resume_pending_ = true`.
   4. `fsm_request_(C)` interrupts B. B was already popped from the queue and is not marked complete, so it is lost.
   5. C finishes, and the manual-run branch resumes A with A's old remaining time.

   This breaks Decision 4 ("the running valve is paused … resumed afterwards"). Fix direction:
   - set `manual_resume_pending_` only when the pause actually took effect (`paused_valve_` equals the valve that was
     active before the call);
   - or `reset_resume()` before `pause()` when a running valve exists, and document that choice;
   - add a check for it. A small pure helper case or a scenario step is enough.
4. **`script/test-cpp` is not executable** (mode `-rw-r--r--`; all other `script/*` are 100755). The task's Files list
   says "executable bit set", and CLAUDE.md documents the command as `script/test-cpp`. pytest calls it via `sh`, which
   hides the problem. Fix direction: `chmod +x` (main session, before `git add`), and optionally a unit test that every
   `script/*` file is executable.

### Suggestions
1. `sprinkler.cpp` `fsm_transition_from_valve_run_` (upstream code): manual-run valves are flagged `USER`, so a manual
   run during a full **cycle** marks that zone `valve_cycle_complete`. After the resume the cycle skips it. That
   contradicts "continues exactly as before" in Decision 4 (arguably fine, since the zone was just watered). Decide and
   document it in PATCHES.md/README, or cover it in 013/014.
2. If `run_valve` is called while the controller is `STOPPING` after a valve finished normally, `active_req_` still
   holds a request, so `busy` is true. The finished valve is "paused" with about 0 s remaining and resumed with a 0 s
   duration after the manual run, which pulses a relay briefly. Consider `busy = state_ == ACTIVE || state_ == STARTING`
   or skipping the resume when `resume_duration_ == 0`.
3. `tests/configs/garden_zones_sim.yaml` step 3: the `delay: 11s` leaves about 1 s of margin over the expected
   timeline (1 s stop + 1 s selection delay + 2 + 3 + 2 s + 1 s stop). Use a larger delay or
   `wait_until: not active` so CI load cannot make the test flaky.
4. Scenario coverage gaps: no "already paused by the user before `run_valve`" case (only `after_manual_run` is unit
   tested), no busy full-cycle case, no `shutdown` during a manual run.
5. `after_manual_run(pending, user_paused)` is called with `user_paused = paused && !pending`, so the second argument
   can never change the result. The helper adds little; consider passing the real "user paused" state, or simplifying.
6. Task file: update the Files list and Decision 8 (doctest files no longer exist; minitest replaces them) and the
   acceptance grep (`"sprinkler\.(?!h")`). `tests/cpp/minitest.h` includes an unused `<functional>`.
7. Record the CI timings of the host compile (pinned and minimum) against the 6-minute Gate when CI first runs.

### Verified OK (by reading)
- `queue_ops.h`: run order, `remove_all` (order kept, count), `pop_next_enabled`, snapshot (value-initialised,
  trivially copyable, 164 bytes, fits the host 255-byte limit) and restore validation are correct. `uint8_t`
  truncation for more than 255 valves is caught by the valve-count mismatch, so restore rejects it safely.
- `tests/cpp/test_queue_ops.cpp` covers every row of the task's cpp table. The cases would catch reversed order, a
  wrong pop end, lost durations and missing validation.
- Persistence: every `queued_valves_` mutation site saves. `save_queue_()` before `setup()` is a safe no-op (null
  backend). Restore happens in `setup()` only, and `SprinklerControllerSwitch::setup()` restores state without
  actions, so **a restored queue never auto-starts**. The active valve is not restored.
- `queue-skip-disabled` pre-pass: drops only from the head, pushes back the first enabled entry, saves, and is skipped
  during a manual run.
- Licence handling (GPLv3 LICENSE verbatim, fork headers, MIT notice, README paragraphs in both languages) and public
  hygiene (no paths, IPs or secrets) are fine. The device config loads neither `garden_zones` nor
  `external_components`.

## Not verified (needs CI / devcontainer)
- C++ unit tests, host compile on 2026.9.1 and 2026.6.3, host scenario (both boots), host preference persistence,
  Gate timings.

---

# 008 — Review (round 2)

Verdict: APPROVE

## Checks run
- `script/lint` → `esphome config OK: garden-pilot.yaml`
- `UV_OFFLINE=1 script/test -rs` → `294 passed, 4 skipped in 9.47s`. The 4 skips are the cpp and host tests: this
  machine has no compiler and `GP_REQUIRE_CXX` is not set here.

## Round 1 required items
1. Scenario boot order: **resolved.**
   - `restored=` is now matched by prefix.
   - Boot 2 asserts `restored=0,1`, then `boot_queue=0,1` after a 1.5 s idle period.
   - Boot 2 asserts that no `active=<n>` other than `none` appears before `step=2`, which is a real "never auto-starts"
     check.
2. Skips enforced: **resolved.**
   - `_need_compiler()` fails under `GP_REQUIRE_CXX=1`, and both devcontainer configs set it in `containerEnv`.
   - `test_devcontainers_require_a_compiler` guards that setting.
   - The scenario now depends on the `host_build_pinned` fixture instead of skipping when the program file is absent.
3. Stale pause in `run_valve`: **resolved.**
   - `busy` now requires `ACTIVE` or `STARTING`, which also covers round-1 suggestion 2: no pause while `STOPPING`.
   - A stale pause is dropped with `reset_resume()` before `pause()` (Assumption 15).
   - A resume with 0 s remaining is skipped.
   - New scenario step 3b covers it: expected active sequence `0,1,2,1`, the stale pause is not resumed. I traced the
     FSM by hand for this step and the expected sequence holds.
   - Step 3 now uses `wait_until` instead of a fixed delay (round-1 suggestion 3).
4. `script/test-cpp` executable bit: **still open, not a blocker.** The file is still mode 644; pytest runs it through
   `sh`. The author should run `chmod +x script/test-cpp` before `git add` (git records the mode).

## Remaining notes (not blocking)
- Still not built anywhere: C++ unit tests, host compile on 2026.9.1 and 2026.6.3, the scenario on both boots, host
  persistence, and the 6-minute timing Gate. The first CI run of `checks` is the real verification; with
  `GP_REQUIRE_CXX=1` it can no longer go green by skipping.
- Round-1 suggestions 1 (a manual run marks the zone cycle-complete) and 4 (no case for a pause by the user before
  `run_valve`, a busy full cycle, or `shutdown` during a manual run) carry over to 013/014.
