#!/usr/bin/env python3
"""Compatibility command; use official_api_selfcheck.py for new callers."""
from official_api_selfcheck import main


if __name__ == "__main__":
    raise SystemExit(main())
