# Four-Layer Documentation Architecture

Use this reference when a project needs a reusable documentation system or when
existing docs are confused.

## 1. Master / Status Layer

Purpose: help a new human or AI know where the project is now, what to read
first, and which systems are authoritative.

Typical files:

- `README.md`
- `AGENTS.md`, `CLAUDE.md`, or AI entrypoint files
- `docs/current_status.md`
- `docs/workroom/CURRENT_STATUS.md`
- `docs/project_brief.md`
- `docs/current/PROBLEM_REGISTER.md` or an external problem/feedback tracker link, when unresolved observations need a durable intake path
- `DOCS_MAP.md` only if no existing master can carry the map

Rules:

- Keep it concise.
- Link to handbooks instead of copying them.
- Record current source-of-truth boundaries.
- Do not store full task histories here.
- Keep a large problem register out of default startup; route to it only when the current task needs unresolved-feedback context.
- A problem register records unresolved observations and their validation state; it does not authorize implementation.

## 2. Handbook Layer

Purpose: durable knowledge about how systems work and how contributors should
operate.

Typical files:

- architecture docs
- API contracts
- database and migration rules
- model-routing rules
- git/change governance
- frontend routing rules
- operational runbooks

Rules:

- Handbook content should remain valid across many tasks.
- One topic should have one primary handbook location.
- If the same rule appears in multiple places, keep the full rule in the
  handbook and link from other places.

## 3. Task Layer

Purpose: define and track a specific unit of work.

Typical systems:

- WCP / workctl
- GitHub Issues
- Jira, Linear, Kiro Tasks
- `TASKS.md` or `docs/tasks/` only when no external task system exists

Rules:

- Do not keep multiple active task sources.
- If tasks are externalized, repo task files become templates, required mirrors,
  or historical records.
- Preserve historical task IDs semantically. Do not reassign old files by count.

## 4. Archive Layer

Purpose: preserve evidence, history, and old context without letting it define
current behavior.

Typical files:

- execution reports
- legacy design docs
- old task prompts
- migration notes
- historical handoff logs
- dated snapshots

Rules:

- Archive files are normally append-only or immutable.
- Do not rewrite old verdicts to match current status.
- Do not put current operating rules only in archive.
- If archive material becomes current again, extract the rule into a handbook
  and link back to the archive as evidence.

## Minimal Map

Every project should have one obvious place that states:

- current status file
- task source of truth
- unresolved problem/feedback source of truth when the project needs one
- handbook locations
- archive locations
- rule for creating new docs

This may be an existing README or AI entrypoint. Create `DOCS_MAP.md` or
`docs/README.md` only when no existing master file can reasonably carry it.

