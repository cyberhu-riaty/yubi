"""Run a short UR10 simulation with identified nonlinear joint friction."""

from pathlib import Path
import sys

import mujoco
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from friction import UR10Friction, step_with_friction  # noqa: E402


def main() -> None:
    model = mujoco.MjModel.from_xml_path(str(ROOT / "models" / "ur10_extfric.xml"))
    data = mujoco.MjData(model)
    law = UR10Friction()
    indices = law.validate_model(model)
    mujoco.mj_resetDataKeyframe(model, data, 0)
    data.ctrl[:] = data.qpos  # Existing XML actuators are position servos.
    for _ in range(100):
        friction_torque = step_with_friction(model, data, law)
    print(f"time_s: {data.time:.3f}")
    print("joint_position_rad:", np.array2string(data.qpos, precision=4))
    print("joint_velocity_rad_s:", np.array2string(data.qvel[indices], precision=4))
    print("friction_compensation_Nm:", np.array2string(friction_torque, precision=4))


if __name__ == "__main__":
    main()
