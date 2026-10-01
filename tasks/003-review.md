# 003 — Review (round 1)

Verdict: CHANGES_REQUESTED

Scope reviewed: `git diff master...HEAD` and `git log master..HEAD` on `task/003-ci` (6 commits: task spec,
`test:`, `feat:`, `ci:` x2, `docs:`). The working tree was clean. No Docker daemon and no PlatformIO registry
access here, so I judged the workflows by reading them. The proof is the PR's GitHub Actions runs.

## Checks run
- `script/lint` → `esphome config OK: garden-pilot.yaml`, exit 0 (yamllint `--strict` over the repo, incl. `.github/`).
- `script/test` → `200 passed in 1.40s`.
- `uv run pytest -m unit tests/test_ci.py tests/test_devcontainer.py -q` → `42 passed`.
- `uv run pytest -m config -q` → `1 passed, 199 deselected`.
- `GP_ESPHOME=minimum GP_SECRETS=example script/config` → `esphome config OK: garden-pilot.yaml` (2026.6.3 via `uvx`).
- `GP_ESPHOME=2026.6.2 GP_SECRETS=example script/config` → `esphome config FAILED` on the `mipi_spi` `dimensions`
  (width 320 / height 240). This confirms that the release just below the floor fails.
- `GP_ESPHOME=bogus sh script/_esphome --resolve` → usage message on stderr, exit 2.
- `git grep -n "until Dependabot"` → hits only in `tasks/002-*.md`, `tasks/003-ci.md` and the test's own
  assertion. None in the Dockerfile or the docs.
- `git grep -n -i "exact minimum ESPHome" docs/SPEC.md` → no hits.
- `git grep -n "pull_request_target\|secrets\." .github/` → no hits.
- `git ls-files --stage script/compile script/_esphome` → both `100755`.
- `git status --porcelain` after the config runs → empty, and no `secrets.yaml` in the repo root.
- Line length > 120 in the workflows, dependabot, scripts and `tests/test_ci.py` → none.
- `git log master..HEAD` author/trailer audit → see Required 1.

## Acceptance criteria
Local:
- [x] `uv run pytest -m unit tests/test_ci.py tests/test_devcontainer.py` → all pass. Verified, 42 passed.
- [x] `script/lint` and `script/test` → green. Verified.
- [ ] `GP_SECRETS=example script/compile` → `Successfully compiled program.` Not verifiable here (no PlatformIO
  registry), and the implementer did not verify it either. The `compile (pinned)` CI job covers it. Leave it
  unticked until the CI log shows success.
- [x] Minimum: `GP_ESPHOME=minimum GP_SECRETS=example script/config` → OK. The per-version table is present.
  I re-ran 2026.6.2 myself: it fails.
- [x] `GP_ESPHOME=bogus sh script/_esphome --resolve` → non-zero exit with a usage message. Verified.
- [x] `until Dependabot` / `exact minimum ESPHome` greps. Verified; the remaining hits are task files only.
- [x] `pull_request_target` / `secrets.` grep in `.github/` → no hits. Verified.
- [x] Script modes `100755`. Verified (the box in the task file can be ticked).

CI, after-merge and author items: none can be verified from here. They stay with the main session and the human:
green `checks` / `compile (pinned)` / `compile (minimum)`, the versions in the logs, Docker accepting the runArgs,
the UID remap, run times, cache sizes, annotations, the canary issue path, Dependabot status, the ruleset, and the
Podman rebuild.

## Review notes (no action needed)
- **Scope:** matches the task. `.claude/settings.json` is untouched, as the orchestrator decided. The decision is
  documented in Implementation notes and Follow-ups. No firmware YAML changed.
- **Checks first:** `9317df9` contains only `tests/test_ci.py` and the `tests/test_devcontainer.py` edits. They come
  before `89439cf`, `3c0d94a`, `7a247a2` and `6659c59`. Every new test references files, keys or Dockerfile shapes
  that did not exist before, so each one would have failed on `master`. Every row of the "Checks to write first"
  table has a matching test. The only rename is `test_spec_versions_match_sources`, which is documented.
- **Cache volumes + ownership:**
  - The volumes are `local` with `type=none,o=bind` on `$RUNNER_TEMP/gp-cache` and `$RUNNER_TEMP/gp-platformio`,
    created by the runner user (uid 1001). Their names match `devcontainer.json`, and a test guards that.
  - `actions/cache` restores before `devcontainers/ci` runs, so the files land in the bind dirs owned by 1001.
  - `updateRemoteUserUID` (the CLI default; the action does not set `skipContainerUserIdUpdate`) remaps `vscode`
    to 1001 and chowns its home in the derived image. If Docker's copy-up copies an existing image dir into an
    empty volume, it carries the 1001 ownership.
  - So everything the container writes is owned by uid 1001, and the post-step `tar` of `actions/cache` can read
    it. The save runs only on job success, which is fine.
  - The GID may stay 1000 if the runner's `docker` GID is taken in the image. That is harmless, because the owner
    UID is enough for reading.
  - The first CI run is the proof.
- **Toolchain path:** ESPHome 2026.9.1 uses `platformdirs.user_cache_dir("esphome")` (`esphome/writer.py`), which
  is `~/.cache/esphome`, so the `gp-cache/esphome` cache path is correct. The minimum (2026.6.3 < 2026.7) goes
  through PlatformIO, which `gp-platformio` covers. If a path does not exist for one leg, actions/cache just skips
  it.
