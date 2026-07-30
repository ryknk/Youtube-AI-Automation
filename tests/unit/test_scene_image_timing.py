"""シーン内画像の切り替えタイミング計算のユニットテスト。"""

import unittest

from youtube_generator.services.scene_image_timing import (
    build_scene_segments,
    distribute_duration,
    group_into_image_windows,
)
from youtube_generator.services.subtitle_splitter import SubtitleSegment


def _segment(text: str, start: float, end: float) -> SubtitleSegment:
    return SubtitleSegment(text, start, end, scene_id=1, index=1)


class GroupIntoImageWindowsTests(unittest.TestCase):
    def test_groups_segments_by_min_and_max_display_seconds(self) -> None:
        segments = (
            _segment("一文目。", 0.0, 4.0),
            _segment("二文目。", 4.0, 8.0),
            _segment("三文目。", 8.0, 12.0),
            _segment("四文目。", 12.0, 16.0),
        )

        windows = group_into_image_windows(segments, min_display_seconds=5.0, max_display_seconds=10.0)

        self.assertEqual(len(windows), 2)
        self.assertEqual((windows[0].start_time, windows[0].end_time), (0.0, 8.0))
        self.assertEqual((windows[1].start_time, windows[1].end_time), (8.0, 16.0))
        self.assertEqual(windows[0].text, "一文目。二文目。")

    def test_single_segment_exceeding_max_becomes_its_own_window(self) -> None:
        segments = (_segment("とても長い一文。", 0.0, 12.0),)

        windows = group_into_image_windows(segments, min_display_seconds=5.0, max_display_seconds=10.0)

        self.assertEqual(len(windows), 1)
        self.assertEqual(windows[0].end_time - windows[0].start_time, 12.0)

    def test_empty_segments_returns_empty_tuple(self) -> None:
        self.assertEqual(group_into_image_windows((), 5.0, 10.0), ())


class DistributeDurationTests(unittest.TestCase):
    def test_single_image_gets_full_duration(self) -> None:
        self.assertEqual(distribute_duration(1, 9.0, (3.0, 6.0)), (9.0,))

    def test_no_boundary_candidates_falls_back_to_even_split(self) -> None:
        self.assertEqual(distribute_duration(3, 9.0, ()), (3.0, 3.0, 3.0))

    def test_snaps_cut_points_to_nearest_boundary(self) -> None:
        durations = distribute_duration(2, 10.0, (4.5,))
        self.assertEqual(durations, (4.5, 5.5))
        self.assertAlmostEqual(sum(durations), 10.0)

    def test_exact_boundaries_are_used_directly(self) -> None:
        self.assertEqual(distribute_duration(3, 9.0, (3.0, 6.0)), (3.0, 3.0, 3.0))


class BuildSceneSegmentsTests(unittest.TestCase):
    def test_splits_by_sentence_and_assigns_proportional_timing(self) -> None:
        segments = build_scene_segments("最初の文。次の文。", duration=4.0, scene_id=1)

        self.assertEqual(len(segments), 2)
        self.assertEqual(segments[0].start_time, 0.0)
        self.assertEqual(segments[-1].end_time, 4.0)

    def test_empty_text_returns_empty_tuple(self) -> None:
        self.assertEqual(build_scene_segments("", duration=4.0, scene_id=1), ())
