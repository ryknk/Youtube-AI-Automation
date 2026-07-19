"""読みやすい最大2行の字幕セグメントへローカル分割する。"""

import re
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class SubtitleSegment:
    text: str
    start_time: float
    end_time: float
    scene_id: int
    index: int


@dataclass(frozen=True, slots=True)
class SubtitleSettings:
    segmentation_mode: str = "semantic"
    max_lines: int = 2
    max_chars_per_line: int = 20
    min_chars_per_segment: int = 6


class SubtitleSplitter:
    def __init__(self, settings: SubtitleSettings) -> None:
        if settings.max_lines < 1 or settings.max_chars_per_line < 1:
            raise ValueError("字幕の行数・文字数設定が不正です。")
        self._settings = settings

    def split(self, text: str, duration: float, scene_id: int) -> tuple[SubtitleSegment, ...]:
        normalized = re.sub(r"\s+", "", text)
        if not normalized or duration <= 0:
            return ()
        if self._settings.segmentation_mode == "scene":
            chunks = (self._line_wrap(normalized),)
        elif self._settings.segmentation_mode == "semantic":
            chunks = tuple(self._semantic_chunks(normalized))
        else:
            raise ValueError("subtitle.segmentation_mode は scene または semantic を指定してください。")
        weights = [max(1, len(chunk.replace("\n", ""))) for chunk in chunks]
        total = sum(weights)
        elapsed = 0.0
        segments = []
        for index, (chunk, weight) in enumerate(zip(chunks, weights), 1):
            end = duration if index == len(chunks) else elapsed + duration * weight / total
            segments.append(SubtitleSegment(chunk, elapsed, end, scene_id, index))
            elapsed = end
        return tuple(segments)

    def _semantic_chunks(self, text: str) -> list[str]:
        capacity = self._settings.max_lines * self._settings.max_chars_per_line
        tokens = [item for item in re.split(r"(?<=[。！？!?、】【、])", text) if item]
        chunks: list[str] = []
        current = ""
        for token in tokens:
            for part in self._split_long(token, capacity):
                if current and len(current) + len(part) > capacity:
                    chunks.append(self._line_wrap(current))
                    current = part
                else:
                    current += part
        if current:
            chunks.append(self._line_wrap(current))
        if len(chunks) > 1 and len(chunks[-1].replace("\n", "")) < self._settings.min_chars_per_segment:
            chunks[-2] = self._line_wrap(chunks[-2].replace("\n", "") + chunks[-1].replace("\n", ""))
            chunks.pop()
        return chunks

    def _split_long(self, text: str, capacity: int) -> list[str]:
        result = []
        while len(text) > capacity:
            candidates = [text.rfind(mark, 0, capacity + 1) + 1 for mark in "、。！？"]
            cut = max(candidates)
            if cut <= self._settings.max_chars_per_line // 2:
                cut = capacity
            result.append(text[:cut])
            text = text[cut:]
        if text:
            result.append(text)
        return result

    def _line_wrap(self, text: str) -> str:
        width = self._settings.max_chars_per_line
        lines = [text[index:index + width] for index in range(0, len(text), width)]
        return "\n".join(lines[:self._settings.max_lines])