- **`uvx --isolated`:** it still uses `UV_CACHE_DIR` (`~/.cache/uv`, inside the cached `gp-cache/uv`). `--isolated`
  only ignores installed tools. However, `uv cache prune --ci` removes pre-built wheels before the save, so the
  `minimum` leg re-downloads ESPHome and its pure-Python dependencies on every run. That is intended by D3 / uv's
  CI guidance; the big win is the ESP-IDF / PlatformIO toolchain.
- **Canary:**
  - The dispatch input reaches the container only through the action's `env` input, never through a shell `run:`.
    `script/_esphome` validates it.
  - The version file is sanitised with `tr -cd`, and every value in `report` reaches `gh` through quoted env vars.
  - The open/comment/close logic follows D6. The label is created with `--force`, and `issues: write` covers both
    the labels and `gh issue list`. `GH_REPO` is set, so no checkout is needed.
  - The YAML block scalar strips the 10-space indent, so the issue body renders as a Markdown list.
  - Fork guard and `always() && != 'cancelled'` are correct. The restore-only cache uses the pinned key.
- **Security baseline:** top-level `permissions: {}`, per-job least privilege, every `uses:` SHA-pinned with
  `# vX.Y.Z`, `persist-credentials: false`, no `secrets.*`, no `pull_request_target`, and timeouts on every job.
- **Hygiene / language:** the diff has no real SSIDs, IPs, emails, local paths or AI-attribution text in tracked
  files. Everything is English except `README.ru.md`. `README.md` and `README.ru.md` are in sync (badge, CI
  section, base-image paragraph).
- **Docs:** CLAUDE.md (layout row, commands, test levels, Bumping ESPHome) and SPEC §6, §7, §9, §10, §10.1 and
  §11 are updated as the task requires.

## Findings
### Required
1. **Commit metadata on `task/003-ci` violates the CLAUDE.md "No AI attribution" rule.** Read with
   `git log --format='%an <%ae>%n%B' master..HEAD`.
   - All 6 commits (`087e0fb`..`6659c59`) have author and committer `Claude <noreply@anthropic.com>`. CLAUDE.md
     says the author is `MrKiirya`.
   - `087e0fb` (`docs: add task 003 spec (CI)`) also carries `Co-Authored-By: Claude …` and a `Claude-Session:`
     URL trailer. CLAUDE.md forbids both.
   - Why it blocks: on squash-merge, GitHub adds a `Co-authored-by: Claude <noreply@anthropic.com>` trailer for
     every commit author that differs from the merger. So the attribution would land on `master` even though the
     squash replaces the branch commits.
   - The local `git config user.name/user.email` in this checkout is `Claude` / `noreply@anthropic.com`, which
     will repeat the problem on future tasks.
   - Direction (main session + human; the branch is already pushed, so a rewrite needs the human's explicit OK):
     - either re-author the branch commits as `MrKiirya` and drop the trailers from `087e0fb`, then force-push the
       task branch;
     - or the human confirms they will squash-merge as `MrKiirya` and delete every `Co-authored-by` /
       `Claude-Session` line from the squash message.
   - In both cases, fix the local git identity before the next task.

### Suggestions
1. `.github/dependabot.yml:20-22`, uv `commit-message: {prefix: chore, include: scope}`:
   - ESPHome, pytest, pyyaml and yamllint all sit in `[dependency-groups] dev`. Dependabot treats them as
     development dependencies, so the scope will likely be `deps-dev`, giving `chore(deps-dev): bump esphome …`.
   - CLAUDE.md "Bumping ESPHome" says "Dependabot opens the `chore(deps):` PR".
   - Either reword CLAUDE.md to "`chore(deps…)`" after the first real Dependabot PR shows the actual title, or
     accept the difference. Both are valid Conventional Commits.
2. `tests/test_ci.py:255` `test_no_untrusted_interpolation_in_run` only inspects `run:` steps.
   - The `devcontainers/ci` `runCmd` is also a shell script that runs in the container. Extend the needle check
     to `with.runCmd`, so a future `${{ inputs.esphome }}` in a `runCmd` is caught too.
   - Today no `runCmd` contains any `${{ }}`.
3. `.github/workflows/ci.yml:50` (`checks` job): unlike `compile`, the job does not run `uv cache prune --ci`.
   - Its `gp-uv-v1` entry therefore keeps every downloaded wheel (ESPHome and all its dependencies).
   - Consider `runCmd: script/lint && script/test && uv cache prune --ci` for consistency and a smaller entry.
     Measure it with `gh cache list` first; this is optional.
4. Canary title: it always says "…with the latest ESPHome", even when a specific version is dispatched (for
   example the planned known-bad test). The body states the real version, so this is cosmetic. Optionally say
   "with ESPHome latest/<version>" in the first comment line.
5. `.github/workflows/canary.yml:58` runs `script/_esphome version` for `latest` with `--refresh-package
   esphome`, and `script/compile` repeats it twice (version echo and compile).
   - If a release lands during the run, the recorded version could differ from the compiled one. This is very
     unlikely.
   - It could be closed by resolving `latest` once and passing the exact version on. That is a follow-up, not
     needed now.
6. Markdown line lengths:
   - `README.md` / `README.ru.md` "Updating the base image or uv" line and the CLAUDE.md `compile` test-level line
     exceed the ~120-char wrap used elsewhere.
   - This is cosmetic; no linter enforces it.
7. Follow-up, not this task: once CI is green, tick the `100755` acceptance box in `tasks/003-ci.md`, and record run
   times and cache sizes as the task requires.
