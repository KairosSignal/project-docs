#!/usr/bin/env python3
"""Run unittest discovery and expose failures as GitHub check annotations."""

from __future__ import annotations

import os
import sys
import unittest


class GithubResult(unittest.TextTestResult):
    def _annotate(self, test, err):
        if not os.environ.get("GITHUB_ACTIONS"):
            return
        message = self._exc_info_to_string(err, test).replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")
        print(f"::error title={test}::{message}")

    def addError(self, test, err):
        super().addError(test, err)
        self._annotate(test, err)

    def addFailure(self, test, err):
        super().addFailure(test, err)
        self._annotate(test, err)


def main():
    suite = unittest.defaultTestLoader.discover("tests", pattern="test_*.py")
    result = unittest.TextTestRunner(verbosity=1, resultclass=GithubResult).run(suite)
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    raise SystemExit(main())
