from __future__ import annotations

import importlib.util
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[2]
MODULE_PATH = ROOT / "tools" / "package_macos_app.py"
SPEC = importlib.util.spec_from_file_location("package_macos_app_test_target", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
PACKAGE_MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(PACKAGE_MODULE)


class MacOSLauncherTemplateTests(unittest.TestCase):
    def test_launcher_runs_an_entry_and_forwards_arguments(self):
        bash = shutil.which("bash")
        if bash is None:
            self.skipTest("Bash is required to exercise the macOS launcher template")

        with tempfile.TemporaryDirectory(prefix="yubi-launcher-test-") as temporary:
            package_root = Path(temporary) / "package"
            resources = package_root / "Yubi.app" / "Contents" / "Resources"
            python = package_root / ".venv" / "bin" / "python"
            resources.mkdir(parents=True)
            python.parent.mkdir(parents=True)
            (package_root / "run_yubi.py").write_text("# test entry\n", encoding="utf-8")
            (package_root / "run_yubi_web.py").write_text("# fallback entry\n", encoding="utf-8")
            (resources / "package_path.txt").write_text(str(package_root) + "\n", encoding="utf-8")

            arguments_file = package_root / "arguments.txt"
            python.write_text(
                "#!/bin/bash\nprintf '%s\\n' \"$@\" > \"$YUBI_TEST_ARGUMENTS\"\n",
                encoding="utf-8",
            )
            python.chmod(0o755)

            template = PACKAGE_MODULE.LAUNCH_SCRIPT_TEMPLATE
            script = (template
                      .replace("{app_name}", "Yubi")
                      .replace("{entry_path}", "run_yubi.py")
                      .replace("{fallback_candidates}", '"$PKG_DIR/run_yubi_web.py"')
                      .replace("{package_dir_name}", package_root.name)
                      .replace("{extra_args}", "")
                      .replace("{{", "{").replace("}}", "}"))
            launcher = resources / "launch.sh"
            launcher.write_text(script, encoding="utf-8")
            launcher.chmod(0o755)

            env = os.environ.copy()
            env["YUBI_TEST_ARGUMENTS"] = str(arguments_file)
            result = subprocess.run(
                [bash, str(launcher), "--check"], cwd=package_root, env=env,
                capture_output=True, text=True, check=False,
            )

            self.assertEqual(result.returncode, 0, result.stderr or result.stdout)
            self.assertEqual(arguments_file.read_text(encoding="utf-8").splitlines()[-1], "--check")


if __name__ == "__main__":
    unittest.main()
