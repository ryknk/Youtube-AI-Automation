"""CachingSceneVisualDescriberのテスト。"""

import tempfile
import unittest
from pathlib import Path

from youtube_generator.infrastructure.cache import CacheManager
from youtube_generator.infrastructure.caching_scene_visual_describer import CachingSceneVisualDescriber


class FakeSceneVisualDescriber:
    def __init__(self, descriptions: tuple[str, ...]) -> None:
        self._descriptions = descriptions
        self.call_count = 0
        self.calls: list[tuple[str, ...]] = []

    def describe_scenes(self, narration_texts: tuple[str, ...]) -> tuple[str, ...]:
        self.call_count += 1
        self.calls.append(narration_texts)
        return self._descriptions


class CachingSceneVisualDescriberTests(unittest.TestCase):
    def test_second_call_with_same_input_uses_cache_and_skips_delegate(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            cache_manager = CacheManager(Path(temporary_directory) / "cache")
            delegate = FakeSceneVisualDescriber(("a calm room", "a busy street"))
            describer = CachingSceneVisualDescriber(delegate, cache_manager, "fingerprint-v1")
            narration_texts = ("静かな部屋", "賑やかな通り")

            first = describer.describe_scenes(narration_texts)
            second = describer.describe_scenes(narration_texts)

            self.assertEqual(first, ("a calm room", "a busy street"))
            self.assertEqual(second, ("a calm room", "a busy street"))
            self.assertEqual(delegate.call_count, 1)

    def test_different_narration_text_bypasses_cache(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            cache_manager = CacheManager(Path(temporary_directory) / "cache")
            delegate = FakeSceneVisualDescriber(("a calm room",))
            describer = CachingSceneVisualDescriber(delegate, cache_manager, "fingerprint-v1")

            describer.describe_scenes(("静かな部屋",))
            describer.describe_scenes(("別のシーン",))

            self.assertEqual(delegate.call_count, 2)

    def test_different_fingerprint_bypasses_cache(self) -> None:
        """場面説明モデル等、fingerprintに含めた設定が変わればキャッシュを再利用しないこと。"""
        with tempfile.TemporaryDirectory() as temporary_directory:
            cache_manager = CacheManager(Path(temporary_directory) / "cache")
            delegate = FakeSceneVisualDescriber(("a calm room",))
            narration_texts = ("静かな部屋",)

            CachingSceneVisualDescriber(delegate, cache_manager, "model-a").describe_scenes(narration_texts)
            CachingSceneVisualDescriber(delegate, cache_manager, "model-b").describe_scenes(narration_texts)

            self.assertEqual(delegate.call_count, 2)

    def test_cached_result_survives_across_instances(self) -> None:
        """--generate-imagesの別プロセス実行間でもキャッシュが再利用されることを、
        新しいCachingSceneVisualDescriberインスタンス（＝別プロセス相当）で確認する。"""
        with tempfile.TemporaryDirectory() as temporary_directory:
            cache_manager = CacheManager(Path(temporary_directory) / "cache")
            narration_texts = ("静かな部屋", "賑やかな通り")
            first_delegate = FakeSceneVisualDescriber(("a calm room", "a busy street"))
            CachingSceneVisualDescriber(first_delegate, cache_manager, "fingerprint-v1").describe_scenes(
                narration_texts,
            )

            second_delegate = FakeSceneVisualDescriber(("should not be used",))
            result = CachingSceneVisualDescriber(second_delegate, cache_manager, "fingerprint-v1").describe_scenes(
                narration_texts,
            )

            self.assertEqual(result, ("a calm room", "a busy street"))
            self.assertEqual(second_delegate.call_count, 0)


if __name__ == "__main__":
    unittest.main()
