#!/usr/bin/env python3
"""Driftlock CLI entry point.

The implementation remains in ``project_docs.py`` so existing integrations and
protocol identifiers stay compatible while the public product name is Driftlock.
"""

from project_docs import main


if __name__ == "__main__":
    raise SystemExit(main())
