# 001 — Review (round 2)

Verdict: CHANGES_REQUESTED

## Checks run
- `git show HEAD` (fcc6daa, "fix: address task 001 review round 1") → 10 files: settings, `CLAUDE.md`, SPEC §8,
  one greenhouse comment, `script/config`, task + review files, three test files.
- `script/lint` → `esphome config OK: garden-pilot.yaml` (yamllint `--strict` silent).
- `script/test` → `125 passed in 3.70s`.
- `uv run --no-sync pytest -m unit -q` → `124 passed, 1 deselected` (the entry-file test now runs as `unit`).
- `script/config nope.yaml` → `config file not found: nope.yaml`, exit 1 (fails early, no temp dir left).
- `GP_SECRETS=example script/config` → `esphome config OK: garden-pilot.yaml`, exit 0; no `secrets.yaml` in the
  checkout afterwards; `git status --short` clean after all runs.
- `python3 -m json.tool .claude/settings.json` → valid JSON.
- `git log --all -S<address>` / `git grep` for the host address quoted in Required 1 → only HEAD's
  `tests/test_public_hygiene.py` (plus a coincidental substring of a wheel hash in `uv.lock`).
- `git branch -vv` → `task/001-scaffold` tracks `origin/task/001-scaffold` (the branch is pushed).
- Line-length scan (`awk 'length>120'`) of `CLAUDE.md`, SPEC, task and agent files.

## Round 1 required items
1. IP matcher misses sentence-final / zero-padded addresses — **resolved.** Lookahead is now `(?!\.?\d)`,
   leading zeros are normalized before `ip_address()`, octets > 255 skipped, CGNAT added, untracked
   non-ignored files are scanned, and `test_ip_matcher` / `test_local_path_matcher` prove the matcher fails on
   leaks and passes versions, loopback, public and `x.x` placeholders. (But see new Required 1 about the test
   data itself.)
2. `CLAUDE.md` does not cover the former Cursor rules — **resolved.** New "ESPHome YAML conventions" covers
   board, secrets files + `.vscode` mapping, remote packages via substitutions, sprinkler usage
   (`valve_switch_id`, `main_switch` / `auto_advance_switch`, never raw GPIO switches), adding an LVGL page,
   the touch overlay, small edits. Security baseline gains `logs:` levels, OTA identity check, fallback `ap:`
   trade-off; hygiene gains the "secret reached git history" procedure. Checked against `garden-pilot.yaml`
   and `packages/` (page order after `lvgl_base`, `touch_dot_overlay` no-op in `display_touch.yaml`): accurate.
3. ESPHome bump rule names `script/test` — **resolved.** Now `pyproject.toml` + `docs/SPEC.md` §6, `uv lock`,
   then `script/setup` / `script/lint` / `script/test`.

Round 1 suggestions claimed as done (1, 2, 3 partly, 4, 5, 7, 8 partly, 9) — verified present and working.
Not done and recorded in the task: 6 (colour forms), per-agent git restrictions, artifact links in `design/`.

## Acceptance criteria
- [x] `script/setup` installs ESPHome 2026.9.1 — pin unchanged since round 1 (`pyproject.toml`, `uv.lock`).
- [x] `script/lint` → yamllint clean, `esphome config OK` — verified by running it.
- [x] `script/test` → all checks pass — verified (125 passed).
- [x] `script/config` never creates `secrets.yaml` in the checkout with the example secrets — verified by running
  it with `GP_SECRETS=example` and checking the tree; the missing-config path also exits before `mktemp`.
- [x] No `.cursor/` / `design/mockup.html`; `CLAUDE.md` covers the former Cursor rules — now met (Round 1
  required 2).
- [x] `git ls-files --eol` shows no `i/crlf` — no line-ending changes in the fix commit.

## Findings
### Required
1. `tests/test_public_hygiene.py:68-69` — the two new `test_ip_matcher` cases use a concrete private address
   that is the author's real Home Assistant host (one of them even with the HA web port). `ALLOWED` exempts
   this file from the scan, so the hygiene check cannot catch it, but `CLAUDE.md` "Public repo hygiene"
   forbids IPs of the author's network in any committed file, and the branch is already pushed. Direction:
   replace both with a made-up address from a range nobody is likely to use at home (for example a random
   `10.x` or `172.16-31.x` host, or a non-default `192.168` subnet), keep a generic port; tell the human the
   current address is in the pushed branch history — the planned squash-merge keeps it out of `master`, and
   the remote task branch should be deleted (or the fix amended before any public review) rather than
   rewriting history unasked. Consider a one-line note next to `ALLOWED` that example data in this file must
   be fictional.

### Suggestions
1. `CLAUDE.md:126` and `CLAUDE.md:147` — the two edited paragraphs were not re-wrapped (137 and 181 columns),
   unlike the rest of the file (120). Re-wrap; also lines 33–34 are slightly over (pre-existing table rows,
   fine to leave).
2. `tests/test_secrets_example.py:6-7` — removing the `Path` import also removed the blank line between the
   stdlib and third-party import groups (`import re` / `import pytest`). Restore it.
3. `tests/conftest.py:42` — the `repo_root` fixture is now unused (its only user was the rewritten
   `test_real_secrets_file_is_not_tracked`). Remove it or use it.
4. `.claude/settings.json` deny list — `Bash(cat secrets.yaml*)` only blocks one spelling (`less`, `head`,
   `grep`, `cp`, `./secrets.yaml` still pass); as round 1 noted, these are speed bumps, not a guarantee.
   Worth a short comment in `CLAUDE.md` that the real protection is the agent rule plus `.gitignore`, so
   nobody relies on the deny list. Patterns otherwise look sensible: deny entries for trailing `--force` /
   `-f` / `--force-with-lease` and `+refspec` take precedence over the `git push origin task/*` allow.
5. `tests/test_public_hygiene.py` `LOCAL_PATH` — the new root-home alternative also matches any URL whose
   path starts with a `root` segment (this very review tripped it on the first draft); acceptable today, but
   if it false-positives, anchor the path alternatives to a start-of-token (`(?<![\w.:/])`).
