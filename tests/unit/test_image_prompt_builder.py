"""ImagePromptBuilderのテスト。"""

import unittest

from youtube_generator.services.image_prompt_builder import ImagePromptBuilder


class ImagePromptBuilderTests(unittest.TestCase):
    def test_build_includes_style_and_narration(self) -> None:
        builder = ImagePromptBuilder("clean 2D digital illustration, non-photorealistic")

        prompt = builder.build("穏やかな朝の風景")

        self.assertIn("clean 2D digital illustration, non-photorealistic", prompt)
        self.assertIn("穏やかな朝の風景", prompt)

    def test_build_passes_through_arbitrary_style_text_unmodified(self) -> None:
        """テンプレート固有の指示（レターボックス対策文言等）はstyleとしてそのまま反映されること。
        image_prompt_builder.pyは共通部品のため、ジャンル固有の対策文言は
        テンプレート側（image_prompt.txt）で持たせ、ここでは素通しするだけにする。"""
        style_with_mitigation = (
            "clean 2D digital illustration, presented as a standalone poster-style illustration, "
            "not a video/TV/film screenshot or frame"
        )
        builder = ImagePromptBuilder(style_with_mitigation)

        prompt = builder.build("シーン本文")

        self.assertIn(style_with_mitigation, prompt)

    def test_build_strips_quote_markers_from_narration(self) -> None:
        builder = ImagePromptBuilder("style")

        prompt = builder.build("「静かな部屋」")

        self.assertNotIn("「", prompt)
        self.assertNotIn("」", prompt)
        self.assertIn("静かな部屋", prompt)

    def test_build_raises_for_empty_scene_text(self) -> None:
        builder = ImagePromptBuilder("style")

        with self.assertRaises(ValueError):
            builder.build("   ")


if __name__ == "__main__":
    unittest.main()
