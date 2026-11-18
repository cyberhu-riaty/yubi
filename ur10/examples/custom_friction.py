"""Interface example: uses the same coefficients as the power law.

Replace the formula here for a new stateless, velocity-based friction model.
"""

import numpy as np

LABEL = "自定义摩擦示例"


def torque(velocity, parameters):
    """rad/s -> compensation N m; preserve the (..., 6) input shape."""
    p = {key: np.asarray(parameters[key]) for key in ("fc", "fv", "b", "alpha")}
    return (p["fc"] + p["fv"] * np.abs(velocity) ** p["alpha"]) * np.sign(velocity) + p[
        "b"
    ]
