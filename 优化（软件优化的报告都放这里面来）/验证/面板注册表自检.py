"""面板注册表语义自检（不需要开窗口）：验证"关掉记忆 / 迁移 / F9 / 重置版面"这几条不回归。

用法：./.venv/bin/python 优化/验证/面板注册表自检.py
"""
from __future__ import annotations

import importlib
import json
import os
import sys
import tempfile

包根 = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
面板目录 = os.path.join(包根, "软件", "面板")
for p in (os.path.join(包根, "软件"), 面板目录):
    if p not in sys.path:
        sys.path.insert(0, p)

状态文件 = os.path.join(包根, "输出", "面板.json")
老状态文件 = os.path.join(包根, "输出", "面板状态.json")
备份 = {}


def 读路径(路径):
    try:
        with open(路径, encoding="utf-8") as f:
            return f.read()
    except FileNotFoundError:
        return None


def 写路径(路径, 文本):
    os.makedirs(os.path.dirname(路径), exist_ok=True)
    with open(路径, "w", encoding="utf-8") as f:
        f.write(文本)


def 还原():
    for 路径, 内容 in 备份.items():
        if 内容 is None:
            if os.path.exists(路径):
                os.remove(路径)
        else:
            写路径(路径, 内容)


class 假面板:
    def __init__(self, 名):
        self.面板显示名 = 名
        self.可见 = False
        self.加载次数 = 0


def 重载():
    import 面板注册表
    模块 = importlib.reload(面板注册表)
    模块.重置缓存()          # 自检要反复换状态文件验证，所以每次重载都清一遍内存状态
    return 模块


def 用例(说明, 条件, 细节=""):
    print(f"  {'✓' if 条件 else '✗'} {说明}" + (f"   [{细节}]" if 细节 and not 条件 else ""))
    return bool(条件)


def main() -> int:
    print("=" * 74)
    print("  面板注册表 语义自检（面板 ① 关掉记忆 ② 老状态迁移 ③ F9 ④ 重置版面）")
    print("=" * 74)
    备份[状态文件] = 读路径(状态文件)
    备份[老状态文件] = 读路径(老状态文件)
    通过 = 0
    总数 = 0
    try:
        # ---- ① 新状态文件：容器关着 → 面板全部不可见；打开 → 全部可见 ----
        print("\n① 容器开关 → 面板可见性（不再有「某个面板被永久关掉」这回事）")
        写路径(状态文件, json.dumps({"容器可见": False, "当前页签": "外观", "弹出": {}},
                                    ensure_ascii=False))
        注册 = 重载()
        甲, 乙 = 假面板("外观"), 假面板("模型库")
        注册.每帧(甲)
        注册.每帧(乙)
        总数 += 1
        通过 += 用例("容器关着 → 面板不可见", 甲.可见 is False and 乙.可见 is False)
        注册.全部显示()
        总数 += 2
        通过 += 用例("F9（全部显示）→ 打开容器", 注册.容器可见() is True)
        通过 += 用例("F9 之后两个面板都可见", 甲.可见 is True and 乙.可见 is True)
        总数 += 1
        通过 += 用例("状态文件里没有「面板被关掉」的字段",
                    "容器可见" in (读路径(状态文件) or "") and "关于" not in (读路径(状态文件) or ""))

        # ---- ② 老状态文件迁移：老版把所有面板都关了 → 容器默认收起 ----
        print("\n② 老版状态迁移（老文件里面板全关 = 用户想清屏 → 容器默认收起）")
        if os.path.exists(状态文件):
            os.remove(状态文件)
        写路径(老状态文件, json.dumps({"关于": False, "外观": False, "模型库": False},
                                    ensure_ascii=False))
        注册 = 重载()
        注册.每帧(假面板("外观"))
        总数 += 1
        通过 += 用例("老文件全关 → 容器收起", 注册.容器可见() is False)
        if os.path.exists(状态文件):
            os.remove(状态文件)
        写路径(老状态文件, json.dumps({"关于": False, "外观": True}, ensure_ascii=False))
        注册 = 重载()
        注册.每帧(假面板("外观"))
        总数 += 1
        通过 += 用例("老文件里有开着的 → 容器打开", 注册.容器可见() is True)

        # ---- ③ 弹出 / 收回 ----
        print("\n③ 弹出去 / 收回来")
        注册 = 重载()
        面板 = 假面板("外观")
        注册.每帧(面板)
        注册.设弹出(面板, True)
        画在容器里 = 注册.画在容器里(面板)
        总数 += 1
        通过 += 用例("弹出后面板自己开窗口（不再由容器画）", 画在容器里 is False)
        注册.全部显示()
        总数 += 1
        通过 += 用例("F9 把弹出的面板收回页签", 注册.是弹出(面板) is False)
        总数 += 1
        通过 += 用例("收回后又由容器画", 注册.画在容器里(面板) is True)

        # ---- ④ 重置版面：只清我们自己的窗口记录，不动官方布局 ----
        print("\n④ 重置版面（清理 ~/.mujoco.ini 里我们这些窗口的记录）")
        ini = os.path.join(tempfile.mkdtemp(), "fake.ini")
        写路径(ini, "\n".join([
            "[Window][Dockspace]", "Pos=0,22", "Size=1200,746", "",
            "[Window][Options]", "Pos=0,22", "DockId=0x00000001,0", "",
            "[Window][Model library]", "Pos=12,56", "Size=360,460", "DockId=0x00000009,0", "",
            "[Window][Appearance]", "Pos=341,189", "DockId=0x00000009,1", "",
            "[Window][About]", "Pos=162,262", "Size=325,776", "",
            "[Docking][Data]", "DockNode ID=0x00000009 Pos=341,189 Size=486,387", "",
            "[Studio][UX]", "theme=1", ""]))
        注册._IMGUI配置 = ini
        注册._清理ini()
        剩下 = 读路径(ini) or ""
        总数 += 6
        通过 += 用例("我们自己的窗口段被删掉（Model library）", "[Window][Model library]" not in 剩下)
        通过 += 用例("我们自己的窗口段被删掉（Appearance）", "[Window][Appearance]" not in 剩下)
        通过 += 用例("官方窗口段保留（Options）", "[Window][Options]" in 剩下)
        通过 += 用例("残留的 DockId 行被清掉", "DockId" not in 剩下)
        # ★ 这两条是回归防线：第一版清理把"跳过"标志一直带下去，把删掉的窗口**之后**
        #   的所有段落都吞了（官方停靠布局 [Docking][Data] 与主题 [Studio][UX] 全没）。
        通过 += 用例("官方停靠数据保留（[Docking][Data]）", "[Docking][Data]" in 剩下)
        通过 += 用例("主题设置保留（[Studio][UX] / theme=1）",
                    "[Studio][UX]" in 剩下 and "theme=1" in 剩下)
    finally:
        还原()

    print("\n" + "=" * 74)
    print(f"  结果：{通过}/{总数} 项通过")
    print("=" * 74)
    return 0 if 通过 == 总数 else 1


if __name__ == "__main__":
    raise SystemExit(main())
