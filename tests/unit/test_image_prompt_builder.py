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

    def test_build_keeps_quote_markers_by_default(self) -> None:
        """FLUX以外（provider_name未指定）では引用符をそのまま残す。"""
        builder = ImagePromptBuilder("style")

        prompt = builder.build("「静かな部屋」")

        self.assertIn("「静かな部屋」", prompt)

    def test_build_keeps_quote_markers_for_non_flux_provider(self) -> None:
        builder = ImagePromptBuilder("style", "qwen_image_nunchaku_local")

        prompt = builder.build("「静かな部屋」")

        self.assertIn("「静かな部屋」", prompt)

    def test_build_strips_quote_markers_for_bfl_provider(self) -> None:
        builder = ImagePromptBuilder("style", "bfl")

        prompt = builder.build("「静かな部屋」")

        self.assertNotIn("「", prompt)
        self.assertNotIn("」", prompt)
        self.assertIn("静かな部屋", prompt)

    def test_build_strips_quote_markers_for_flux_schnell_local_provider(self) -> None:
        builder = ImagePromptBuilder("style", "flux_schnell_local")

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
