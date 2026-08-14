#!/usr/bin/env python3
"""Run the Driftlock happy path and one intentional stale transition."""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path


REPOSITORY = Path(__file__).resolve().parents[1]
CLI = REPOSITORY / "scripts" / "driftlock.py"
FIXTURE = Path(__file__).resolve().parent / "demo-project"


def run(project, *args, expected=(0,)):
    result = subprocess.run(
        [sys.executable, str(CLI), *args, str(project), "--format", "json"],
        text=True,
        capture_output=True,
    )
    if result.returncode not in expected:
        raise RuntimeError(
            f"command {args[0]} returned {result.returncode}\n"
            f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
        )
    return json.loads(result.stdout)


def git(project, *args):
    subprocess.run(["git", *args], cwd=project, check=True, capture_output=True)


def main():
    with tempfile.TemporaryDirectory() as temporary:
        project = Path(temporary) / "demo-project"
        shutil.copytree(FIXTURE, project)
        git(project, "init", "-q")
        git(project, "config", "user.email", "demo@example.com")
        git(project, "config", "user.name", "Driftlock Demo")
        git(project, "add", ".")
        git(project, "commit", "-qm", "initial demo")

        for doc_id in (
            "demo-auth-contract",
            "demo-billing-contract",
            "demo-backend-index",
            "demo-project-entry",
        ):
            run(project, "verify", "--doc", doc_id, "--status-effect", "initial")
        git(project, "add", ".driftlock.lock.json")
        git(project, "commit", "-qm", "verify documentation")

        current = run(project, "check")
        states = {item["doc_id"]: item["state"] for item in current["results"]}
        if set(states.values()) != {"CURRENT"}:
            raise RuntimeError(f"expected all CURRENT, got {states}")

        auth_source = project / "src" / "auth" / "session.py"
        auth_source.write_text(auth_source.read_text(encoding="utf-8") + "\n# Contract change.\n", encoding="utf-8")
        impact = run(project, "impact", expected=(1,))
        changed = {item["doc_id"]: item["state"] for item in impact["results"]}
        expected = {
            "demo-auth-contract": "STALE",
            "demo-backend-index": "REVIEW_REQUIRED",
            "demo-project-entry": "REVIEW_REQUIRED",
        }
        if changed != expected:
            raise RuntimeError(f"unexpected impact: {changed}")
        if "demo-billing-contract" in impact["update_queue"]:
            raise RuntimeError("unrelated billing contract entered the update queue")

        print("initial: all 4 documents CURRENT")
        print("after auth code change: auth STALE, backend and project REVIEW_REQUIRED")
        print("impact exit code 1 accepted as non-blocking; unrelated billing stayed out")


if __name__ == "__main__":
    main()
