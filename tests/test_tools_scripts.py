"""工具脚本要能按用法里写的方式（uv run python tools/xxx.py）直接跑。

pytest 会把仓库根放进 sys.path，所以 `from tools.xxx import` 在测试里总是好的；
按脚本路径跑时仓库根不在 sys.path 里，这里用子进程按真实用法跑一遍 --help。
"""

import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent


@pytest.mark.parametrize("script", ["eval_threads.py", "probe_book.py", "eval_entities.py", "scramble.py",
                                    "eval_archives.py", "export_lane_fixtures.py", "eval_skeleton.py"])
def test_tool_runs_as_a_script(script):
    env = {**os.environ, "PYTHONIOENCODING": "utf-8"}
    r = subprocess.run(
        [sys.executable, str(ROOT / "tools" / script), "--help"], cwd=ROOT, capture_output=True, env=env
    )
    assert r.returncode == 0, r.stderr.decode("utf-8", "replace")
