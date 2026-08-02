"""--edit-imagesの再試行時に既編集画像をスキップするマーカー機構のテスト。"""

import tempfile
import unittest
from pathlib import Path

from youtube_generator.cli.main import _is_already_edited, _mark_edited


class EditImageResumeMarkerTests(unittest.TestCase):
    def test_not_edited_when_no_marker_exists(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            image_file = Path(temporary_directory) / "scene01_01.png"
            image_file.write_bytes(b"raw")

            self.assertFalse(_is_already_edited(image_file, "key-a"))

    def test_marked_edited_is_detected_with_same_key(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            image_file = Path(temporary_directory) / "scene01_01.png"
            image_file.write_bytes(b"raw")

            _mark_edited(image_file, "key-a")

            self.assertTrue(_is_already_edited(image_file, "key-a"))

    def test_marked_edited_is_invalidated_when_settings_change(self) -> None:
        """編集設定が変わった場合は別のresume_keyになるため、再編集対象として扱う。"""
        with tempfile.TemporaryDirectory() as temporary_directory:
            image_file = Path(temporary_directory) / "scene01_01.png"
            image_file.write_bytes(b"raw")

            _mark_edited(image_file, "key-a")

            self.assertFalse(_is_already_edited(image_file, "key-b"))

    def test_marker_file_does_not_collide_with_scene_png_glob(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            directory = Path(temporary_directory)
            image_file = directory / "scene01_01.png"
            image_file.write_bytes(b"raw")

            _mark_edited(image_file, "key-a")

            self.assertEqual([path.name for path in directory.glob("scene*.png")], ["scene01_01.png"])


if __name__ == "__main__":
    unittest.main()
