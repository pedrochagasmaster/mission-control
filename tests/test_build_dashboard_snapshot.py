import subprocess
import sys
import unittest
from pathlib import Path
from unittest import mock


SCRIPTS_DIR = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

import build_dashboard_snapshot as snapshot  # noqa: E402


class RunTextCommandTests(unittest.TestCase):
    def test_run_text_command_handles_timeout(self) -> None:
        with mock.patch.object(
            snapshot.subprocess,
            "run",
            side_effect=subprocess.TimeoutExpired(cmd=["openclaw", "status"], timeout=5),
        ):
            ok, text = snapshot.run_text_command(["openclaw", "status"])

        self.assertFalse(ok)
        self.assertIn("timed out", text)


if __name__ == "__main__":
    unittest.main()
