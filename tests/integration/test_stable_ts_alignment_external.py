"""実際のstable-tsを利用するアライメントの疎通テスト。

RUN_EXTERNAL_TESTS=true を指定した場合のみ実行される（tests/conftest.py参照）。
stable-tsは音声認識モデルのダウンロードが発生するため、通常のpytest実行では呼び出さない。
音声はリポジトリへバイナリを同梱せず、テスト実行時にその場で合成する。
"""

import json
import struct
import wave
from pathlib import Path

import pytest

from youtube_generator.plugins.alignment.stable_ts_alignment import StableTSAlignmentProvider


def _write_silent_wav(path: Path, duration_seconds: float = 1.0, framerate: int = 16000) -> None:
    frame_count = int(duration_seconds * framerate)
    with wave.open(str(path), "w") as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(framerate)
        wav_file.writeframes(struct.pack(f"<{frame_count}h", *([0] * frame_count)))


@pytest.mark.external
def test_stable_ts_aligns_short_narration_against_real_engine(tmp_path: Path) -> None:
    pytest.importorskip("stable_whisper", reason="stable-tsが未インストールです。")

    audio_file = tmp_path / "scene01.mp3"
    _write_silent_wav(audio_file)
    output_file = tmp_path / "scene01.alignment.json"
    provider = StableTSAlignmentProvider(model="base", language="ja")

    provider.align(audio_file, "テストナレーション", output_file)

    payload = json.loads(output_file.read_text(encoding="utf-8"))
    assert payload["provider"] == "stable_ts"
    assert isinstance(payload["units"], list)
