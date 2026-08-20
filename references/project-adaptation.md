# Project Adaptation Guide

Use the smallest documentation system that gives clear ownership.

## No Docs Project

Signs:

- only code and maybe `README.md`
- no stable docs directory

Recommended shape:

- Use `README.md` as the master layer.
- Add one "Documentation" section listing current docs and task system.
- Do not create empty directories.
- Create a handbook file only when a durable rule appears.

## Small Project

Signs:

- fewer than about 10 markdown docs
- one or two maintainers

Recommended shape:

- Collapse master and handbook into README sections when possible.
- Use issue tracker or a short `TASKS.md` for tasks. If unresolved feedback is rare, keep it in that tracker rather than creating a separate register.
- Use `archive/` only when history starts getting noisy.
- Avoid `docs/README.md` unless docs has multiple subtopics.

## Medium Project

Signs:

- docs directory exists
- several stable subject areas
- tasks and reports are accumulating

Recommended shape:

- Master/status: README plus current status or project brief.
- Handbook: topic files under docs.
- Task: external tracker or docs/tasks.
- Archive: docs/archive, docs/reports, or execution_reports.
- If user feedback and discovered problems routinely exist before task authorization, use one current problem/feedback register or link to the authoritative external tracker.
- Add a docs map only if users struggle to find the source of truth.

## Large / Multi-Agent Project

Signs:

- many task handoffs
- multiple agents or models
- execution reports and task prompts accumulate
- context compression causes agents to rediscover old facts

Recommended shape:

- External task system strongly recommended.
- Master/status must explicitly state the task source of truth.
- Repo task boards are snapshots only.
- Keep unresolved user feedback in one authoritative problem/issue intake so it is neither forgotten in chat nor automatically promoted to a task.
- Handbooks should hold durable rules by topic.
- Archives should be kept but demoted from current authority.
- New docs require a placement check and a single link from the master map.

## Messy Legacy Project

Signs:

- many README/status/task/report files
- old and current rules conflict
- task numbering is inconsistent
- agents keep adding new summaries instead of updating existing ones

Recommended workflow:

1. Audit first; do not move files immediately.
2. Identify current sources of truth.
3. Map files into the four layers.
4. Mark duplicate or stale files as recommendations.
5. Merge new rules into existing masters/handbooks.
6. Move or delete only after user approval and reference checks.

