# 006 — Review (round 1)

Verdict: CHANGES_REQUESTED

Scope: working tree on `task/006-pc-emulator` (19 modified files plus the new `garden-pilot-sim.yaml`,
`packages/core/{api,ota,time_host}.yaml`, `packages/display_sdl.yaml`, `script/sim`, `tasks/006-pc-emulator.md`).
I ignored the untracked planning files `tasks/007`, `009`, `010` and `011`.

## Checks run
- `script/lint` → yamllint clean, `esphome config OK: garden-pilot.yaml` (rc 0).
- `script/test` (reviewer host, no `sdl2-config`) → `288 passed, 3 skipped`. The 3 skips are `sim_full`,
  `sim_no_touch_debug` and `test_esphome_config_passes_for_the_sim_entry_file`, each with the reason
  "sdl2-config not found: the PC emulator config needs SDL2 dev files (libsdl2-dev) even for `esphome config`".
- `GP_REQUIRE_SDL=1 uv run pytest -k "sim_full or sim_no_touch_debug or passes_for_the_sim"` → `3 failed`, so
  the require path works. `sim_api_only` passes without SDL and is never skipped.
- Device config compared with master. I extracted master with `git archive` into the scratch dir and copied the
  branch `garden-pilot.yaml`, `packages` and `hardware` there. Both used `secrets.example.yaml` and were rendered with
  `uv run esphome config` (pinned 2026.9.1). I dropped `INFO`/`WARNING` lines and the `substitutions:` block, then ran
  `diff` → **no differences at all** (1382 lines each). The `api`/`ota`/`wifi` order is preserved, and this time
  there is not even the `long_press_*` order noise.
- Minimum ESPHome (2026.6.3, `UV_OFFLINE=1`, cached): the branch `garden-pilot.yaml` → "Configuration is valid". A
  scratch copy of the `sim_api_only` shape (host + `core_api` + `core_time_host` + irrigation + 3 beds) → valid.
- `esphome config` of a sim copy with the secret renamed → "Secret '…' not defined". This confirms the failure mode
  Decision 7 describes for a real `secrets.yaml` that lacks the key.
- Host compile (`uv run esphome compile garden-pilot-sim.yaml`) was **not run by the reviewer**. This host has no
  SDL2 dev files and no PlatformIO `native` platform, and downloads were not allowed. The implementer's build artifact
  `.esphome/sim-build/.esphome/build/garden-pilot-sim/.pioenvs/garden-pilot-sim/program` exists, and so does
  `.esphome/sim-prefs/garden-pilot-sim.prefs`. CI's `compile (pinned|minimum)` will be the independent proof.
- `grep -rn '!secret' packages hardware` → nothing.
- `grep -nE 'GPIO[0-9]+|web_server' garden-pilot-sim.yaml packages/display_sdl.yaml packages/core/*` → nothing.
- `git grep -nE '[Ss]tages? [0-9]+' -- ':!tasks/'` → `CLAUDE.md:26` "7-9", `README.md:117` "7",
  `README.ru.md:117` "этап 7", `docs/SPEC.md` 80 "7" / 204, 205 "12" / 238 "9" / 241 "4" / 270 "9",
  `garden-pilot.yaml:45,47` "8"/"9", `bed.yaml:18` "7", `bed_soil.yaml:2` "7". All of them use the new numbers.
  SPEC §9 has 12 items: 6 = "PC emulator (host + SDL)" (both parts, default-OFF auto drift), 12 = "Screenshot checks
  in CI".
- Hygiene: I grepped the diff and the new files for `/home/`, `/var/mnt`, the user name, IPv4 literals other than
  `127.0.0.1` / `192.168.x.x`, `.local` and mail addresses → nothing. `git check-ignore -v .esphome/spike/xauth` →
  `.gitignore:7:.esphome/` (ignored), and `git ls-files .esphome` is empty.

## Acceptance criteria
- [x] Spike a–h recorded for both versions. Verified by reading Implementation notes. The d and g findings are
      reflected in the config: `reboot_timeout: 0s`, and clock polling with no lambdas.
