---
name: project-docs
description: Govern documentation in small through large multi-agent projects using progressive L0/L1/L2 indexes, deterministic freshness checks, dependency propagation, context budgets, and archive isolation. Use when creating, auditing, reorganizing, validating, compacting, or archiving project docs; detecting stale status or contract files after code changes; establishing a project map; or controlling docs/workroom/task/report sprawl.
---

# Project Docs

Keep current knowledge small and navigable while preserving history outside the
default AI context. Upgrade the existing project structure in place; never
create a competing documentation source of truth.

## Operating Sequence

1. Read the project collaboration rules.
2. Find the single L0 `project_entry` document.
3. Read only its ordered `startup` files.
4. Route the task to the narrowest matching L1 branch via `read_when`.
5. Load deeper contracts or runbooks only when that branch requires them.
6. Exclude archive roots unless the task explicitly investigates history.

If no valid L0 exists, treat the project as unmanaged. Run `discover`; do not
guess which status file is authoritative.

## Commands

Resolve the directory containing this `SKILL.md` once as `<skill-root>`. Run
the standard-library CLI from that absolute skill root, not from the target
project's current working directory:

```bash
python3 <skill-root>/scripts/project_docs.py discover <project-root>
python3 <skill-root>/scripts/project_docs.py check <project-root>
python3 <skill-root>/scripts/project_docs.py impact <project-root> [--since COMMIT]
python3 <skill-root>/scripts/project_docs.py verify <project-root> --doc DOC_ID --status-effect initial|changed|unchanged
python3 <skill-root>/scripts/project_docs.py archive-plan <project-root>
```

Use `--format json` for agents and automation.

- `discover`, `check`, `impact`, and `archive-plan` are always read-only.
- `verify` is the only command that writes, and it writes only
  `.project-docs.lock.json` atomically.
- Never call `verify` until an AI or human has reviewed the real code,
  configuration, child documents, and contracts.
- Do not verify relevant uncommitted paths. Unrelated dirty paths are allowed.
- In a non-Git project, require explicit `--allow-hash-only` and report the
  reduced assurance.
- Treat malformed index or lock input as structured errors. A read-only command
  must never emit a Python traceback for user-controlled project metadata.

## Freshness And Propagation

Treat lifecycle (`active`, `superseded`, `archived`) as authored metadata.
Treat `CURRENT`, `STALE`, `REVIEW_REQUIRED`, and `UNVERIFIED` as computed state.
Never write computed state back into Markdown.

`check` includes both direct freshness and the mechanically propagated
`REVIEW_REQUIRED` state. Use `impact` when the task also needs the minimal
update queue, propagation reasons, or a `--since` baseline.

Propagate changes according to declared edges:

- `link_only`: validate identity/path only.
- `summary`: review the parent summary.
- `status_only`: wait for explicit `status_effect`; propagate only `changed`.
- `contract`: review parents and all declared `depends_on` consumers.

Dates never override hash or dependency evidence.

## Safety Boundaries

- Do not automatically create authority, semantic summaries, task status,
  blockers, or next actions.
- Do not move, delete, merge, compress, or rewrite documents without a separate
  authorized migration task.
- Do not use text similarity alone to merge documents.
- Keep archive files out of startup, active children, `depends_on`, and
  `watch_paths`.
- Commit the lock file for cross-machine and cross-agent reproducibility.
- Never hand-merge a conflicted lock; retain one valid side and re-run `verify`
  for affected documents.
- Recommend `.gitattributes` with LF rules so raw-byte SHA-256 remains stable
  across platforms.

Exit code `1` means ordinary stale/review state. Git hooks and CI wrappers must
map it to success. Only exit codes `2` and `3` may block.

## References

- Read `references/index-schema-v2.md` before creating indexes, implementing a
  checker, or interpreting errors.
- Read `references/migration-playbook.md` before reorganizing an existing
  project or generating its first lock.
- Read `references/four-layer-architecture.md` when selecting L0/L1/L2/archive
  boundaries.
- Read `references/placement-checklist.md` before adding or moving documents.
- Read `references/project-adaptation.md` when sizing the hierarchy or context
  budgets.
- Read `references/task-system-boundaries.md` when tasks live in WCP, GitHub,
  Jira, Linear, or repository task files.
