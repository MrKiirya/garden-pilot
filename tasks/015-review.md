# 015 — Review (round 2)

Verdict: CHANGES_REQUESTED

## Checks run
- `script/lint` (host, worktree) → exit 0, `esphome config OK: garden-pilot.yaml`
- `uv run pytest -m unit -q` (host) → `486 passed, 24 deselected in 15.53s`
- `podman exec -w /workspaces/garden-pilot gp-sim-015 sh -c 'GP_REQUIRE_SIM_UI=1 uv run pytest -q tests/test_sim_ui.py -rs'`
  → `17 passed in 20.87s` (pinned ESPHome 2026.9.1). Afterwards only `sleep infinity` (PID 1) is live in the container,
  port 6053 is free, and the host `/tmp/.X11-unix` (bind-mounted into the container) has only the `X1` socket that
  was there before the run.
- Suggestion 6 (minimum version): `podman exec ... sh -c 'GP_ESPHOME=minimum script/sim-ui start'` →
  build OK (`INFO ESPHome 2026.6.3`, `[SUCCESS] Took 66.65 seconds`), then
  `sim-ui: timeout after 900 s waiting for 'setup() finished' (.esphome/sim-ui/sim.log)`, **exit 1**. See Required 1.
  - While `start` waited, the emulator was fully up: `xdotool search --onlyvisible --name .` found a 320x240 window,
    `ss -ltn` showed `0.0.0.0:6053` listening, and a manual `ImageGrab.grab(xdisplay=":0")` crop
    (`.esphome/shots/min_home_manual.png`, git-ignored) shows the screensaver (clock, `22C - soil 50%`, "Touch to wake")
    rendered correctly. So the UI works on 2026.6.3; only the ready detection fails.
  - `sim.log` held nothing after `INFO Running program from path ...` for the full 900 s. The program's
    `[I][app:117]: setup() finished successfully!` line appeared in the log only after `start` killed the session
    (the stdio buffer was flushed on exit). The wording matches; the problem is that on 2026.6.3 the program's stdout
    is block-buffered when it goes to a file.
  - `shot min_home` could not be run (no session). `script/sim-ui stop` → exit 0, `status` → `not running`, exit 1;
    no live processes, 6053 free, no new X socket, `state.json` removed. The timeout path cleans up correctly.

## Round 1 items
- Required 1 (`docs/SPEC.md` §9 stage 12): **resolved**. It now reads "Screenshots and taps under Xvfb exist
  (task 015, `script/sim-ui`, CI job `sim-ui`); remaining: reference-image comparison and `aioesphomeapi` scenarios."
  §7 item 6 got the same note.
- Suggestion 1 (tap range before session): **resolved**. `cmd_tap` validates against `(0, 0, WIDTH, HEIGHT)` first.
  New unit test `test_tap_validates_range_before_session` (`tap 320 0` → 2, `tap 10 10` → 1 without a session).
- Suggestion 2 (`pgrep -f` patterns): **resolved**. The host test reads the pids from `state.json` after `start` and
  asserts `not _group_has_live(sim_pgid)` and `not _alive(xvfb_pid)` (zombie-aware via `/proc/<pid>/stat`).
- Suggestion 3 (stale state leaks Xvfb): **resolved**. `cmd_start` calls `_stop_all(state)` and removes `state.json`
  on a stale state. Covered by `test_start_with_stale_state_cleans_up`.
- Suggestion 4 (`os.read` blocks past the deadline): **resolved**. `select.select` with the remaining time runs before
  each read. Covered by `test_start_xvfb_deadline_holds_when_xvfb_hangs` (fake `Xvfb` that sleeps, 1 s timeout, < 10 s).
- Suggestion 5 (`CLAUDE.md` stale roadmap line): **resolved**. It now reads "reference-image comparison of the
  `script/sim-ui` screenshots, `aioesphomeapi` integration scenarios".
- Suggestion 6 (ready line on 2026.6.3): **run, fails**. Promoted to Required 1 below.

## Acceptance criteria
- [x] Unit tests pass without X (host run above).
- [ ] `which Xvfb xdotool` in a rebuilt image: still not verified. The Dockerfile change is covered by a unit test;
      CI will show the rest.
- [x] start / shot home / tap / shot setup / stop on the pinned version: the host scenario passed in the container.
- [x] `sim-ctl` + shot: unchanged since round 1 (implementer's run, `temp35.png`).
- [x] Exit codes: `tap 320 0` → 2 now holds even without a session (unit test); `start` busy → 3 by code + unit test.
- [ ] SDL devcontainer config criterion: not verified (no SDL desktop session used in review).
- [x] Host test runs in the container and skips with the tool name on the host.
- [x] `script/lint` and unit tests green on the host.
- [x] Device / sim entry files, `packages/`, `hardware/` unchanged.
- [ ] CI `sim-ui` green: cannot be verified before push.
- [x] `docs/SPEC.md` §7/§9, `CLAUDE.md`, READMEs updated. But the new SPEC §7 item 5 wording "works on every supported
      ESPHome version" is false today (Required 1).
- [ ] Ready signal verified against 2026.9.1 **and 2026.6.3** (task, "Ready signal"): fails on 2026.6.3.

## Findings
### Required
1. `script/sim_ui.py:36,291-299` (`READY_TEXT` / `_wait_ready`): on the minimum ESPHome 2026.6.3, `script/sim-ui start`
   always times out (900 s, exit 1), although the emulator is up about 1 s after the build. The host program's stdout
   is block-buffered when redirected to `.esphome/sim-ui/sim.log`, so `setup() finished` only reaches the file when the
   process exits. The task asks to verify the ready signal on 2026.6.3, and `docs/SPEC.md` §7 item 5 now claims
   "works on every supported ESPHome version". CI builds only the pinned version, so it would not catch this.
   Direction (pick one; keeping the log line as an extra signal is fine):
   - treat the session as ready when the API port 6053 accepts a TCP connection (`port_busy()` already exists) and/or
     the 320x240 window is found (`find_window`). Both are version-independent and were true here within seconds; or
   - force line-buffered output for the program (e.g. run `script/sim` under `stdbuf -oL -eL`, which glibc stdio
     honours through the inherited `LD_PRELOAD`, or a pty).
   Add a unit check for the chosen signal (e.g. ready when the port opens while the log has no ready line), re-run
   `GP_ESPHOME=minimum script/sim-ui start` → `shot` → `stop`, and record the result in Implementation notes. The
   alternative is to leave the code as is, drop "works on every supported ESPHome version" from SPEC §7 and document
   the limitation. That contradicts the task's ready-signal requirement, so it is the human's call.

### Suggestions
- None new.

### Follow-ups (not blocking)
- Making `sim-ui` required later (already in the task's Follow-ups).
- Optionally also run the `sim-ui` CI job with `GP_ESPHOME=minimum` (matrix), so CI catches version-dependent
  regressions like Required 1.

This is review round 2 of 2: if Required 1 is not fixed as described, escalate to the human per `CLAUDE.md`.
