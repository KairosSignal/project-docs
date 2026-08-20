# Task System Boundaries

Use this reference when a project has WCP, GitHub Issues, Jira, Linear, Kiro
Tasks, or any external task tracker.

## Core Boundary

Task systems record lifecycle:

- task creation
- assignment / dispatch
- claim
- execution submission
- monitor snapshot
- validation
- rework
- closure

Repo documentation records:

- project state summaries
- durable rules
- architecture and operating procedures
- required mirrors or historical evidence

Do not make repo docs a second task database.

## WCP Pattern

If Work Control Plane is present:

- WCP is authoritative for task IDs, packages, claims, reports, validation,
  rework, and closure.
- Repo `task_queue` files are templates, required mirrors, or historical task
  prompts.
- Repo `execution_reports` files are historical evidence or required mirrors.
- `workroom` and `TASK_BOARD.md` are status snapshots, not assignment authority.
- The master/status layer should include the WCP path or anchor command.

## Issue Tracker Pattern

If GitHub Issues, Jira, Linear, or another tracker is authoritative:

- Link to the tracker from the master/status layer.
- Do not copy issue body fields into docs unless a decision becomes durable.
- Store durable decisions in ADR/handbook docs.
- Store postmortems or execution evidence in archive/report docs.

## No External Task System

If no tracker exists:

- A simple `TASKS.md` is enough for small projects.
- For medium projects, use `docs/tasks/` or one task board.
- Do not create both `TASKS.md`, `TASK_BOARD.md`, and many task files unless
  their roles are explicit.
- If repository-native task files need stable identities across child scopes,
  rework, and archive, read `task-identity-and-naming.md` and document the
  project's chosen convention.
