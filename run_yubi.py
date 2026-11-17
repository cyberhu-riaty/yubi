"""Stable ASCII entry point for the Yubi desktop application."""
from __future__ import annotations

from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parent
RUNTIME_DIRECTORY = ROOT / "runtime"
if str(RUNTIME_DIRECTORY) not in sys.path:
    sys.path.insert(0, str(RUNTIME_DIRECTORY))

from legacy_imports import install

install()

from desktop_app import main  # noqa: E402


if __name__ == "__main__":
    raise SystemExit(main())
