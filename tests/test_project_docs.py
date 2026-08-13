from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


SCRIPT = Path(__file__).parents[1] / "scripts" / "project_docs.py"
README = Path(__file__).parents[1] / "README.md"
DEMO = Path(__file__).parents[1] / "examples" / "run_demo.py"


def load_module():
    spec = importlib.util.spec_from_file_location("project_docs", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader
    spec.loader.exec_module(module)
    return module


def index_doc(meta: dict, body: str = "Current summary.\n") -> str:
    return "# Doc\n\n" + body + "\n```project-docs-index\n" + json.dumps(meta) + "\n```\n"


class RepoCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        subprocess.run(["git", "init", "-q"], cwd=self.root, check=True)
        subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=self.root, check=True)
        subprocess.run(["git", "config", "user.name", "Test"], cwd=self.root, check=True)

    def tearDown(self):
        self.tmp.cleanup()

    def write(self, rel: str, content: str):
        path = self.root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        return path

    def commit(self):
        subprocess.run(["git", "add", "."], cwd=self.root, check=True)
        subprocess.run(["git", "commit", "-qm", "state"], cwd=self.root, check=True)

    def read_meta(self, rel: str) -> dict:
        text = (self.root / rel).read_text(encoding="utf-8")
        return json.loads(text.split("```project-docs-index\n", 1)[1].split("\n```", 1)[0])

    def write_meta(self, rel: str, meta: dict, body: str = "Current summary.\n"):
        return self.write(rel, index_doc(meta, body=body))

    def basic(self, propagation="summary"):
        self.write("AGENTS.md", "# Rules\n")
        self.write("src/a.py", "VALUE = 1\n")
        child = {
            "schema_version": 2, "id": "child", "authority_key": "domain.contract",
            "level": 1, "role": "contract", "lifecycle_status": "active",
            "watch_paths": ["src/**/*.py"],
        }
        root = {
            "schema_version": 2, "id": "root", "authority_key": "project.entry",
            "level": 0, "role": "project_entry", "lifecycle_status": "active",
            "startup": ["AGENTS.md"],
            "startup_budget": {"max_files": 3, "max_characters": 10000},
            "children": [{"id": "child", "path": "docs/child.md", "propagation": propagation}],
            "archive_roots": ["docs/archive"],
        }
        self.write("PROJECT_MAP.md", index_doc(root))
        self.write("docs/child.md", index_doc(child))
        self.write(".gitattributes", "*.md text eol=lf\n*.json text eol=lf\n*.py text eol=lf\n")
        self.commit()


