"""跨平台加载 MuJoCo XML，兼容 Windows 中文路径。"""
from __future__ import annotations

import os
import re


def _读取XML与资源(路径: str) -> tuple[str, dict[str, bytes], dict[str, bytes]]:
    with open(路径, encoding="utf-8") as 文件:
        xml = 文件.read()

    目录 = os.path.dirname(os.path.abspath(路径))
    包含文件: dict[str, bytes] = {}
    资源: dict[str, bytes] = {}
    for 当前目录, _, 文件名们 in os.walk(目录):
        for 文件名 in 文件名们:
            文件路径 = os.path.join(当前目录, 文件名)
            if os.path.normcase(文件路径) == os.path.normcase(os.path.abspath(路径)):
                continue
            相对路径 = os.path.relpath(文件路径, 目录).replace(os.sep, "/")
            with open(文件路径, "rb") as 文件:
                内容 = 文件.read()
            if 文件名.lower().endswith(".xml"):
                包含文件[相对路径] = 内容
            else:
                资源[相对路径] = 内容
    return xml, 包含文件, 资源


def 加载模型(mujoco, 路径: str):
    """优先按路径加载；Windows 中文 XML 路径失败时改为内存加载。"""
    try:
        return mujoco.MjModel.from_xml_path(路径)
    except ValueError:
        if os.name != "nt" or str(路径).isascii() or not str(路径).lower().endswith(".xml"):
            raise

    with open(路径, encoding="utf-8") as 文件:
        xml = 文件.read()
    try:
        return mujoco.MjModel.from_xml_string(xml)
    except ValueError:
        pass

    xml, 包含文件, 资源 = _读取XML与资源(路径)
    全部资源 = {**包含文件, **资源}
    return mujoco.MjModel.from_xml_string(xml, assets=全部资源 or None)


def 加载规格(mujoco, 路径: str):
    """加载 MjSpec，并为 Windows 中文 XML 路径提供相同的回退。"""
    try:
        return mujoco.MjSpec.from_file(路径)
    except ValueError:
        if os.name != "nt" or str(路径).isascii() or not str(路径).lower().endswith(".xml"):
            raise

    with open(路径, encoding="utf-8") as 文件:
        xml = 文件.read()
    if not re.search(r"\bfile\s*=", xml):
        return mujoco.MjSpec.from_string(xml)

    xml, 包含文件, 资源 = _读取XML与资源(路径)
    return mujoco.MjSpec.from_string(
        xml,
        include=包含文件 or None,
        assets=资源 or None,
    )
