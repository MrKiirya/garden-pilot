# 022 — Review (round 1)

Verdict: CHANGES_REQUESTED

Range: `git diff task/021-review-follow-ups HEAD` (4 commits, stacked on 021).

## Checks run
- `script/test -v --durations=25` (parallel, 8 workers, devcontainer, `GP_FAKETIME_LIB` = local 0.9.12 build,
  `GP_REQUIRE_FAKETIME=1`, `GP_REQUIRE_CXX=1`, `GP_SECRETS=example`) → `778 passed in 357.47s (0:05:57)`;
  slowest: schedule 317.6 s, gp 280.0 s, greenhouse 247.2 s, groups 104.1 s, safety 76.9 s, host_scenario 65.1 s.
- `GP_PYTEST_WORKERS=0 script/test -m unit -q` → `684 passed, 94 deselected in 23.19s`.
- `script/lint` → green (`esphome config OK: garden-pilot.yaml`).
- `GP_REQUIRE_FAKETIME=1` without the library, `require_faketime_or_none()` → `Failed: libfaketime not found
  (searched /usr/lib/*/faketime/libfaketime.so.1, /usr/lib/faketime/libfaketime.so.1); install the libfaketime
  package (GP_REQUIRE_FAKETIME=1)`.
- Minimal xdist experiment in the container (`/tmp`, removed afterwards): conftest `pytest_collection_modifyitems`
  adding `xdist_group` without `tryfirst` → the marked tests went to different workers and had no `@g1` suffix;
  with `@pytest.hookimpl(tryfirst=True)` → `test_a1@g1` and `test_a2@g1` both on `gw0`.

## Acceptance criteria
- [x] Baseline recorded — 021 numbers (763 passed, 22:22 serial) are in the Implementation notes; not re-measured.
- [x] `uv run pytest -m unit` green — 684 passed (serial, via `GP_PYTEST_WORKERS=0`).
- [x] `script/lint` green.
- [x] Parallel `script/test --durations=25` green — 778 passed in 5:57 (but see Required 1: the grouping is not
      in effect, so the run is not yet the run the task specifies).
- [x] Serial `-m "host or config"` — not re-run (21 min); taken from the notes. Serial mode is plain `-n 0`.
- [x] Same number of collected tests — 778 = 769 + 9 new. Checked by the diff: the only removed lines in `tests/`
      are the old `_run_program` signature / docstring / env line, one import line and the five `_run_program(...)`
      calls in the schedule scenario that now pass `env_extra`. No test function, parametrization or mark was removed.
- [x] No removed or weakened `assert` in the scenario tests — verified by reading
      `git diff task/021-review-follow-ups HEAD -- tests` (zero `-` lines containing `assert`).
- [x] Schedule scenario stable with libfaketime — 317.6 s in my run, matching the notes (317.2 / 317.5 / 318.0 s).
- [x] `GP_REQUIRE_FAKETIME=1` with the library missing fails with a clear message — verified (above).
- [ ] CI `checks` <= 15 min — pending (the run on the branch is in progress; the caller is checking it).
- [x] Ruleset and required check names unchanged — no diff under `.github/rulesets/`; `test_ci.py` ruleset checks
      green.
- [x] `CLAUDE.md` and SPEC §7 mention `GP_PYTEST_WORKERS`, the parallel default and the shifted clock.
- [x] No hardware criterion.

## Findings
### Required
1. `tests/conftest.py:86` — **the xdist grouping does nothing.** xdist's `WorkerInteractor.pytest_collection_modifyitems`
   (`xdist/remote.py`) reads the `xdist_group` marks and adds the `@group` suffix that `LoadGroupScheduling`
   distributes by. It is a plain hookimpl registered after the conftest, so pluggy (LIFO) calls it **before** the
   conftest hook adds the marks. The marks arrive too late and every test is distributed like `--dist load`.
   Evidence from the full run: no nodeid has an `@` suffix, and every fixed build directory was built on two
   workers at once: `test_host_compile[pinned]` gw2 vs `test_host_scenario` gw1 (`.esphome/gz-host/<pinned>`),
   `test_groups_host_compile` gw6 vs `test_groups_host_scenario` gw4, `test_safety_host_compile` gw3 vs
   `test_safety_host_scenario` gw6, `test_greenhouse_zones_host_compile` gw0 vs
   `test_greenhouse_zones_host_scenario` gw2. Locally this passes only because the build dirs are warm, so both
   builds are incremental no-ops. On a cold CI cache, two PlatformIO builds race in one directory: flaky failures or
   a corrupted `program`, and twice the CPU on a 4-CPU runner. The same applies to the `sim-ui` module group
   (`.esphome/sim-build` and port 6053) whenever `script/test` runs it with Xvfb present.
   Fix: decorate the hook with `@pytest.hookimpl(tryfirst=True)` (verified above to give `test_a1@g1` and
   `test_a2@g1` on one worker). Add a check that would have caught this: `tests/test_harness.py` only tests the pure
   `host_group()` mapping, not whether the marks take effect. For example, assert the hookimpl is `tryfirst`
   (`conftest.pytest_collection_modifyitems.pytest_impl["tryfirst"]` or the equivalent pluggy attribute). Or run a
   tiny pytester / subprocess session with `-n 2 --dist loadgroup -v` on a throwaway test file and assert the
   `@<group>` suffix and a single worker. Then re-run `script/test -v` and confirm that every host nodeid carries
   its group and that each group's tests share one `gwN`.

