# Task Identity And Naming

Use this reference when a project keeps repository-native task files and needs stable task identities across decomposition, rework, review, and archive.

Driftlock does not require one universal task prefix. Projects may use `TASK-`, issue numbers, Jira keys, or another stable identifier. The important contract is that identity stays stable and that different concepts remain distinguishable.

## Core Principles

- Treat a task ID as a durable identity, not a status label.
- Never renumber historical tasks merely to make a new scheme look cleaner.
- Do not encode every project dimension into the ID. Phase, area, owner, status, and priority belong in metadata unless the project has a strong reason otherwise.
- Distinguish scope decomposition from rework. They are different concepts and should not share the same suffix semantics.
- Prefer separators between different identity concepts so humans and agents can parse them without guessing.
- A rework round must remain traceable to the exact code and evidence it changed.

## Recommended Repository-Native Pattern

For projects that use sequential `TASK-NNN` identities, a readable convention is:

```text
TASK-114          main task
TASK-114-A        independently executable child scope A
TASK-114-B        independently executable child scope B
TASK-114-R1       first rework of the main task
TASK-114-A-R1     first rework of child scope A
TASK-114-A-R2     second rework of child scope A
```

The hyphen is significant: it separates different concepts instead of compressing them into an ambiguous token such as `TASK-114AR2`.

This is a recommendation, not a Driftlock-wide requirement. A project may choose another stable syntax if it documents the same semantics.

## When To Split A Child Scope

Do not create `-A`, `-B`, or other child IDs merely because a task contains several implementation steps.

Split only when the child scope has a meaningful independent boundary, for example when it can be:

- implemented independently;
- reviewed or accepted independently;
- rolled back independently;
- assigned to a different executor;
- blocked or resumed independently; or
- preserved as a distinct engineering decision or evidence trail.

Small, already-closed tasks should normally remain one task.

## Rework Semantics

Use `-R1`, `-R2`, and later rework suffixes only when the original scope remains the same but an accepted or submitted implementation must be corrected.

A rework is not a new independent problem. Each rework record should preserve, at minimum:

- parent task or child-scope ID;
- rework number;
- base commit SHA;
- resulting commit SHA;
- executor;
- tests or other validation evidence;
- review result and rejection/repair reason; and
- next action when the round is not accepted.

Do not overwrite an earlier rework record. Repository history, reports, and commits must make it possible to identify which round introduced or corrected a regression.

## When To Create A New Task

Create a new task instead of another rework suffix when investigation reveals a genuinely independent root cause, scope, or deliverable.

For example:

```text
TASK-114          migrate the Today workspace
TASK-114-A        Today read-model API
TASK-114-A-R1     rework the same API contract after review
TASK-117          independent PostgreSQL history-query defect discovered during TASK-114
```

Link the new task with metadata such as `related_to`, `depends_on`, or the project's equivalent. Do not disguise a new scope as rework simply to keep one task open.

## Metadata Still Matters

Keep task identity small. Put changing project context in task metadata, for example:

```yaml
id: TASK-114-A
phase: architecture-modernization
area: frontend
status: ready_for_review
parent: TASK-114
related_to: []
executor: example-agent
reviewer: example-reviewer
baseline: <commit-sha>
```

The exact field names are project-specific; Driftlock governs documentation placement and freshness, not a universal task database schema.

## Migration And Legacy IDs

When adopting this convention in an existing repository:

- keep all historical IDs unchanged;
- document legacy forms instead of renaming them;
- apply the new convention only to newly created tasks unless an explicit migration has been approved;
- never rewrite archived evidence just to normalize identifiers; and
- keep redirects or cross-references when a historical alias must remain discoverable.
