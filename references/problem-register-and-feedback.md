# Problem Register And Feedback Intake

Use this reference when a project receives user feedback, screenshots, bug reports,
UX complaints, operational observations, or other unresolved findings that should
not be forgotten but do not yet justify an authorized implementation task.

Driftlock does not require every project to create a problem register. Use the
smallest authoritative mechanism that fits the project: an external issue tracker,
a repository-native current problem register, or an existing product feedback
system. The important boundary is that unresolved observations have one durable
intake path and do not silently become implementation authority.

## Why This Exists

A task board answers "what work is authorized or planned?" It is a poor place to
store every observation that might matter later. Without a separate intake path,
projects usually drift toward one of two failure modes:

- every complaint becomes a task, creating task sprawl; or
- complaints remain only in chat, screenshots, or memory and are later forgotten.

A problem register preserves the middle state: "this matters enough to retain,
but it is not yet an authorized task."

## Core Boundary

A problem record is not a task and does not authorize implementation.

Recommended flow:

```text
user feedback / screenshot / runtime observation
  -> authoritative problem intake
  -> revalidate against current reality
  -> classify or deduplicate
  -> human/project authority decides whether to create work
  -> task system
  -> implementation / validation
  -> write the verified outcome back to the problem record
```

Never infer that `confirmed`, `planned`, or any other problem status grants an
executor permission to change code, data, production, or infrastructure. Task
creation and execution remain governed by the project's collaboration rules.

## Recommended States

Keep the state set small. A practical default is:

- `needs_revalidation`: historical or reported issue that has not been confirmed
  against the current implementation.
- `confirmed`: reproduced or otherwise verified in the current system.
- `planned`: project authority has decided it should be addressed, but an
  implementation task may not exist yet.
- `in_task`: linked to an active authoritative task.
- `resolved`: fix or outcome has been verified.
- `obsolete`: the old behavior no longer exists, usually because the page,
  architecture, or requirement changed.
- `parked`: intentionally retained but not currently being pursued.

Projects may use different names, but must distinguish unverified historical
feedback from a currently reproduced defect.

## Minimum Problem Record

A repository-native record should normally preserve:

- stable problem ID;
- short title;
- area or product surface;
- current problem state;
- priority or severity if the project uses one;
- first-seen date when known;
- last-confirmed date or `unknown`;
- source type and evidence pointers, such as screenshot, user feedback, report,
  runtime observation, or task ID;
- related tasks or designs;
- target stage or planned revalidation point when useful;
- converted task ID when one exists;
- concise observed behavior;
- current interpretation, including uncertainty;
- next validation step.

Do not fabricate timestamps, screenshots, reproduction results, or "current"
status merely to fill fields.

## Historical Feedback Must Be Revalidated

Old feedback is evidence that a problem existed or was perceived at some point;
it is not proof that the current product still behaves that way.

Prefer wording such as:

```text
Historical feedback: sidebar navigation previously jumped after selection.
State: needs_revalidation.
Current reproduction: not yet checked.
```

Only move the record to `confirmed` after current evidence supports it. If a
migration or redesign makes the issue irrelevant, use `obsolete` rather than
pretending it was fixed by the current task.

## Deduplication And Problem Families

Do not create one problem ID per sentence or screenshot. Group reports that share
the same user-visible failure or decision boundary.

For example, "image too small", "image area wastes space", and "product photo has
low visual priority" may belong to one problem family if they describe the same
cross-page design defect. Keep the individual observations as evidence under one
record when that preserves meaning.

Split records when they require independent reproduction, ownership, rollout, or
acceptance.

## Repository-Native Placement

When no external issue/feedback system is authoritative, a medium or large
project may use a current file such as:

```text
docs/current/PROBLEM_REGISTER.md
current/PROBLEM_REGISTER.md
```

This is current state, not archive and not a task database.

For Driftlock-managed repositories, a problem register can be an L1 `status`
document with a stable `authority_key`. Keep it out of default `startup` once it
becomes large. Route to it with `read_when` or an equivalent project map rule
when the task touches product feedback, UX, defects, migration acceptance, or a
specific affected surface.

The L0 may reference it with a `link_only` child edge when the L0 only needs to
assert that the register exists. Use stronger propagation only when the L0
semantically summarizes problem state.

Example index:

````markdown
```driftlock-index
{
  "schema_version": 2,
  "id": "project-problem-register",
  "authority_key": "project.problem_register",
  "level": 1,
  "role": "status",
  "lifecycle_status": "active",
  "read_when": {
    "any": [
      "the task investigates unresolved product feedback",
      "the task migrates or redesigns a user-facing surface",
      "the task decides whether a reported problem still exists"
    ]
  }
}
```
````

Do not create a second register if GitHub Issues, Jira, Linear, WCP, or another
system is already authoritative for unresolved problem intake. Instead, link to
that system from the project map or status layer and document the boundary.

## Relationship To The Task System

The problem register answers:

- what has been reported or discovered;
- what still needs revalidation;
- what is confirmed, parked, obsolete, or resolved; and
- which authoritative task, if any, owns implementation.

The task system answers:

- what work is authorized;
- who executes it;
- what scope is allowed;
- what evidence is required; and
- whether the task is accepted, reworked, or closed.

Do not duplicate task execution state into every problem record. A stable task
link and verified outcome are usually enough.

## Closure And Archive

Resolved and obsolete records should remain discoverable long enough to prevent
repeat investigation and to preserve the reason they disappeared. Large
registers may periodically move old resolved/obsolete records into an archive or
historical register, but only after:

1. the current record keeps any still-relevant durable rule;
2. task/report/evidence links remain valid;
3. active records do not depend on the archived record as current authority; and
4. the move is an explicitly authorized documentation migration.

A problem register is successful when it reduces forgotten feedback without
turning every observation into a task or forcing agents to load the entire issue
history on every startup.
