"""Stable ASCII entry point for the Yubi desktop application.

The current runtime still lives in the legacy ``软件`` directory.  Keeping the
compatibility import in this one file lets launchers, terminals and packagers use
an ASCII-only path while the internal modules are migrated gradually.
"""
from __future__ import annotations

from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parent
LEGACY_RUNTIME = ROOT / "软件"
if str(LEGACY_RUNTIME) not in sys.path:
    sys.path.insert(0, str(LEGACY_RUNTIME))

from desktop_app import main  # noqa: E402


if __name__ == "__main__":
    raise SystemExit(main())
