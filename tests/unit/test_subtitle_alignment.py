import json

from youtube_generator.services.subtitle_alignment import JsonSubtitleAlignmentProvider
from youtube_generator.services.subtitle_splitter import SubtitleSegment, SubtitleSettings, SubtitleSplitter


def _write_alignment(file, units):
    file.write_text(
        json.dumps({"provider": "stable_ts", "text": "".join(u["text"] for u in units), "units": units}),
        encoding="utf-8",
    )


def test_units_are_mapped_to_segments_by_character_offset(tmp_path):
    file = tmp_path / "scene01.alignment.json"
    _write_alignment(file, [
        {"text": "A", "start": 0.0, "end": 1.0},
        {"text": "B", "start": 1.0, "end": 1.5},
        {"text": "C", "start": 1.5, "end": 3.0},
        {"text": "D", "start": 3.0, "end": 4.0},
    ])
    segments = (SubtitleSegment("AB", 0, 0, 1, 1), SubtitleSegment("CD", 0, 0, 1, 2))

    aligned = JsonSubtitleAlignmentProvider().align(file, segments, duration=4.0)

    assert aligned is not None
    assert (aligned[0].start_time, aligned[0].end_time) == (0.0, 1.5)
    assert (aligned[1].start_time, aligned[1].end_time) == (1.5, 4.0)


def test_missing_alignment_file_falls_back(tmp_path):
    segment = SubtitleSegment("字幕", 0, 2, 1, 1)
    assert JsonSubtitleAlignmentProvider().align(tmp_path / "missing.json", (segment,), 2) is None


def test_malformed_json_falls_back(tmp_path):
    file = tmp_path / "scene01.alignment.json"
    file.write_text("not-json", encoding="utf-8")
    segment = SubtitleSegment("字幕", 0, 2, 1, 1)
    assert JsonSubtitleAlignmentProvider().align(file, (segment,), 2) is None


def test_missing_units_key_falls_back(tmp_path):
    file = tmp_path / "scene01.alignment.json"
    file.write_text(json.dumps({"provider": "stable_ts", "text": "字幕"}), encoding="utf-8")
    segment = SubtitleSegment("字幕", 0, 2, 1, 1)
    assert JsonSubtitleAlignmentProvider().align(file, (segment,), 2) is None


def test_old_top_level_array_format_is_no_longer_accepted(tmp_path):
    """旧: 未使用だったトップレベル配列形式は、新スキーマ導入により受け付けない。"""
    file = tmp_path / "scene01.alignment.json"
    file.write_text(json.dumps([{"start_time": 0, "end_time": 1}]), encoding="utf-8")
    segment = SubtitleSegment("字幕", 0, 2, 1, 1)
    assert JsonSubtitleAlignmentProvider().align(file, (segment,), 2) is None


def test_end_time_exceeding_duration_falls_back(tmp_path):
    file = tmp_path / "scene01.alignment.json"
    _write_alignment(file, [{"text": "字幕", "start": 0.0, "end": 4.0}])
    segment = SubtitleSegment("字幕", 0, 0, 1, 1)

    assert JsonSubtitleAlignmentProvider().align(file, (segment,), duration=1.0) is None


def test_aligns_segments_produced_by_subtitle_splitter(tmp_path):
    """SubtitleSplitterが生成したセグメントへ、stable-tsの単語タイムスタンプを反映できる。"""
    splitter = SubtitleSplitter(SubtitleSettings(segmentation_mode="scene", max_lines=1, max_chars_per_line=10))
    segments = splitter.split("おはよう世界", duration=2.0, scene_id=1)
    assert len(segments) == 1

    file = tmp_path / "scene01.alignment.json"
    _write_alignment(file, [
        {"text": "おはよう", "start": 0.1, "end": 1.0},
        {"text": "世界", "start": 1.0, "end": 1.9},
    ])

    aligned = JsonSubtitleAlignmentProvider().align(file, segments, duration=2.0)

    assert aligned is not None
    assert aligned[0].start_time == 0.1
    assert aligned[0].end_time == 1.9
