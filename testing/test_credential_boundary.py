import os
import shutil
import subprocess
import sys
import tempfile
import unittest


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class CredentialBoundaryTest(unittest.TestCase):
    def test_environment_credentials_are_loaded_without_value_output(self):
        environment = os.environ.copy()
        environment["UPBIT_ACCESS_KEY"] = "fixture-access"
        environment["UPBIT_SECRET_KEY"] = "fixture-secret"

        with tempfile.TemporaryDirectory() as temp_dir:
            shutil.copyfile(os.path.join(ROOT, "apis.py"), os.path.join(temp_dir, "apis.py"))
            environment["PYTHONPATH"] = temp_dir
            result = subprocess.run(
                [
                    sys.executable,
                    "-c",
                    "import apis, os, sys; sys.exit(0 if apis.access_key == os.environ['UPBIT_ACCESS_KEY'] and apis.secret_key == os.environ['UPBIT_SECRET_KEY'] else 1)",
                ],
                cwd=temp_dir,
                env=environment,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                universal_newlines=True,
            )

        self.assertEqual(result.returncode, 0)
        self.assertNotIn("fixture-access", result.stdout + result.stderr)
        self.assertNotIn("fixture-secret", result.stdout + result.stderr)

    def test_live_auth_fails_closed_without_environment_credentials(self):
        environment = os.environ.copy()
        environment.pop("UPBIT_ACCESS_KEY", None)
        environment.pop("UPBIT_SECRET_KEY", None)
        environment["TRADING_MODE"] = "live"

        result = subprocess.run(
            [sys.executable, "-c", "import apis; apis._auth_headers()"],
            cwd=ROOT,
            env=environment,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            universal_newlines=True,
        )

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("CredentialConfigurationError", result.stderr)
        self.assertNotIn("Bearer ", result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
