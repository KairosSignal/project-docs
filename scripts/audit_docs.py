#!/usr/bin/env python3
"""Deprecated compatibility entrypoint for Project Docs v2."""

from __future__ import annotations

import sys

from project_docs import main


if __name__ == "__main__":
    root = sys.argv[1] if len(sys.argv) > 1 else "."
    raise SystemExit(main(["check", root]))