class ParserAndStructureTests(RepoCase):
    def test_readme_minimal_index_matches_real_schema(self):
        text = README.read_text(encoding="utf-8")
        section = text.split("## Minimal Index", 1)[1].split("## Recommended Workflow", 1)[0]
        payload = section.split("```project-docs-index\n", 1)[1].split("\n```", 1)[0]

        issues = load_module()._index_issues(json.loads(payload), "README-example.md")

        self.assertEqual([], [issue.as_dict() for issue in issues])

    def test_index_example_inside_longer_fence_is_not_managed_document(self):
        self.basic()
        self.write("docs/schema-example.md", "# Example\n\n````markdown\n```project-docs-index\n{}\n```\n````\n")
        project = load_module().Project.load(self.root)
        self.assertEqual(set(project.documents), {"root", "child"})
        self.assertEqual(len(project.document_list), 2)
        self.assertEqual(project.parse_issues, [])

    def test_extracts_one_index_and_finds_unique_l0(self):
        self.basic()
        mod = load_module()
        project = mod.Project.load(self.root)
        self.assertEqual(project.entry.id, "root")
        self.assertEqual(set(project.documents), {"root", "child"})

    def test_duplicate_id_and_authority_are_blocking(self):
        self.basic()
        meta = {
            "schema_version": 2, "id": "child", "authority_key": "domain.contract",
            "level": 1, "role": "contract", "lifecycle_status": "active",
        }
        self.write("docs/duplicate.md", index_doc(meta))
        mod = load_module()
        report = mod.Project.load(self.root).check()
        codes = {issue.code for issue in report.blocking_errors}
        self.assertIn("DUPLICATE_DOCUMENT_ID", codes)
        self.assertIn("DUPLICATE_AUTHORITY_KEY", codes)

    def test_near_authority_is_warning_only(self):
        self.basic()
        meta = {
            "schema_version": 2, "id": "other", "authority_key": "legacy.domain.contract",
            "level": 1, "role": "contract", "lifecycle_status": "active",
        }
        self.write("docs/other.md", index_doc(meta))
        report = load_module().Project.load(self.root).check()
        self.assertIn("NEAR_DUPLICATE_AUTHORITY_KEY", {x.code for x in report.warnings})

    def test_archive_cannot_be_startup_child_dependency_or_watch_path(self):
        self.basic()
        root_path = self.root / "PROJECT_MAP.md"
        text = root_path.read_text()
        text = text.replace('"AGENTS.md"', '"docs/archive/old.md"')
        self.write("PROJECT_MAP.md", text)
        self.write("docs/archive/old.md", "# Old\n")
        report = load_module().Project.load(self.root).check()
        self.assertIn("ARCHIVE_IN_STARTUP", {x.code for x in report.blocking_errors})

    def test_path_traversal_and_external_symlink_fail(self):
        self.basic()
        child = self.root / "docs/child.md"
        child.write_text(child.read_text().replace('"src/**/*.py"', '"../outside"'))
        report = load_module().Project.load(self.root).check()
        self.assertIn("PATH_OUTSIDE_PROJECT", {x.code for x in report.blocking_errors})

    def test_real_external_symlink_in_watch_paths_is_blocking(self):
        self.basic()
        outside = Path(self.tmp.name).parent / f"outside-{self.root.name}.txt"
        outside.write_text("outside\n", encoding="utf-8")
        try:
            (self.root / "outside-link.txt").symlink_to(outside)
            child = self.read_meta("docs/child.md")
            child["watch_paths"] = ["outside-link.txt"]
            self.write_meta("docs/child.md", child)

            report = load_module().Project.load(self.root).check()

            self.assertIn("PATH_OUTSIDE_PROJECT", {x.code for x in report.blocking_errors})
        finally:
            outside.unlink(missing_ok=True)

    def test_children_cycle_is_blocking(self):
        self.basic()
        child = self.root / "docs/child.md"
        meta = json.loads(child.read_text().split("```project-docs-index\n", 1)[1].split("\n```", 1)[0])
        meta["children"] = [{"id": "root", "path": "PROJECT_MAP.md", "propagation": "summary"}]
        child.write_text(index_doc(meta))
        report = load_module().Project.load(self.root).check()
        self.assertIn("CHILDREN_CYCLE", {x.code for x in report.blocking_errors})

    def test_superseded_target_must_not_remain_active(self):
        self.basic()
        root = self.root / "PROJECT_MAP.md"
        text = root.read_text().replace('"archive_roots"', '"supersedes": ["child"], "archive_roots"')
        root.write_text(text)
        report = load_module().Project.load(self.root).check()
        self.assertIn("SUPERSEDES_ACTIVE_DOCUMENT", {x.code for x in report.blocking_errors})

    def test_active_authoritative_role_requires_authority_key(self):
        self.basic()
        child = self.root / "docs/child.md"
        meta = json.loads(child.read_text().split("```project-docs-index\n", 1)[1].split("\n```", 1)[0])
        meta.pop("authority_key")
        child.write_text(index_doc(meta))
        report = load_module().Project.load(self.root).check()
        self.assertIn("MISSING_AUTHORITY_KEY", {x.code for x in report.blocking_errors})

    def test_l1_budget_is_checked(self):
        self.basic()
        child = self.root / "docs/child.md"
        meta = json.loads(child.read_text().split("```project-docs-index\n", 1)[1].split("\n```", 1)[0])
        meta["startup_budget"] = {"max_files": 1, "max_characters": 1}
        child.write_text(index_doc(meta, body="long module summary"))
        report = load_module().Project.load(self.root).check()
        self.assertIn("MODULE_BUDGET_EXCEEDED", {x.code for x in report.warnings})

    def test_active_dependency_on_archive_is_blocking(self):
        self.basic()
        archived = {
            "schema_version": 2, "id": "old", "level": 2, "role": "reference",
            "lifecycle_status": "archived",
        }
        self.write("docs/archive/old.md", index_doc(archived))
        child = self.root / "docs/child.md"
        meta = json.loads(child.read_text().split("```project-docs-index\n", 1)[1].split("\n```", 1)[0])
        meta["depends_on"] = [{"id": "old", "propagation": "contract"}]
        child.write_text(index_doc(meta))
        report = load_module().Project.load(self.root).check()
        self.assertIn("ACTIVE_DEPENDS_ON_ARCHIVE", {x.code for x in report.blocking_errors})

    def test_startup_budget_counts_duplicate_once(self):
        self.basic()
        root = self.root / "PROJECT_MAP.md"
        meta = json.loads(root.read_text().split("```project-docs-index\n", 1)[1].split("\n```", 1)[0])
        meta["startup"] = ["AGENTS.md", "AGENTS.md"]
        meta["startup_budget"] = {"max_files": 2, "max_characters": 10000}
        root.write_text(index_doc(meta))
        report = load_module().Project.load(self.root).check()
        self.assertNotIn("STARTUP_BUDGET_EXCEEDED", {x.code for x in report.warnings})

    def test_missing_gitattributes_warns_when_autocrlf_enabled(self):
        self.basic()
        (self.root / ".gitattributes").unlink()
        subprocess.run(["git", "config", "core.autocrlf", "true"], cwd=self.root, check=True)
        report = load_module().Project.load(self.root).check()
        self.assertIn("CROSS_PLATFORM_EOL_RISK", {x.code for x in report.warnings})

    def test_read_when_requires_nonempty_any_conditions(self):
        self.basic()
        root = self.read_meta("PROJECT_MAP.md")
        root["read_when"] = {"any": ["the task changes authentication"]}
        self.write_meta("PROJECT_MAP.md", root)
        self.assertNotIn(
            "INVALID_INDEX",
            {issue.code for issue in load_module().Project.load(self.root).check().blocking_errors},
        )

        for invalid in ({}, {"any": "authentication"}, {"any": []}, {"any": [""]}, {"all": ["auth"]}):
            with self.subTest(invalid=invalid):
                root["read_when"] = invalid
                self.write_meta("PROJECT_MAP.md", root)
                self.assertIn(
                    "INVALID_INDEX",
                    {issue.code for issue in load_module().Project.load(self.root).check().blocking_errors},
                )

    def test_relative_paths_reject_windows_and_backslash_forms_on_every_os(self):
        self.basic()
        project = load_module().Project.load(self.root)

        for value in ("C:/secrets.md", "C:\\secrets.md", "\\\\server\\share.md", "docs\\child.md"):
            with self.subTest(value=value):
                self.assertFalse(project._validate_relpath(value))

    def test_windows_markdown_link_is_a_path_error_on_every_os(self):
        self.basic()
        child = self.read_meta("docs/child.md")
        self.write_meta("docs/child.md", child, body="[escape](C:/secrets.md)")

        report = load_module().Project.load(self.root).check()

        self.assertIn("PATH_OUTSIDE_PROJECT", {issue.code for issue in report.blocking_errors})

    def test_valid_markdown_link_destinations_do_not_report_broken_links(self):
        self.basic()
        self.write("docs/foo_(bar).md", "# Parentheses\n")
        self.write("docs/a.md", "# Title destination\n")
        self.write("docs/a(b).md", "# Escaped parentheses\n")
        child = self.read_meta("docs/child.md")
        body = "\n".join((
            "[parenthesized](foo_(bar).md)",
            "[angle](<foo_(bar).md>)",
            "[title](a.md \"optional title\")",
            "[escaped](a\\(b\\).md#section)",
            "[fragment](a.md#section)",
        ))
        self.write_meta("docs/child.md", child, body=body)

        report = load_module().Project.load(self.root).check()

        self.assertNotIn("BROKEN_LINK", {issue.code for issue in report.blocking_errors})


