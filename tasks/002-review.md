# 002 — Review (round 2)

Verdict: APPROVE

## Iteration 2

### Checks run
- `script/lint` → `esphome config OK: garden-pilot.yaml`, exit 0.
- `script/test` → `162 passed in 6.83s` (3 new: extensions volume in every config + Dockerfile, hygiene matcher).
- Rootless Podman 5.8.7, SELinux enforcing, `@devcontainers/cli` via npx, `PODMAN_USERNS=keep-id`, `DISPLAY` /
  `WAYLAND_DISPLAY` unset, fresh scratch copy of the working tree (example secrets only, nothing created in the
  repo): default config `devcontainer up` → `"outcome":"success"`. Inside: `id` → `uid=1000(vscode)`, groups
  include `dialout`; `findmnt` shows the named volume `garden-pilot-vscode-extensions` at
  `~vscode/.vscode-server/extensions`; the dir and its parent are `vscode:vscode`; creating, reading and removing a
  probe dir there as `vscode` works → **extensions volume mounts and is writable by `vscode`**. Not exercised: VS
  Code actually installing extensions into it and reusing them after a rebuild (the author's currently running
  container predates this change and has no such mount).
- Cleanup: removed my container, my `vsc-ws2-*` images, the `garden-pilot-vscode-extensions` volume (did not exist
  before my run) and my `garden-pilot-claude-<id>` volume. The shared `garden-pilot-cache` /
  `garden-pilot-platformio` volumes belong to the author's running VS Code devcontainer and were left untouched
  (my container mounted them; it only ran `script/setup`).

### Round 1 required items
1. False verification claims — **resolved.** `README.md:29-31`, `README.ru.md:29-31`, `CLAUDE.md:86-87`,
   `docs/SPEC.md:158` now say: verified on Linux with rootless Podman in VS Code (incl. USB flash and OTA);
   Windows not verified yet; Docker Engine and macOS untested. Consistent in all four places and matches the task
   file.
2. Open required manual items — **resolved.** The author recorded a manual run (SDL window seen, ESP-IDF cache
   survives a rebuild, Claude sign-in persists, USB flash via CH343 on `/dev/ttyACM0`, OTA and logs by IP) and
   explicit deferrals for Windows (DEFERRED by the author), Docker Engine and macOS (not tested). Per the
   coordinator these deferrals are accepted as satisfying those items. The `git ls-files --stage` item stays with
   the main session after commit (`core.fileMode=true`, file is `-rwxr-xr-x` on disk).

### Round 1 suggestions
- `script/sdl-smoke` failure grep tightened to real "no window" messages — resolved.
- Explicit "compiled program not found" check — resolved.
- Claude sign-in persistence — now verified by the author.
- Implementation notes / Status / leftover image — still open (see below).
- WSLg sentence in README — moot while Windows is deferred.

### New findings
#### Required
None.

#### Suggestions
1. `tasks/002-devcontainer.md` Implementation notes are stale: they still say the `garden-pilot.yaml` compile
   was not run and list compile, cache reuse, VS Code, Claude, USB and OTA as "Not verified … stay unticked",
   which now contradicts the ticked boxes and the author's section. Update them, and record the round-1 finding
   that ESP-IDF brings its own cmake and ninja comes from the venv (the reason the apt list has no
   `cmake`/`ninja-build`).
2. `tasks/002-devcontainer.md:3` — `Status: planned` → `in-review` / `done` as appropriate.
3. The task asks to record VS Code and Dev Containers versions, the `DISPLAY` value in a VS Code terminal, whether
   `garden-pilot.local` resolves in the container, and both compile durations plus `podman volume ls`; the author's
   section has none of these. Add them if known; not blocking.
4. The USB checkbox text names `/dev/ttyUSB0` but the verified board uses `/dev/ttyACM0` (CH343). It is explained
   in the author's section; optionally adjust the checkbox wording so it reads truthfully on its own.
5. `garden-pilot-vscode-extensions` has a fixed name, so it is shared by both configs and every checkout (fine,
   same image). Side effect: once `anthropic.claude-code` is installed via `dev.containers.defaultExtensions`, it
   stays in the volume after the user removes the setting. One sentence in the README "Optional: Claude Code"
   paragraph (both languages) pointing at the existing "remove the extensions volume" instruction would cover it.
6. The untagged 2.02 GB image `a1acc970f5fc` from the round-1 implementer run is still in the local Podman store;
   the human can remove it.

### Scope and hygiene (iteration 2 delta)
- New: extensions volume in both configs + Dockerfile mount point + `test_vscode_extensions_are_a_named_volume`,
  README USB section (ttyUSB vs ttyACM, `/dev/serial/by-id/`, unplugged-board caveat) and extensions-volume note,
  in sync in both languages. These are small, task-related additions driven by the manual run; acceptable.
