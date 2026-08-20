# Document Placement Checklist

Run this checklist before creating or moving project documentation.

## Before Adding A New Document

1. Can this be appended to an existing master/status file?
2. Can this be appended to an existing handbook?
3. Is this a live task that should go to a task system?
4. Is this an unresolved observation that belongs in the project's existing problem/feedback intake rather than a new task or new document?
5. Is this historical evidence that belongs in archive?
6. Will creating this file require updating a docs map or master link?
7. Is there already a semantically similar file?
8. Will this create a second source of truth?

If any answer is uncertain, stop and present a recommendation instead of editing.

## Sprawl Signals

Flag these as warnings:

- multiple README files that mostly explain directory roles
- multiple current status files with conflicting next tasks
- task prompts stored as live authority after an external task system exists
- execution reports copied into status files
- archive files treated as current rules
- new docs not linked from any master/status map
- unresolved problems copied across chat, task boards, and ad hoc feedback files with no single intake authority
- historical task IDs renumbered by import order

## Output Format For Audits

Use this shape:

```text
Master/status:
- file: reason

Handbook:
- file: reason

Task:
- file or system: reason

Archive:
- file: reason

Warnings:
- file: issue, recommended action

Minimum changes:
- exact file/action
```

