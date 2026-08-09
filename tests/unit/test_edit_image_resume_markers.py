"""--edit-imagesの再試行時に既編集画像をスキップするマーカー機構のテスト。"""

import logging
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock

from youtube_generator.cli.main import _edit_pending_files, _is_already_edited, _mark_edited, create_parser


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


class EditPendingFilesTests(unittest.TestCase):
    def _logger(self) -> logging.Logger:
        return logging.getLogger("test-edit-pending-files")

    def test_edits_all_files_and_marks_them(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            first = Path(temporary_directory) / "scene01_01.png"
            second = Path(temporary_directory) / "scene02_01.png"
            first.write_bytes(b"a")
            second.write_bytes(b"b")
            editor = MagicMock()

            result = _edit_pending_files(editor, (first, second), "key-a", False, self._logger())

            self.assertEqual(editor.edit.call_args_list, [((first,),), ((second,),)])
            self.assertEqual(result, (first, second))
            self.assertTrue(_is_already_edited(first, "key-a"))
            self.assertTrue(_is_already_edited(second, "key-a"))

    def test_skips_already_edited_file_with_same_key(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            image_file = Path(temporary_directory) / "scene01_01.png"
            image_file.write_bytes(b"a")
            _mark_edited(image_file, "key-a")
            editor = MagicMock()

            _edit_pending_files(editor, (image_file,), "key-a", False, self._logger())

            editor.edit.assert_not_called()

    def test_force_reedits_even_when_already_marked(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            image_file = Path(temporary_directory) / "scene01_01.png"
            image_file.write_bytes(b"a")
            _mark_edited(image_file, "key-a")
            editor = MagicMock()

            _edit_pending_files(editor, (image_file,), "key-a", True, self._logger())

            editor.edit.assert_called_once_with(image_file)


class EditImagesArgumentParsingTests(unittest.TestCase):
    def test_edit_images_accepts_a_single_folder(self) -> None:
        args = create_parser().parse_args(["--edit-images", "output/work", "--template", "science"])

        self.assertEqual(args.edit_images, [Path("output/work")])

    def test_edit_images_accepts_multiple_explicit_files(self) -> None:
        args = create_parser().parse_args([
            "--edit-images", "output/work/scene01_01.png", "output/work/scene02_01.png",
            "--template", "science",
        ])

        self.assertEqual(args.edit_images, [Path("output/work/scene01_01.png"), Path("output/work/scene02_01.png")])


if __name__ == "__main__":
    unittest.main()
