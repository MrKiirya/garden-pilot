# 022 — CI speed: parallel pytest, aligned schedule clock, cached toolchain

Status: planned
Roadmap: developer tooling (supports every stage; SPEC §7 "Testing without hardware")
Spec sections: SPEC §7 (test levels), SPEC §6 (pinned / minimum ESPHome, unchanged)
Hardware check: none (CI and test harness only; no firmware, package or component change)

Branch: `task/022-ci-speed`, stacked on `task/021` (rebase onto `master` after 021 merges).

## Goal
The required CI job `checks` drops from ~25 min back to **about 12 min wall time** (hard limit 15 min), and a local
`script/test` gets correspondingly faster, **without removing any test, parametrization or scenario assertion**.
This is done by (1) running pytest in parallel with `pytest-xdist`, keeping every host build and the tests that
use it on one worker; (2) removing the random minute-boundary waits from the schedule host scenario by starting the
host program at a chosen second of the minute through `libfaketime` (offsets only grow, so the scenario still sees a
continuous clock); (3) caching the PlatformIO / ESPHome toolchain in `checks` like `compile` already does.
Per-test durations are measured **before and after** and recorded in this file.
Required check names (`checks`, `compile (pinned)`, `compile (minimum)`) and the ruleset stay unchanged.

## Context
- CI today (`.github/workflows/ci.yml`): `checks` runs `script/lint && script/test && uv cache prune --ci` in the
  devcontainer, `timeout-minutes: 40` (raised in 021), caches only `gp-cache/uv`. `compile` caches
  `gp-cache/uv`, `gp-cache/esphome` and `gp-platformio` with key
  `gp-toolchain-v1-<os>-<target>-<hash(pyproject.toml, uv.lock)>`. Ubuntu runners have 4 CPUs.
- `script/test` = `uv run --no-sync pytest "$@"`. `pytest-xdist` is **not** in `uv.lock` (checked); adding it to
  the `dev` dependency group is allowed.
- Slow tests reported by the 021 run (verify with the baseline measurement): gp scenario ~280 s, greenhouse 014
  scenario ~247 s, schedule scenario ~430 s (56 s to 429 s depending on minute boundaries), garden_zones safety
  ~4 min, groups scenario; plus the `esphome config` rows (`config` marker) for pinned and minimum.
- Host programs are built by module-scoped fixtures into **fixed** directories (incremental rebuilds):
  `tests/test_garden_zones.py` (`host_build` [params pinned/minimum], `host_build_pinned` via the module dict
  `_BUILT`, `groups_*`, `safety_*`, `overlap_program`, `pump_program`), `tests/test_greenhouse_zones.py`
  (`scenario_program`), `tests/test_gp_layer.py` (fixture at line ~337), `tests/test_schedule.py`
  (`schedule_program`, dir `.esphome/schedule-host/<version>`). `test_greenhouse_zones.py`, `test_gp_layer.py` and
  `test_schedule.py` import `_need_compiler`, `_resolve`, `_run_program` from `test_garden_zones.py`.
  Two workers must never build into the same fixed directory at the same time.
- Schedule scenario (`tests/configs/schedule_sim.yaml`, `time: host`, real clock): phase 1 and 4 set the slot start
  to `now + 90 s` truncated to the minute (30-90 s wait); phase 5 waits until `second == 20` (0-60 s), then
  `now + 100 s` truncated. The slot granularity is one minute, so these waits are random; the catch-up window is
  60 min, so a clock shifted forward by up to a few minutes in total is harmless. A **backward** jump between phases
  could move phase 2 before the slot's start minute and break "ran (catch-up)" — so offsets must never decrease.