- [x] `uv run pytest -m unit` → all pass. Verified as part of `script/test` above.
- [x] `script/lint` → clean. Verified above.
- [~] `script/test` with `GP_REQUIRE_SDL=1`, 10 variants, none skipped. Not reproducible here (no SDL2). Verified that
      the 10 variants exist and that the require flag turns the skips into failures. CI `checks` sets it.
- [x] `GP_ESPHOME=minimum` config. The device file and the sim shape without SDL are verified by the reviewer. The full
      sim file on minimum needs SDL, so I am trusting the implementer and CI for it.
- [~] Sim compile on pinned and minimum, with cold/warm times. I did not reproduce it (see above). The warm time is
      recorded (46 s; 9 s incremental), the cold CI time is not. CI on the PR will show it.
- [x] Normalized device `esphome config` diff master vs. branch → empty. Verified independently above.
- [x] `!secret` / `GPIO` / `web_server` greps → no output. Verified.
- [x] SPEC §9 has 12 stages, and every "stage N" outside `tasks/` uses the new numbers. Verified.
- [ ] CI green on the PR, and the ruleset file unchanged. The ruleset is untouched in the diff. `tests/test_ci.py` is
      green locally and the check names are unchanged. CI is pending (no PR yet).
- [x] `docs/SPEC.md`, `CLAUDE.md`, both READMEs updated and in sync. The one exception is Required 1.
- [ ] PC without HA, PC with HA, and the device OTA. These are author checks, open as expected.
- [x] The implementer states which PC and device items it did not verify. The "Not verified" list is present.

## Findings
### Required
1. **Docs: the "real `secrets.yaml` without `sim_api_encryption_key`" failure is not documented (Decision 7).**
   Decision 7 says that `script/config` / `script/compile` work for the sim file with `GP_SECRETS=example`. It also
   says that with a real `secrets.yaml` lacking the key they fail with "secret not defined", and that this is
   documented. Today nothing in `README.md`, `README.ru.md`, `CLAUDE.md` or the `garden-pilot-sim.yaml` header says
   it. Only `script/sim` (line 6) says it always uses the example secrets. Anyone whose `secrets.yaml` predates this
   change will hit `Secret 'sim_api_encryption_key' not defined` the first time they run
   `script/config garden-pilot-sim.yaml` or `script/compile garden-pilot-sim.yaml`. **Fix direction:** add one sentence
   to the README "Run on a PC" section (EN + RU in sync), to the `garden-pilot-sim.yaml` header, and optionally to the
   CLAUDE.md Commands row. The sentence: to validate or compile the sim by hand, use `GP_SECRETS=example`; with a real
   `secrets.yaml` it fails unless that file also has `sim_api_encryption_key` (copy the public dummy, never a device
   key).

### Suggestions
1. **Delete the X auth cookie copy `.esphome/spike/xauth`**, along with the rest of `.esphome/spike*`. It is git-ignored
   (`.gitignore:7`) and cannot be committed by accident with the current ignore rules, but it is a live credential for
   the author's X session and has no reason to exist. The author should remove it by hand (the reviewer does not
   delete files).
2. `docs/SPEC.md:188-190` (§7 items 1–2) still say the matrix variants are "built from the real entry file", that "the
   sim board (config only)" exists, and that compile is "for ESP32". These are now partly stale: there are sim-entry
   rows, the sim board runs, and the CI jobs also build the host binary. A half-sentence each would align them with
   item 4.
3. `tests/test_secrets_example.py`: for `sim_api_encryption_key`, the placeholder test only checks 32 bytes. The device
   key is pinned to its readable text (`EXAMPLE_API_KEY_TEXT`), and the sim key could get the same treatment:
   `b"garden-pilot-sim-public-dummy!!!"`, as documented in `secrets.example.yaml`. That would keep "obviously fake"
   enforced if someone pastes a real key there.
4. `.devcontainer/sdl/devcontainer.json`: publishing `127.0.0.1:6053` makes the container fail to start if host port
   6053 is already taken, for example by a second SDL container or another host-platform ESPHome program. Consider one
   README line: "if Rebuild fails with 'address already in use', set `GP_SIM_API_PUBLISH` to another host port, e.g.
   `127.0.0.1:16053`".
5. `tasks/006-pc-emulator.md` Status: per the lifecycle in `tasks/README.md` this should be `in-review` rather than
   "implemented (author checks pending)".
