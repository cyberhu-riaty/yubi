"""Load MuJoCo XML across platforms and compose the shared scene."""
from __future__ import annotations

import os
import re
import warnings


PACKAGE_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
COMMON_SCENE_PATH = os.path.join(PACKAGE_ROOT, "模型", "公共场景.xml")


def _read_xml_and_assets(
    path: str,
) -> tuple[str, dict[str, bytes], dict[str, bytes]]:
    """Read one XML plus sibling include files and binary assets."""
    with open(path, encoding="utf-8") as source_file:
        xml = source_file.read()

    directory = os.path.dirname(os.path.abspath(path))
    include_files: dict[str, bytes] = {}
    assets: dict[str, bytes] = {}
    for current_directory, _, filenames in os.walk(directory):
        for filename in filenames:
            file_path = os.path.join(current_directory, filename)
            if os.path.normcase(file_path) == os.path.normcase(os.path.abspath(path)):
                continue
            relative_path = os.path.relpath(file_path, directory).replace(os.sep, "/")
            with open(file_path, "rb") as asset_file:
                content = asset_file.read()
            if filename.lower().endswith(".xml"):
                include_files[relative_path] = content
            else:
                assets[relative_path] = content
    return xml, include_files, assets


def _load_raw_model(mujoco, path: str):
    """Load a model without attaching the shared scene."""
    try:
        return mujoco.MjModel.from_xml_path(path)
    except ValueError:
        if os.name != "nt" or str(path).isascii() or not str(path).lower().endswith(".xml"):
            raise

    # MuJoCo may reject a non-ASCII Windows path even when Python can open it.
    with open(path, encoding="utf-8") as source_file:
        xml = source_file.read()
    try:
        return mujoco.MjModel.from_xml_string(xml)
    except ValueError:
        pass

    xml, include_files, assets = _read_xml_and_assets(path)
    all_assets = {**include_files, **assets}
    return mujoco.MjModel.from_xml_string(xml, assets=all_assets or None)


def _has_ground_plane(mujoco, model) -> bool:
    plane_type = int(mujoco.mjtGeom.mjGEOM_PLANE)
    return any(
        int(model.geom_type[index]) == plane_type
        for index in range(int(model.ngeom))
    )


def _attach_common_scene(mujoco, path: str):
    """Attach the shared environment to a robot specification and compile it."""
    robot_spec = load_spec(mujoco, path)
    environment_spec = load_spec(mujoco, COMMON_SCENE_PATH)
    attachment_frame = robot_spec.worldbody.add_frame(name="yubi_environment_frame")
    # MuJoCo prefixes attached assets and fixes their references automatically.
    with warnings.catch_warnings():
        warnings.filterwarnings(
            "ignore", message="Attaching a child without asset dict.*")
        robot_spec.attach(
            environment_spec,
            prefix="yubi_env_",
            frame=attachment_frame,
        )
    return robot_spec.compile()


def load_model(mujoco, path: str):
    """Load a model and attach the shared scene when no ground plane exists."""
    model = _load_raw_model(mujoco, path)
    if (
        not os.path.isfile(COMMON_SCENE_PATH)
        or os.path.normcase(os.path.abspath(path))
        == os.path.normcase(os.path.abspath(COMMON_SCENE_PATH))
        or _has_ground_plane(mujoco, model)
    ):
        return model
    return _attach_common_scene(mujoco, path)


def load_spec(mujoco, path: str):
    """Load an ``MjSpec`` with a Windows non-ASCII-path fallback."""
    try:
        return mujoco.MjSpec.from_file(path)
    except ValueError:
        if os.name != "nt" or str(path).isascii() or not str(path).lower().endswith(".xml"):
            raise

    with open(path, encoding="utf-8") as source_file:
        xml = source_file.read()
    if not re.search(r"\bfile\s*=", xml):
        return mujoco.MjSpec.from_string(xml)

    xml, include_files, assets = _read_xml_and_assets(path)
    return mujoco.MjSpec.from_string(
        xml,
        include=include_files or None,
        assets=assets or None,
    )


__all__ = ["PACKAGE_ROOT", "COMMON_SCENE_PATH", "load_model", "load_spec"]
