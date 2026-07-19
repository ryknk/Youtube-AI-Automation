"""FFmpeg依存の統合テスト用環境確認。"""

import shutil
import subprocess

import pytest


@pytest.mark.integration
@pytest.mark.slow
def test_ffmpeg_is_available_for_optional_rendering_tests():
    executable = shutil.which("ffmpeg")
    if executable is None:
        pytest.skip("FFmpegがないため、実レンダリング統合テストをスキップします。")
    completed = subprocess.run([executable, "-version"], capture_output=True, text=True, check=False)
    assert completed.returncode == 0, completed.stderr
