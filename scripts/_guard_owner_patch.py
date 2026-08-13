from pathlib import Path

SRC = Path("scripts/project_docs.py")
TESTS = Path("tests/test_project_docs.py")

src = SRC.read_text(encoding="utf-8")
tests = TESTS.read_text(encoding="utf-8")


def replace_once(text, old, new, label):
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected 1 match, found {count}")
    return text.replace(old, new, 1)


src = replace_once(src, 'TOOL_VERSION = "0.1.0"', 'TOOL_VERSION = "0.1.1"', "tool version")
src = replace_once(
    src,
    "MAX_CONFIG_BYTES = 1024 * 1024\nHASH_CHUNK_BYTES = 1024 * 1024\n",
    "MAX_CONFIG_BYTES = 1024 * 1024\nMAX_GUARD_BYTES = 4096\nHASH_CHUNK_BYTES = 1024 * 1024\n",
    "guard size constant",
)
src = replace_once(
    src,
    '''        return resolved, data

    def _safe_markdown_entries(self, report):
''',
    '''        return resolved, data

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
''',
    "guard release helper",
)
src = replace_once(
    src,
    '''        guard_path = lock_path.with_name(lock_path.name + ".guard")
        guard_fd = None
        try:
''',
    '''        guard_path = lock_path.with_name(lock_path.name + ".guard")
        guard_fd = None
        guard_token = None
        try:
''',
    "guard token init",
)
src = replace_once(
    src,
    '''            try:
                guard_fd = os.open(guard_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
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
                    guard_fd = os.open(guard_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
                except FileExistsError as retry_exc:
                    raise ValueError("LOCK_CONCURRENT_MODIFICATION") from retry_exc
            current = self._read_file_bytes(lock_path, MAX_LOCK_BYTES)[1] if lock_path.exists() else b""
''',
    '''            guard_token = f"{os.getpid()}:{time.time_ns()}:{os.urandom(16).hex()}".encode("ascii")

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
''',
    "guard acquire block",
)
src = replace_once(
    src,
    '''        finally:
            if guard_fd is not None:
                os.close(guard_fd)
                try:
                    guard_path.unlink()
                except FileNotFoundError:
                    pass
            if os.path.exists(tmp_name): os.unlink(tmp_name)
''',
    '''        finally:
            self._release_guard(guard_path, guard_fd, guard_token)
            if os.path.exists(tmp_name): os.unlink(tmp_name)
''',
    "guard cleanup",
)

tests = tests.replace('"0.1.0"', '"0.1.1"')
tests = replace_once(
    tests,
    '''    def test_stale_guard_is_recovered_but_fresh_guard_is_refused(self):
        self.basic()
        mod = load_module()
        guard = self.root / ".project-docs.lock.json.guard"
        guard.write_text("stale", encoding="utf-8")
        import time as _time
        old = _time.time() - mod.GUARD_STALE_SECONDS - 5
        os.utime(guard, (old, old))

        project = mod.Project.load(self.root)
        project.verify("child", status_effect="initial")
        self.assertFalse(guard.exists())

        guard.write_text("fresh", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "LOCK_CONCURRENT_MODIFICATION"):
            mod.Project.load(self.root).verify("root", status_effect="initial")


if __name__ == "__main__":
''',
    '''    def test_stale_guard_is_recovered_but_fresh_guard_is_refused(self):
        self.basic()
        mod = load_module()
        guard = self.root / ".project-docs.lock.json.guard"
        guard.write_text("stale", encoding="utf-8")
        import time as _time
        old = _time.time() - mod.GUARD_STALE_SECONDS - 5
        os.utime(guard, (old, old))

        project = mod.Project.load(self.root)
        project.verify("child", status_effect="initial")
        self.assertFalse(guard.exists())

        guard.write_text("fresh", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "LOCK_CONCURRENT_MODIFICATION"):
            mod.Project.load(self.root).verify("root", status_effect="initial")

    def test_guard_release_does_not_delete_another_owner(self):
        self.basic()
        mod = load_module()
        project = mod.Project.load(self.root)
        guard = self.root / ".project-docs.lock.json.guard"
        guard.write_bytes(b"replacement-owner")
        fd = os.open(guard, os.O_WRONLY)

        project._release_guard(guard, fd, b"original-owner")

        self.assertTrue(guard.exists())
        self.assertEqual(b"replacement-owner", guard.read_bytes())


if __name__ == "__main__":
''',
    "guard ownership regression test",
)

SRC.write_text(src, encoding="utf-8", newline="\n")
TESTS.write_text(tests, encoding="utf-8", newline="\n")
