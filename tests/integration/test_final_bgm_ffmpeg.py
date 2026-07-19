"""FFmpegがある環境だけで実行する最終BGMミックス統合テスト。"""

import shutil
import subprocess

import pytest

from youtube_generator.infrastructure.final_bgm_renderer import FinalBGMRenderer, FinalRenderSettings
from youtube_generator.services.bgm_manager import BgmSettings


@pytest.mark.slow
def test_final_mix_renders_short_video_with_continuous_bgm(tmp_path):
    ffmpeg = shutil.which("ffmpeg")
    ffprobe = shutil.which("ffprobe")
    if ffmpeg is None or ffprobe is None:
        pytest.skip("FFmpeg/FFprobeがないため最終ミックス統合テストをスキップします。")
    main = tmp_path / "main.mp4"
    ending = tmp_path / "ending.mp4"
    bgm = tmp_path / "bgm.wav"
    for destination, color in ((main, "blue"), (ending, "green")):
        subprocess.run([
            ffmpeg, "-y", "-f", "lavfi", "-i", f"color=c={color}:s=320x180:r=1:d=1",
            "-f", "lavfi", "-i", "sine=frequency=600:duration=1", "-shortest",
            "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", str(destination),
        ], check=True, capture_output=True)
    subprocess.run([ffmpeg, "-y", "-f", "lavfi", "-i", "sine=frequency=200:duration=1", str(bgm)], check=True, capture_output=True)

    final = FinalBGMRenderer(FinalRenderSettings(320, 180, 1)).render(
        main, ending, tmp_path / "video", BgmSettings(True, bgm, 0.05, True, 0.1, 0.1)
    )

    assert final.is_file() and final.stat().st_size > 0