- References checked:
  - pytest-xdist distribution modes (https://pytest-xdist.readthedocs.io/en/stable/distribution.html):
    `--dist loadgroup` keeps tests with the same `@pytest.mark.xdist_group(name=...)` on one worker; the mark also
    works through fixtures and `pytestmark`; unmarked tests are distributed like `load`. Fixtures are per worker
    (module fixtures run once per worker that needs them), hence the grouping.
  - libfaketime README (https://github.com/wolfcw/libfaketime): relative offsets as `FAKETIME="+N"` (seconds, no
    `s` suffix); `FAKETIME_DONT_FAKE_MONOTONIC=1` keeps the monotonic clock real (needed here: ESPHome `millis()` and
    the scheduler must not jump); `FAKETIME_NO_CACHE` not needed (offset is fixed per process). On Debian the
    package `libfaketime` installs `/usr/lib/x86_64-linux-gnu/faketime/libfaketime.so.1` — **implementer: verify
    the path in the trixie image** (`dpkg -L libfaketime`) and resolve it at runtime, not hard-coded per arch.
  - No ESPHome component schema is touched by this task, so no esphome.io check is needed; the scenario keeps using
    `time: host` unchanged. Minimum version (SPEC §6) is unaffected.
- Required-check implications: adding or renaming a required job needs the admin to re-apply
  `.github/rulesets/master.json`. This task therefore keeps all work inside the existing `checks` job.

## Decisions made by the planner (author to confirm)
1. **No job split in this task.** Everything stays in `checks` (no ruleset change, no admin action). If after the
   change `checks` is still above 12 min, the fallback is follow-up task: rename the current job to e.g. `tests`,
   add a `scenarios` matrix job, and make `checks` a tiny aggregator with `needs: [tests, scenarios]`, `if: always()`
   that fails unless every need succeeded — required names stay the same, so still no ruleset re-apply. Not done
   now because xdist + aligned clock is expected to be enough and is simpler.
2. **Parallelism by default in `script/test`:** `-n "${GP_PYTEST_WORKERS:-auto}" --dist loadgroup`;
   `GP_PYTEST_WORKERS=0` runs serially (xdist's `-n 0`), useful for debugging. Extra args still pass through, so
   `script/test -m unit` keeps working. (`uv run pytest -m unit` stays serial: no `-n` in `addopts`.)
3. **Grouping is central, not scattered:** `tests/conftest.py` gets one table `HOST_GROUPS` mapping each host-build
   fixture name to an xdist group (one group per fixed build directory, e.g. `gz-host-pinned`, `gz-host-minimum`,
   `gz-groups`, `gz-safety`, `gz-overlap`, `gz-pump`, `greenhouse-host`, `gp-host`, `schedule-host`) and a
   `pytest_collection_modifyitems` hook that adds `xdist_group` to every item using one of those fixtures (for the
   parametrized `host_build`, the group includes the version param). `host_build_pinned` and `host_build[pinned]`
   share the same directory, so they get the **same** group. Config rows that only use `tmp_path` stay ungrouped.
   If any `*_generated` / config fixture writes to a fixed shared directory, it is grouped too (implementer checks).
4. **Schedule clock alignment via libfaketime, harness side only:** `_run_program` gets an optional
   `env_extra` (or `faketime_offset`) argument; `tests/test_schedule.py` gets a pure helper
   `_align_offset(now_epoch: float, target_second: int, previous: int) -> int` returning the smallest offset
   `>= previous` with `(now_epoch + offset) % 60` in the target second. Phases 1 and 4 are launched so the slot start
   (unchanged `+90 s` rule in the config, or a smaller margin if the implementer keeps every "before the start"
   check meaningful — see the phase comments in the config) is ~30 s away instead of 30-90 s; phase 5 is launched
   just before `second == 20`. Phases 2 and 3 reuse the previous offset. Offsets never decrease. The YAML scenario
   and all its assertions stay as they are (only timing constants in the config may change, and only if justified in
   the Implementation notes).
5. **libfaketime in the image + strict in CI:** `.devcontainer/Dockerfile` installs `libfaketime`. Without it the
   schedule scenario still runs unaligned (slow, same assertions) — but `GP_REQUIRE_FAKETIME=1` (set in the CI
   `checks` env, same pattern as `GP_REQUIRE_SDL`) turns a missing library into a failure.
6. **Toolchain cache in `checks`:** same paths as `compile` (`gp-cache/uv`, `gp-cache/esphome`, `gp-platformio`)
   with its own key prefix `gp-checks-v1-<os>-<hash(pyproject.toml, uv.lock)>` so it does not fight with the
   compile caches. `ccache` / caching `.esphome/*-host` build dirs is **not** done here (checkout mtimes defeat
   PlatformIO's incremental build; ccache needs more image work) — follow-up only if builds still dominate.
7. **Scenario run durations are not shortened** (engine durations such as the >= 55 s cycle beds are part of the
   safety assertions); only the idle waits for minute boundaries are removed.
8. `checks` gets `--durations=25` (passed as `script/test --durations=25` in `runCmd`) so every CI log shows the
   slowest tests, and `timeout-minutes` goes back down to **25**.

## Files
- modify: `pyproject.toml` — add `pytest-xdist` (lower bound only, like the other dev deps) to the `dev` group.
- modify: `uv.lock` — `uv lock` (adds `pytest-xdist`, `execnet`).
- modify: `script/test` — `-n "${GP_PYTEST_WORKERS:-auto}" --dist loadgroup` before `"$@"`; comment explains
  `GP_PYTEST_WORKERS=0`. Warm-up if needed (decision below in "Risks").
- modify: `tests/conftest.py` — `HOST_GROUPS` table + `pytest_collection_modifyitems` adding `xdist_group`;
  `require_faketime_or_none()` helper (returns the library path, or `None`; fails when `GP_REQUIRE_FAKETIME=1`).
- modify: `tests/test_garden_zones.py` — `_run_program(..., env_extra=None)` (merged into the child env; default
  behaviour unchanged).
- modify: `tests/test_schedule.py` — `_align_offset` helper, phase launches with `LD_PRELOAD` + `FAKETIME="+N"` +
  `FAKETIME_DONT_FAKE_MONOTONIC=1`; assertions unchanged.
- modify (only if needed): `tests/configs/schedule_sim.yaml` — timing margins, with a comment.
- modify: `.devcontainer/Dockerfile` — install `libfaketime` (with a comment like the other packages).
- modify: `.github/workflows/ci.yml` — `checks`: toolchain cache, `script/test --durations=25`,
  `GP_REQUIRE_FAKETIME=1`, `timeout-minutes: 25`.
- modify: `tests/test_ci.py`, `tests/test_devcontainer.py` — new checks below.
- modify: `CLAUDE.md` (Commands / Test levels: `GP_PYTEST_WORKERS`, parallel default, faketime note) and
  `docs/SPEC.md` §7 (one sentence: host scenarios run in parallel groups; schedule scenario uses a shifted clock).

That is 12-13 files but most edits are a few lines; the coherent goal is one CI-speed change.

## Checks to write first
| Level | Test | Asserts |
|---|---|---|
| unit | `tests/test_ci.py::test_xdist_is_a_dev_dependency` | `pytest-xdist` is in `[dependency-groups].dev` of `pyproject.toml` and has a `[[package]]` entry in `uv.lock`. |
| unit | `tests/test_ci.py::test_script_test_runs_in_parallel` | `script/test` contains `--dist loadgroup` and `-n "${GP_PYTEST_WORKERS:-auto}"` and still ends with `"$@"`. |
| unit | `tests/test_ci.py::test_checks_job_settings` | `checks` runCmd still runs `script/lint` and `script/test` (with `--durations=`); env has `GP_REQUIRE_FAKETIME=1`, `GP_REQUIRE_SDL=1`, `GP_SKIP_SIM_UI=1`; `timeout-minutes <= 25`. |
| unit | `tests/test_ci.py::test_checks_cache_key` | `checks` caches `gp-cache/uv`, `gp-cache/esphome`, `gp-platformio`; key starts with `gp-checks-v` and hashes `pyproject.toml` and `uv.lock`; prefix differs from the compile key. |
| unit | existing `tests/test_ci.py::test_ruleset_required_checks_match_ci_jobs` / `test_required_check_names_are_stable` | unchanged and green: no required name changes. |
| unit | `tests/test_devcontainer.py::test_image_has_libfaketime` | the Dockerfile `apt-get install` list contains `libfaketime`. |
| unit | `tests/test_garden_zones.py::test_host_fixtures_are_grouped` (or in a new `tests/test_harness.py`) | every module-scoped fixture in `tests/test_*.py` that builds a host program (regex on `def \w+(_program|_build\w*)\(` under `@pytest.fixture(scope="module"...)`) has an entry in `conftest.HOST_GROUPS`; `host_build_pinned` and `host_build[pinned]` map to the same group; group names are unique per build directory. |
| unit | `tests/test_schedule.py::test_align_offset` | for several `now` values: result `>= previous`, `< previous + 60`, `(now + result) % 60` is in the target second; `previous` larger than the natural offset keeps monotonicity (wraps to the next minute). |
| unit | `tests/conftest.py` helper test, e.g. `tests/test_schedule.py::test_faketime_required_in_ci` | with `GP_REQUIRE_FAKETIME=1` and a fake missing path the helper calls `pytest.fail`; without the variable it returns `None` (monkeypatch). |
| host | existing `tests/test_schedule.py::test_schedule_host_scenario` | **all assertions unchanged**; now runs with the aligned clock when libfaketime is present. |
| host | all other existing `host` / `config` tests | unchanged, green under `-n auto --dist loadgroup` and under `GP_PYTEST_WORKERS=0`. |

## Acceptance criteria
- [ ] **Baseline recorded first** (before any change, on the 021 tip): `GP_SECRETS=example uv run pytest
      --durations=25 -p no:cacheprovider` (serial) — total wall time and the top-25 table pasted into
      Implementation notes, plus the CI `checks` duration of the 021 PR run.
- [ ] `uv run pytest -m unit` → green (new unit checks included).
- [ ] `script/lint` → green.
- [ ] `GP_SECRETS=example script/test --durations=25` (parallel, default) → green; wall time and top-25 table
      recorded in Implementation notes next to the baseline.
- [ ] `GP_PYTEST_WORKERS=0 GP_SECRETS=example script/test -m "host or config"` → green (serial still works).
- [ ] `uv run pytest --collect-only -q` → the same number of tests as the baseline (no test or parametrization
      lost); counts of both recorded.
- [ ] `git diff <base> -- tests/test_*.py` shows no removed or weakened `assert` in the scenario tests
      (`test_*host_scenario`, `test_safety_*`, `test_groups_*`); reviewer checks by reading the diff.
- [ ] Schedule scenario: with libfaketime present, its duration is recorded for 3 consecutive runs and the spread is
      small (no 56 s vs 429 s swing); without libfaketime (`LD_PRELOAD` path absent) it still passes.
- [ ] `GP_REQUIRE_FAKETIME=1` with the library missing → the schedule host test fails with a clear message.
- [ ] CI on the PR: `checks` green, duration **<= 15 min** (target ~12 min) recorded in Implementation notes;
      `compile (pinned)`, `compile (minimum)` green; `sim-ui` result noted (not required).
- [ ] `.github/rulesets/master.json` unchanged; required check names unchanged.
- [ ] `CLAUDE.md` and SPEC §7 mention `GP_PYTEST_WORKERS` / parallel default and the shifted schedule clock.
- [ ] No hardware criterion (nothing hardware-facing changes).

## Risks the implementer must handle (and note what was done)
- **First-use races:** the `minimum` ESPHome environment (see `script/_esphome`) and PlatformIO's native platform
  may be installed on first use by several workers at once. Check whether both are lock-safe (uv uses its own
  locks; PlatformIO's package manager uses lock files — verify). If not, warm them up serially in `script/test`
  before pytest (e.g. `sh script/_esphome --resolve` for both labels) or with a file lock in a session fixture.
- **CPU oversubscription:** 4 workers each starting a PlatformIO build with N parallel jobs. If builds get slower
  than serial, cap workers (e.g. `auto` -> 4) or set PlatformIO jobs; record the measurement.
- **Output in failures:** keep the existing tail-of-log assertion messages; xdist prints them per test as before.
- **Cross-module imports** (`from test_garden_zones import ...`): the module dict `_BUILT` is per worker; with the
  grouping this only means one build per group, as today.

## Out of scope
- Splitting `checks` into parallel jobs / aggregator (decision 1; follow-up if > 12 min after this task).
- `ccache` or caching host build directories across CI runs (decision 6).
- Shortening engine run durations in the gp / greenhouse / garden_zones scenarios (decision 7).
- De-duplicating `esphome config` between `script/lint` and the `config` pytest rows (measure and list as a
  follow-up if it is significant).
- Any change to components, packages, entry files or the ruleset.

## Open questions
- (Author) OK to make parallel the default for local `script/test` (decision 2), or prefer opt-in?
- (Author) If `checks` lands between 12 and 15 min, accept it, or schedule the aggregator split (decision 1) next?

<!-- Filled in by implementer -->
## Implementation notes
## Follow-ups
