#!/usr/bin/env python3
"""Driftlock CLI entry point.

The implementation remains in ``project_docs.py`` so existing integrations and
protocol identifiers stay compatible while the public product name is Driftlock.
"""

import project_docs


_original_build_parser = project_docs.build_parser


def _build_parser():
    parser = _original_build_parser()
    parser.description = "Driftlock documentation graph and freshness manager"
    return parser


project_docs.build_parser = _build_parser


if __name__ == "__main__":
    raise SystemExit(project_docs.main())
