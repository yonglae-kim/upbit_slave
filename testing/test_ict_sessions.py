import subprocess
import sys
import textwrap
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent.parent


class ICTSessionCompatibilityTest(unittest.TestCase):
    def test_module_import_falls_back_when_zoneinfo_is_unavailable(self):
        code = textwrap.dedent(
            """
            import builtins
            import importlib

            original_import = builtins.__import__


            def fake_import(name, globals=None, locals=None, fromlist=(), level=0):
                if name == "zoneinfo":
                    raise ModuleNotFoundError("No module named 'zoneinfo'")
                return original_import(name, globals, locals, fromlist, level)


            builtins.__import__ = fake_import
            module = importlib.import_module("core.strategies.ict_sessions")
            print(
                module.is_in_silver_bullet_window(
                    {"candle_date_time_utc": "2024-01-02T15:30:00"}
                )
            )
            """
        )

        result = subprocess.run(
            [sys.executable, "-c", code],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "True")


if __name__ == "__main__":
    unittest.main()
