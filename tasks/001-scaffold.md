# 001 — Process scaffold (agent guide, agents, spec, pinned ESPHome, scripts, repo checks)

Status: in-review
Roadmap: SPEC §9 stage 1
Spec sections: SPEC §1–§10 (written by this task)
Hardware check: none — the firmware YAML is unchanged apart from comment wrapping and line endings

## Goal
A contributor (human or agent) can clone the repo, run `script/setup`, `script/lint` and `script/test`, and get
the same pinned ESPHome and the same checks as everyone else. Agents have a guide (`CLAUDE.md`), three roles
(planner / implementer / reviewer), task and review templates, and a spec to work from. The old Cursor rules
and the external context draft are folded in and removed.

## Context
- Process copied from the author's previous project (`MrKiirya/ha-energy-cost-stats`): `CLAUDE.md` structure,
  agents, `.claude/settings.json` allow/ask/deny scheme, `tasks/README.md` templates, git/PR rules.
  Adapted for ESPHome; Windows/PowerShell, HA, hassfest/HACS parts dropped.
- Decisions confirmed by the human (2026-10-01):
  1. Full agent process (planner → implementer → reviewer), with the light path for trivial changes.
  2. Devcontainer first (task 002) so the project also works from Windows; distrobox is not used.
  3. Everything in the repo is English, except `README.ru.md` (bilingual README).
  4. `.cursor/rules/*` → `CLAUDE.md`; `docs/GARDENPILOT_CONTEXT.md` (external draft, never committed) →
     `docs/SPEC.md`; originals removed.
  5. Design: claude.ai artifacts are the live master; the repo keeps a snapshot of what the firmware depends on
     (`design/README.md`, `design/tokens.json`, `design/icons/`). `design/mockup.html` (pre-design-system
     reference sheet) removed.
  6. ESPHome pinned exactly at **2026.9.1** (latest stable on 2026-10-01). Minimum supported version is decided
     in task 003 (floor 2026.2.3, sprinkler `millis()` fix esphome#14299). Weekly canary on stable only.
  7. License MIT. Commit author `MrKiirya`.
- ESPHome 2026.9 rejects an all-zeros API encryption key ("The all-zeros key is reserved…"), so the
  `secrets.example.yaml` placeholder is now base64 of the readable text `garden-pilot-example-key-dummy!!`.
- The committed YAML had CRLF line endings (written on Windows). `.gitattributes` forces LF; files were
  renormalized in a separate whitespace-only commit.

## Files
- create: `CLAUDE.md` — principles, layout, `packages:` order, ESPHome gotchas, environment, commands, test
  levels, security baseline, hygiene, definition of done, git rules, language, agent workflow.
- create: `.claude/agents/{planner,implementer,reviewer}.md`, `.claude/settings.json`.
- create: `tasks/README.md` (templates), `tasks/001-scaffold.md` (this file).
- create: `docs/SPEC.md`.
- create: `pyproject.toml`, `uv.lock`, `.python-version` (3.13).
- create: `script/setup`, `script/config`, `script/lint`, `script/test`, `.yamllint`.
- create: `tests/conftest.py`, `tests/test_secrets_example.py`, `tests/test_public_hygiene.py`,
  `tests/test_design_tokens.py`, `tests/test_esphome_config.py`.
- create: `README.md`, `README.ru.md`, `LICENSE`, `.gitattributes`.
- create: `design/README.md`, `design/tokens.json`, `design/icons/*`.
- modify: `.gitignore`; `secrets.example.yaml` (API key placeholder); three greenhouse YAML files (comments
  wrapped to 120 columns for yamllint).
- delete: `.cursor/rules/*`, `design/mockup.html`.

## Checks to write first
| Level | Test | Asserts |
|---|---|---|
| unit | `tests/test_secrets_example.py::test_every_secret_reference_has_an_example` | every `!secret x` has `x` in the template |
| unit | `tests/test_secrets_example.py::test_example_has_no_unused_keys` | no stale keys in the template |
| unit | `tests/test_secrets_example.py::test_example_values_are_obvious_placeholders` | zero-only values; API key decodes to the dummy text |
| unit | `tests/test_secrets_example.py::test_real_secrets_file_is_not_tracked` | `secrets.yaml` is not in git |
| unit | `tests/test_public_hygiene.py::test_no_private_ip_addresses` | no private IPv4 in tracked text files |
| unit | `tests/test_public_hygiene.py::test_no_local_absolute_paths` | no local absolute paths (patterns in the test file) |
| unit | `tests/test_design_tokens.py::test_page_uses_only_token_colors` | `page_home.yaml` colours ⊂ `design/tokens.json` |
| config | `tests/test_esphome_config.py::test_entry_file_is_a_package_list` | entry file has only `esphome/esp32/logger/packages` |
| config | `tests/test_esphome_config.py::test_esphome_config_passes_with_example_secrets` | `script/config` exits 0 |

## Acceptance criteria
- [x] `script/setup` installs ESPHome 2026.9.1 (`uv run esphome version` → `Version: 2026.9.1`).
- [x] `script/lint` → yamllint clean, `esphome config OK: garden-pilot.yaml`.
- [x] `script/test` → all checks pass.
- [x] `script/config` never creates `secrets.yaml` in the checkout when using the example secrets.
- [x] No `.cursor/` and no `design/mockup.html` in the tree; `CLAUDE.md` covers the former Cursor rules.
- [x] `git ls-files --eol` shows no `i/crlf` entries.

## Out of scope
- Devcontainer (task 002), CI / ruleset / Dependabot / canary (task 003).
- Any firmware behaviour change, the modular layout, `gp_*`, screens on the design system.

## Open questions
- None blocking. Product questions are collected in SPEC §10.

<!-- Filled in by implementer -->
## Implementation notes
- Implemented by the main session (bootstrap: the agent files did not exist before this task).
- `script/config` copies `garden-pilot.yaml`, `packages/` (and `hardware/`, `components/` once they exist)
  into a temp dir with `secrets.example.yaml` as `secrets.yaml`, so validation never touches real secrets.
- yamllint uses `truthy: check-keys: false` (ESPHome keys such as `on:` style triggers) and 120 columns.

## Follow-ups
- ESPHome 2026.9 warns that the OTA password wastes ~3.5 KB flash/RAM and recommends `ota: encryption` using
  the API key instead. Decide and change in a small task (affects `secrets.example.yaml` too).
- ESPHome warns `transparency_key` redaction heuristic will be removed in 2026.12.0 (upstream, informational).
