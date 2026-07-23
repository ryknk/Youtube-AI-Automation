"""SRT字幕生成ユースケースのユニットテスト。"""

import tempfile
import unittest
from pathlib import Path

from youtube_generator.app.generate_subtitles import GenerateSubtitlesUseCase
from youtube_generator.services.srt_builder import SrtBuilder
from youtube_generator.services.subtitle_splitter import SubtitleSegment, SubtitleSettings, SubtitleSplitter


class FakeDurationProvider:
    def get_duration_seconds(self, audio_file: Path) -> float:
        return {"scene01.mp3": 1.25, "scene02.mp3": 2.5}[audio_file.name]


class TwoSceneDurationProvider:
    def __init__(self, durations: dict[str, float]) -> None:
        self._durations = durations

    def get_duration_seconds(self, audio_file: Path) -> float:
        return self._durations[audio_file.name]


class ShortfallAlignmentProvider:
    """scene02のみ、末尾に無音を残したまま(音声長より短く)アライメントするフェイク。"""

    def align(self, alignment_file: Path, segments, duration: float):
        if alignment_file.name != "scene02.alignment.json":
            return None
        segment = segments[0]
        return (SubtitleSegment(segment.text, 0.0, duration - 0.5, segment.scene_id, segment.index),)


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

    def test_execute_pads_final_cue_when_alignment_ends_before_audio_duration(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            scenes_dir = Path(temporary_directory)
            (scenes_dir / "scene01.mp3").write_bytes(b"audio")
            (scenes_dir / "scene01.txt").write_text("1番目の字幕", encoding="utf-8")
            (scenes_dir / "scene02.mp3").write_bytes(b"audio")
            (scenes_dir / "scene02.txt").write_text("2番目の字幕", encoding="utf-8")

            subtitle_file = GenerateSubtitlesUseCase(
                TwoSceneDurationProvider({"scene01.mp3": 1.0, "scene02.mp3": 2.0}),
                SrtBuilder(),
                splitter=SubtitleSplitter(SubtitleSettings(segmentation_mode="scene")),
                alignment_provider=ShortfallAlignmentProvider(),
                timing_mode="alignment",
            ).execute(scenes_dir)

            # scene02はアライメント上1.5秒(2.0 - 0.5)で終わるが、
            # 音声合計長3.0秒に合わせて末尾を00:00:03,000まで延長する。
            self.assertEqual(
                subtitle_file.read_text(encoding="utf-8"),
                "1\n00:00:00,000 --> 00:00:01,000\n1番目の字幕\n\n"
                "2\n00:00:01,000 --> 00:00:03,000\n2番目の字幕\n",
            )
