#!/usr/bin/env python3
"""Deterministic documentation graph and freshness manager.

All commands are read-only except ``verify``, which atomically updates
``.driftlock.lock.json``. The implementation uses only the Python standard
library and never rewrites Markdown content.
"""

from __future__ import annotations

import argparse
import bisect
import fnmatch
import hashlib
import json
import os
import re
import stat
import subprocess
import time
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from urllib.parse import urlsplit


SCHEMA_VERSION = 2
TOOL_VERSION = "0.2.1"
ASCII_PUNCTUATION = frozenset(r"!\"#$%&'()*+,-./:;<=>?@[\]^_`{|}~")
ROLES = {
    "project_entry", "module_index", "submodule_index", "status", "task_board",
    "contract", "runbook", "reference", "task", "report", "archive_index",
}
AUTHORITATIVE_ROLES = {
    "project_entry", "module_index", "submodule_index", "status", "task_board",
    "contract", "runbook",
}
LIFECYCLES = {"active", "superseded", "archived"}
PROPAGATIONS = {"link_only", "summary", "status_only", "contract"}
IGNORED_DIRS = {".git", ".venv", "venv", "node_modules", "__pycache__"}
HEX_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
MAX_MARKDOWN_BYTES = 16 * 1024 * 1024
MAX_LOCK_BYTES = 16 * 1024 * 1024
MAX_CONFIG_BYTES = 1024 * 1024
MAX_GUARD_BYTES = 4096
HASH_CHUNK_BYTES = 1024 * 1024
GUARD_STALE_SECONDS = 300
FILE_SAFETY_CODES = {"PATH_OUTSIDE_PROJECT", "SYMLINK_NOT_ALLOWED", "NON_REGULAR_FILE", "FILE_TOO_LARGE", "UNSAFE_FILE"}


def _file_safety_code(exc, default="DOCUMENT_READ_ERROR"):
    code = str(exc).split(":", 1)[0]
    return code if code in FILE_SAFETY_CODES else default


def sha256_bytes(data):
    return hashlib.sha256(data).hexdigest()


def utc_now():
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def is_external_uri(value):
    return value.startswith("//") or bool(urlsplit(value).scheme)


def _code_span_ranges(text):
    """Return paired backtick ranges so link-looking code remains inert."""
    runs = [(match.start(), match.end(), len(match.group(0))) for match in re.finditer(r"`+", text)]
    positions = {}
    for start, _end, length in runs:
        positions.setdefault(length, []).append(start)
    ranges = []
    run_index = 0
    while run_index < len(runs):
        start, _end, length = runs[run_index]
        candidates = positions[length]
        position = bisect.bisect_right(candidates, start)
        if position >= len(candidates):
            run_index += 1
            continue
        close_start = candidates[position]
        close_end = close_start + length
        ranges.append((start, close_end))
        while run_index < len(runs) and runs[run_index][0] < close_end:
            run_index += 1
    return ranges


def _link_close(text, index):
    quote = None
    escaped = False
    while index < len(text):
        char = text[index]
        if escaped:
            escaped = False
        elif char == "\\" and index + 1 < len(text) and text[index + 1] in ASCII_PUNCTUATION:
            escaped = True
        elif quote:
            if char == quote:
                quote = None
        elif char in {'"', "'"}:
            quote = char
        elif char == ")":
            return index
        index += 1
    return None


def _inline_link_destination(text, index):
    while index < len(text) and text[index].isspace():
        index += 1
    if index >= len(text):
        return None, index

    if text[index] == "<":
        end = index + 1
        while end < len(text) and text[end] != ">":
            end += 1
        if end >= len(text):
            return None, len(text)
        close = _link_close(text, end + 1)
        return (text[index + 1:end], close + 1) if close is not None else (None, len(text))

    value = []
    depth = 0
    while index < len(text):
        char = text[index]
        if char == "\\":
            if index + 1 < len(text) and text[index + 1] in ASCII_PUNCTUATION:
                value.append(text[index + 1])
                index += 2
                continue
            value.append(char)
        elif char == "(":
            depth += 1
            value.append(char)
        elif char == ")":
            if depth == 0:
                return ("".join(value), index + 1) if value else (None, index + 1)
            depth -= 1
            value.append(char)
        elif char.isspace() and depth == 0:
            close = _link_close(text, index)
            return ("".join(value), close + 1) if value and close is not None else (None, len(text))
        else:
            value.append(char)
        index += 1
    return None, len(text)


def markdown_link_destinations(text):
    """Return inline Markdown link destinations in one forward scan."""
    destinations = []
    code_ranges = _code_span_ranges(text)
    code_index = 0
    cursor = 0
    while cursor < len(text):
        if code_index < len(code_ranges) and cursor >= code_ranges[code_index][0]:
            cursor = code_ranges[code_index][1]
            code_index += 1
            continue
        if text[cursor] != "[":
            cursor += 1
            continue

        is_image = cursor > 0 and text[cursor - 1] == "!"
        label_depth = 1
        index = cursor + 1
        while index < len(text) and label_depth:
            char = text[index]
            if char == "\\" and index + 1 < len(text) and text[index + 1] in ASCII_PUNCTUATION:
                index += 2
                continue
            if char == "[":
                label_depth += 1
            elif char == "]":
                label_depth -= 1
            index += 1
        if label_depth:
            break
        if index >= len(text) or text[index] != "(":
            cursor = index
            continue
        destination, cursor = _inline_link_destination(text, index + 1)
        if destination is not None and not is_image:
            destinations.append(destination)
    return destinations


def extract_index_blocks(text):
    """Extract top-level driftlock fences while respecting longer fences."""
    blocks, active = [], None
    capture = None
    for line in text.splitlines():
        match = re.match(r"^ {0,3}(`{3,}|~{3,})(.*)$", line)
        if active is None:
            if not match:
                continue
            fence, info = match.group(1), match.group(2).strip()
            active = (fence[0], len(fence))
            capture = [] if info == "driftlock-index" else None
            continue
        if match and match.group(1)[0] == active[0] and len(match.group(1)) >= active[1] and not match.group(2).strip():
            if capture is not None:
                blocks.append("\n".join(capture))
            active, capture = None, None
            continue
        if capture is not None:
            capture.append(line)
    return blocks


def run_git(root, *args):
    return subprocess.run(["git", *args], cwd=root, text=True, capture_output=True)


def git_root(root):
    result = run_git(root, "rev-parse", "--show-toplevel")
    return Path(result.stdout.strip()).resolve() if result.returncode == 0 else None


def rel_posix(path, root):
    return path.resolve().relative_to(root.resolve()).as_posix()


class Issue:
    def __init__(self, code, message, path=None):
        self.code, self.message, self.path = code, message, path

    def as_dict(self):
        value = {"code": self.code, "message": self.message}
        if self.path:
            value["path"] = self.path
        return value


class Result:
    def __init__(self, doc_id, state, reason=""):
        self.doc_id, self.state, self.reason = doc_id, state, reason

    def as_dict(self):
        return {"doc_id": self.doc_id, "state": self.state, "reason": self.reason}


class Report:
    def __init__(self, command="check"):
        self.command = command
        self.results = []
        self.blocking_errors = []
        self.warnings = []
        self.update_queue = []
        self.archive_candidates = []
        self.discovery = {}

    @property
    def exit_code(self):
        if self.blocking_errors:
            return 2
        if any(x.state in {"STALE", "REVIEW_REQUIRED", "UNVERIFIED"} for x in self.results):
            return 1
        return 0


