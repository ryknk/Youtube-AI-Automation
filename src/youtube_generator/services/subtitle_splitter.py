"""読みやすい最大2行の字幕セグメントへローカル分割する。"""

import re
from dataclasses import dataclass
from math import ceil


SUBTITLE_SPLITTER_VERSION = "sentence-boundary-v2"
_SENTENCE_END_PATTERN = re.compile(r".+?[。！？!?]+[」』）】”’]*|.+$")
_CLAUSE_MARKS = "、，,；;：:"


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
        overflow_tolerance = max(2, min(10, self._settings.max_chars_per_line // 2))
        soft_capacity = capacity + overflow_tolerance
        raw_chunks: list[str] = []
        current = ""
        sentences = [match.group(0) for match in _SENTENCE_END_PATTERN.finditer(text)]

        for sentence in sentences:
            if len(sentence) <= capacity:
                if current and len(current) + len(sentence) > capacity:
                    raw_chunks.append(current)
                    current = sentence
                else:
                    current += sentence
                continue

            if current:
                raw_chunks.append(current)
                current = ""
            if len(sentence) <= soft_capacity:
                raw_chunks.append(sentence)
            else:
                raw_chunks.extend(self._split_long(sentence, capacity))

        if current:
            raw_chunks.append(current)
        if (
            len(raw_chunks) > 1
            and len(raw_chunks[-1]) < self._settings.min_chars_per_segment
            and len(raw_chunks[-2]) + len(raw_chunks[-1]) <= soft_capacity
        ):
            raw_chunks[-2] += raw_chunks.pop()
        return [self._line_wrap(chunk) for chunk in raw_chunks]

    def _split_long(self, text: str, capacity: int) -> list[str]:
        result = []
        while len(text) > capacity:
            candidates = [text.rfind(mark, 0, capacity + 1) + 1 for mark in _CLAUSE_MARKS]
            cut = max(candidates)
            if cut <= self._settings.max_chars_per_line // 2:
                cut = capacity
            result.append(text[:cut])
            text = text[cut:]
        if text:
            result.append(text)
        return result

    def _line_wrap(self, text: str) -> str:
        width = max(
            self._settings.max_chars_per_line,
            ceil(len(text) / self._settings.max_lines),
        )
        lines = [text[index:index + width] for index in range(0, len(text), width)]
        return "\n".join(lines)
