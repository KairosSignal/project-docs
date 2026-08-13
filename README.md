# Project Docs

[![Tests](https://github.com/KairosSignal/project-docs/actions/workflows/test.yml/badge.svg)](https://github.com/KairosSignal/project-docs/actions/workflows/test.yml)

Project Docs is an agent skill and a dependency-free Python CLI for keeping
project documentation small, current, and safe for AI-assisted development.

It gives a repository one authoritative documentation entry point, routes
agents through layered indexes, detects stale contracts after code changes,
propagates review requirements through declared dependencies, and keeps
archives outside the default context.

## Why

Long-running projects often accumulate multiple status files, duplicated
architecture notes, stale handoffs, and large archives. An AI agent can then
read the wrong document, repeat completed work, or spend most of its context on
history.

Project Docs makes freshness deterministic. Markdown documents declare their
identity and relationships in a small JSON index block. The CLI records reviewed
content hashes in `.project-docs.lock.json` and reports computed states:

- `CURRENT`
- `STALE`
- `REVIEW_REQUIRED`
- `UNVERIFIED`

## Features

- Progressive L0/L1/L2 documentation indexes
- One authoritative project entry document
- SHA-256 freshness checks for documents and watched code paths
- Dependency propagation for summaries, status, and contracts
- Git-aware verification with dirty-path protection
- Read-only discovery and archive planning
- Archive isolation from startup context and active dependency graphs
- Structured JSON output for agents and CI
- Standard-library Python with no runtime dependencies

## Agent Compatibility

Project Docs is not tied to one model or coding agent:

- Any agent with shell access can run the Python CLI.
- Agents that support `SKILL.md` packages can load the repository as a skill.
- Agents without a skill system can use `SKILL.md` as project instructions and
  call `scripts/project_docs.py` directly.
- Humans and CI can use the same CLI without an agent.

`agents/openai.yaml` provides optional OpenAI/Codex interface metadata. The core
skill and CLI do not import or depend on OpenAI libraries.

## Install

Clone the repository into the skill or instruction directory used by your
agent:

```bash
git clone https://github.com/KairosSignal/project-docs.git
```

Then either register the cloned directory as an agent skill or run the CLI from
it. Consult your agent's documentation for its skill discovery directory.

### Codex

Ask Codex to install the public skill:

```text
Install the project-docs skill from https://github.com/KairosSignal/project-docs
```

Or clone it into the Codex skills directory:

```bash
git clone https://github.com/KairosSignal/project-docs.git \
  ~/.codex/skills/project-docs
```

Restart Codex after installation so the skill is discovered.

## Use With An Agent

For any agent, ask it to read `SKILL.md` and use the bundled CLI:

```text
Read the project-docs SKILL.md, audit this repository's documentation, and
report the minimum updates needed. Do not read archives unless required.
```

### Codex

Invoke the skill explicitly:

```text
Use $project-docs to audit this repository's documentation and report the
minimum updates needed. Do not read archives unless required.
```

The skill also triggers for documentation audits, reorganization, freshness
validation, archive isolation, project-map creation, and task/report sprawl.

## CLI

Requirements:

- Python 3.9 or newer
- Git 2.25 or newer for commit-aware verification
- Linux, macOS, or Windows

Git is optional only in explicit hash-only mode. Without Git, `verify` requires
`--allow-hash-only` and reports reduced assurance.

Run the CLI directly from the skill directory:

```bash
python3 scripts/project_docs.py discover /path/to/project
python3 scripts/project_docs.py check /path/to/project
python3 scripts/project_docs.py impact /path/to/project --since HEAD~1
python3 scripts/project_docs.py verify /path/to/project \
  --doc project-entry --status-effect initial
python3 scripts/project_docs.py archive-plan /path/to/project
```

Add `--format json` for automation.

`discover`, `check`, `impact`, and `archive-plan` are read-only. `verify` is the
only writing command, and it writes only `.project-docs.lock.json` atomically.

CLI JSON reports and generated lock files include `tool_version`. The current
release line is `0.1.0`.

## Runnable Demo

Run the bundled example from any checkout:

```bash
python3 examples/run_demo.py
```

The demo creates a temporary Git repository, verifies four documents to
`CURRENT`, changes authentication code, and checks that only the authentication
contract and its summary chain enter the update queue. It also demonstrates the
CI contract: exit code `1` is ordinary stale state, while only `2` and `3`
block.

## Minimal Index

Every managed Markdown file contains one fenced `project-docs-index` block with
strict JSON. A minimal L0 entry looks like this:

````markdown
```project-docs-index
{
  "schema_version": 2,
  "id": "project-entry",
  "authority_key": "project.entry",
  "level": 0,
  "role": "project_entry",
  "lifecycle_status": "active",
  "startup": [
    "docs/current/status.md",
    "docs/current/task-board.md"
  ],
  "startup_budget": {
    "max_files": 5,
    "max_characters": 12000
  },
  "archive_roots": [
    "docs/archive"
  ]
}
```
````

Use `discover` first when a repository has no valid L0 entry. It reports
candidates without inventing authority or moving files.

## Recommended Workflow

1. Run `discover` to understand the existing documentation.
2. Establish one L0 entry and narrow L1 branches.
3. Add indexes and explicit dependency edges.
4. Review each document and run `verify`.
5. Commit `.project-docs.lock.json` with the reviewed documents.
6. Run `check` in agent workflows or CI.

Project Docs never automatically rewrites semantic content, assigns authority,
moves documents, or deletes archives. Those remain explicit human or agent
decisions.

## Exit Codes

| Code | Meaning |
|---:|---|
| `0` | Current and structurally valid |
| `1` | Ordinary stale, review-required, or unverified state |
| `2` | Structural error or refused verification |
| `3` | Argument, Git, permission, JSON, or filesystem failure |

CI wrappers should treat `0` and `1` as non-blocking and block only on `2` or
`3`.

## Test

```bash
python3 -m unittest discover -s tests -p 'test_*.py'
```

## License

MIT
