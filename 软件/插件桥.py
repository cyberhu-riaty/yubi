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
import os
from typing import Any

from 官方层 import messages          # 全部走适配层，见 软件/官方层.py


# ---------------------------------------------------------------------------
# 仿真侧 → 界面：插件目录
# ---------------------------------------------------------------------------
@dataclasses.dataclass(frozen=True)
class 插件目录(messages.Snapshot):
    数量: int = 0
    # 每项：{插件, 分组, 版本, 说明, 作者, 文件, 被项目使用, 当前启用}
    插件: tuple = ()
    说明: str = ""


# 插件类上我们认识的元信息（与 算法库/通用/我的控制律_模板.py 里的一致）
元信息字段 = ("名称", "版本", "说明", "作者")


def _读类属性(路径: str) -> dict[str, str]:
    """用 AST 从插件文件里取"类属性字面量"，**不执行代码**。

    只认顶层 `class Xxx:` 里的 `版本 = "1.1"` 这种简单赋值；
    取不到就跳过（宁可留空也不猜）。
    """
    出: dict[str, str] = {}
    try:
        树 = ast.parse(open(路径, encoding="utf-8").read())
    except (OSError, SyntaxError, UnicodeDecodeError):
        return 出
    for 节点 in 树.body:
        if not isinstance(节点, ast.ClassDef):
            continue
        for 子 in 节点.body:
            if not isinstance(子, ast.Assign):
                continue
            for 目标 in 子.targets:
                if not isinstance(目标, ast.Name) or 目标.id not in 元信息字段:
                    continue
                if isinstance(子.value, ast.Constant) and isinstance(子.value.value, str):
                    # 第一个带字面量值的类优先（一个文件里通常只有一个插件类）
                    出.setdefault(目标.id, 子.value.value)
    return 出


def _被项目使用(包根: str) -> dict[str, list[str]]:
    """反查：每个插件被哪些项目用到。数据来自 `项目/*.json` 的 `算法` 列。"""
    import json
    结果: dict[str, list[str]] = {}
    目录 = os.path.join(包根, "项目")
    try:
        文件名们 = [n for n in os.listdir(目录) if n.endswith(".json") and n != "索引.json"]
    except OSError:
        return 结果
    for 名 in sorted(文件名们):
        try:
            d = json.load(open(os.path.join(目录, 名), encoding="utf-8"))
        except Exception:                                             # noqa: BLE001
            continue
        项目名 = str(d.get("项目") or os.path.splitext(名)[0])
        for 项 in (d.get("算法") or []):
            插件 = str((项 or {}).get("插件") or "") if isinstance(项, dict) else ""
            if 插件:
                结果.setdefault(插件, []).append(项目名)
    return 结果


def 取插件目录(包根: str, 当前算法: list[str] | None = None) -> dict:
    """给发布器用：扫 `算法库/` 出清单。

    参数
      当前算法 : 当前项目真正启用的插件名（有序）。用来标"已启用"。
    """
    import 项目 as _项目

    启用 = set(当前算法 or [])
    使用表 = _被项目使用(包根)
    出 = []
    try:
        发现 = _项目.发现的算法()
    except Exception as 异常:                                         # noqa: BLE001
        return {"数量": 0, "插件": [], "说明": f"算法库扫描失败：{异常}"}

    for 项 in 发现:
        名 = str(项.get("插件", ""))
        文件 = str(项.get("文件", ""))
        元 = _读类属性(文件) if 文件 else {}
        出.append({
            "插件": 名,
            "分组": str(项.get("分组", "")),
            "版本": 元.get("版本", ""),
            "说明": 元.get("说明", ""),
            "作者": 元.get("作者", ""),
            "名称": 元.get("名称", 名),
            "文件": str(项.get("相对包根", "")),
            "被项目使用": 使用表.get(名, []),
            # ★ 判定"已启用"要同时认两种标识：
            #   · 模块名（`关节pd控制`）—— 项目文件与命令里用的就是它
            #   · 类属性 `名称`（`关节 PD 位置控制`）—— 插件实例上只有这个
            #   只认一种的话，界面上那个"已启用"徽标永远不亮
            #   （实测踩过：后端明明装配成功，前端还显示未启用）。
            "当前启用": (名 in 启用) or (元.get("名称", "") in 启用),
        })
    出.sort(key=lambda x: (not x["当前启用"], x["分组"], x["插件"]))
    return {"数量": len(出), "插件": 出, "说明": ""}
