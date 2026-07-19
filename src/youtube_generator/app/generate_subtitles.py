"""シーン音声群からSRT字幕を生成するユースケース。"""

import re
from pathlib import Path

from youtube_generator.domain.audio_duration_provider import AudioDurationProvider
from youtube_generator.services.srt_builder import SrtBuilder, SubtitleCue
from youtube_generator.services.subtitle_splitter import SubtitleSplitter
from youtube_generator.services.subtitle_alignment import JsonSubtitleAlignmentProvider, SubtitleAlignmentProvider


SCENE_AUDIO_PATTERN = re.compile(r"scene(\d{2})\.mp3$", re.IGNORECASE)


class GenerateSubtitlesUseCase:
    """sceneNN.mp3の音声長を使い、対応する台本からSRTを作成する。"""

    def __init__(self, duration_provider: AudioDurationProvider, srt_builder: SrtBuilder, splitter: SubtitleSplitter | None = None, alignment_provider: SubtitleAlignmentProvider | None = None, timing_mode: str = "character_ratio") -> None:
        self._duration_provider = duration_provider
        self._srt_builder = srt_builder
        self._splitter = splitter
        self._alignment_provider = alignment_provider or JsonSubtitleAlignmentProvider()
        self._timing_mode = timing_mode

    def execute(self, scenes_dir: Path) -> Path:
        """すべてのシーン音声を時間順に並べたsubtitles.srtを保存する。"""
        audio_files = self._find_audio_files(scenes_dir)
        if not audio_files:
            raise FileNotFoundError(f"sceneNN.mp3 が見つかりません: {scenes_dir}")

        cues: list[SubtitleCue] = []
        for scene_id, audio_file in enumerate(audio_files, 1):
            scene_file = audio_file.with_suffix(".txt")
            try:
                text = scene_file.read_text(encoding="utf-8-sig")
            except OSError as error:
                raise FileNotFoundError(f"対応するシーンテキストが見つかりません: {scene_file}") from error
            duration = self._duration_provider.get_duration_seconds(audio_file)
            if self._splitter is None:
                cues.append(SubtitleCue(text=text, duration_seconds=duration))
            else:
                segments = self._splitter.split(text, duration, scene_id)
                if self._timing_mode == "alignment":
                    aligned = self._alignment_provider.align(audio_file.with_suffix(".alignment.json"), segments, duration)
                    if aligned is not None:
                        segments = aligned
                cues.extend(SubtitleCue(segment.text, segment.end_time - segment.start_time) for segment in segments)

        subtitle_file = scenes_dir / "subtitles.srt"
        subtitle_file.write_text(self._srt_builder.build(tuple(cues)), encoding="utf-8")
        return subtitle_file

    @staticmethod
    def _find_audio_files(scenes_dir: Path) -> tuple[Path, ...]:
        if not scenes_dir.is_dir():
            raise FileNotFoundError(f"シーンフォルダが見つかりません: {scenes_dir}")
        numbered_files = []
        for path in scenes_dir.glob("scene*.mp3"):
            match = SCENE_AUDIO_PATTERN.fullmatch(path.name)
            if match:
                numbered_files.append((int(match.group(1)), path))
        return tuple(path for _, path in sorted(numbered_files))