class LockAndImpactTests(RepoCase):
    def test_reports_and_lock_include_tool_version(self):
        self.basic()
        mod = load_module()
        project = mod.Project.load(self.root)

        payload = mod.report_dict(project, project.check())
        project.verify("child", status_effect="initial")
        lock = json.loads((self.root / ".project-docs.lock.json").read_text(encoding="utf-8"))

        self.assertEqual("0.1.0", payload["tool_version"])
        self.assertEqual("0.1.0", lock["tool_version"])

    def test_unverified_then_verify_then_current(self):
        self.basic()
        mod = load_module()
        project = mod.Project.load(self.root)
        self.assertEqual(project.status("child").state, "UNVERIFIED")
        project.verify("child", status_effect="initial")
        project = mod.Project.load(self.root)
        self.assertEqual(project.status("child").state, "CURRENT")

    def test_watch_file_change_makes_document_stale_and_parent_review(self):
        self.basic()
        mod = load_module()
        project = mod.Project.load(self.root)
        project.verify("child", status_effect="initial")
        project.verify("root", status_effect="initial")
        self.commit()
        self.write("src/a.py", "VALUE = 2\n")
        project = mod.Project.load(self.root)
        impact = project.impact()
        states = {r.doc_id: r.state for r in impact.results}
        self.assertEqual(states["child"], "STALE")
        self.assertEqual(states["root"], "REVIEW_REQUIRED")

    def test_status_only_waits_for_classification_and_stops_when_unchanged(self):
        self.basic(propagation="status_only")
        mod = load_module()
        project = mod.Project.load(self.root)
        project.verify("child", status_effect="initial")
        project.verify("root", status_effect="initial")
        self.commit()
        self.write("docs/child.md", (self.root / "docs/child.md").read_text() + "\nDetail.\n")
        project = mod.Project.load(self.root)
        self.assertIn("WAITING_STATUS_CLASSIFICATION", {x.reason for x in project.impact().results if x.doc_id == "root"})
        self.commit()
        project = mod.Project.load(self.root)
        project.verify("child", status_effect="unchanged")
        project = mod.Project.load(self.root)
        self.assertNotIn("root", {x.doc_id for x in project.impact().results})

    def test_verify_refuses_relevant_dirty_paths(self):
        self.basic()
        self.write("src/a.py", "DIRTY = 1\n")
        with self.assertRaisesRegex(ValueError, "VERIFY_REFUSED_RELEVANT_DIRTY_PATH"):
            load_module().Project.load(self.root).verify("child", status_effect="initial")

    def test_lock_corruption_is_blocking(self):
        self.basic()
        self.write(".project-docs.lock.json", "not json")
        report = load_module().Project.load(self.root).check()
        self.assertIn("LOCK_CORRUPTED", {x.code for x in report.blocking_errors})

    def test_contract_change_reaches_declared_consumer(self):
        self.basic()
        consumer = {
            "schema_version": 2, "id": "consumer", "authority_key": "other.consumer",
            "level": 1, "role": "contract", "lifecycle_status": "active",
            "depends_on": [{"id": "child", "propagation": "contract"}],
        }
        self.write("docs/consumer.md", index_doc(consumer))
        root = self.root / "PROJECT_MAP.md"
        meta = json.loads(root.read_text().split("```project-docs-index\n", 1)[1].split("\n```", 1)[0])
        meta["children"].append({"id": "consumer", "path": "docs/consumer.md", "propagation": "link_only"})
        root.write_text(index_doc(meta))
        self.commit()
        mod = load_module(); project = mod.Project.load(self.root)
        project.verify("child", status_effect="initial"); project.verify("consumer", status_effect="unchanged")
        self.commit(); self.write("src/a.py", "VALUE = 9\n")
        results = {x.doc_id: x.state for x in mod.Project.load(self.root).impact().results}
        self.assertEqual(results["consumer"], "REVIEW_REQUIRED")

    def test_status_changed_continues_to_parent(self):
        self.basic(propagation="status_only")
        mod = load_module(); project = mod.Project.load(self.root)
        project.verify("child", status_effect="initial"); project.verify("root", status_effect="initial")
        self.commit(); self.write("docs/child.md", (self.root / "docs/child.md").read_text() + "Changed.\n"); self.commit()
        project = mod.Project.load(self.root); project.verify("child", status_effect="changed")
        result = {x.doc_id: x.state for x in mod.Project.load(self.root).impact().results}
        self.assertEqual(result["root"], "REVIEW_REQUIRED")

    def test_verify_refuses_stale_required_child(self):
        self.basic()
        mod = load_module(); project = mod.Project.load(self.root)
        project.verify("child", status_effect="initial"); self.commit()
        self.write("src/a.py", "VALUE = 7\n"); self.commit()
        with self.assertRaisesRegex(ValueError, "VERIFY_REFUSED_STALE_DEPENDENCY"):
            mod.Project.load(self.root).verify("root", status_effect="initial")

    def test_impact_since_maps_git_change_to_watched_document(self):
        self.basic()
        baseline = subprocess.run(["git", "rev-parse", "HEAD"], cwd=self.root, text=True, capture_output=True, check=True).stdout.strip()
        self.write("src/a.py", "VALUE = 12\n"); self.commit()
        impact = load_module().Project.load(self.root).impact(since=baseline)
        self.assertIn("child", {x.doc_id for x in impact.results})