class Document:
    def __init__(self, path, relpath, meta, raw):
        self.path, self.relpath, self.meta, self.raw = path, relpath, meta, raw
        self.id = meta.get("id") if isinstance(meta.get("id"), str) else ""
        self.authority_key = meta.get("authority_key")
        self.level = meta.get("level")
        self.role = meta.get("role")
        self.lifecycle = meta.get("lifecycle_status")
        self.children = [
            item for item in meta.get("children", []) if isinstance(item, dict)
        ] if isinstance(meta.get("children", []), list) else []
        self.depends_on = [
            item for item in meta.get("depends_on", []) if isinstance(item, dict)
        ] if isinstance(meta.get("depends_on", []), list) else []
        self.watch_paths = [
            item for item in meta.get("watch_paths", []) if _nonempty_string(item)
        ] if isinstance(meta.get("watch_paths", []), list) else []
        self.startup = [
            item for item in meta.get("startup", []) if _nonempty_string(item)
        ] if isinstance(meta.get("startup", []), list) else []
        self.startup_budget = meta.get("startup_budget") if isinstance(meta.get("startup_budget"), dict) else {}
        self.archive_roots = [
            item for item in meta.get("archive_roots", []) if _nonempty_string(item)
        ] if isinstance(meta.get("archive_roots", []), list) else []
        self.supersedes = [
            item for item in meta.get("supersedes", []) if _nonempty_string(item)
        ] if isinstance(meta.get("supersedes", []), list) else []
        self.content_sha256 = sha256_bytes(raw)


def _nonempty_string(value):
    return isinstance(value, str) and bool(value.strip())


def _index_issues(meta, relpath):
    issues = []
    if not isinstance(meta, dict):
        return [Issue("INVALID_INDEX", "index JSON must be an object", relpath)]
    if meta.get("schema_version") != SCHEMA_VERSION:
        issues.append(Issue("INVALID_INDEX", f"schema_version must be {SCHEMA_VERSION}", relpath))
    if not _nonempty_string(meta.get("id")):
        issues.append(Issue("INVALID_INDEX", "id must be a non-empty string", relpath))
    level = meta.get("level")
    if isinstance(level, bool) or not isinstance(level, int) or level < 0:
        issues.append(Issue("INVALID_INDEX", "level must be a non-negative integer", relpath))
    if meta.get("role") not in ROLES:
        issues.append(Issue("INVALID_INDEX", "role is invalid", relpath))
    if meta.get("lifecycle_status") not in LIFECYCLES:
        issues.append(Issue("INVALID_INDEX", "lifecycle_status is invalid", relpath))
    if "authority_key" in meta and meta.get("authority_key") is not None and not _nonempty_string(meta.get("authority_key")):
        issues.append(Issue("INVALID_INDEX", "authority_key must be a non-empty string", relpath))

    for field in ("startup", "watch_paths", "archive_roots", "supersedes"):
        value = meta.get(field, [])
        if not isinstance(value, list) or any(not _nonempty_string(item) for item in value):
            issues.append(Issue("INVALID_INDEX", f"{field} must be a list of non-empty strings", relpath))

    for field in ("children", "depends_on"):
        value = meta.get(field, [])
        if not isinstance(value, list):
            issues.append(Issue("INVALID_INDEX", f"{field} must be a list", relpath))
            continue
        for index, edge in enumerate(value):
            required = ("id", "path", "propagation") if field == "children" else ("id", "propagation")
            if not isinstance(edge, dict):
                issues.append(Issue("INVALID_INDEX", f"{field}[{index}] must be an object", relpath))
                continue
            if any(not _nonempty_string(edge.get(key)) for key in required):
                issues.append(Issue("INVALID_INDEX", f"{field}[{index}] is missing required fields", relpath))
            if edge.get("propagation") not in PROPAGATIONS:
                issues.append(Issue("INVALID_INDEX", f"{field}[{index}] propagation is invalid", relpath))

    budget = meta.get("startup_budget")
    if budget is not None:
        if not isinstance(budget, dict):
            issues.append(Issue("INVALID_INDEX", "startup_budget must be an object", relpath))
        else:
            for field in ("max_files", "max_characters"):
                value = budget.get(field)
                if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
                    issues.append(Issue("INVALID_INDEX", f"startup_budget.{field} must be a positive integer", relpath))
    if "read_when" in meta:
        read_when = meta.get("read_when")
        if (
            not isinstance(read_when, dict)
            or set(read_when) != {"any"}
            or not isinstance(read_when.get("any"), list)
            or not read_when["any"]
            or any(not _nonempty_string(item) for item in read_when["any"])
        ):
            issues.append(Issue(
                "INVALID_INDEX",
                "read_when must be an object with exactly one non-empty any string list",
                relpath,
            ))
    return issues


