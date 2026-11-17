"""
ui_bridge.py —— 把官方 GUI 面板的数值传给插件（viewer 侧插件）

为什么需要它：
  官方把程序分成两半 —— 仿真侧（sim）和窗口侧（viewer）。两边只能通过消息通信。
  窗口侧的 `ux_state.ctrl_target` 就是你拖【Controls】面板滑杆时改的那 6 个目标值，
  但它住在 viewer 侧；插件住在 sim 侧，默认拿不到。
  这个小插件住在 viewer 侧，每帧把 ctrl_target 塞进一条消息发给 sim 侧。

插件使用方式（见 plugins/关节pd控制.py）：
      @每步
      def step(self, event: messages.StepEvent) -> bool:
          目标 = 插件.滑块目标(界面.面板目标, 默认值)     # ← 界面滑杆优先
"""
from __future__ import annotations

import dataclasses
import os

from official_api import messages, viewer_protocol    # 全部走适配层，见 runtime/official_api.py


@dataclasses.dataclass(frozen=True)
class PanelTargetMessage(messages.Snapshot):
    """一条「最新覆盖」消息：滑杆的当前值（Snapshot = 只保留最新一条，不排队）。

    注意：官方所有具体消息都是 dataclass 并且**必须加 @dataclasses.dataclass**，
    否则 pybind 侧的字段访问拿不到值（实测：不加时消息对象是空的）。
    """

    ctrl_target: object


class UIBridge:
    """viewer 侧插件：① 每帧把 Controls 面板的滑杆值发给仿真侧 ② 首帧应用界面主题。"""

    def __init__(self):
        self.viewer = None
        self.panel_target = None                 # 给需要在 viewer 侧读的人用
        self._theme_applied = False

    @messages.handler(priority=messages.Priority.CRITICAL)
    def _remember_viewer(self, event: viewer_protocol.ViewerInitEvent) -> bool:
        self.viewer = event.viewer
        return False

    # ------------------------------------------------------------------
    # 界面主题：必须等窗口和 ImGui 上下文都建好之后才能设置。
    # ★ 踩过的坑：在窗口创建之前调用 ux.setup_theme() 会直接**段错误（segfault）**，
    #   整个程序崩掉、窗口都没有。所以放到首帧里做。
    # ------------------------------------------------------------------
    @messages.handler(priority=messages.Priority.CRITICAL)
    def _apply_initial_theme(self, event: messages.UpdateEvent) -> bool:
        if self._theme_applied:
            return False
        self._theme_applied = True
        self._apply_theme()
        return False

    def _apply_theme(self) -> None:
        from official_api import ux          # 全部走适配层，见 runtime/official_api.py

        theme_name = (os.environ.get("MUJOCO_STUDIO_THEME") or "").strip().upper()
        if not theme_name:
            return
        themes = {"LIGHT": ux.GuiTheme.LIGHT, "浅色": ux.GuiTheme.LIGHT,
              "DARK": ux.GuiTheme.DARK, "深色": ux.GuiTheme.DARK,
              "CLASSIC": ux.GuiTheme.CLASSIC, "经典": ux.GuiTheme.CLASSIC}
        theme = themes.get(theme_name)
        if theme is None:
            print(f'⚠ 认不出主题「{theme_name}」，可选：dark / light / classic')
            return
        try:
            # 官方 ViewerApp 关闭窗口时会用它自己记的 theme 再存一次设置，
            # 不告诉它的话，就会把我们刚设的深色覆盖回浅色（实测踩过）。
            # 这里把主题同步给官方 App：菜单显示、实际样式、保存的值三者一致。
            for instance in self._viewer_apps():
                instance.theme = theme
            ux.setup_theme(theme)
            ux.save_settings(theme)          # 存进 ~/.mujoco.ini，下次启动仍是这个主题
            print(f'【界面主题】已设为 {theme.name}'
                  f"（改：--主题 dark/light/classic，或窗口里 Options → Theme）", flush=True)
        except Exception as exc:           # noqa: BLE001 —— 主题失败不能影响使用
            print(f'⚠ 主题设置失败（不影响使用）：{exc}')

    def _viewer_apps(self):
        """窗口侧带 theme 属性的插件（就是官方 ViewerApp）。

        官方 Viewer 只保留 PluginRegistry、不保留插件实例列表，
        所以由我们的窗口子类在构造时把实例挂到 viewer.app 上（见 制作窗口类）。
        """
        window = getattr(self.viewer, "app", None)
        return [window] if window is not None else []

    @messages.handler
    def _publish_target(self, event: messages.UpdateEvent) -> bool:
        viewer = self.viewer
        if viewer is None:
            return False

        # ★ Web 上行命令的接缝（P1）：这里**已经**满足三个条件 ——
        #   每帧、在 viewer 线程、手里有 viewer（= 能 send_to_sim）。
        #   所以 Web 来的命令不必新起线程，也不必改仿真循环，在这里顺手清空队列即可。
        #   `命令桥` 内部只在队列非空时才做事，空队列的代价是一次加锁取空表。
        try:
            import command_bridge as _command_bridge
            _command_bridge.forward_pending_commands(viewer)
        except Exception:                      # noqa: BLE001 —— 命令通道绝不能拖垮绘制
            pass

        ux_state = getattr(viewer, "ux_state", None)
        target = getattr(ux_state, "ctrl_target", None) if ux_state is not None else None
        if target is None:
            return False
        self.panel_target = target
        try:
            viewer.send_to_sim(PanelTargetMessage(ctrl_target=target.copy()))
        except Exception:                      # noqa: BLE001 —— 界面桥绝不能拖垮窗口
            pass
        return False


def make_window_class(window_base):
    """把官方 ViewerApp 包一层：让界面桥能拿到它，从而正确设置/保留界面主题。

    为什么需要：
      官方 Viewer 只保留了 PluginRegistry，没有保留插件实例列表 —— 界面桥要同步主题
      就得能拿到 ViewerApp 本体，所以在这里把本窗口挂到 `viewer.app`。
      之后 `界面桥._应用主题()` 会把主题同时写进：官方 App 的 theme（菜单显示）、
      ImGui 样式（实际外观）、ini 文件（下次启动的值），三者保持一致。
    """
    from official_api import ux          # 全部走适配层，见 runtime/official_api.py

    class WorkbenchWindow(window_base):
        theme_name = (os.environ.get("MUJOCO_STUDIO_THEME") or "").strip().upper()

        @messages.handler(priority=messages.Priority.CRITICAL)
        def _attach_app(self, event: viewer_protocol.ViewerInitEvent) -> bool:
            event.viewer.app = self
            return False

        @messages.handler(priority=messages.Priority.INTERNAL)
        def _save_cli_theme_on_exit(self, event: messages.ExitEvent) -> bool:
            # 官方紧接着也会存一次；这里先按 CLI 指定的主题存，避免被旧值覆盖
            themes = {"LIGHT": ux.GuiTheme.LIGHT, "DARK": ux.GuiTheme.DARK, "CLASSIC": ux.GuiTheme.CLASSIC}
            if self.theme_name in themes:
                self.theme = themes[self.theme_name]
                ux.save_settings(self.theme)
            return False

    return WorkbenchWindow
