from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def test_photo_page_frontend_regressions():
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node.js is required for the frontend mock regressions")
    result = subprocess.run(
        [node, str(ROOT / "tests" / "frontend_photo_page_regressions.cjs")],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=30,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
