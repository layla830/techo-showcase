import shutil
import subprocess
from pathlib import Path

import pytest


def test_readonly_demo_never_calls_backend():
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node.js is unavailable")
    root = Path(__file__).resolve().parents[1]
    result = subprocess.run(
        [node, "--test", "tests/demo_contract.cjs"],
        cwd=root,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
