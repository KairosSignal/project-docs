# Documentation Migration Playbook

## Phase 1: Upgrade The Global Skill

Implement and validate the skill in isolation. Do not reorganize the target
project while changing the global tooling.

## Phase 2: Read-Only Discovery

Run `discover`, `check`, and `archive-plan`. Identify L0 candidates, L1 domains,
current authorities, duplicate responsibilities, loose root files, dated
snapshots, archive boundaries, inbound references, and broken links.

## Phase 3: Human Review

Approve one L0, domain boundaries, authority keys, startup budgets, active
sources of truth, archive roots, merge candidates, and migration order. Text
similarity is evidence, never authority.

## Phase 4: Authorized Migration

Use a separate task with exact allowed files and rollback. Create L0/L1 indexes,
add machine blocks, move historical files with Git-aware operations, update
references mechanically, add `.gitattributes`, and generate the first lock only
after semantic review.

## Phase 5: Verify Bottom-Up

Verify contracts and runbooks first, then submodule indexes, domain indexes, and
finally L0. Use `status_effect` at every status-only boundary. Commit the lock
with the migration so other agents receive the same baseline.

Never silently migrate a live project, rewrite historical conclusions, or leave
current rules available only inside archive material.
