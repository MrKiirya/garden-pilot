# 003 — Review (round 2)

Verdict: APPROVE

This round covers the whole `git diff master...HEAD` on `task/003-ci`, focusing on what changed since round 1:
`83ee302` (round 1 review), `7817405` (`ci: address review round 1 suggestions`) and `bfb13ca` (`ci: print the
resolved ESPHome version per compile leg; record CI results`). The working tree was clean. I did not change any
code.

Round 1 required item 1 (AI attribution and commit authorship) is **pending a decision by the human**. The options
are to re-author the six commits `087e0fb`..`6659c59` as MrKiirya and force-push, or to delete every
`Co-authored-by` / `Claude-Session` line at squash-merge. That choice belongs to the human, so this review does not
re-raise it as a code finding. The commits after `6659c59` are clean: author and committer are MrKiirya, there are
no trailers, and no new attribution text was added to tracked files. The only mentions are in this review file, and
they describe the finding. The local git identity is now MrKiirya.

## Checks run
- `script/lint` → `esphome config OK: garden-pilot.yaml`, exit 0.
- `script/test` → `202 passed in 1.39s`.
- `uv run pytest -m unit tests/test_ci.py tests/test_devcontainer.py -q` → `42 passed`.
- `GP_ESPHOME=pinned sh script/_esphome --resolve` → `2026.9.1`. `GP_ESPHOME=minimum …` → `2026.6.3`.
- `git grep -n "pull_request_target\|secrets\." .github/` → no hits.
- `git ls-files --stage script/compile script/_esphome` → both `100755`.
- `git log --format='%h %an %cn' 6659c59..HEAD` plus a body grep for `co-authored|claude` → MrKiirya only, no
  trailers.
- `git status --porcelain` after the runs → empty.
- `gh run list --branch task/003-ci` and `gh run view <id> --json headSha,jobs` (read-only):
  - Run `36932721007` on `6659c59`: all three jobs green.
  - Run `36933504950` on `7817405`: all three jobs green.
  - Run `36934069196` on `bfb13ca`: still in progress when this review was written.
  - The proxy blocked job logs and `gh cache list` (403), so I could not check the log contents or the cache
    sizes myself.

## Round 1 suggestions
1. Dependabot `chore(deps-dev)` vs CLAUDE.md `chore(deps):` → deferred to Follow-ups. OK.
2. `runCmd` included in the untrusted-interpolation check → done (`tests/test_ci.py:255-262`, through
   `uses_steps`, so it covers `ci.yml` and `canary.yml`).
3. `uv cache prune --ci` in `checks` → done (`.github/workflows/ci.yml:50`).
4. Canary title names the version → done (`.github/workflows/canary.yml:92`). `$VERSION` comes from a job env
   (`needs.canary.outputs.version`, sanitised with `tr -cd`), not from `${{ }}` inside the script.
5. Resolve `latest` once → deferred to Follow-ups. OK.
6. Markdown line lengths → not addressed. Cosmetic.
7. Tick the `100755` box and record times and caches → done.

## New step: `Show the ESPHome version` (`ci.yml:86-90`)
- `matrix.target` reaches the shell only through `env: GP_ESPHOME`, which is consistent with the interpolation rule.
- `script/_esphome --resolve` needs only `sh`/`sed`/`grep` and runs on the host after checkout. No uv is needed.
- It prints the version from `pyproject.toml`, which is the version the leg is meant to use. The proof of the
  version actually installed is still the `ESPHome x.y.z` line that `script/compile` prints in the container (via
  `esphome version`). The new step only makes the label easy to find.

## "PR CI results" section vs the workflows and runs
- Job durations match the run metadata:
  - Run 1: `checks` 1:23, pinned 3:13, minimum 6:17.
  - Run 2: `checks` 1:04 (the section says 1:03; this is rounding), pinned 3:37, minimum 4:23.
- "Warm, caches from run 1" is consistent with the cache keys:
  - Both keys depend only on `uv.lock` / `pyproject.toml`, which did not change, so run 2 restored the run 1
    entries.
  - Run 2 was a new push (`7817405`), not a `gh run rerun` as the acceptance text suggests. Because the keys are
    unchanged, it is equivalent.
- "Warm pinned compile is not faster" is consistent: the cached paths are `gp-cache/uv`, `gp-cache/esphome` and
  `gp-platformio`. `.esphome/example-build/.esphome/` is not cached.
- The three cache entries and their key prefixes (`gp-uv-v1`, `gp-toolchain-v1-…-pinned`, `…-minimum`) match the
  workflow keys. I could not check the sizes from here.
- The statement that the compile jobs "now print the resolved version" matches `bfb13ca`. That step had not run in
  CI yet at the time of writing (run 3 in progress).

## Acceptance criteria
Local:
- [x] Unit checks, `script/lint`, `script/test` → green. I re-ran them.
- [x] `pull_request_target` / `secrets.` grep → no hits. I re-ran it.
- [x] Script modes `100755`. I re-ran the check.
- [ ] `GP_SECRETS=example script/compile` → locally not verifiable here. It is covered by the green
  `compile (pinned)` job in runs 1 and 2.

CI:
- [x] Green on `checks`, `compile (pinned)`, `compile (minimum)` with exactly these names. Checked in the run
  metadata.
- [ ] Logs show `ESPHome 2026.9.1` / `2026.6.3`. Still unticked in the task file, which is correct until someone
  reads it from a log. The job summary of run 3 will show it.
- [x] Run times recorded. Checked against the run metadata (see the suggestion below about the split).
- [x] / not verified: Docker accepted the runArgs, no ownership errors, cache sizes ≤ ~6 GB, no deprecation
  annotations. These are plausible because every job is green, but I could not open the logs or the cache list
  through the proxy. I am relying on the main session's evidence.

After-merge and author items (canary dispatch, Dependabot, ruleset, Podman rebuild): open, as the task expects.

## Findings
### Required
None (round 1 item 1 is pending the human's decision, see above).

### Suggestions
1. `tasks/003-ci.md` "PR CI results":
   - The image build is given as "~16 s" in the table and "~15 s" in the bullet. Pick one.
   - The acceptance item asks for an image build / up + setup / compile split for each compile leg. Only
     `checks` and pinned (the compile itself is ~2 min) are split; the minimum leg is not. Add the split, or note
     that the step total is enough.
2. Once run `36934069196` finishes, read its job summaries (`ESPHome (pinned): 2026.9.1`,
   `ESPHome (minimum): 2026.6.3`) together with the in-container `ESPHome x.y.z` line from `script/compile`. Then
   tick the remaining "log shows" acceptance item.
3. The `gp-uv-v1` 45 MB figure was saved by run 1, before `uv cache prune --ci` was added to `checks`. Run 2 hit the
   same key, so it did not re-save. The prune takes effect only when `uv.lock` changes. Note this next to the size,
   or leave it as is.
4. `.github/workflows/canary.yml:93` label description still says "…against the latest ESPHome". It is fine for the
   scheduled run, but slightly off for a dispatched version. Cosmetic.
5. The canary issue is de-duplicated by label, so later failures with a newer version comment on an issue whose
   title names the first failing version. This is acceptable because the comments name the current version. Just
   be aware of it.
6. The commits after `6659c59` use a personal e-mail address as author. That is the author's call. GitHub's
   `…@users.noreply.github.com` address is an option if they prefer not to publish it in a public history.
