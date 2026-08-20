# Task Lifecycle And Status Semantics

Use this reference when repository-native tasks, task mirrors, or project status
summaries need to distinguish implementation progress from review, integration,
deployment, and final closure.

Driftlock does not impose one universal task database schema. GitHub, Jira,
Linear, WCP, and repository-native task systems may use different names. The
requirement is that a project documents stable meanings for its task states so
humans and agents do not confuse "code written" with "accepted", "merged",
"deployed", or "closed".

## Core Principle

A task state is a lifecycle fact, not a synonym for "looks done".

At minimum, a project that separates implementation, review, integration, and
production should be able to answer these questions independently:

- Has implementation started?
- Is the implementation ready for independent review?
- Did the reviewer accept or reject it?
- Has the accepted change entered the authoritative integration branch?
- Has the required remote/release state been published when the project tracks
  that separately?
- Has production or another target environment been updated when deployment is
  part of scope?
- Has post-deploy/runtime/user acceptance evidence been collected when required?
- Is there any remaining action before the task can be closed?

Do not collapse these facts merely to reduce the number of status labels.

## Recommended Repository-Native Lifecycle

A practical default is:

```text
planned
  -> in_progress
  -> ready_for_review
  -> accepted
  -> integrated
  -> deployed
  -> closed
```

Projects may use more explicit compound states when the next action matters, for
example:

```text
accepted_pending_integration
merged_pending_push
pushed_pending_deploy
deployed_pending_close
```

These are recommendations, not Driftlock-wide required enum values. A project
may map them to its own tracker states as long as the meanings remain explicit.

## Required Semantic Distinctions

### `planned`

The work has been approved or queued according to project governance but has not
started. A problem record by itself must not silently become `planned` unless the
project authority has actually authorized work.

### `in_progress`

An authorized executor is actively implementing or validating the defined scope.
This does not imply review has passed.

### `ready_for_review`

The executor has submitted a concrete implementation/evidence set for independent
review. The state should point to the exact branch/commit, tests, and relevant
runtime evidence. It is not acceptance.

### `rework_required`

Review found a defect or unmet acceptance criterion in the same scope. Keep the
rejected round traceable and create the project's documented rework identity,
such as `TASK-114-R1`, when that convention is used.

### `accepted`

The required reviewer or acceptance authority has accepted the submitted scope.
`accepted` does **not** mean merged, pushed, released, deployed, or closed unless
the project explicitly defines those actions as out of scope.

### `integrated`

The accepted change has entered the project's authoritative integration branch
or equivalent mainline. If remote publication is operationally important, track
or evidence `push`/release publication separately instead of assuming local merge
means remote state is current.

### `deployed`

The target environment required by the task has been updated. Deployment alone
is not proof of runtime correctness. When the task requires smoke, natural-run,
data, security, visual, or user acceptance evidence, keep the task open until
that evidence exists.

### `closed`

No required action remains for the task under the project's documented scope and
closure policy. The task's final record must make it possible to determine why it
was safe to close.

A task may close without deployment when deployment is explicitly outside its
scope, for example a design-only, documentation-only, investigation-only, or
non-production engineering task. Record the closure basis rather than pretending
that deployment occurred.

## Side States

Common non-linear states include:

- `blocked`: work cannot progress until a named dependency or decision changes.
- `deferred`: intentionally postponed; the reason and re-entry condition should
  remain discoverable.
- `cancelled`: authorized work was intentionally abandoned before successful
  closure; preserve the reason and any useful evidence.

Projects may also use `parked`, `obsolete`, or tracker-specific states when their
semantics are documented.

## Rework And Parent Task Semantics

Do not overwrite a rejected rework round after a later round succeeds.

Example:

```text
TASK-115       -> closed
TASK-115-R1    -> rework_required   (historical rejected round)
TASK-115-R2    -> rework_required   (historical rejected round)
TASK-115-R3    -> rework_required   (historical rejected round)
TASK-115-R4    -> accepted/deployed/closed according to project policy
```

The parent may close after the current accepted scope has completed all required
integration/deployment/acceptance gates even though earlier rejected rounds retain
their historical outcome. Link the chain so an agent can identify which round
superseded which rejection.

A genuinely independent defect discovered during review is a new task, not a new
rework suffix. Read `task-identity-and-naming.md` for that boundary.

## Human And Domain-Specific Acceptance Gates

Technical review does not automatically replace domain acceptance.

If the project requires a separate user, product, visual, legal, security, data,
or operational approval, record that gate explicitly. For example, a frontend
migration may pass automated browser tests and code review but still remain open
until the project owner approves the visual direction through screenshots or a
protected preview environment.

Do not let a generic `accepted` label hide an unmet project-specific gate. Either
make the acceptance authority explicit or use a pending state until all required
acceptance dimensions have been satisfied.

## Minimum Closure Evidence

A repository-native task that reaches `closed` should normally preserve or link
to the evidence relevant to its scope, such as:

- final accepted commit/release identity;
- reviewer result and rework chain when any;
- test summary;
- integration/mainline state when applicable;
- deployment target and rollback reference when applicable;
- runtime/smoke/natural-run/user acceptance evidence when required;
- unresolved exceptions explicitly carried forward to a problem register or a
  separate task.

Do not fabricate a completed step just to make the lifecycle look linear.

## Relationship To Driftlock

Driftlock governs document placement, freshness, dependency propagation, and
traceability. It intentionally does not validate one universal task-status enum
inside `scripts/driftlock.py`.

Projects should define their status vocabulary in their own workflow/task
contract and use Driftlock to keep that contract and the current task/status
summaries fresh. This preserves interoperability with external task systems while
preventing ambiguous repository-native task closure.
