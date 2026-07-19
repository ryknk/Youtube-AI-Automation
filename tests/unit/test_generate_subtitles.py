"""SRT字幕生成ユースケースのユニットテスト。"""

import tempfile
import unittest
from pathlib import Path

from youtube_generator.app.generate_subtitles import GenerateSubtitlesUseCase
from youtube_generator.services.srt_builder import SrtBuilder


class FakeDurationProvider:
    def get_duration_seconds(self, audio_file: Path) -> float:
        return {"scene01.mp3": 1.25, "scene02.mp3": 2.5}[audio_file.name]


class GenerateSubtitlesUseCaseTests(unittest.TestCase):
    def test_execute_creates_srt_using_audio_durations_in_scene_order(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            scenes_dir = Path(temporary_directory)
            (scenes_dir / "scene02.mp3").write_bytes(b"audio")
            (scenes_dir / "scene02.txt").write_text("2番目の字幕", encoding="utf-8")
            (scenes_dir / "scene01.mp3").write_bytes(b"audio")
            (scenes_dir / "scene01.txt").write_text("1番目の字幕", encoding="utf-8")

            subtitle_file = GenerateSubtitlesUseCase(
                FakeDurationProvider(),
                SrtBuilder(),
            ).execute(scenes_dir)

            self.assertEqual(
                subtitle_file.read_text(encoding="utf-8"),
                "1\n00:00:00,000 --> 00:00:01,250\n1番目の字幕\n\n"
                "2\n00:00:01,250 --> 00:00:03,750\n2番目の字幕\n",
            )
