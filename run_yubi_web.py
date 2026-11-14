"""Stable ASCII entry point for the browser-hosted Yubi application."""
from __future__ import annotations

from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parent
LEGACY_RUNTIME = ROOT / "软件"
if str(LEGACY_RUNTIME) not in sys.path:
    sys.path.insert(0, str(LEGACY_RUNTIME))

from web_app import main  # noqa: E402


if __name__ == "__main__":
    raise SystemExit(main())
