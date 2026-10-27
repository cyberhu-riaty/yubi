"""跨平台加载 MuJoCo XML，兼容 Windows 中文路径与公共场景组合。"""
from __future__ import annotations

import os
import re
import warnings


包根 = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
公共场景路径 = os.path.join(包根, "模型", "公共场景.xml")


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


def _加载原模型(mujoco, 路径: str):
    """不附加公共场景地加载一次模型。"""
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


def _已有地面(mujoco, 模型) -> bool:
    平面类型 = int(mujoco.mjtGeom.mjGEOM_PLANE)
    return any(int(模型.geom_type[i]) == 平面类型 for i in range(int(模型.ngeom)))


def _附加公共场景(mujoco, 路径: str):
    """把独立的公共环境 XML 挂到机械臂规格上，再编译成一个 MjModel。"""
    机械臂规格 = 加载规格(mujoco, 路径)
    环境规格 = 加载规格(mujoco, 公共场景路径)
    挂载点 = 机械臂规格.worldbody.add_frame(name="yubi_environment_frame")
    # attach 会自动给环境中的材质、纹理、灯和地面改名并修正引用，
    # 所以不用修改厂家机械臂 XML，也不会与模型自身名称冲突。
    with warnings.catch_warnings():
        warnings.filterwarnings(
            "ignore", message="Attaching a child without asset dict.*")
        机械臂规格.attach(环境规格, prefix="yubi_env_", frame=挂载点)
    return 机械臂规格.compile()


def 加载模型(mujoco, 路径: str):
    """加载模型；纯机械臂 XML 自动与 ``公共场景.xml`` 组合。"""
    模型 = _加载原模型(mujoco, 路径)
    if (not os.path.isfile(公共场景路径)
            or os.path.normcase(os.path.abspath(路径))
            == os.path.normcase(os.path.abspath(公共场景路径))
            or _已有地面(mujoco, 模型)):
        return 模型
    return _附加公共场景(mujoco, 路径)


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
