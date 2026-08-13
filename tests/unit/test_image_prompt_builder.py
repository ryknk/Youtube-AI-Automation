"""ImagePromptBuilderのテスト。"""

import unittest
from unittest.mock import patch

from youtube_generator.services.image_prompt_builder import (
    ImagePromptBuilder,
    _FEMALE_HAIRSTYLES,
    _MALE_HAIRSTYLES,
)


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

    def test_build_assigns_sampled_female_and_male_hairstyles(self) -> None:
        """女性用・男性用プールからそれぞれサンプリングした髪型が、指示文へ順序通り
        埋め込まれること（random.sampleをモックして決定的に検証する）。"""
        builder = ImagePromptBuilder("style")

        with patch(
            "youtube_generator.services.image_prompt_builder.random.sample",
            side_effect=[
                [_FEMALE_HAIRSTYLES[0], _FEMALE_HAIRSTYLES[1], _FEMALE_HAIRSTYLES[2]],
                [_MALE_HAIRSTYLES[3], _MALE_HAIRSTYLES[4], _MALE_HAIRSTYLES[5]],
            ],
        ):
            prompt = builder.build("シーン本文")

        expected_female = f"{_FEMALE_HAIRSTYLES[0]}, then {_FEMALE_HAIRSTYLES[1]}, then {_FEMALE_HAIRSTYLES[2]}"
        expected_male = f"{_MALE_HAIRSTYLES[3]}, then {_MALE_HAIRSTYLES[4]}, then {_MALE_HAIRSTYLES[5]}"
        self.assertIn(expected_female, prompt)
        self.assertIn(expected_male, prompt)

    def test_build_includes_fallback_instruction_for_additional_same_gender_people(self) -> None:
        """明示リストの3人を超える同性人物向けのフォールバック指示が含まれること。"""
        builder = ImagePromptBuilder("style")

        prompt = builder.build("シーン本文")

        self.assertIn(
            "For any additional people of the same gender beyond this list, keep varying hair "
            "length and style so none of them duplicate each other or the people already listed.",
            prompt,
        )

    def test_build_varies_hairstyle_selection_across_calls(self) -> None:
        """build()を複数回呼ぶと（実際のrandomを使って）異なる組み合わせが選ばれうること。
        同一プールから毎回同じ組み合わせしか選ばれない実装ミス（例: 固定シード）を検出する。"""
        builder = ImagePromptBuilder("style")

        prompts = {builder.build("シーン本文") for _ in range(30)}

        self.assertGreater(len(prompts), 1)


if __name__ == "__main__":
    unittest.main()