- No author paths, IPs, SSIDs or entity ids in the changed files. The task file names the author's OS (Bazzite)
  and the bridge chip's public USB vendor id; neither is sensitive.

---

# Round 1 (kept for reference)

Verdict: CHANGES_REQUESTED

## Checks run
- `script/lint` → `esphome config OK: garden-pilot.yaml`, exit 0.
- `script/test` → `159 passed in 4.13s`.
- `git grep -n "stages 4–5"` → no hits. `devcontainer is planned` / `devcontainer в планах` → only in the task file
  (quoted as the text to replace), not in the READMEs. SPEC §9 numbered 1–11, item 5 = Device Builder path.
- Rootless Podman 5.8.7, SELinux enforcing, `@devcontainers/cli` via npx, `PODMAN_USERNS=keep-id`, `DISPLAY` /
  `WAYLAND_DISPLAY` unset, on a scratch copy of the working tree with `secrets.example.yaml` copied to
  `secrets.yaml` in the copy (no `secrets.yaml` created in the repo):
  - `devcontainer up` (default config) → `"outcome":"success"` in about 1.5 min, including `script/setup`.
  - `devcontainer exec … uv run esphome version` → `Version: 2026.9.1`.
  - `devcontainer exec … uv run esphome compile garden-pilot.yaml` → `Successfully compiled program.`
    (`real 3m55.9s`, cold cache, ESP-IDF 5.5.5 downloaded into `~vscode/.cache/esphome/idf`). No system `cmake`
    in the image: ESP-IDF uses its own `idf/tools/cmake/3.30.2`, and `ninja` comes from the venv (Python
    package). **So `cmake`/`ninja-build` are not needed in the Dockerfile. This is not a blocking finding.**
  - `podman image history` of the built image → only base-image layers, the uv `COPY multi … /bin/`, apt,
    `install -d`, `usermod`. No repo files, no secrets.
  - Not run: the second compile after `--remove-existing-container`, because the permission system blocked
    the command. ESP-IDF cache reuse across a rebuild is still **unverified**.
  - Cleanup: I removed my test container, the three `garden-pilot-*` volumes and both `vsc-ws-*` images.

## Acceptance criteria
Mechanical:
- [x] `uv run pytest -m unit tests/test_devcontainer.py tests/test_public_hygiene.py`: verified as part of
  `script/test` (159 passed).
- [x] `script/lint` and `script/test` → green on the host (above).
- [ ] `git ls-files --stage script/sdl-smoke` → `100755`: can't verify yet because the file is untracked. On
  disk it is `-rwxr-xr-x` and `core.fileMode=true`, so `git add` should record `100755`. The main session must
  confirm after committing. The box in the task file was ticked too early.
- [x] `stages 4–5` grep → no hits; SPEC §9 is 1–11; item 5 is the Device Builder path.
- [x] "devcontainer is planned" grep → no hits outside the task file itself.

Manual, required (Linux, rootless Podman):
- [x] Default config `devcontainer up` with no serial device and `DISPLAY` unset: verified by the reviewer
  (above).
- [x] `esphome version` = 2026.9.1: verified by the reviewer. Venv outside the workspace and host `.venv`
  untouched: reported by the implementer, not re-checked.
- [ ] `script/lint` / `script/test` inside the container: reported by the implementer (159 passed). Not
  re-run by the reviewer.
- [ ] Workspace files owned by the host user: reported by the implementer. Not re-checked.
- [ ] `esphome compile` in the container: **compile verified by the reviewer** (with example secrets, not
  real ones). Cache reuse after `--remove-existing-container` is not verified, and durations and `podman volume
  ls` are not recorded for a second run.
- [x] `podman image history`: clean, verified by the reviewer.
- [ ] SDL config window + exit 0: implementer ran it from the CLI but "a window was not looked at". The VS Code
  terminal run and its `DISPLAY` value are not recorded.
- [ ] Default config `script/sdl-smoke` exits non-zero with the message: reported by the implementer. The code
  path (`exit 2` when neither `DISPLAY` nor `WAYLAND_DISPLAY` is set) is correct by reading.
- [ ] VS Code "Reopen in Container" picker, extensions, local validator: not tested.
- [ ] Claude opt-in and sign-in persistence: not tested.
- [ ] Hardware: USB flash (`ttyUSB0`, `ttyACM0`): not tested.
- [ ] Hardware: OTA from the container, `.local` resolution: not tested.

Manual, author-verified / best-effort:
- [ ] Linux + Docker Engine: not tested.
- [ ] (required) Windows 11 + Docker Desktop (WSL2): not tested.
- [ ] macOS: not tested (optional, ships as untested).

