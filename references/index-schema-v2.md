# Driftlock Index Schema v2

## Contents

1. Index container
2. Fields and enums
3. Relationships
4. Lock format
5. Commands and exit codes
6. Structural errors

## Index Container

Every managed active or superseded Markdown file contains exactly one fenced
`driftlock-index` block with strict JSON. Archived legacy files may remain
unmanaged. Use relative POSIX paths only. Reject absolute paths, Windows
drive-qualified paths, UNC paths, every backslash path form, `..` escapes, and
symlinks resolving outside the project root on every operating system.

## Fields And Enums

Required fields: `schema_version` (`2`), stable `id`, integer `level`, `role`,
and `lifecycle_status`. Require `authority_key` for current authoritative entry,
index, status, task-board, contract, runbook, and long-lived rule documents.
The single L0 must also use `role=project_entry`; another active role at level
zero is not a project entry.

Roles:

```text
project_entry module_index submodule_index status task_board contract runbook
reference task report archive_index
```

Lifecycle values:

```text
active superseded archived
```

Optional fields: `startup`, `startup_budget`, `read_when`, `children`,
`depends_on`, `watch_paths`, `archive_roots`, and `supersedes`.

When present, `read_when` has exactly this shape:

```json
{"any": ["the task changes authentication", "the task changes sessions"]}
```

`any` must contain one or more non-empty strings and no sibling keys are
allowed. These phrases guide an agent's semantic routing; the CLI validates
their shape but does not infer task meaning from them.

`0.2.0` is the first tagged public contract for this field. Projects created
from earlier untagged snapshots that used another object shape must migrate to
`{"any": [...]}` before adopting `0.2.0`.

Use exact `authority_key` equality as a blocking conflict between active docs.
Use shared suffix segments only for the non-blocking
`NEAR_DUPLICATE_AUTHORITY_KEY` warning.

## Relationships

Each `children` record contains `id`, `path`, and `propagation`. Each
`depends_on` record contains `id` and `propagation`. Allowed propagation:

```text
link_only summary status_only contract
```

Build separate children and dependency graphs and reject cycles with the full
cycle path. Build reverse edges for parent and contract-consumer propagation.
Reject non-object relation entries, missing fields, invalid propagation values,
missing targets, and child paths that do not exactly match the target document.
An active document may reference only active children and active dependency
targets. Treat superseded and archived targets as structural errors.

`watch_paths` uses `pathlib.Path.glob` semantics, not Gitignore semantics. Store
the pattern, resolved file set, relative paths, and raw-byte SHA-256 hashes.

## Lock Format

Commit `.driftlock.lock.json`. Sort documents by ID and serialize with stable
field ordering and indentation. Each record stores path, authority key,
document SHA-256, verified commit/time, `status_effect`, and snapshots for
children, dependencies, and watch paths.

The lock root and every JSON command report include `tool_version`. Version
`0.2.0` writes this field. Older schema-v2 locks without it remain readable and
gain it on their next successful verification.

Bind `status_effect` to the current document hash and verified commit. First
verification uses `initial`; later versions use `changed` or `unchanged` when a
parent edge is `status_only`.

Each lock record also stores `status_effect_applicable` as a Boolean. Set it to
true only when the document has an incoming `status_only` parent edge at verify
time. Impact propagation must ignore a status effect when this field is false,
even if the stored string is `changed`.

Validate every lock record before freshness calculation. Required record fields
are `path`, `authority_key`, `content_sha256`, `verified_commit`, `verified_at`,
`status_effect`, `status_effect_applicable`, and `dependencies`. Validate nested
dependency, child, watch-pattern, and resolved-file records. Compare both
`path` and `authority_key` with the current document before returning CURRENT.

Write the lock by temporary file, flush, fsync, compare the original lock bytes,
then `os.replace`. Refuse concurrent replacement. Report invalid JSON or schema
as `LOCK_CORRUPTED`; never hand-merge conflicts.

Hash raw bytes with SHA-256. Recommend committed `.gitattributes` rules:

```gitattributes
*.md text eol=lf
*.json text eol=lf
*.py text eol=lf
```

## Commands And Exit Codes

All commands support `--format text|json`. `discover`, `check`, `impact`, and
`archive-plan` are read-only. `verify` updates only the lock.

Exit codes:

```text
0 success without blocking state
1 STALE, REVIEW_REQUIRED, or UNVERIFIED
2 structural error or refused verification
3 argument, Git, permission, JSON, or filesystem failure
```

Hooks must treat `0` and `1` as success and may block only on `2` or `3`.

## Structural Errors

Block on invalid/unsupported schema, missing or multiple L0 entries, duplicate
IDs, duplicate active authority keys, active supersedes targets, broken local
links, path escape, archive boundary violations, graph cycles, orphan active
documents, corrupted lock, and invalid verified commit ancestry.

External URLs are references only; never access the network to validate them.

Combine `archive_roots` declared by valid L0 and L1 indexes. Reject active
documents physically located below those roots, archived active children,
archived dependencies, any L0/L1 startup entry in an archive, and any
`watch_paths` pattern whose resolved file set enters an archive root.

`discover` returns candidate groups for L0, L1 modules, status, task boards,
contracts, runbooks, archives, loose root files, possible responsibility
duplicates, and a suggested hierarchy. `archive-plan` returns each candidate's
classification, reasons, all inbound references, suggested target, authority
candidate, risk, and rollback guidance. Both commands remain strictly read-only.

Malformed project structure and corrupted locks block both `check` and
`impact`. In hash-only mode all read-only reports include an explicit
`HASH_ONLY_MODE` warning. CLI argument errors use exit code `3`.

Parse Git dirty paths from `git status --porcelain=v1 -z`. Preserve both rename
or copy endpoints and never unquote paths manually. A relevant source or target,
including paths containing whitespace or non-ASCII characters, blocks verify.

Classify a document's own content, identity, watch set, or watched bytes as
`STALE`. Classify a parent or contract consumer whose saved child/dependency
hash changed as `REVIEW_REQUIRED`; retain the separate `status_only` rules.

Require a committed `.gitattributes` rule containing `*.md text eol=lf` for
reproducible raw-byte hashes. Treat any Markdown destination with a URI scheme,
including `mailto:` and `tel:`, plus protocol-relative URLs, as external rather
than as a local file path.