class CliAndArchiveTests(RepoCase):
    def run_cli(self, *args):
        return subprocess.run([sys.executable, str(SCRIPT), *args], text=True, capture_output=True)

    def test_json_output_and_exit_codes(self):
        self.basic()
        result = self.run_cli("check", str(self.root), "--format", "json")
        self.assertEqual(result.returncode, 1)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["command"], "check")
        self.assertIn("results", payload)

    def test_discover_and_archive_plan_are_read_only(self):
        self.basic()
        self.write("docs/old_snapshot_2020-01-01.md", "# Old\n")
        before = {str(p.relative_to(self.root)): p.read_bytes() for p in self.root.rglob("*") if p.is_file() and ".git" not in p.parts}
        result = self.run_cli("archive-plan", str(self.root), "--format", "json")
        self.assertIn(result.returncode, (0, 1))
        after = {str(p.relative_to(self.root)): p.read_bytes() for p in self.root.rglob("*") if p.is_file() and ".git" not in p.parts}
        self.assertEqual(before, after)
        self.assertTrue(json.loads(result.stdout)["archive_candidates"])

    def test_archive_plan_flags_docs_root_loose_file_and_exact_duplicate(self):
        self.basic()
        self.write("docs/current_system_snapshot.md", "# Historical state\n")
        self.write("docs/copy.md", "# Historical state\n")
        self.write("docs/history.md", "See `docs/current_system_snapshot.md` for evidence.\n")
        report = load_module().Project.load(self.root).archive_plan()
        rows = {row["path"]: row for row in report.archive_candidates}
        self.assertIn("loose_docs_root_document", rows["docs/current_system_snapshot.md"]["reasons"])
        self.assertIn("exact_duplicate", rows["docs/copy.md"]["reasons"])
        self.assertIn("docs/history.md", rows["docs/current_system_snapshot.md"]["inbound_references"])

    def test_hash_only_verify_requires_opt_in(self):
        plain = Path(tempfile.mkdtemp())
        try:
            (plain / "PROJECT_MAP.md").write_text(index_doc({
                "schema_version": 2, "id": "root", "authority_key": "project.entry",
                "level": 0, "role": "project_entry", "lifecycle_status": "active",
            }))
            result = self.run_cli("verify", str(plain), "--doc", "root", "--status-effect", "initial")
            self.assertEqual(result.returncode, 2)
            allowed = self.run_cli("verify", str(plain), "--doc", "root", "--status-effect", "initial", "--allow-hash-only")
            self.assertEqual(allowed.returncode, 0)
        finally:
            import shutil
            shutil.rmtree(plain)