### Suggestions
1. `tests/test_schedule.py` (`_Clock`) / `tests/conftest.py:100` — `GP_REQUIRE_FAKETIME=1` checks only that the
   `.so` exists, not that it works. Local verification used a 0.9.12 source build; CI will use Debian trixie's
   `libfaketime` package (older upstream version). If that preload does not shift `CLOCK_REALTIME` for the host
   program, the scenario still passes, only slowly again, and nothing reports it. Consider one cheap assertion when
   the library is used: phase 1's first `rel ... sec=` / `start` value consistent with the aligned second (±a few s),
   or log the program's view of `now().second` at boot and compare it with the target. Also confirm the path with
   `dpkg -L libfaketime` in the first CI image build, as the notes say.
2. `tests/conftest.py` `HOST_GROUPS["host_build"] = "gz-host-{param}"` — the group is keyed by label, but the
   directory is keyed by the resolved version (`_host_dir(version)` = `.esphome/gz-host/<resolved>`). If the minimum
   is ever raised to equal the pin, `host_build[pinned]` and `host_build[minimum]` build into one directory from two
   groups (`_BUILT` is keyed by label too). This is unlikely and transient. A one-line comment, or keying the group by
   `_resolve(param)`, would close it.
3. Phase 5 alignment (`clock.env(44)`) lands about 1 s before `second == 20`. If the ~35 s of steps run a second or
   two longer on a loaded 4-CPU runner, the wait becomes ~59 s (slower, still correct). Starting at second 42-43
   would add headroom at a cost of 1-2 s. Check the CI duration of the schedule test against 317 s.
4. Cold-cache first-use race (PlatformIO native platform, the uvx `minimum` env) is left unverified, as the notes
   say. Once Required 1 is fixed, the first cold CI run is the real test. Keep the serial warm-up idea ready if it
   flakes.

### Semantics checked (no finding)
- libfaketime: `FAKETIME="+N"` is a relative offset, and `FAKETIME_DONT_FAKE_MONOTONIC=1` keeps
  `CLOCK_MONOTONIC` real. ESPHome host `millis()` / scheduler use `clock_gettime(CLOCK_MONOTONIC)`
  (`esphome/components/host/hal.cpp`), so engine durations are unaffected.
- Offsets: phases 2 and 3 reuse the phase 1 offset, so the clock is continuous across restarts. Phases 4 and 5 only
  move forward, by < 60 s each, which stays well inside the 60 min catch-up window, and "ran (catch-up)" / "stopped"
  semantics are unchanged. The alignment uses the test process clock just before `Popen`, which is correct for a
  relative offset. DST behaviour is unchanged: the shift is minutes, and the config and assertions are untouched.
- Phase 1/4 at second 22: `now + 90` at about second 25 truncates to the next minute, so the slot is about 35 s away,
  inside the original 30-90 s range. "Before the start" checks stay meaningful.
- Fallback: without the library, `env()` returns `None` and the env is unchanged. The serial no-library run is in
  the notes.
- `ci.yml` cache: same three paths as `compile`, mounted through the same bind volumes; key
  `gp-checks-v1-<os>-<hash(pyproject.toml, uv.lock)>` (the minimum version lives in `pyproject.toml`). The prefix
  differs from `gp-toolchain-v1`, and there are no `restore-keys`. The `sim-ui` job keeps `gp-uv-v1` and runs pytest
  serially (unchanged).
- Dockerfile: `libfaketime` is the right Debian package name; base `python:3.14-trixie`.
- Scope, hygiene, principles: no component, package, entry-file or ruleset change. No secrets, IPs or local paths.

## Decisions for the author (not blocking)
- Decision 2: parallel `script/test` by default (`GP_PYTEST_WORKERS=0` for serial). Reasonable. Note that `auto`
  means 8 workers on an 8-CPU desktop with three ~5 min scenarios plus PlatformIO builds.
- Decision 1: if `checks` lands between 12 and 15 min, accept it, or do the aggregator split next. The local wall
  time is now bound by the schedule scenario (~5.3 min) plus lint, so 12 min on CI looks plausible once builds are
  cached.
- `GP_FAKETIME_LIB` override (an implementer addition) and the `sim-ui` module group (not in the task text): both
  sensible.
- Decision 6 (no ccache / build-dir cache) and decision 7 (scenario durations untouched): agreed.
