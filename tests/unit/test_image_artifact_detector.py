"""image_artifact_detector.has_letterbox_barsのテスト。"""

import unittest

from PIL import Image, ImageDraw

from youtube_generator.services.image_artifact_detector import has_letterbox_bars


class HasLetterboxBarsTests(unittest.TestCase):
    def test_uniform_black_bars_top_and_bottom_are_detected(self) -> None:
        image = Image.new("RGB", (800, 450), color=(120, 130, 140))
        draw = ImageDraw.Draw(image)
        draw.rectangle((0, 0, 800, 15), fill=(0, 0, 0))
        draw.rectangle((0, 434, 800, 450), fill=(0, 0, 0))

        self.assertTrue(has_letterbox_bars(image))

    def test_uniform_black_bar_only_at_top_is_detected(self) -> None:
        image = Image.new("RGB", (800, 450), color=(200, 180, 160))
        draw = ImageDraw.Draw(image)
        draw.rectangle((0, 0, 800, 15), fill=(2, 2, 2))

        self.assertTrue(has_letterbox_bars(image))

    def test_colorful_illustration_without_bars_is_not_detected(self) -> None:
        image = Image.new("RGB", (800, 450), color=(200, 180, 160))
        draw = ImageDraw.Draw(image)
        draw.ellipse((100, 50, 700, 400), fill=(30, 60, 200))

        self.assertFalse(has_letterbox_bars(image))

    def test_naturally_dark_but_non_uniform_edge_is_not_detected(self) -> None:
        """星空のような自然な暗部（輝度は低いがムラがある）は誤検出しないこと。"""
        image = Image.new("RGB", (800, 450), color=(5, 5, 10))
        draw = ImageDraw.Draw(image)
        for x in range(20, 780, 40):
            draw.ellipse((x, 3, x + 4, 7), fill=(255, 255, 255))
            draw.ellipse((x, 443, x + 4, 447), fill=(255, 255, 255))

        self.assertFalse(has_letterbox_bars(image))


if __name__ == "__main__":
    unittest.main()