## Findings
### Required
1. `README.md:29`, `README.ru.md:29`, `CLAUDE.md:86-87`, `docs/SPEC.md:158`: these lines claim things that were
   not verified. The READMEs say "Verified by the author: Linux (Docker Engine and rootless Podman …) and Windows
   11 (Docker Desktop + WSL2)" / "Проверено автором: …". CLAUDE.md and SPEC say "Verified on Linux and Windows
   (WSL2)". Windows has not been tested. Docker Engine has not been tested either. Only rootless Podman on Linux
   was exercised, and only partly, from the CLI. Task Decision 3 says the README states which platforms *were*
   verified. A false claim misleads contributors and hides the open required checks. Direction: state the real
   status in all four places, kept in sync in both READMEs. For example: "Verified: Linux + rootless Podman
   (CLI). Pending author verification: Linux + Docker Engine, Windows 11 + Docker Desktop (WSL2). macOS
   untested, reports welcome." Update the wording when the author finishes each check.
2. `tasks/002-devcontainer.md` acceptance criteria: several **required** manual items are still open. These are
   Windows 11 + Docker Desktop, Linux + Docker Engine, VS Code "Reopen in Container" with extensions and the
   validator, the SDL window seen by a person plus `DISPLAY` from a VS Code terminal, Claude opt-in and sign-in
   persistence, ESP-IDF cache reuse across a rebuild, USB flashing and OTA. Per the Definition of done, the task
   can't be `done` until they are checked, or until the human explicitly defers them. Direction: the author runs
   them, or records the deferral in the task file (move the items to Follow-ups, with a note). The mechanical
   `git ls-files --stage` box should be ticked only after the commit.

### Suggestions
1. `tasks/002-devcontainer.md:368-369` (Implementation notes): update with the reviewer's result. `esphome
   compile garden-pilot.yaml` succeeds in the container without system `cmake`/`ninja-build`, because ESP-IDF
   downloads its own cmake 3.30.2 and ninja comes from the venv. That justifies the apt list as it is.
2. `script/sdl-smoke:171`: the failure grep may give false failures. `XDG_RUNTIME_DIR` and `sdl.*(error|fail)`
   also match harmless warnings that Mesa/SDL/dbus often print in containers, for example "XDG_RUNTIME_DIR is
   invalid or not set" while X11 works fine. Consider matching only messages that really mean no window
   (`Authorization required`, `cannot open display`, `Couldn't open X11 display`, `No available video device`).
3. `script/sdl-smoke:152-153`: if the build output isn't found, `program` is empty and the script reports "the
   program exited early (no window?)", which is misleading. Add an explicit `[ -n "$program" ] || { echo
   "sdl-smoke: built program not found" >&2; exit 1; }`.
4. `script/sdl-smoke` robustness otherwise looks fine. It sends SIGTERM, waits 2 s, sends SIGKILL, then `wait`.
   `kill -0` correctly detects an early exit under both dash (container `/bin/sh`) and bash. I tested both. The
   executable bit is set on disk.
5. README "Windows" paragraph: the task expects `script/sdl-smoke` to open a window via WSLg using the
   **default** config (VS Code forwards the WSLg `DISPLAY`). One sentence saying so would help Windows users,
   because the SDL config is labelled "Linux host".
6. README "Optional: Claude Code": "sign-in persists across rebuilds" is not verified yet (acceptance item
   open). Keep it, but confirm it during the manual check.
7. `tasks/002-devcontainer.md:3`: `Status: planned` should be `in-review`.
8. Leftover from the implementer run: an untagged 2.02 GB image `a1acc970f5fc` (devcontainer metadata labels,
   created during the implementation run) is still in the local Podman store, although the notes say images
   were removed. The base image and `ghcr.io/astral-sh/uv:0.12.21` / `:latest` are also still there. I left them
   in place because I didn't create them. The human can remove them if they're not wanted as cache.

### Scope notes (no action)
- `.claude/settings.json` (`Bash(script/sdl-smoke)` allow rule) **is in scope**: the task's Files list names it
  explicitly.
- No `sdl-wslg` config was created, which is correct (no Windows verification). It is listed as a follow-up.
- Public hygiene: no author-specific paths, IPs, SSIDs or entity ids in `.devcontainer/`, `script/sdl-smoke`,
  tests, READMEs, CLAUDE.md or SPEC. `/home/vscode` is the allowed generic container home. The hygiene regex
  allow-list is exact (`vscodex`, `myvscode`, `alice` are still flagged and tested).
- Principles: no firmware YAML changed. The Dockerfile has no repo `COPY`, the build context is
  `.devcontainer/` only, ESPHome comes only from `uv.lock`, and there are no `features`. `runArgs` are
  engine-neutral, with env-driven serial defaults.