class AdversarialSchemaTests(RepoCase):
    def run_cli(self, *args):
        return subprocess.run([sys.executable, str(SCRIPT), *args], text=True, capture_output=True)

    def test_missing_id_is_invalid_index_without_traceback(self):
        self.basic()
        meta = self.read_meta("docs/child.md")
        meta.pop("id")
        self.write_meta("docs/child.md", meta)

        result = self.run_cli("check", str(self.root), "--format", "json")

        self.assertEqual(result.returncode, 2)
        self.assertNotIn("Traceback", result.stderr)
        payload = json.loads(result.stdout)
        self.assertIn("INVALID_INDEX", {row["code"] for row in payload["blocking_errors"]})

    def test_non_object_index_and_relationship_values_are_reported(self):
        self.basic()
        self.write("docs/not-object.md", "# Bad\n\n```project-docs-index\n[]\n```\n")
        meta = self.read_meta("PROJECT_MAP.md")
        meta["children"] = ["child"]
        self.write_meta("PROJECT_MAP.md", meta)

        result = self.run_cli("check", str(self.root), "--format", "json")

        self.assertEqual(result.returncode, 2)
        self.assertNotIn("Traceback", result.stderr)
        self.assertIn("INVALID_INDEX", {row["code"] for row in json.loads(result.stdout)["blocking_errors"]})

    def test_malformed_startup_and_budget_are_structured_errors(self):
        self.basic()
        root = self.read_meta("PROJECT_MAP.md")
        root["startup"] = [7]
        root["startup_budget"] = "large"
        self.write_meta("PROJECT_MAP.md", root)

        for command in ("check", "impact"):
            result = self.run_cli(command, str(self.root), "--format", "json")
            self.assertEqual(result.returncode, 2, command)
            self.assertNotIn("Traceback", result.stderr, command)
            self.assertIn("INVALID_INDEX", {
                row["code"] for row in json.loads(result.stdout)["blocking_errors"]
            })

    def test_archive_plan_does_not_crash_on_malformed_relationship(self):
        self.basic()
        meta = self.read_meta("PROJECT_MAP.md")
        meta["children"] = ["child"]
        self.write_meta("PROJECT_MAP.md", meta)

        result = self.run_cli("archive-plan", str(self.root), "--format", "json")

        self.assertNotIn("Traceback", result.stderr)
        self.assertIn(result.returncode, (0, 1, 2))
        self.assertEqual(json.loads(result.stdout)["command"], "archive-plan")

    def test_managed_markdown_symlink_outside_project_is_structured_error(self):
        outside = Path(self.tmp.name).parent / f"managed-outside-{self.root.name}.md"
        outside.write_text(index_doc({
            "schema_version": 2, "id": "outside", "authority_key": "outside.contract",
            "level": 1, "role": "contract", "lifecycle_status": "active",
        }), encoding="utf-8")
        try:
            (self.root / "outside.md").symlink_to(outside)

            result = self.run_cli("check", str(self.root), "--format", "json")

            self.assertEqual(result.returncode, 2)
            self.assertNotIn("Traceback", result.stderr)
            self.assertIn("PATH_OUTSIDE_PROJECT", {row["code"] for row in json.loads(result.stdout)["blocking_errors"]})
        finally:
            outside.unlink(missing_ok=True)

    def test_relationships_require_complete_fields_and_existing_targets(self):
        self.basic()
        root = self.read_meta("PROJECT_MAP.md")
        root["children"][0].pop("path")
        child = self.read_meta("docs/child.md")
        child["depends_on"] = [{"id": "missing-contract", "propagation": "contract"}]
        self.write_meta("PROJECT_MAP.md", root)
        self.write_meta("docs/child.md", child)

        report = load_module().Project.load(self.root).check()
        codes = {issue.code for issue in report.blocking_errors}

        self.assertIn("INVALID_INDEX", codes)
        self.assertIn("BROKEN_DEPENDENCY", codes)

    def test_l0_requires_project_entry_role(self):
        self.basic()
        root = self.read_meta("PROJECT_MAP.md")
        root["role"] = "contract"
        self.write_meta("PROJECT_MAP.md", root)

        report = load_module().Project.load(self.root).check()

        self.assertIsNone(load_module().Project.load(self.root).entry)
        self.assertIn("UNMANAGED_PROJECT", {issue.code for issue in report.blocking_errors})


class ArchiveBoundaryRevisionTests(RepoCase):
    def test_active_child_physically_inside_archive_is_blocked(self):
        self.basic()
        child = self.read_meta("docs/child.md")
        (self.root / "docs/child.md").unlink()
        self.write_meta("docs/archive/child.md", child)
        root = self.read_meta("PROJECT_MAP.md")
        root["children"][0]["path"] = "docs/archive/child.md"
        self.write_meta("PROJECT_MAP.md", root)

        report = load_module().Project.load(self.root).check()

        self.assertIn("ARCHIVE_AS_ACTIVE_CHILD", {issue.code for issue in report.blocking_errors})

    def test_watch_glob_that_resolves_archive_file_is_blocked(self):
        self.basic()
        self.write("docs/archive/history.md", "# History\n")
        child = self.read_meta("docs/child.md")
        child["watch_paths"] = ["docs/**/*.md"]
        self.write_meta("docs/child.md", child)

        report = load_module().Project.load(self.root).check()

        self.assertIn("ARCHIVE_IN_WATCH_PATHS", {issue.code for issue in report.blocking_errors})

    def test_l1_archive_root_and_startup_are_enforced(self):
        self.basic()
        self.write("docs/history/old.md", "# Old\n")
        child = self.read_meta("docs/child.md")
        child["archive_roots"] = ["docs/history"]
        child["startup"] = ["docs/history/old.md", "docs/missing.md"]
        self.write_meta("docs/child.md", child)

        report = load_module().Project.load(self.root).check()
        codes = {issue.code for issue in report.blocking_errors}

        self.assertIn("ARCHIVE_IN_STARTUP", codes)
        self.assertIn("BROKEN_LINK", codes)


