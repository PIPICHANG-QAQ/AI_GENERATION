#!/usr/bin/env python3
from __future__ import annotations

import os
import re
import subprocess
import tempfile
import unittest
from pathlib import Path


SCRIPT_PATH = Path(__file__).with_name("docker-entrypoint.sh")
CLEANUP_TAIL = re.compile(
    r'^status=0\n'
    r'wait -n "\$\{pids\[@\]\}" \|\| status=\$\?\n'
    r'terminate\n'
    r'exit "\$\{status\}"\s*$',
    flags=re.MULTILINE,
)


class DockerEntrypointContractTest(unittest.TestCase):
    def test_nonzero_wait_still_terminates_all_processes_and_preserves_status(self):
        source = SCRIPT_PATH.read_text(encoding="utf-8")
        match = CLEANUP_TAIL.search(source)
        self.assertIsNotNone(match, "entrypoint must capture wait -n failure before cleanup")

        with tempfile.TemporaryDirectory() as tmp:
            terminate_log = Path(tmp) / "terminate.log"
            harness = (
                "set -euo pipefail\n"
                "pids=(101 202)\n"
                "wait() { return 23; }\n"
                "terminate() { printf 'terminated\\n' >> \"${TERMINATE_LOG}\"; }\n"
                f"{match.group(0)}\n"
            )
            completed = subprocess.run(
                ["bash", "-c", harness],
                env={**os.environ, "TERMINATE_LOG": str(terminate_log)},
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertEqual(23, completed.returncode)
            self.assertEqual("terminated\n", terminate_log.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
