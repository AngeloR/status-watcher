#!/usr/bin/env python3
"""
Terminal dashboard for monitoring status feeds and status pages.

Usage:
    python3 tui.py
    python3 tui.py feeds.json

Behavior:
    Uses ./feeds.json when present.
    Falls back to built-in defaults if no config file exists.
    An explicit CLI path overrides both.
"""

from __future__ import annotations

import sys

from status_watcher.cli import main


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
