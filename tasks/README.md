# Tasks

Each unit of work is a task file written by the `planner` agent, implemented by `implementer`,
and checked by `reviewer`. Files are public — use generic examples only.

- Spec: `tasks/NNN-short-name.md` (NNN = zero-padded sequence: 001, 002, …)
- Review: `tasks/NNN-review.md` (overwritten on each review round; history is in git)
- Branch: `task/NNN-short-name` → PR → green CI → merge into `master`.

Lifecycle: `planned` → `in-progress` → `in-review` → `done` (or `blocked`). Update `Status` in the spec.

## Task spec template

```markdown
# NNN — Title

Status: planned
Roadmap: <stage from docs/SPEC.md §9>
Spec sections: <e.g. SPEC §3, §5>
Hardware check: <none | what must be verified on a real device>

## Goal
One paragraph: what changes for the user/developer when this is done.

## Context
Relevant facts, API references checked (with links), decisions already made.

## Files
- create: `path` — purpose
- modify: `path` — what changes

## Checks to write first
| Level | Test | Asserts |
|---|---|---|
| unit | `tests/test_x.py::test_y` | … |

## Acceptance criteria
- [ ] `<command>` → passes / expected output
- [ ] …

## Out of scope
- …

## Open questions
- …

<!-- Filled in by implementer -->
## Implementation notes
## Follow-ups
```

## Review template

```markdown
# NNN — Review (round N)

Verdict: APPROVE | CHANGES_REQUESTED

## Checks run
- `<command>` → <summary line>

## Acceptance criteria
- [x] … — verified by …
- [ ] … — not met: …

## Findings
### Required
1. `path:line` — problem — why — suggested direction.
### Suggestions
1. …
```