6. The cold CI compile time for the host build is not measured (Decision 10 asks for cold and warm). Read it from the
   first PR run of `compile (pinned)` / `compile (minimum)` and note it in Implementation notes.

### Follow-ups (not blocking)
- Already listed by the implementer: neutral time id instead of `ha_time`, sim build in the weekly canary, and `xvfb`
  in the SDL image for click tests.

### Checked and fine
- Principles. Secrets only as entry-file substitutions: the sim file's only `!secret` is `sim_api_encryption_key`, and
  a test enforces it. `packages/core/*` are display-independent and covered by the existing test, including untracked
  files. Sim relays stay `internal: true` + `ALWAYS_OFF`, and the added `logger.log` actions need no lambdas. The
  device `packages:` order is `hardware → core_api → core_ota → core_network → core_time`, with the rest unchanged.
- `display_sdl.yaml` has the same ids and scripts as `display_touch.yaml`. It uses no pins and no
  `headless`/`snapshot_key`/`window_options`, and its 320×240 matches `design/tokens.json` `screen-w`/`screen-h`.
- CI keeps `checks`, `compile (pinned)` and `compile (minimum)` with one devcontainer step each. `GP_REQUIRE_SDL=1`
  is in `checks`. The shared `.devcontainer/Dockerfile` (used by the CI default config) installs `libsdl2-dev`, so the
  SDL rows will not fail in CI. The ruleset test is unchanged and green.
- `script/sim` is executable POSIX sh with the display guard. It stages only `secrets.example.yaml` and uses the same
  copy list as `script/compile`, which a test enforces. It also sets `ESPHOME_PREFDIR` (absolute) and
  `SDL_RENDER_DRIVER=software`, and execs `script/_esphome run`.
- The new tests would fail without the change: core split, shared display ids, sim entry shape, beds match device,
  sim substitutions resolve, publish arg, sim script, CI sim compile, sim key distinct, and the device key order.

## Iteration 2

Verdict: APPROVE

### Checks run
- `script/lint` → yamllint clean, `esphome config OK: garden-pilot.yaml`.
- `script/test -rs` (reviewer host, no `sdl2-config`) → `290 passed, 3 skipped`. The 3 skips are the same SDL-only
  rows, each with the stated `sdl2-config` reason. The count rose from 288 because the placeholder test now covers the
  sim key.
- `garden-pilot.yaml`, `packages/` and `hardware/`: I compared them with my round-1 snapshot using `cmp`, file by file.
  Nothing changed, so the round-1 result still stands: the device `esphome config` is identical to master.
- `git grep -nE '[Ss]tages? [0-9]+' -- ':!tasks/'` → the same 12 hits, all using the new numbers.
- Hygiene grep of the diff (author paths, user name, IPv4 literals other than loopback) → nothing.
- `.esphome/spike/xauth` → gone.

### Round-1 items
- Required 1 (undocumented "secret not defined" failure for a real `secrets.yaml`) → **resolved**. The note is in
  the `garden-pilot-sim.yaml` header (lines 4–5), in `README.md` and `README.ru.md` ("Checking the sim config by hand",
  in sync), and in the CLAUDE.md Commands row "Validate config by hand".
- Suggestion 1 (xauth cookie) → resolved by the author.
- Suggestion 2 (SPEC §7 items 1–2) → resolved. They now cover the sim matrix rows, `GP_REQUIRE_SDL` and the host
  compile in the CI jobs. Item 1 still says "variants built from the real entry file", which is acceptable.
- Suggestion 3 (pin the sim key text) → resolved. `EXAMPLE_SIM_KEY_TEXT` is asserted in
  `test_example_values_are_obvious_placeholders`.
- Suggestion 4 (port already in use) → addressed with a README line in both languages ("stop that program first").
  It does not mention the alternative of setting `GP_SIM_API_PUBLISH` to another host port; that is fine as is.
- Suggestion 5 (Status) → `in-review`.
- Suggestion 6 (cold CI compile time) → still open by nature. Read it from the first PR run.

### Remaining before merge (not reviewer items)
- CI green on the PR for `checks`, `compile (pinned)` and `compile (minimum)`. These are also the independent proof
  of the host compile on both versions, which the reviewer could not run here.
- Author checks: PC without HA, the optional PC with HA, and the device OTA with the split network package.