class LockAndImpactRevisionTests(RepoCase):
    def test_empty_lock_record_is_corrupted(self):
        self.basic()
        self.write(".project-docs.lock.json", json.dumps({
            "schema_version": 2,
            "generated_at": "2026-07-18T00:00:00Z",
            "documents": {"child": {}},
        }))

        report = load_module().Project.load(self.root).check()

        self.assertIn("LOCK_CORRUPTED", {issue.code for issue in report.blocking_errors})

    def test_nested_lock_record_missing_field_is_corrupted(self):
        self.basic()
        mod = load_module()
        mod.Project.load(self.root).verify("child", status_effect="initial")
        lock_path = self.root / ".project-docs.lock.json"
        lock = json.loads(lock_path.read_text(encoding="utf-8"))
        lock["documents"]["child"]["dependencies"].pop("children")
        lock_path.write_text(json.dumps(lock), encoding="utf-8")

        report = mod.Project.load(self.root).check()

        self.assertIn("LOCK_CORRUPTED", {issue.code for issue in report.blocking_errors})

    def test_moved_document_and_authority_change_are_not_current(self):
        self.basic()
        mod = load_module()
        project = mod.Project.load(self.root)
        project.verify("child", status_effect="initial")
        self.commit()
        child = self.read_meta("docs/child.md")
        (self.root / "docs/child.md").unlink()
        self.write_meta("docs/renamed-child.md", child)
        root = self.read_meta("PROJECT_MAP.md")
        root["children"][0]["path"] = "docs/renamed-child.md"
        self.write_meta("PROJECT_MAP.md", root)
        self.commit()

        state = mod.Project.load(self.root).status("child")

        self.assertEqual(state.state, "STALE")
        self.assertIn("identity", state.reason)

    def test_lock_authority_mismatch_is_not_current(self):
        self.basic()
        mod = load_module()
        mod.Project.load(self.root).verify("child", status_effect="initial")
        lock_path = self.root / ".project-docs.lock.json"
        lock = json.loads(lock_path.read_text(encoding="utf-8"))
        lock["documents"]["child"]["authority_key"] = "wrong.authority"
        lock_path.write_text(json.dumps(lock), encoding="utf-8")

        state = mod.Project.load(self.root).status("child")

        self.assertEqual(state.state, "STALE")
        self.assertIn("identity", state.reason)

    def test_impact_inherits_lock_and_structure_errors(self):
        self.basic()
        self.write(".project-docs.lock.json", "not json")

        report = load_module().Project.load(self.root).impact()

        self.assertEqual(report.exit_code, 2)
        self.assertIn("LOCK_CORRUPTED", {issue.code for issue in report.blocking_errors})

    def test_non_status_only_record_cannot_drive_status_propagation(self):
        self.basic(propagation="summary")
        mod = load_module()
        project = mod.Project.load(self.root)
        record = project.verify("child", status_effect="changed")

        self.assertFalse(record["status_effect_applicable"])

    def test_status_only_ignores_changed_record_marked_not_applicable(self):
        self.basic(propagation="status_only")
        mod = load_module()
        project = mod.Project.load(self.root)
        project.verify("child", status_effect="initial")
        project.verify("root", status_effect="initial")
        self.commit()
        lock_path = self.root / ".project-docs.lock.json"
        lock = json.loads(lock_path.read_text(encoding="utf-8"))
        lock["documents"]["child"]["status_effect"] = "changed"
        lock["documents"]["child"]["status_effect_applicable"] = False
        lock_path.write_text(json.dumps(lock), encoding="utf-8")

        results = {row.doc_id for row in mod.Project.load(self.root).impact().results}

        self.assertNotIn("root", results)

    def test_concurrent_lock_change_is_refused(self):
        from unittest import mock

        self.basic()
        mod = load_module()
        project = mod.Project.load(self.root)
        project.verify("child", status_effect="initial")
        self.commit()
        project = mod.Project.load(self.root)
        lock_path = self.root / ".project-docs.lock.json"

        def mutate_lock(_fd):
            lock_path.write_bytes(lock_path.read_bytes() + b" ")

        with mock.patch.object(mod.os, "fsync", side_effect=mutate_lock):
            with self.assertRaisesRegex(ValueError, "LOCK_CONCURRENT_MODIFICATION"):
                project.verify("root", status_effect="initial")

    def test_parallel_verifies_do_not_lose_successful_records(self):
        self.write("AGENTS.md", "# Rules\n")
        children = []
        for index in range(8):
            doc_id = f"child-{index}"
            rel = f"docs/{doc_id}.md"
            self.write_meta(rel, {
                "schema_version": 2,
                "id": doc_id,
                "authority_key": f"domain.contract.{index}",
                "level": 1,
                "role": "contract",
                "lifecycle_status": "active",
            })
            children.append({"id": doc_id, "path": rel, "propagation": "link_only"})
        self.write_meta("PROJECT_MAP.md", {
            "schema_version": 2,
            "id": "root",
            "authority_key": "project.entry",
            "level": 0,
            "role": "project_entry",
            "lifecycle_status": "active",
            "startup": ["AGENTS.md"],
            "children": children,
        })
        self.write(".gitattributes", "*.md text eol=lf\n*.json text eol=lf\n*.py text eol=lf\n")
        self.commit()

        processes = [
            subprocess.Popen(
                [sys.executable, str(SCRIPT), "verify", str(self.root), "--doc", f"child-{index}"],
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            for index in range(8)
        ]
        outcomes = [process.communicate() + (process.returncode,) for process in processes]
        successes = sum(returncode == 0 for _stdout, _stderr, returncode in outcomes)
        lock = json.loads((self.root / ".project-docs.lock.json").read_text(encoding="utf-8"))

        self.assertGreaterEqual(successes, 1)
        self.assertEqual(len(lock["documents"]), successes, outcomes)

    def test_committed_lock_is_consistent_across_clones(self):
        import shutil

        self.basic()
        mod = load_module()
        project = mod.Project.load(self.root)
        project.verify("child", status_effect="initial")
        project.verify("root", status_effect="initial")
        self.commit()
        clone = Path(tempfile.mkdtemp()) / "clone"
        try:
            subprocess.run(["git", "clone", "-q", str(self.root), str(clone)], check=True)
            source_states = {doc_id: mod.Project.load(self.root).status(doc_id).state for doc_id in ("root", "child")}
            clone_states = {doc_id: mod.Project.load(clone).status(doc_id).state for doc_id in ("root", "child")}

            self.assertEqual(source_states, clone_states)
            self.assertEqual(source_states, {"root": "CURRENT", "child": "CURRENT"})
        finally:
            shutil.rmtree(clone.parent)

    def test_check_includes_propagated_review_required(self):
        self.basic()
        mod = load_module()
        project = mod.Project.load(self.root)
        project.verify("child", status_effect="initial")
        project.verify("root", status_effect="initial")
        self.commit()
        self.write("src/a.py", "VALUE = 2\n")

        states = {row.doc_id: row.state for row in mod.Project.load(self.root).check().results}

        self.assertEqual(states["child"], "STALE")
        self.assertEqual(states["root"], "REVIEW_REQUIRED")


class DiscoveryAndArchiveContractTests(RepoCase):
    def test_discover_reports_required_candidate_groups_and_hierarchy(self):
        self.basic()
        self.write("docs/CURRENT_STATUS.md", "# Current status\n")
        self.write("docs/TASK_BOARD.md", "# Tasks\n")
        self.write("docs/collection/INDEX.md", "# Collection module\n")
        self.write("docs/contracts/API_CONTRACT.md", "# API contract\n")
        self.write("docs/runbooks/DEPLOYMENT_RUNBOOK.md", "# Deploy runbook\n")
        self.write("docs/archive/old.md", "# Archived\n")

        payload = load_module().report_dict(load_module().Project.load(self.root), load_module().Project.load(self.root).discover())
        groups = payload["discovery"]

        for key in (
            "l0_candidates", "l1_module_candidates", "status_candidates",
            "task_board_candidates", "contract_candidates", "runbook_candidates",
            "archive_candidates", "loose_root_documents",
            "possible_responsibility_duplicates", "suggested_hierarchy",
        ):
            self.assertIn(key, groups)
        self.assertIn("PROJECT_MAP.md", groups["l0_candidates"])
        self.assertIn("docs/collection/INDEX.md", groups["l1_module_candidates"])

    def test_archive_plan_has_complete_fields_and_merge_candidates(self):
        self.basic()
        self.write("docs/current_status_2026-07-01.md", "# Prior status\n")
        self.write("docs/current_status_2026-07-02.md", "# Other prior status\n")

        report = load_module().Project.load(self.root).archive_plan()
        rows = {row["path"]: row for row in report.archive_candidates}
        candidate = rows["docs/current_status_2026-07-01.md"]

        for key in (
            "path", "classification", "reasons", "inbound_references",
            "suggested_target", "authority_candidate", "risk", "rollback",
        ):
            self.assertIn(key, candidate)
        self.assertEqual(candidate["inbound_references"], [])
        self.assertEqual(candidate["classification"], "POSSIBLE_MERGE_CANDIDATE")


class CliRevisionTests(RepoCase):
    def run_cli(self, *args, cwd=None):
        return subprocess.run([sys.executable, str(SCRIPT), *args], cwd=cwd, text=True, capture_output=True)

    def test_argument_errors_use_exit_code_three(self):
        result = self.run_cli("check")

        self.assertEqual(result.returncode, 3)
        self.assertNotIn("Traceback", result.stderr)

    def test_verify_json_includes_tool_version(self):
        self.basic()

        result = self.run_cli(
            "verify", str(self.root), "--doc", "child",
            "--status-effect", "initial", "--format", "json",
        )

        self.assertEqual(0, result.returncode)
        self.assertEqual("0.1.0", json.loads(result.stdout)["tool_version"])

    def test_runnable_demo_exercises_current_and_stale_workflow(self):
        result = subprocess.run(
            [sys.executable, str(DEMO)], text=True, capture_output=True,
        )

        self.assertEqual(0, result.returncode, result.stderr)
        self.assertIn("all 4 documents CURRENT", result.stdout)
        self.assertIn("impact exit code 1 accepted", result.stdout)

    def test_hash_only_reports_explicit_warning(self):
        plain = Path(tempfile.mkdtemp())
        try:
            (plain / "PROJECT_MAP.md").write_text(index_doc({
                "schema_version": 2, "id": "root", "authority_key": "project.entry",
                "level": 0, "role": "project_entry", "lifecycle_status": "active",
            }), encoding="utf-8")

            result = self.run_cli("check", str(plain), "--format", "json")
            payload = json.loads(result.stdout)

            self.assertIn("HASH_ONLY_MODE", {row["code"] for row in payload["warnings"]})
        finally:
            import shutil
            shutil.rmtree(plain)


class R3RegressionTests(RepoCase):
    def test_uncommitted_rename_out_of_watch_pattern_blocks_verify(self):
        self.basic()
        mod = load_module()
        project = mod.Project.load(self.root)
        project.verify("child", status_effect="initial")
        self.commit()

        self.write("moved/.keep", "")
        subprocess.run(["git", "add", "moved/.keep"], cwd=self.root, check=True)
        subprocess.run(["git", "commit", "-qm", "add destination"], cwd=self.root, check=True)
        subprocess.run(["git", "mv", "src/a.py", "moved/a.txt"], cwd=self.root, check=True)

        project = mod.Project.load(self.root)
        self.assertIn("src/a.py", project._dirty_paths())
        with self.assertRaisesRegex(ValueError, "VERIFY_REFUSED_RELEVANT_DIRTY_PATH"):
            project.verify("child", status_effect="changed")

    def test_dirty_watched_path_with_spaces_blocks_verify(self):
        self.basic()
        self.write("src/a b.py", "VALUE = 1\n")
        self.commit()
        mod = load_module()
        project = mod.Project.load(self.root)
        project.verify("child", status_effect="initial")
        self.commit()

        self.write("src/a b.py", "VALUE = 2\n")
        project = mod.Project.load(self.root)
        self.assertIn("src/a b.py", project._dirty_paths())
        with self.assertRaisesRegex(ValueError, "VERIFY_REFUSED_RELEVANT_DIRTY_PATH"):
            project.verify("child", status_effect="changed")

    def test_impact_since_rename_uses_old_and_new_paths(self):
        self.basic()
        mod = load_module()
        project = mod.Project.load(self.root)
        project.verify("child", status_effect="initial")
        project.verify("root", status_effect="initial")
        self.commit()
        baseline = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=self.root, text=True, capture_output=True, check=True
        ).stdout.strip()

        self.write("moved/.keep", "")
        subprocess.run(["git", "add", "moved/.keep"], cwd=self.root, check=True)
        subprocess.run(["git", "commit", "-qm", "add destination"], cwd=self.root, check=True)
        subprocess.run(["git", "mv", "src/a.py", "moved/a.txt"], cwd=self.root, check=True)
        subprocess.run(["git", "commit", "-qm", "rename watched file"], cwd=self.root, check=True)

        report = mod.Project.load(self.root).impact(since=baseline)
        states = {row.doc_id: row.state for row in report.results}
        self.assertEqual(states.get("child"), "STALE")
        self.assertEqual(states.get("root"), "REVIEW_REQUIRED")

    def test_archived_and_superseded_documents_do_not_enter_current_impact_graph(self):
        self.basic()
        archived = {
            "schema_version": 2, "id": "old-parent", "level": 1,
            "role": "module_index", "lifecycle_status": "archived",
            "children": [{"id": "child", "path": "docs/child.md", "propagation": "summary"}],
        }
        superseded = {
            "schema_version": 2, "id": "old-consumer", "level": 1,
            "role": "contract", "lifecycle_status": "superseded",
            "depends_on": [{"id": "child", "propagation": "contract"}],
        }
        self.write("docs/archive/old-parent.md", index_doc(archived))
        self.write("docs/old-consumer.md", index_doc(superseded))
        self.commit()

        mod = load_module()
        project = mod.Project.load(self.root)
        project.verify("child", status_effect="initial")
        project.verify("root", status_effect="initial")
        self.commit()
        self.write("src/a.py", "VALUE = 2\n")

        report = mod.Project.load(self.root).impact()
        affected = {row.doc_id for row in report.results}
        self.assertIn("child", affected)
        self.assertIn("root", affected)
        self.assertNotIn("old-parent", affected)
        self.assertNotIn("old-consumer", affected)

    def test_verify_refuses_non_active_documents(self):
        self.basic()
        meta = {
            "schema_version": 2, "id": "old", "level": 1,
            "role": "reference", "lifecycle_status": "archived",
        }
        self.write("docs/archive/old.md", index_doc(meta))
        self.commit()

        with self.assertRaisesRegex(ValueError, "VERIFY_REFUSED_NON_ACTIVE_DOCUMENT"):
            load_module().Project.load(self.root).verify("old")

    def test_non_active_l1_archive_root_does_not_reclassify_current_files(self):
        self.basic()
        root = self.read_meta("PROJECT_MAP.md")
        root["children"][0]["path"] = "docs/live/child.md"
        self.write_meta("PROJECT_MAP.md", root)
        (self.root / "docs/live").mkdir(parents=True, exist_ok=True)
        (self.root / "docs/child.md").replace(self.root / "docs/live/child.md")
        old_index = {
            "schema_version": 2, "id": "old-index", "level": 1,
            "role": "module_index", "lifecycle_status": "superseded",
            "archive_roots": ["docs/live"],
        }
        self.write("docs/old-index.md", index_doc(old_index))

        report = load_module().Project.load(self.root).check()
        codes = {issue.code for issue in report.blocking_errors}
        self.assertNotIn("ACTIVE_DOCUMENT_IN_ARCHIVE", codes)
        self.assertNotIn("ARCHIVE_AS_ACTIVE_CHILD", codes)


if __name__ == "__main__":
    unittest.main()
