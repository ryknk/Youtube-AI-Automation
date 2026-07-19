import json

from youtube_generator.services.subtitle_alignment import JsonSubtitleAlignmentProvider
from youtube_generator.services.subtitle_splitter import SubtitleSegment


def test_json_alignment_is_used_when_segment_count_matches(tmp_path):
    file = tmp_path / "scene01.alignment.json"
    file.write_text(json.dumps([{"start_time": 0, "end_time": 1}, {"start_time": 1, "end_time": 3}]), encoding="utf-8")
    segments = (SubtitleSegment("前半", 0, 1.5, 1, 1), SubtitleSegment("後半", 1.5, 3, 1, 2))
    aligned = JsonSubtitleAlignmentProvider().align(file, segments, 3)
    assert aligned is not None and aligned[1].start_time == 1


def test_invalid_alignment_falls_back(tmp_path):
    segment = SubtitleSegment("字幕", 0, 2, 1, 1)
    assert JsonSubtitleAlignmentProvider().align(tmp_path / "missing.json", (segment,), 2) is None
