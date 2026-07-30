"""シーン内で画像を複数枚表示する際の、切り替えタイミングに関する共通処理。

画像の切り替えは文単位の自然な区切りで行う。subtitles設定（行の折返し・最大文字数など）には
依存しない独立した文分割を行うため、字幕設定の変更でシーン画像がキャッシュ再生成されることはない
（CLAUDE.mdの「字幕設定変更→字幕・動画のみ再生成」という方針を画像生成へ波及させないため）。
"""

import re
from dataclasses import dataclass
from pathlib import Path

from youtube_generator.services.subtitle_alignment import JsonSubtitleAlignmentProvider, SubtitleAlignmentProvider
from youtube_generator.services.subtitle_splitter import SubtitleSegment


_SENTENCE_END_PATTERN = re.compile(r".+?[。！？!?]+[」』）】”’]*|.+$")


@dataclass(frozen=True, slots=True)
class ImageWindow:
    """1枚の画像を表示するシーン内の時間範囲と、対応する台本テキスト。"""

    text: str
    start_time: float
    end_time: float


def build_scene_segments(
    text: str,
    duration: float,
    scene_id: int,
    alignment_file: Path | None = None,
    alignment_provider: SubtitleAlignmentProvider | None = None,
) -> tuple[SubtitleSegment, ...]:
    """シーン本文を文単位で分割し、alignment.jsonがあれば実際の読み上げ時刻へ補正する。

    stable-tsのalignment結果が無い・不正な場合はcharacter_ratio（文字数比率）へフォールバックする
    （GenerateSubtitlesUseCaseと同じ方針。動画生成を停止させないため）。
    """
    normalized = re.sub(r"\s+", "", text)
    if not normalized or duration <= 0:
        return ()
    sentences = [match.group(0) for match in _SENTENCE_END_PATTERN.finditer(normalized)] or [normalized]
    weights = [max(1, len(sentence)) for sentence in sentences]
    total = sum(weights)
    elapsed = 0.0
    segments: list[SubtitleSegment] = []
    for index, (sentence, weight) in enumerate(zip(sentences, weights), 1):
        end = duration if index == len(sentences) else elapsed + duration * weight / total
        segments.append(SubtitleSegment(sentence, elapsed, end, scene_id, index))
        elapsed = end
    result = tuple(segments)

    if alignment_file is not None and alignment_file.is_file():
        provider = alignment_provider or JsonSubtitleAlignmentProvider()
        aligned = provider.align(alignment_file, result, duration)
        if aligned is not None:
            return aligned
    return result


def group_into_image_windows(
    segments: tuple[SubtitleSegment, ...], min_display_seconds: float, max_display_seconds: float,
) -> tuple[ImageWindow, ...]:
    """字幕セグメントを、最小・最大表示秒数の範囲へ収まるようグルーピングする。

    セグメント境界（文の区切り）以外の位置では切り替えないため、常に自然なタイミングになる。
    1セグメント単独でmax_display_secondsを超える場合は、そのセグメントのみで1枚とする
    （文を分割する情報を持たないため。stable-ts失敗時の character_ratio と同様、次善策として許容する）。
    """
    if not segments:
        return ()
    buckets: list[list[SubtitleSegment]] = []
    current: list[SubtitleSegment] = []
    accumulated = 0.0
    for segment in segments:
        span = segment.end_time - segment.start_time
        if current and accumulated + span > max_display_seconds:
            buckets.append(current)
            current = []
            accumulated = 0.0
        current.append(segment)
        accumulated += span
        if accumulated >= max_display_seconds:
            buckets.append(current)
            current = []
            accumulated = 0.0
    if current:
        if buckets and accumulated < min_display_seconds:
            buckets[-1].extend(current)
        else:
            buckets.append(current)
    return tuple(_to_window(bucket) for bucket in buckets)


def _to_window(bucket: list[SubtitleSegment]) -> ImageWindow:
    text = "".join(segment.text.replace("\n", "") for segment in bucket)
    return ImageWindow(text=text, start_time=bucket[0].start_time, end_time=bucket[-1].end_time)


def distribute_duration(
    image_count: int, duration: float, boundary_times: tuple[float, ...],
) -> tuple[float, ...]:
    """durationをimage_count枚へ配分する。自然な区切り（boundary_times）があればそこへスナップし、
    無ければ均等割りへフォールバックする。

    画像生成時に決めた枚数と、レンダリング時に実測した音声長・アライメントは完全には一致しないため
    （台本文字数からの推定と実際の読み上げ速度の差など）、実際に生成された画像の枚数を正として
    実時間側を後から自然な区切りへスナップさせる方式にしている。
    """
    if image_count <= 1 or duration <= 0:
        return (duration,) * max(image_count, 1)
    candidates = sorted(set(time for time in boundary_times if 0 < time < duration))
    if not candidates:
        return tuple(duration / image_count for _ in range(image_count))
    cut_points: list[float] = []
    for index in range(1, image_count):
        target = duration * index / image_count
        candidate = min(candidates, key=lambda time: abs(time - target))
        if cut_points and candidate <= cut_points[-1]:
            candidate = min(duration, cut_points[-1] + 0.1)
        cut_points.append(candidate)
    bounds = [0.0, *cut_points, duration]
    return tuple(bounds[index + 1] - bounds[index] for index in range(image_count))
