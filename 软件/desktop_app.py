"""English desktop application entry point.

The window implementation remains in the legacy module during the incremental
migration.  Launchers and packaging should import this module only.
"""
from __future__ import annotations

from 主程序窗口 import main


__all__ = ["main"]