class Project:
    def __init__(self, root):
        self.root = Path(root).resolve()
        self.git_root = git_root(self.root)
        self.documents = {}
        self.document_list = []
        self.parse_issues = []
        self.lock_error = None
        self.lock = {"schema_version": SCHEMA_VERSION, "tool_version": TOOL_VERSION, "documents": {}}
        self.lock_bytes = b""
        self._load_documents()
        self._load_lock()

    @classmethod
    def load(cls, root):
        return cls(root)

    @property
    def entry(self):
        entries = [
            d for d in self.document_list
            if d.level == 0 and d.role == "project_entry" and d.lifecycle == "active"
        ]
        return entries[0] if len(entries) == 1 else None

    def _markdown_files(self):
        for current, dirs, files in os.walk(self.root):
            dirs[:] = sorted(d for d in dirs if d not in IGNORED_DIRS)
            base = Path(current)
            for name in sorted(files):
                if name.lower().endswith(".md"):
                    yield base / name

    def _safe_regular_path(self, path, max_bytes=None):
        """Resolve a project file and reject unsafe file types before reading."""
        path = Path(path)
        info = path.lstat()
        try:
            resolved = path.resolve(strict=True)
        except (OSError, RuntimeError) as exc:
            raise ValueError(f"UNSAFE_FILE: {path}") from exc
        try:
            resolved.relative_to(self.root)
        except ValueError as exc:
            raise ValueError(f"PATH_OUTSIDE_PROJECT: {path}") from exc
        if stat.S_ISLNK(info.st_mode):
            raise ValueError(f"SYMLINK_NOT_ALLOWED: {path}")
        if not stat.S_ISREG(info.st_mode):
            raise ValueError(f"NON_REGULAR_FILE: {path}")
        if max_bytes is not None and info.st_size > max_bytes:
            raise ValueError(f"FILE_TOO_LARGE: {path} ({info.st_size} > {max_bytes})")
        return resolved

    def _open_regular_file(self, path, max_bytes=None):
        resolved = self._safe_regular_path(path, max_bytes=max_bytes)
        flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)
        fd = None
        try:
            fd = os.open(str(resolved), flags)
            info = os.fstat(fd)
            if not stat.S_ISREG(info.st_mode):
                raise ValueError(f"NON_REGULAR_FILE: {path}")
            if max_bytes is not None and info.st_size > max_bytes:
                raise ValueError(f"FILE_TOO_LARGE: {path} ({info.st_size} > {max_bytes})")
            return resolved, fd
        except Exception:
            if fd is not None:
                os.close(fd)
            raise

    def _read_file_bytes(self, path, max_bytes):
        resolved, fd = self._open_regular_file(path, max_bytes=max_bytes)
        with os.fdopen(fd, "rb") as handle:
            data = handle.read(max_bytes + 1)
        if len(data) > max_bytes:
            raise ValueError(f"FILE_TOO_LARGE: {path} (> {max_bytes})")
        return resolved, data

    def _release_guard(self, guard_path, guard_fd, guard_token):
        """Release only the guard instance owned by this verify call."""
        if guard_fd is None:
            return
        os.close(guard_fd)
        try:
            _resolved, current_token = self._read_file_bytes(guard_path, MAX_GUARD_BYTES)
        except (OSError, ValueError):
            return
        if current_token != guard_token:
            return
        try:
            guard_path.unlink()
        except FileNotFoundError:
            pass

    def _safe_markdown_entries(self, report):
        for path in self._markdown_files():
            try:
                resolved = self._safe_regular_path(path, max_bytes=MAX_MARKDOWN_BYTES)
                yield resolved, rel_posix(resolved, self.root)
            except ValueError as exc:
                report.blocking_errors.append(Issue(
                    _file_safety_code(exc),
                    str(exc),
                    os.path.relpath(path, self.root),
                ))
            except OSError as exc:
                report.blocking_errors.append(Issue(
                    "DOCUMENT_READ_ERROR", str(exc), os.path.relpath(path, self.root)
                ))

    def _load_documents(self):
        for path in self._markdown_files():
            try:
                resolved, raw = self._read_file_bytes(path, MAX_MARKDOWN_BYTES)
                text = raw.decode("utf-8", errors="strict")
            except ValueError as exc:
                self.parse_issues.append(Issue(
                    _file_safety_code(exc), str(exc), os.path.relpath(path, self.root)
                ))
                continue
            except (OSError, UnicodeDecodeError) as exc:
                self.parse_issues.append(Issue("DOCUMENT_READ_ERROR", str(exc), str(path)))
                continue
            matches = extract_index_blocks(text)
            if not matches:
                continue
            rel = rel_posix(resolved, self.root)
            if len(matches) != 1:
                self.parse_issues.append(Issue("INVALID_INDEX", "document must contain exactly one index", rel))
                continue
            try:
                meta = json.loads(matches[0])
            except json.JSONDecodeError as exc:
                self.parse_issues.append(Issue("INVALID_INDEX", str(exc), rel))
                continue
            issues = _index_issues(meta, rel)
            self.parse_issues.extend(issues)
            if not isinstance(meta, dict):
                continue
            doc = Document(resolved, rel, meta, raw)
            doc.content_sha256 = self._file_sha256(resolved, raw)
            self.document_list.append(doc)
            if doc.id and doc.id not in self.documents:
                self.documents[doc.id] = doc

    def _load_lock(self):
        path = self.root / ".driftlock.lock.json"
        if not path.exists():
            return
        try:
            _resolved, raw = self._read_file_bytes(path, MAX_LOCK_BYTES)
            value = json.loads(raw.decode("utf-8"))
            self._validate_lock(value)
            self.lock = value
            self.lock_bytes = raw
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            self.lock_error = Issue("LOCK_CORRUPTED", f"rebuild with verify: {exc}", ".driftlock.lock.json")

    def _validate_lock(self, value):
        if not isinstance(value, dict):
            raise ValueError("lock JSON must be an object")
        if value.get("schema_version") != SCHEMA_VERSION:
            raise ValueError("unsupported lock schema")
        if "tool_version" in value and not _nonempty_string(value.get("tool_version")):
            raise ValueError("invalid tool_version")
        if not _nonempty_string(value.get("generated_at")):
            raise ValueError("missing generated_at")
        documents = value.get("documents")
        if not isinstance(documents, dict):
            raise ValueError("documents must be an object")
        for doc_id, record in documents.items():
            if not _nonempty_string(doc_id) or not isinstance(record, dict):
                raise ValueError(f"invalid document record: {doc_id!r}")
            required = {
                "path", "authority_key", "content_sha256", "verified_commit",
                "verified_at", "status_effect", "status_effect_applicable", "dependencies",
            }
            missing = required.difference(record)
            if missing:
                raise ValueError(f"document {doc_id} missing fields: {','.join(sorted(missing))}")
            if not _nonempty_string(record["path"]) or not self._validate_relpath(record["path"]):
                raise ValueError(f"document {doc_id} has invalid path")
            if record["authority_key"] is not None and not _nonempty_string(record["authority_key"]):
                raise ValueError(f"document {doc_id} has invalid authority_key")
            if not isinstance(record["content_sha256"], str) or not HEX_SHA256_RE.fullmatch(record["content_sha256"]):
                raise ValueError(f"document {doc_id} has invalid content hash")
            if record["verified_commit"] is not None and not _nonempty_string(record["verified_commit"]):
                raise ValueError(f"document {doc_id} has invalid verified_commit")
            if not _nonempty_string(record["verified_at"]):
                raise ValueError(f"document {doc_id} has invalid verified_at")
            if record["status_effect"] not in {"initial", "changed", "unchanged"}:
                raise ValueError(f"document {doc_id} has invalid status_effect")
            if not isinstance(record["status_effect_applicable"], bool):
                raise ValueError(f"document {doc_id} has invalid status_effect_applicable")
            self._validate_lock_dependencies(doc_id, record["dependencies"])

    def _validate_lock_dependencies(self, doc_id, dependencies):
        if not isinstance(dependencies, dict) or set(dependencies) != {"documents", "children", "watch_paths"}:
            raise ValueError(f"document {doc_id} has invalid dependencies")
        for field in ("documents", "children", "watch_paths"):
            if not isinstance(dependencies[field], list):
                raise ValueError(f"document {doc_id} dependencies.{field} must be a list")
        for item in dependencies["documents"]:
            if not isinstance(item, dict) or not _nonempty_string(item.get("id")) or not HEX_SHA256_RE.fullmatch(str(item.get("content_sha256", ""))):
                raise ValueError(f"document {doc_id} has invalid dependency record")
        for item in dependencies["children"]:
            if (
                not isinstance(item, dict)
                or not _nonempty_string(item.get("id"))
                or item.get("propagation") not in PROPAGATIONS
                or not HEX_SHA256_RE.fullmatch(str(item.get("content_sha256", "")))
            ):
                raise ValueError(f"document {doc_id} has invalid child record")
        for item in dependencies["watch_paths"]:
            if not isinstance(item, dict) or not _nonempty_string(item.get("pattern")) or not isinstance(item.get("resolved_files"), list):
                raise ValueError(f"document {doc_id} has invalid watch record")
            for resolved in item["resolved_files"]:
                if (
                    not isinstance(resolved, dict)
                    or not _nonempty_string(resolved.get("path"))
                    or not self._validate_relpath(resolved.get("path"))
                    or not HEX_SHA256_RE.fullmatch(str(resolved.get("sha256", "")))
                ):
                    raise ValueError(f"document {doc_id} has invalid resolved watch file")

    def _archive_roots(self):
        """Return archive roots declared by the current active L0/L1 indexes."""
        roots = []
        for doc in self.document_list:
            if doc.lifecycle == "active" and doc.level in {0, 1}:
                roots.extend(root for root in doc.archive_roots if self._validate_relpath(root))
        return tuple(dict.fromkeys(roots))

    def _is_archive_path(self, rel):
        if not isinstance(rel, str):
            return False
        roots = self._archive_roots()
        rel = PurePosixPath(rel)
        return any(rel == PurePosixPath(root) or PurePosixPath(root) in rel.parents for root in roots)

    def _file_sha256(self, path, data=None):
        """Hash safe regular files without loading watched files into memory."""
        resolved = self._safe_regular_path(path)
        rel = rel_posix(resolved, self.root)
        normalize_lf = False
        if self.git_root:
            attr = run_git(self.root, "check-attr", "-z", "eol", "--", rel)
            fields = attr.stdout.split("\0") if attr.returncode == 0 else []
            normalize_lf = len(fields) >= 3 and fields[1] == "eol" and fields[2] == "lf"
        if data is not None:
            if normalize_lf:
                data = data.replace(b"\r\n", b"\n")
            return sha256_bytes(data)

        _resolved, fd = self._open_regular_file(resolved)
        digest = hashlib.sha256()
        carry = b""
        with os.fdopen(fd, "rb") as handle:
            while True:
                chunk = handle.read(HASH_CHUNK_BYTES)
                if not chunk:
                    break
                if normalize_lf:
                    chunk = carry + chunk
                    if chunk.endswith(b"\r"):
                        carry, chunk = b"\r", chunk[:-1]
                    else:
                        carry = b""
                    digest.update(chunk.replace(b"\r\n", b"\n"))
                else:
                    digest.update(chunk)
            if normalize_lf and carry:
                digest.update(carry)
        return digest.hexdigest()

    def _validate_relpath(self, value):
        if (
            not isinstance(value, str)
            or not value
            or "\\" in value
            or re.match(r"^[A-Za-z]:", value)
            or Path(value).is_absolute()
            or PurePosixPath(value).is_absolute()
            or ".." in PurePosixPath(value).parts
        ):
            return False

        # Glob patterns are syntax, not concrete filesystem paths. Resolve only
        # their literal prefix; concrete matches are containment-checked again
        # in _resolved_pattern before any matched file is read.
        static_parts = []
        for part in PurePosixPath(value).parts:
            if any(char in part for char in "*?["):
                break
            static_parts.append(part)
        try:
            target = self.root.joinpath(*static_parts).resolve()
            target.relative_to(self.root)
        except (OSError, ValueError):
            return False
        return True

    def _graph_cycle(self, relation):
        """Detect cycles only in the current active document graph.

        Superseded and archived documents are historical evidence and must not
        participate in the current routing or propagation graph.
        """
        active = {d.id: d for d in self.document_list if d.id and d.lifecycle == "active"}
        graph = {doc_id: [] for doc_id in active}
        for doc in active.values():
            for edge in getattr(doc, relation):
                target = edge.get("id") if isinstance(edge, dict) else None
                if target in active:
                    graph[doc.id].append(target)
        visiting, visited = [], set()
        def visit(node):
            if node in visiting:
                return visiting[visiting.index(node):] + [node]
            if node in visited:
                return None
            visiting.append(node)
            for target in graph[node]:
                cycle = visit(target)
                if cycle:
                    return cycle
            visiting.pop(); visited.add(node)
            return None
        for node in graph:
            cycle = visit(node)
            if cycle:
                return cycle
        return None

    def _reachable(self):
        if not self.entry:
            return set()
        seen, stack = set(), [self.entry.id]
        while stack:
            item = stack.pop()
            if item in seen:
                continue
            doc = self.documents.get(item)
            if not doc or doc.lifecycle != "active":
                continue
            seen.add(item)
            for edge in doc.children:
                target = self.documents.get(edge.get("id")) if isinstance(edge, dict) else None
                if target and target.lifecycle == "active":
                    stack.append(target.id)
        return seen

    def _resolved_pattern(self, pattern):
        if not self._validate_relpath(pattern):
            raise ValueError(f"PATH_OUTSIDE_PROJECT: {pattern}")
        base = self.root / pattern
        if not any(c in pattern for c in "*?[") and base.is_dir():
            paths = [p for p in base.rglob("*") if p.is_file()]
        elif any(c in pattern for c in "*?["):
            paths = [p for p in self.root.glob(pattern) if p.is_file()]
        elif base.is_file():
            paths = [base]
        else:
            paths = []
        values = []
        for path in sorted(paths):
            try:
                resolved = self._safe_regular_path(path)
            except (OSError, ValueError) as exc:
                raise ValueError(f"{_file_safety_code(exc, 'PATH_OUTSIDE_PROJECT')}: {pattern}") from exc
            values.append({"path": rel_posix(resolved, self.root), "sha256": self._file_sha256(resolved)})
        return values

    def _snapshot(self, doc):
        watched = []
        for pattern in doc.watch_paths:
            watched.append({"pattern": pattern, "resolved_files": self._resolved_pattern(pattern)})
        deps = []
        for edge in doc.depends_on:
            target = self.documents.get(edge.get("id")) if isinstance(edge, dict) else None
            if target:
                deps.append({"id": target.id, "content_sha256": target.content_sha256})
        children = []
        for edge in doc.children:
            target = self.documents.get(edge.get("id")) if isinstance(edge, dict) else None
            if target:
                children.append({"id": target.id, "content_sha256": target.content_sha256,
                                 "propagation": edge.get("propagation")})
        return {"documents": sorted(deps, key=lambda x: x["id"]),
                "children": sorted(children, key=lambda x: x["id"]), "watch_paths": watched}

    def _git_head(self):
        if not self.git_root:
            return None
        result = run_git(self.root, "rev-parse", "HEAD")
        return result.stdout.strip() if result.returncode == 0 else None

    def _dirty_paths(self):
        """Return every dirty Git path, including both sides of renames/copies.

        Porcelain v1 with ``-z`` disables quoting, preserves spaces, and emits
        rename/copy destinations followed by their source paths. Both paths are
        relevant because a watched file may have been moved out of its pattern.
        """
        if not self.git_root:
            return []
        result = run_git(self.root, "status", "--porcelain=v1", "-z", "--untracked-files=all")
        if result.returncode != 0:
            raise ValueError("GIT_STATUS_FAILED")
        records = result.stdout.split("\0")
        paths = []
        index = 0
        while index < len(records):
            record = records[index]
            index += 1
            if not record:
                continue
            if len(record) < 4 or record[2] != " ":
                raise ValueError("GIT_STATUS_PARSE_ERROR")
            status = record[:2]
            paths.append(PurePosixPath(record[3:]).as_posix())
            if "R" in status or "C" in status:
                if index >= len(records) or not records[index]:
                    raise ValueError("GIT_STATUS_PARSE_ERROR")
                paths.append(PurePosixPath(records[index]).as_posix())
                index += 1
        return list(dict.fromkeys(paths))

    @staticmethod
    def _glob_matches_path(pattern, path):
        """Match a project-relative path using the documented pathlib glob model.

        ``fnmatch`` and ``PurePath.match`` do not treat ``**`` as matching zero
        path segments, so ``src/**/*.py`` would incorrectly miss ``src/a.py``.
        This segment-based matcher implements the required zero-or-more
        semantics and also works for deleted or renamed paths that no longer
        exist in the working tree.
        """
        if not isinstance(pattern, str) or not isinstance(path, str):
            return False
        pattern_parts = PurePosixPath(pattern).parts
        path_parts = PurePosixPath(path).parts
        has_magic = any(any(char in part for char in "*?[") for part in pattern_parts)
        if not has_magic:
            return path_parts == pattern_parts or path_parts[:len(pattern_parts)] == pattern_parts

        memo = {}
        def match(pattern_index, path_index):
            key = (pattern_index, path_index)
            if key in memo:
                return memo[key]
            if pattern_index == len(pattern_parts):
                result = path_index == len(path_parts)
            elif pattern_parts[pattern_index] == "**":
                result = match(pattern_index + 1, path_index) or (
                    path_index < len(path_parts) and match(pattern_index, path_index + 1)
                )
            else:
                result = (
                    path_index < len(path_parts)
                    and fnmatch.fnmatchcase(path_parts[path_index], pattern_parts[pattern_index])
                    and match(pattern_index + 1, path_index + 1)
                )
            memo[key] = result
            return result
        return match(0, 0)

    def _recorded_path(self, doc_id):
        record = self.lock.get("documents", {}).get(doc_id, {})
        value = record.get("path") if isinstance(record, dict) else None
        return value if _nonempty_string(value) else None

    def _relevant_paths(self, doc):
        """Return current and previously verified paths relevant to a document."""
        paths = {doc.relpath}
        recorded_doc_path = self._recorded_path(doc.id)
        if recorded_doc_path:
            paths.add(recorded_doc_path)
        for edge in doc.children:
            target = self.documents.get(edge.get("id")) if isinstance(edge, dict) else None
            if target and edge.get("propagation") != "status_only":
                paths.add(target.relpath)
                recorded = self._recorded_path(target.id)
                if recorded:
                    paths.add(recorded)
        for edge in doc.depends_on:
            target = self.documents.get(edge.get("id")) if isinstance(edge, dict) else None
            if target:
                paths.add(target.relpath)
                recorded = self._recorded_path(target.id)
                if recorded:
                    paths.add(recorded)
        for pattern in doc.watch_paths:
            try:
                paths.update(x["path"] for x in self._resolved_pattern(pattern))
            except ValueError:
                pass
        record = self.lock.get("documents", {}).get(doc.id, {})
        for item in (record.get("dependencies") or {}).get("watch_paths", []):
            for resolved in item.get("resolved_files", []):
                path = resolved.get("path")
                if _nonempty_string(path):
                    paths.add(path)
        return paths

    def _has_relevant_dirty(self, doc):
        dirty = self._dirty_paths()
        relevant = self._relevant_paths(doc)
        return [
            path for path in dirty
            if path in relevant or any(self._glob_matches_path(pattern, path) for pattern in doc.watch_paths)
        ]

    def _changed_paths_since(self, since):
        """Return both old and new paths changed since a Git commit."""
        result = run_git(self.root, "diff", "--name-status", "-z", f"{since}..HEAD")
        if result.returncode != 0:
            raise ValueError("INVALID_SINCE_COMMIT")
        records = result.stdout.split("\0")
        paths = []
        index = 0
        while index < len(records):
            status = records[index]
            index += 1
            if not status:
                continue
            if index >= len(records) or not records[index]:
                raise ValueError("GIT_DIFF_PARSE_ERROR")
            paths.append(PurePosixPath(records[index]).as_posix())
            index += 1
            if status.startswith(("R", "C")):
                if index >= len(records) or not records[index]:
                    raise ValueError("GIT_DIFF_PARSE_ERROR")
                paths.append(PurePosixPath(records[index]).as_posix())
                index += 1
        return set(paths)

    def _structure_report(self, command):
        report = Report(command)
        report.blocking_errors.extend(self.parse_issues)
        if self.lock_error:
            report.blocking_errors.append(self.lock_error)
        if not self.git_root:
            report.warnings.append(Issue(
                "HASH_ONLY_MODE",
                "Git repository not found; freshness assurance is limited to hashes",
            ))
        ids, authorities = {}, {}
        for doc in self.document_list:
            if doc.lifecycle == "active" and doc.role in AUTHORITATIVE_ROLES and not doc.authority_key:
                report.blocking_errors.append(Issue("MISSING_AUTHORITY_KEY", doc.role, doc.relpath))
            ids.setdefault(doc.id, []).append(doc)
            if doc.lifecycle == "active" and doc.authority_key:
                authorities.setdefault(doc.authority_key, []).append(doc)
            if doc.lifecycle == "active" and self._is_archive_path(doc.relpath):
                report.blocking_errors.append(Issue("ACTIVE_DOCUMENT_IN_ARCHIVE", doc.id, doc.relpath))
            for root in doc.archive_roots:
                if not self._validate_relpath(root):
                    report.blocking_errors.append(Issue("PATH_OUTSIDE_PROJECT", str(root), doc.relpath))
            for value in doc.watch_paths:
                if not self._validate_relpath(value):
                    report.blocking_errors.append(Issue("PATH_OUTSIDE_PROJECT", str(value), doc.relpath))
                    continue
                if self._is_archive_path(value):
                    report.blocking_errors.append(Issue("ARCHIVE_IN_WATCH_PATHS", str(value), doc.relpath))
                try:
                    matches = self._resolved_pattern(value)
                except (OSError, ValueError) as exc:
                    report.blocking_errors.append(Issue("PATH_OUTSIDE_PROJECT", str(exc), doc.relpath))
                    continue
                if any(self._is_archive_path(item["path"]) for item in matches):
                    report.blocking_errors.append(Issue(
                        "ARCHIVE_IN_WATCH_PATHS",
                        f"{value} resolves archived files",
                        doc.relpath,
                    ))
            for target_id in doc.supersedes:
                target = self.documents.get(target_id)
                if target and target.lifecycle == "active":
                    report.blocking_errors.append(Issue("SUPERSEDES_ACTIVE_DOCUMENT", target_id, doc.relpath))
        for key, docs in ids.items():
            if key and len(docs) > 1:
                report.blocking_errors.append(Issue("DUPLICATE_DOCUMENT_ID", key))
        for key, docs in authorities.items():
            if len(docs) > 1:
                report.blocking_errors.append(Issue("DUPLICATE_AUTHORITY_KEY", key))
        keys = sorted(authorities)
        for i, left in enumerate(keys):
            for right in keys[i + 1:]:
                lp, rp = left.split("."), right.split(".")
                if lp[-2:] == rp[-2:] or (len(lp) < len(rp) and rp[-len(lp):] == lp) or (len(rp) < len(lp) and lp[-len(rp):] == rp):
                    report.warnings.append(Issue("NEAR_DUPLICATE_AUTHORITY_KEY", f"{left} ~ {right}"))
        entries = [
            d for d in self.document_list
            if d.level == 0 and d.role == "project_entry" and d.lifecycle == "active"
        ]
        if not entries:
            report.blocking_errors.append(Issue("UNMANAGED_PROJECT", "no active L0 entry"))
        elif len(entries) > 1:
            report.blocking_errors.append(Issue("MULTIPLE_PROJECT_ENTRIES", "multiple active L0 entries"))
        cycle = self._graph_cycle("children")
        if cycle:
            report.blocking_errors.append(Issue("CHILDREN_CYCLE", " -> ".join(cycle)))
        cycle = self._graph_cycle("depends_on")
        if cycle:
            report.blocking_errors.append(Issue("DEPENDENCY_CYCLE", " -> ".join(cycle)))
        reachable = self._reachable()
        for doc in self.document_list:
            if doc.lifecycle == "active" and doc.id not in reachable:
                report.blocking_errors.append(Issue("ORPHANED", doc.id, doc.relpath))
        for doc in self.document_list:
            if doc.lifecycle != "active" or doc.level not in {0, 1}:
                continue
            startup = []
            for value in doc.startup:
                if not self._validate_relpath(value):
                    report.blocking_errors.append(Issue("PATH_OUTSIDE_PROJECT", str(value), doc.relpath))
                elif self._is_archive_path(value):
                    report.blocking_errors.append(Issue("ARCHIVE_IN_STARTUP", value, doc.relpath))
                elif not (self.root / value).exists():
                    report.blocking_errors.append(Issue("BROKEN_LINK", value, doc.relpath))
                startup.append(value)
            budget = doc.startup_budget
            unique = [doc.relpath] + list(dict.fromkeys(startup))
            chars = 0
            for value in unique:
                try:
                    _resolved, raw = self._read_file_bytes(self.root / value, MAX_MARKDOWN_BYTES)
                    chars += len(raw.decode("utf-8"))
                except FileNotFoundError:
                    pass
                except ValueError as exc:
                    report.blocking_errors.append(Issue(_file_safety_code(exc), str(exc), value))
                except (OSError, UnicodeDecodeError):
                    pass
            if len(unique) > budget.get("max_files", 10**9) or chars > budget.get("max_characters", 10**18):
                code = "STARTUP_BUDGET_EXCEEDED" if doc.level == 0 else "MODULE_BUDGET_EXCEEDED"
                report.warnings.append(Issue(code, f"files={len(unique)} characters={chars}", doc.relpath))
        if self.git_root:
            attributes_path = self.root / ".gitattributes"
            has_markdown_lf = False
            if attributes_path.exists():
                try:
                    _resolved, attributes_raw = self._read_file_bytes(attributes_path, MAX_CONFIG_BYTES)
                    for line in attributes_raw.decode("utf-8").splitlines():
                        tokens = line.split()
                        if tokens and tokens[0] == "*.md" and "text" in tokens and "eol=lf" in tokens:
                            has_markdown_lf = True
                            break
                except (OSError, UnicodeDecodeError, ValueError):
                    pass
            if not has_markdown_lf:
                report.warnings.append(Issue(
                    "CROSS_PLATFORM_EOL_RISK",
                    "add a committed '*.md text eol=lf' rule to .gitattributes",
                ))
            if ".gitattributes" in self._dirty_paths():
                report.warnings.append(Issue(
                    "UNCOMMITTED_GITATTRIBUTES",
                    ".gitattributes must be committed for reproducible hashes",
                ))
        for doc in self.document_list:
            for edge in doc.children:
                if not isinstance(edge, dict):
                    continue
                target = self.documents.get(edge.get("id"))
                path = edge.get("path")
                if _nonempty_string(path) and not self._validate_relpath(path):
                    report.blocking_errors.append(Issue("PATH_OUTSIDE_PROJECT", path, doc.relpath))
                if not target or path != target.relpath:
                    report.blocking_errors.append(Issue("BROKEN_LINK", str(edge), doc.relpath))
                if target and doc.lifecycle == "active" and target.lifecycle != "active":
                    report.blocking_errors.append(Issue("NON_ACTIVE_CHILD", target.id, doc.relpath))
                if target and doc.lifecycle == "active" and self._is_archive_path(target.relpath):
                    report.blocking_errors.append(Issue("ARCHIVE_AS_ACTIVE_CHILD", target.id, doc.relpath))
            for edge in doc.depends_on:
                if not isinstance(edge, dict):
                    continue
                target = self.documents.get(edge.get("id"))
                if not target:
                    report.blocking_errors.append(Issue("BROKEN_DEPENDENCY", str(edge), doc.relpath))
                else:
                    if doc.lifecycle == "active" and target.lifecycle != "active":
                        report.blocking_errors.append(Issue(
                            "ACTIVE_DEPENDS_ON_NON_ACTIVE_DOCUMENT", target.id, doc.relpath
                        ))
                    if doc.lifecycle == "active" and self._is_archive_path(target.relpath):
                        report.blocking_errors.append(Issue("ACTIVE_DEPENDS_ON_ARCHIVE", target.id, doc.relpath))
            text = doc.raw.decode("utf-8")
            for href in markdown_link_destinations(text):
                href = href.split("#", 1)[0]
                if not href or href.startswith("#"):
                    continue
                if "\\" in href or re.match(r"^[A-Za-z]:", href):
                    report.blocking_errors.append(Issue("PATH_OUTSIDE_PROJECT", href, doc.relpath)); continue
                if is_external_uri(href):
                    continue
                target = (doc.path.parent / href).resolve()
                try: target.relative_to(self.root)
                except ValueError:
                    report.blocking_errors.append(Issue("PATH_OUTSIDE_PROJECT", href, doc.relpath)); continue
                if not target.exists():
                    report.blocking_errors.append(Issue("BROKEN_LINK", href, doc.relpath))
        return report

    def check(self):
        report = self._structure_report("check")
        seen = set()
        for doc in self.document_list:
            if doc.id and doc.id not in seen:
                report.results.append(self.status(doc.id))
                seen.add(doc.id)
        if not report.blocking_errors:
            propagated = {result.doc_id: result for result in self._calculate_impact()}
            report.results = [propagated.get(result.doc_id, result) for result in report.results]
        return report

    def status(self, doc_id):
        doc = self.documents[doc_id]
        if doc.lifecycle == "archived": return Result(doc_id, "ARCHIVED", "lifecycle")
        if doc.lifecycle == "superseded": return Result(doc_id, "SUPERSEDED", "lifecycle")
        record = self.lock.get("documents", {}).get(doc_id)
        if not record: return Result(doc_id, "UNVERIFIED", "missing lock record")
        if record.get("path") != doc.relpath or record.get("authority_key") != doc.authority_key:
            return Result(doc_id, "STALE", "document identity changed")
        if record.get("content_sha256") != doc.content_sha256: return Result(doc_id, "STALE", "document content changed")
        try: snapshot = self._snapshot(doc)
        except ValueError as exc: return Result(doc_id, "STALE", str(exc))
        recorded = record.get("dependencies") or {}
        if recorded.get("watch_paths") != snapshot.get("watch_paths"):
            return Result(doc_id, "STALE", "watch path snapshot changed")
        commit = record.get("verified_commit")
        if self.git_root and commit:
            if run_git(self.root, "merge-base", "--is-ancestor", commit, "HEAD").returncode != 0:
                return Result(doc_id, "STALE", "verified commit is not HEAD ancestor")
        if self._has_relevant_dirty(doc): return Result(doc_id, "STALE", "relevant dirty paths")
        return Result(doc_id, "CURRENT", "verified")

    def _parents(self):
        parents = {}
        for doc in self.document_list:
            if doc.lifecycle != "active":
                continue
            for edge in doc.children:
                target = self.documents.get(edge.get("id")) if isinstance(edge, dict) else None
                if target and target.lifecycle == "active":
                    parents.setdefault(target.id, []).append((doc.id, edge.get("propagation")))
        return parents

    def _consumers(self):
        consumers = {}
        for doc in self.document_list:
            if doc.lifecycle != "active":
                continue
            for edge in doc.depends_on:
                target = self.documents.get(edge.get("id")) if isinstance(edge, dict) else None
                if target and target.lifecycle == "active":
                    consumers.setdefault(target.id, []).append((doc.id, edge.get("propagation")))
        return consumers

    def _calculate_impact(self, since=None):
        active_docs = [doc for doc in self.document_list if doc.id and doc.lifecycle == "active"]
        base = {doc.id: self.status(doc.id) for doc in active_docs}
        if since:
            if not self.git_root:
                raise ValueError("IMPACT_SINCE_REQUIRES_GIT")
            changed = self._changed_paths_since(since)
            affected = {}
            for doc in active_docs:
                relevant = self._relevant_paths(doc)
                if (
                    doc.relpath in changed
                    or relevant.intersection(changed)
                    or any(
                        self._glob_matches_path(pattern, path)
                        for path in changed for pattern in doc.watch_paths
                    )
                ):
                    affected[doc.id] = Result(doc.id, "STALE", f"changed since {since}")
        else:
            affected = {k: v for k, v in base.items() if v.state in {"STALE", "UNVERIFIED"}}
        parents, consumers = self._parents(), self._consumers()
        if not since:
            for child_id, edges in parents.items():
                child_doc = self.documents.get(child_id)
                if not child_doc:
                    continue
                child_record = self.lock.get("documents", {}).get(child_id, {})
                for parent_id, propagation in edges:
                    if parent_id in affected or propagation == "link_only":
                        continue
                    parent_record = self.lock.get("documents", {}).get(parent_id, {})
                    recorded_children = {
                        item.get("id"): item
                        for item in (parent_record.get("dependencies") or {}).get("children", [])
                    }
                    if recorded_children.get(child_id, {}).get("content_sha256") == child_doc.content_sha256:
                        continue
                    reason = propagation
                    if propagation == "status_only":
                        if (
                            child_record.get("status_effect_applicable")
                            and child_record.get("content_sha256") == child_doc.content_sha256
                        ):
                            if child_record.get("status_effect") == "unchanged":
                                continue
                            reason = "status changed" if child_record.get("status_effect") == "changed" else "WAITING_STATUS_CLASSIFICATION"
                        else:
                            reason = "WAITING_STATUS_CLASSIFICATION"
                    affected[parent_id] = Result(parent_id, "REVIEW_REQUIRED", reason)

            for dependency_id, edges in consumers.items():
                dependency = self.documents.get(dependency_id)
                if not dependency:
                    continue
                for consumer_id, propagation in edges:
                    if consumer_id in affected or propagation == "link_only":
                        continue
                    consumer_record = self.lock.get("documents", {}).get(consumer_id, {})
                    recorded_dependencies = {
                        item.get("id"): item
                        for item in (consumer_record.get("dependencies") or {}).get("documents", [])
                    }
                    if recorded_dependencies.get(dependency_id, {}).get("content_sha256") != dependency.content_sha256:
                        affected[consumer_id] = Result(consumer_id, "REVIEW_REQUIRED", propagation)

        queue = list(affected)
        while queue:
            child = queue.pop(0)
            for parent, propagation in parents.get(child, []) + consumers.get(child, []):
                if parent in affected:
                    continue
                reason = propagation
                if propagation == "link_only":
                    continue
                if propagation == "status_only":
                    record = self.lock.get("documents", {}).get(child, {})
                    current = self.documents.get(child)
                    if (
                        record.get("status_effect_applicable")
                        and record.get("content_sha256") == getattr(current, "content_sha256", None)
                    ):
                        if record.get("status_effect") == "unchanged":
                            continue
                        if record.get("status_effect") == "changed":
                            reason = "status changed"
                        else:
                            reason = "WAITING_STATUS_CLASSIFICATION"
                    else:
                        reason = "WAITING_STATUS_CLASSIFICATION"
                affected[parent] = Result(parent, "REVIEW_REQUIRED", reason)
                if propagation != "status_only":
                    queue.append(parent)
        results = list(affected.values())
        depth = {d.id: d.level for d in self.document_list if d.lifecycle == "active"}
        results.sort(key=lambda x: (-int(depth.get(x.doc_id) or 0), x.doc_id))
        return results

    def impact(self, since=None):
        report = self._structure_report("impact")
        if report.blocking_errors:
            return report
        report.results = self._calculate_impact(since=since)
        report.update_queue = [x.doc_id for x in report.results]
        return report

    def verify(self, doc_id, status_effect=None, allow_hash_only=False):
        if doc_id not in self.documents: raise ValueError("unknown document")
        doc = self.documents[doc_id]
        if doc.lifecycle != "active":
            raise ValueError("VERIFY_REFUSED_NON_ACTIVE_DOCUMENT")
        if self.check().blocking_errors: raise ValueError("VERIFY_REFUSED_STRUCTURE_ERROR")
        if not self.git_root and not allow_hash_only: raise ValueError("VERIFY_REFUSED_HASH_ONLY_MODE")
        for edge in doc.children + doc.depends_on:
            if edge.get("propagation") == "link_only":
                continue
            target = self.documents.get(edge.get("id"))
            if target and self.status(target.id).state in {
                "STALE", "UNVERIFIED", "REVIEW_REQUIRED", "SUPERSEDED", "ARCHIVED",
            }:
                raise ValueError("VERIFY_REFUSED_STALE_DEPENDENCY: " + target.id)
        relevant_dirty = self._has_relevant_dirty(doc)
        if relevant_dirty: raise ValueError("VERIFY_REFUSED_RELEVANT_DIRTY_PATH: " + ",".join(relevant_dirty))
        status_edges = any(
            edge.get("propagation") == "status_only"
            for parent in self.document_list if parent.lifecycle == "active"
            for edge in parent.children
            if edge.get("id") == doc_id
            and self.documents.get(doc_id)
            and self.documents[doc_id].lifecycle == "active"
        )
        existing = self.lock.get("documents", {}).get(doc_id)
        if status_edges:
            allowed = {"initial"} if not existing else {"changed", "unchanged"}
            if status_effect not in allowed: raise ValueError("VERIFY_REFUSED_STATUS_EFFECT_REQUIRED")
        elif status_effect is None:
            status_effect = "unchanged"
        head = self._git_head() if self.git_root else None
        record = {
            "path": doc.relpath, "authority_key": doc.authority_key,
            "content_sha256": doc.content_sha256, "verified_commit": head,
            "verified_at": utc_now(), "status_effect": status_effect,
            "status_effect_applicable": status_edges,
            "dependencies": self._snapshot(doc),
        }
        lock_path = self.root / ".driftlock.lock.json"
        original = self.lock_bytes
        if self.lock_error: raise ValueError("LOCK_CORRUPTED")
        new_lock = dict(self.lock)
        new_lock["schema_version"] = SCHEMA_VERSION
        new_lock["tool_version"] = TOOL_VERSION
        new_lock["generated_at"] = utc_now()
        docs = dict(new_lock.get("documents", {})); docs[doc_id] = record
        new_lock["documents"] = {key: docs[key] for key in sorted(docs)}
        payload = (json.dumps(new_lock, ensure_ascii=False, indent=2) + "\n").encode()
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp_name = tempfile.mkstemp(prefix=".driftlock-lock-", dir=lock_path.parent)
        guard_path = lock_path.with_name(lock_path.name + ".guard")
        guard_fd = None
        guard_token = None
        try:
            with os.fdopen(fd, "wb") as handle:
                handle.write(payload); handle.flush(); os.fsync(handle.fileno())
            guard_token = f"{os.getpid()}:{time.time_ns()}:{os.urandom(16).hex()}".encode("ascii")

            def acquire_guard():
                acquired_fd = os.open(guard_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
                try:
                    os.write(acquired_fd, guard_token)
                    os.fsync(acquired_fd)
                except Exception:
                    os.close(acquired_fd)
                    try:
                        guard_path.unlink()
                    except FileNotFoundError:
                        pass
                    raise
                return acquired_fd

            try:
                guard_fd = acquire_guard()
            except FileExistsError as exc:
                try:
                    guard_age = time.time() - guard_path.lstat().st_mtime
                except FileNotFoundError:
                    guard_age = 0
                if guard_age <= GUARD_STALE_SECONDS:
                    raise ValueError("LOCK_CONCURRENT_MODIFICATION") from exc
                try:
                    guard_path.unlink()
                except FileNotFoundError:
                    pass
                try:
                    guard_fd = acquire_guard()
                except FileExistsError as retry_exc:
                    raise ValueError("LOCK_CONCURRENT_MODIFICATION") from retry_exc
            current = self._read_file_bytes(lock_path, MAX_LOCK_BYTES)[1] if lock_path.exists() else b""
            if current != original:
                raise ValueError("LOCK_CONCURRENT_MODIFICATION")
            os.replace(tmp_name, lock_path)
        finally:
            self._release_guard(guard_path, guard_fd, guard_token)
            if os.path.exists(tmp_name): os.unlink(tmp_name)
        self.lock, self.lock_bytes, self.lock_error = new_lock, payload, None
        return record

    def archive_plan(self):
        report = Report("archive-plan")
        if not self.git_root:
            report.warnings.append(Issue(
                "HASH_ONLY_MODE",
                "Git repository not found; archive evidence is limited to the working tree",
            ))
        inbound = {}
        for doc in self.document_list:
            for edge in doc.children + doc.depends_on:
                if not isinstance(edge, dict):
                    continue
                target = self.documents.get(edge.get("id"))
                if target:
                    inbound.setdefault(target.relpath, set()).add(doc.relpath)
        entries = list(self._safe_markdown_entries(report))
        files = [path for path, _rel in entries]
        hashes = {}
        texts = {}
        for path, source_rel in entries:
            try:
                _resolved, raw = self._read_file_bytes(path, MAX_MARKDOWN_BYTES)
                text = raw.decode("utf-8")
            except ValueError as exc:
                report.blocking_errors.append(Issue(_file_safety_code(exc), str(exc), source_rel))
                continue
            except (OSError, UnicodeDecodeError):
                continue
            hashes.setdefault(sha256_bytes(raw), []).append(source_rel)
            texts[source_rel] = text
            for href in markdown_link_destinations(text):
                href = href.split("#", 1)[0]
                if not href or is_external_uri(href):
                    continue
                target = (path.parent / href).resolve()
                try: target_rel = rel_posix(target, self.root)
                except ValueError: continue
                if target.exists(): inbound.setdefault(target_rel, set()).add(source_rel)
        for target, target_rel in entries:
            name = target.name
            for source_rel, text in texts.items():
                if source_rel == target_rel:
                    continue
                if target_rel in text or f"`{name}`" in text or f"({name})" in text:
                    inbound.setdefault(target_rel, set()).add(source_rel)
        duplicates = {path for group in hashes.values() if len(group) > 1 for path in group}
        date_re = re.compile(r"(?:19|20)\d{2}[-_]?\d{2}[-_]?\d{2}")
        standard = {"readme.md", "agents.md", "project_map.md", "docs_map.md", "index.md"}
        responsibility_groups = {}
        for path, rel in entries:
            stem = date_re.sub("", path.stem.lower())
            stem = re.sub(r"(?:[-_](?:v|r)?\d+)+$", "", stem).strip("-_")
            if stem:
                responsibility_groups.setdefault(stem, []).append(rel)
        merge_candidates = {
            rel
            for group in responsibility_groups.values() if len(group) > 1
            for rel in group
        }
        for path, rel in entries:
            doc = next((d for d in self.document_list if d.relpath == rel), None)
            reasons = []
            if date_re.search(path.name): reasons.append("dated_snapshot")
            if doc and doc.lifecycle in {"superseded", "archived"}: reasons.append(doc.lifecycle)
            if path.parent == self.root and path.name.lower() not in standard: reasons.append("loose_root_document")
            if path.parent == self.root / "docs" and path.name.lower() not in standard: reasons.append("loose_docs_root_document")
            if rel in duplicates: reasons.append("exact_duplicate")
            if rel in merge_candidates: reasons.append("possible_responsibility_duplicate")
            if not inbound.get(rel) and (not doc or doc.lifecycle != "active") and path.name.lower() not in standard:
                reasons.append("no_inbound_references")
            if reasons:
                deterministic = bool(doc and doc.lifecycle != "active") or "exact_duplicate" in reasons
                if deterministic:
                    classification = "DETERMINISTIC_ARCHIVE_CANDIDATE"
                elif "possible_responsibility_duplicate" in reasons:
                    classification = "POSSIBLE_MERGE_CANDIDATE"
                else:
                    classification = "MANUAL_REVIEW_REQUIRED"
                authority_candidates = sorted(
                    candidate.relpath for candidate in self.document_list
                    if candidate.lifecycle == "active"
                    and candidate.relpath != rel
                    and candidate.path.stem.lower().split(".")[0] in path.stem.lower()
                )
                inbound_refs = sorted(inbound.get(rel, set()))
                report.archive_candidates.append({
                    "path": rel,
                    "classification": classification,
                    "reasons": reasons,
                    "inbound_references": inbound_refs,
                    "suggested_target": f"docs/archive/{path.name}",
                    "authority_candidate": authority_candidates[0] if authority_candidates else None,
                    "risk": "high: update inbound references before moving" if inbound_refs else (
                        "medium: confirm which document owns the responsibility" if classification == "POSSIBLE_MERGE_CANDIDATE"
                        else "low: no inbound references detected"
                    ),
                    "rollback": f"Move the file back to {rel} and restore only its reference-update diff.",
                })
        return report

    def discover(self):
        report = Report("discover")
        if not self.git_root:
            report.warnings.append(Issue(
                "HASH_ONLY_MODE",
                "Git repository not found; discovery uses working-tree evidence only",
            ))
        groups = {
            "l0_candidates": [],
            "l1_module_candidates": [],
            "status_candidates": [],
            "task_board_candidates": [],
            "contract_candidates": [],
            "runbook_candidates": [],
            "archive_candidates": [],
            "loose_root_documents": [],
            "possible_responsibility_duplicates": [],
            "suggested_hierarchy": [],
        }
        responsibility = {}
        for path, rel in self._safe_markdown_entries(report):
            lower = path.stem.lower()
            doc = next((item for item in self.document_list if item.relpath == rel), None)
            if (doc and doc.level == 0 and doc.role == "project_entry") or lower in {"project_map", "docs_map"}:
                groups["l0_candidates"].append(rel)
            if (doc and doc.level == 1 and doc.role == "module_index") or (
                path.name.lower() in {"index.md", "overview.md"} and len(path.relative_to(self.root).parts) >= 3
            ):
                groups["l1_module_candidates"].append(rel)
            if (doc and doc.role == "status") or "status" in lower or "snapshot" in lower:
                groups["status_candidates"].append(rel)
            if (doc and doc.role == "task_board") or "task_board" in lower or lower == "tasks":
                groups["task_board_candidates"].append(rel)
            if (doc and doc.role == "contract") or "contract" in lower:
                groups["contract_candidates"].append(rel)
            if (doc and doc.role == "runbook") or "runbook" in lower or "deployment" in lower:
                groups["runbook_candidates"].append(rel)
            if self._is_archive_path(rel) or (doc and doc.lifecycle in {"archived", "superseded"}) or "archive" in path.parts:
                groups["archive_candidates"].append(rel)
            if path.parent in {self.root, self.root / "docs"} and path.name.lower() not in {"readme.md", "agents.md", "project_map.md", "index.md"}:
                groups["loose_root_documents"].append(rel)
            key = re.sub(r"(?:19|20)\d{2}[-_]?\d{2}[-_]?\d{2}", "", lower).strip("-_")
            if key:
                responsibility.setdefault(key, []).append(rel)
            role = "status_candidate" if any(x in lower for x in ("status", "task_board", "project")) else "document_candidate"
            report.results.append(Result(rel, role.upper(), "heuristic candidate"))
        groups["possible_responsibility_duplicates"] = [
            {"key": key, "paths": sorted(paths)}
            for key, paths in sorted(responsibility.items()) if len(paths) > 1
        ]
        groups["suggested_hierarchy"] = [
            {"level": 0, "purpose": "single project entry", "candidates": groups["l0_candidates"]},
            {"level": 1, "purpose": "module indexes", "candidates": groups["l1_module_candidates"]},
            {"level": 2, "purpose": "contracts, runbooks, status, and task boards"},
            {"level": "archive", "purpose": "history excluded from startup and active dependency graphs"},
        ]
        for key, value in groups.items():
            if key not in {"possible_responsibility_duplicates", "suggested_hierarchy"}:
                groups[key] = sorted(set(value))
        report.discovery = groups
        return report


def report_dict(project, report):
    return {
        "command": report.command, "schema_version": SCHEMA_VERSION, "tool_version": TOOL_VERSION,
        "project_root": str(project.root), "head_commit": project._git_head(),
        "working_tree_dirty": bool(project._dirty_paths()) if project.git_root else False,
        "verification_mode": "git" if project.git_root else "hash_only",
        "results": [x.as_dict() for x in report.results], "update_queue": report.update_queue,
        "archive_candidates": report.archive_candidates,
        "discovery": report.discovery,
        "relevant_dirty_paths": sorted({
            path
            for doc in project.document_list if doc.id and doc.lifecycle == "active"
            for path in project._has_relevant_dirty(doc)
        }) if project.git_root else [],
        "blocking_errors": [x.as_dict() for x in report.blocking_errors],
        "warnings": [x.as_dict() for x in report.warnings],
    }


def print_report(project, report, fmt):
    payload = report_dict(project, report)
    if fmt == "json":
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print(f"{report.command}: {project.root}")
        for item in report.results: print(f"{item.state:16} {item.doc_id} {item.reason}")
        for item in report.archive_candidates:
            print(f"{item['classification']:32} {item['path']} {','.join(item['reasons'])}")
        if report.update_queue:
            print("update_queue: " + " -> ".join(report.update_queue))
        for item in report.blocking_errors: print(f"ERROR {item.code}: {item.message}")
        for item in report.warnings: print(f"WARN  {item.code}: {item.message}")
    return report.exit_code


class CliArgumentError(Exception):
    pass


class DriftlockArgumentParser(argparse.ArgumentParser):
    def error(self, message):
        raise CliArgumentError(message)


def build_parser():
    parser = DriftlockArgumentParser(description="Driftlock v2 graph and freshness manager")
    subs = parser.add_subparsers(dest="command", required=True, parser_class=DriftlockArgumentParser)
    for name in ("discover", "check", "impact", "archive-plan"):
        sub = subs.add_parser(name); sub.add_argument("project_root"); sub.add_argument("--format", choices=("text", "json"), default="text")
        if name == "impact": sub.add_argument("--since")
    verify = subs.add_parser("verify"); verify.add_argument("project_root"); verify.add_argument("--doc", required=True)
    verify.add_argument("--status-effect", choices=("initial", "changed", "unchanged")); verify.add_argument("--allow-hash-only", action="store_true")
    verify.add_argument("--format", choices=("text", "json"), default="text")
    return parser


def main(argv=None):
    args = None
    try:
        args = build_parser().parse_args(argv)
        project = Project.load(args.project_root)
        if args.command == "verify":
            record = project.verify(args.doc, args.status_effect, args.allow_hash_only)
            if args.format == "json": print(json.dumps({
                "command": "verify", "schema_version": SCHEMA_VERSION,
                "tool_version": TOOL_VERSION, "ok": True,
                "document": args.doc, "record": record,
            }, indent=2))
            else: print(f"verified {args.doc}")
            return 0
        if args.command == "impact":
            report = project.impact(since=args.since)
        else:
            report = getattr(project, args.command.replace("-", "_"))()
        return print_report(project, report, args.format)
    except CliArgumentError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 3
    except ValueError as exc:
        payload = {
            "command": getattr(args, "command", None),
            "schema_version": SCHEMA_VERSION,
            "tool_version": TOOL_VERSION,
            "blocking_errors": [{"code": str(exc).split(":", 1)[0], "message": str(exc)}],
        }
        if getattr(args, "format", "text") == "json": print(json.dumps(payload, indent=2))
        else: print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    except (OSError, subprocess.SubprocessError, json.JSONDecodeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr); return 3


if __name__ == "__main__":
    raise SystemExit(main())
