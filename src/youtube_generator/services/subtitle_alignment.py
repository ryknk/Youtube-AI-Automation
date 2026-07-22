"""字幕タイミング供給元の抽象化。stable-ts等の外部アライメント結果を読み込む。"""

import json
import re
from pathlib import Path
from typing import Protocol

from youtube_generator.services.subtitle_splitter import SubtitleSegment


class SubtitleAlignmentProvider(Protocol):
    def align(self, alignment_file: Path, segments: tuple[SubtitleSegment, ...], duration: float) -> tuple[SubtitleSegment, ...] | None: ...


class JsonSubtitleAlignmentProvider:
    """sceneNN.alignment.json を読み、SubtitleSplitterのセグメントへ高精度な時刻を割り当てる。

    形式: ``{"provider": "...", "text": "...", "units": [{"text": "...", "start": 0.0, "end": 0.5}, ...]}``。
    units は単語または短いフレーズ単位のタイムスタンプ列を想定する。各セグメントの文字位置を
    units の文字オフセットへ線形補間で対応付けるため、SubtitleSplitterの分割単位と units の
    分割単位が一致していなくてもよい。読み込み・整合性チェックに失敗した場合はNoneを返し、
    呼び出し側はcharacter_ratio方式へフォールバックする。
    """

    def align(
        self, alignment_file: Path, segments: tuple[SubtitleSegment, ...], duration: float,
    ) -> tuple[SubtitleSegment, ...] | None:
        if not segments or not alignment_file.is_file():
            return None
        try:
            payload = json.loads(alignment_file.read_text(encoding="utf-8"))
            checkpoints = self._checkpoints(payload)
        except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError):
            return None
        if not checkpoints:
            return None

        aligned: list[SubtitleSegment] = []
        offset = 0.0
        for segment in segments:
            length = len(self._normalize(segment.text))
            start_time = self._time_at_offset(checkpoints, offset)
            end_time = self._time_at_offset(checkpoints, offset + length)
            aligned.append(SubtitleSegment(segment.text, start_time, end_time, segment.scene_id, segment.index))
            offset += length

        if any(item.start_time < 0 or item.end_time <= item.start_time for item in aligned):
            return None
        if aligned[-1].end_time > duration + 0.05:
            return None
        return tuple(aligned)

    @classmethod
    def _checkpoints(cls, payload: object) -> list[tuple[float, float]]:
        """(累積文字オフセット, 時刻) のチェックポイント列を units から構築する。"""
        if not isinstance(payload, dict):
            return []
        units = payload.get("units")
        if not isinstance(units, list) or not units:
            return []
        checkpoints: list[tuple[float, float]] = []
        cursor = 0.0
        for unit in units:
            if not isinstance(unit, dict):
                return []
            text = cls._normalize(str(unit.get("text", "")))
            start_time = float(unit["start"])
            end_time = float(unit["end"])
            if end_time < start_time:
                return []
            checkpoints.append((cursor, start_time))
            cursor += len(text)
            checkpoints.append((cursor, end_time))
        return checkpoints

    @staticmethod
    def _time_at_offset(checkpoints: list[tuple[float, float]], offset: float) -> float:
        """文字オフセットに対応する時刻を、チェックポイント間の線形補間で求める。"""
        if offset <= checkpoints[0][0]:
            return checkpoints[0][1]
        if offset >= checkpoints[-1][0]:
            return checkpoints[-1][1]
        for (offset_a, time_a), (offset_b, time_b) in zip(checkpoints, checkpoints[1:]):
            if offset_a <= offset <= offset_b:
                if offset_b == offset_a:
                    return time_a
                ratio = (offset - offset_a) / (offset_b - offset_a)
                return time_a + (time_b - time_a) * ratio
        return checkpoints[-1][1]

    @staticmethod
    def _normalize(text: str) -> str:
        return re.sub(r"\s+", "", text)
