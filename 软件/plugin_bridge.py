"""
插件桥.py —— 界面的「插件」目录（P4 · 插件市场）

★ 先说清楚这一步**做到了哪、没做到哪**（这比功能本身更重要）：

  做到了：把 `算法库/` 下的插件连同它们的**真实元信息**（版本/说明/作者/分组/
          被哪些项目用到）列出来，并能在当前项目里启用/停用。
          数据全部来自磁盘上的真实文件，没有一条是编的。

  **没做到**：远端市场（下载安装）。这个软件没有远端仓库、没有签名校验、没有
          版本服务器 —— 所以界面上**不画一个像商店的页面**。
          一个"点了会转圈但不会安装任何东西"的市场，比没有市场更糟：
          它会让用户以为插件装上了。

          同理也没有"从文件夹安装"：那需要文件选择器 + 复制 + 冲突处理，
          而且**装了不等于能用**（插件还得符合我们的接口）。这一版先不做，
          界面上如实写"当前只列出本机算法库里的插件"。

为什么元信息用 **AST 解析**而不是 import：
    · import 会**执行模块顶层代码**。列个清单而已，不值得冒副作用的风险
      （插件里有 import numpy、读文件、甚至建线程的都不奇怪）。
    · AST 只读源码文本，快且无副作用。代价是"只认类属性字面量"——
      如果哪天有人把 `版本` 写成 f-string 或函数调用，这里会读不到。
      所以**读不到就留空**，界面上显示「未标注」，绝不猜。
"""
from __future__ import annotations

import ast
import dataclasses
from wire_compatibility import legacy_wire
import os
from typing import Any

from official_api import messages          # 全部走适配层，见 软件/official_api.py


# ---------------------------------------------------------------------------
# 仿真侧 → 界面：插件目录
# ---------------------------------------------------------------------------
@legacy_wire('PluginCatalog', {'count': '数量', 'plugins': '插件', 'description': '说明'})
@dataclasses.dataclass(frozen=True)
class PluginCatalog(messages.Snapshot):
    count: int = 0
    # 每项：{插件, 分组, 版本, 说明, 作者, 文件, 被项目使用, 当前启用, 当前顺序}
    plugins: tuple = ()
    description: str = ""


# 插件类上我们认识的元信息（与 算法库/通用/我的控制律_模板.py 里的一致）
METADATA_FIELDS = {
    "name": "名称",
    "version": "版本",
    "description": "说明",
    "author": "作者",
}


def _read_class_attributes(path: str) -> dict[str, str]:
    """用 AST 从插件文件里取"类属性字面量"，**不执行代码**。

    只认顶层 `class Xxx:` 里的 `版本 = "1.1"` 这种简单赋值；
    取不到就跳过（宁可留空也不猜）。
    """
    output: dict[str, str] = {}
    try:
        tree = ast.parse(open(path, encoding="utf-8").read())
    except (OSError, SyntaxError, UnicodeDecodeError):
        return output
    for node in tree.body:
        if not isinstance(node, ast.ClassDef):
            continue
        for child in node.body:
            if not isinstance(child, ast.Assign):
                continue
            for target in child.targets:
                if not isinstance(target, ast.Name) or target.id not in METADATA_FIELDS:
                    continue
                if isinstance(child.value, ast.Constant) and isinstance(child.value.value, str):
                    # 第一个带字面量值的类优先（一个文件里通常只有一个插件类）
                    output.setdefault(METADATA_FIELDS[target.id], child.value.value)
    return output


def _projects_using_plugins(package_root: str) -> dict[str, list[str]]:
    """反查：每个插件被哪些项目用到。数据来自 `项目/*.json` 的 `算法` 列。"""
    import json
    result: dict[str, list[str]] = {}
    directory = os.path.join(package_root, "项目")
    try:
        filenames = [n for n in os.listdir(directory) if n.endswith(".json") and n != "索引.json"]
    except OSError:
        return result
    for name in sorted(filenames):
        try:
            d = json.load(open(os.path.join(directory, name), encoding="utf-8"))
        except Exception:                                             # noqa: BLE001
            continue
        project_name = str(d.get("项目") or os.path.splitext(name)[0])
        for items in (d.get("算法") or []):
            plugins = str((items or {}).get("插件") or "") if isinstance(items, dict) else ""
            if plugins:
                result.setdefault(plugins, []).append(project_name)
    return result


def get_plugin_catalog(package_root: str, current_algorithms: list[str] | None = None) -> dict:
    """给发布器用：扫 `算法库/` 出清单。

    参数
      当前算法 : 当前项目真正启用的插件名（有序）。用来标"已启用"。
    """
    import project_registry as _project

    # 顺序不能只做成 set：多个算法依次写 data.ctrl 时，后执行者可能覆盖前者。
    # 插件目录把真实执行序号一并交给 GUI，避免用户只点一次保存就改变控制顺序。
    enabled_order = {str(identifier): i for i, identifier in enumerate(current_algorithms or [])}
    usage = _projects_using_plugins(package_root)
    output = []
    try:
        discovered = _project.discover_algorithms()
    except Exception as exc:                                         # noqa: BLE001
        return {"数量": 0, "插件": [], "说明": f"算法库扫描失败：{exc}"}

    for items in discovered:
        name = str(items.get("插件", ""))
        file = str(items.get("文件", ""))
        metadata = _read_class_attributes(file) if file else {}
        display_name = metadata.get("名称", name)
        current_order = enabled_order.get(name, enabled_order.get(display_name, -1))
        output.append({
            "插件": name,
            "分组": str(items.get("分组", "")),
            "版本": metadata.get("版本", ""),
            "说明": metadata.get("说明", ""),
            "作者": metadata.get("作者", ""),
            "名称": display_name,
            "文件": str(items.get("相对包根", "")),
            "被项目使用": usage.get(name, []),
            # ★ 判定"已启用"要同时认两种标识：
            #   · 模块名（`关节pd控制`）—— 项目文件与命令里用的就是它
            #   · 类属性 `名称`（`关节 PD 位置控制`）—— 插件实例上只有这个
            #   只认一种的话，界面上那个"已启用"徽标永远不亮
            #   （实测踩过：后端明明装配成功，前端还显示未启用）。
            "当前启用": current_order >= 0,
            "当前顺序": current_order if current_order >= 0 else None,
        })
    output.sort(key=lambda x: (
        not x["当前启用"],
        x["当前顺序"] if x["当前顺序"] is not None else 10**9,
        x["分组"],
        x["插件"],
    ))
    return {"数量": len(output), "插件": output, "说明": ""}

WIRE_CLASS_ALIASES = {'PluginCatalog': 'PluginCatalog'}
