"""字幕タイミング供給元の抽象化。将来Whisper等へ差し替え可能。"""

import json
from pathlib import Path
from typing import Protocol

from youtube_generator.services.subtitle_splitter import SubtitleSegment


class SubtitleAlignmentProvider(Protocol):
    def align(self, alignment_file: Path, segments: tuple[SubtitleSegment, ...], duration: float) -> tuple[SubtitleSegment, ...] | None: ...


class JsonSubtitleAlignmentProvider:
    """外部アライメント結果を sceneNN.alignment.json から読む。

    形式: [{"start_time": 0.0, "end_time": 1.2}, ...]。件数不一致時はNoneを返しフォールバックする。
    """
    def align(self, alignment_file: Path, segments: tuple[SubtitleSegment, ...], duration: float) -> tuple[SubtitleSegment, ...] | None:
        if not alignment_file.is_file():
            return None
        try:
            values = json.loads(alignment_file.read_text(encoding="utf-8"))
            if not isinstance(values, list) or len(values) != len(segments):
                return None
            aligned = tuple(
                SubtitleSegment(segment.text, float(value["start_time"]), float(value["end_time"]), segment.scene_id, segment.index)
                for segment, value in zip(segments, values)
            )
        except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError):
            return None
        if any(item.start_time < 0 or item.end_time <= item.start_time for item in aligned):
            return None
        if aligned[-1].end_time > duration + 0.05:
            return None
        return aligned
