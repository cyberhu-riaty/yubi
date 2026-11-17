"""Lazy compatibility for pre-migration module imports.

Only explicit historical names are accepted. Canonical implementations and
message classes remain shared with the English modules.
"""
from __future__ import annotations

import importlib
import importlib.abc
import importlib.util
import sys

ALIASES = {'Web桥': 'legacy.web_bridge', '参数辨识': 'legacy.parameter_identification', '命令桥': 'legacy.command_bridge', '契约': 'legacy.contract', '官方层': 'legacy.official_api', '录制桥': 'legacy.recording_bridge', '控制台': 'legacy.console_support', '插件桥': 'legacy.plugin_bridge', '文案': 'legacy.i18n', '界面文字': 'legacy.ascii_text', '界面桥': 'legacy.ui_bridge', '观测核心': 'legacy.observation_core', '设备.契约': 'legacy.devices.contract', '设备.安全层': 'legacy.devices.safety', '设备.模拟后端': 'legacy.devices.simulated_backend', '设备.跟踪回路': 'legacy.devices.tracking_loop', '设备.连接桥': 'legacy.devices.connection_bridge', '诊断桥': 'legacy.diagnostics_bridge', '辨识桥': 'legacy.identification_bridge', '部署桥': 'legacy.deployment_bridge', '验证参数辨识': 'legacy.validate_identification', '骨架.官方接口清单': 'legacy.skeleton.official_interface_inventory', '高亮桥': 'legacy.highlight_bridge', '设备': 'legacy.devices', '骨架': 'legacy.skeleton'}
PACKAGES = {"设备", "骨架"}


class AliasLoader(importlib.abc.Loader):
    def __init__(self, target: str):
        self.target = target

    def create_module(self, spec):
        return importlib.import_module(self.target)

    def exec_module(self, module):
        # create_module already loaded the adapter under its ASCII module name.
        pass


class LegacyImportFinder(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        canonical = ALIASES.get(fullname)
        if canonical is None:
            return None
        return importlib.util.spec_from_loader(
            fullname, AliasLoader(canonical), is_package=fullname in PACKAGES)


def install() -> None:
    """Register once, without importing any Studio, device or GUI dependencies."""
    if not any(isinstance(finder, LegacyImportFinder) for finder in sys.meta_path):
        sys.meta_path.insert(0, LegacyImportFinder())
