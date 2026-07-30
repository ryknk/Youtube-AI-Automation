"""プロジェクト品質チェックのテスト。"""

import json
import tempfile
import unittest
from pathlib import Path

from PIL import Image

from youtube_generator.services.image_prompt_builder import ImagePromptBuilder
from youtube_generator.services.quality_checker import QualityChecker, QualityRules


class FakeDurationProvider:
    def get_duration_seconds(self, audio_file: Path) -> float:
        return 2.0


def _write_valid_scene_project(project_dir: Path, image_size: tuple[int, int] = (1920, 1080)) -> None:
    project_dir.joinpath("script.txt").write_text(("これは安全な台本です。" * 10) + "\n" + ("これは別の台本です。" * 10), encoding="utf-8")
    project_dir.joinpath("scene01.txt").write_text("十分な長さを持つシーンの本文です。", encoding="utf-8")
    project_dir.joinpath("scene01.mp3").write_bytes(b"mp3")
    Image.new("RGB", image_size, color="red").save(project_dir / "scene01_01.png")
    project_dir.joinpath("subtitles.srt").write_text(
        "1\n00:00:00,000 --> 00:00:02,000\n字幕\n", encoding="utf-8"
    )
    project_dir.joinpath("titles.txt").write_text("1. 適切なタイトル\n", encoding="utf-8")
    project_dir.joinpath("description.txt").write_text("説明文です。" * 30, encoding="utf-8")


class QualityCheckerTests(unittest.TestCase):
    def test_checks_project_and_saves_json_and_html_reports(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            project_dir = Path(temporary_directory)
            _write_valid_scene_project(project_dir)
            checker = QualityChecker(
                QualityRules(10, 1000, 6.0, (), 2), FakeDurationProvider()  # type: ignore[arg-type]
            )

            report = checker.check_project(
                project_dir, ImagePromptBuilder("realistic"), expected_scene_size=(1920, 1080),
            )
            json_file, html_file = checker.save_report(report, project_dir)
            payload = json.loads(json_file.read_text(encoding="utf-8"))

            self.assertFalse(report.has_errors)
            self.assertTrue(html_file.is_file())
            self.assertIn("checks", payload)
            self.assertEqual(len(payload["checks"]), 14)

    def test_ng_word_creates_error(self) -> None:
        checker = QualityChecker(QualityRules(1, 1000, 6.0, ("禁止語",), 2))
        report = checker.check_project(Path("."), ImagePromptBuilder("realistic"))
        # script.txtが存在しないため、文字数チェックがERRORになる。
        self.assertTrue(report.has_errors)

    def test_missing_scene_image_is_reported_as_error(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            project_dir = Path(temporary_directory)
            _write_valid_scene_project(project_dir)
            (project_dir / "scene01_01.png").unlink()
            checker = QualityChecker(QualityRules(10, 1000, 6.0, (), 2), FakeDurationProvider())  # type: ignore[arg-type]

            report = checker.check_project(project_dir, ImagePromptBuilder("realistic"), expected_scene_size=(1920, 1080))

            image_check = next(check for check in report.checks if check.check_name == "シーン画像")
            self.assertEqual(image_check.severity.value, "error")
            self.assertIn("ファイルが見つかりません", image_check.message)
            self.assertTrue(report.has_errors)

    def test_zero_byte_scene_image_is_reported_as_error(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            project_dir = Path(temporary_directory)
            _write_valid_scene_project(project_dir)
            (project_dir / "scene01_01.png").write_bytes(b"")
            checker = QualityChecker(QualityRules(10, 1000, 6.0, (), 2), FakeDurationProvider())  # type: ignore[arg-type]

            report = checker.check_project(project_dir, ImagePromptBuilder("realistic"), expected_scene_size=(1920, 1080))

            image_check = next(check for check in report.checks if check.check_name == "シーン画像")
            self.assertEqual(image_check.severity.value, "error")
            self.assertIn("ファイルサイズが0です", image_check.message)

    def test_corrupted_scene_image_is_reported_as_error(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            project_dir = Path(temporary_directory)
            _write_valid_scene_project(project_dir)
            (project_dir / "scene01_01.png").write_bytes(b"not a valid png")
            checker = QualityChecker(QualityRules(10, 1000, 6.0, (), 2), FakeDurationProvider())  # type: ignore[arg-type]

            report = checker.check_project(project_dir, ImagePromptBuilder("realistic"), expected_scene_size=(1920, 1080))

            image_check = next(check for check in report.checks if check.check_name == "シーン画像")
            self.assertEqual(image_check.severity.value, "error")
            self.assertIn("画像として読み込めません", image_check.message)

    def test_wrong_resolution_scene_image_is_reported_as_error(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            project_dir = Path(temporary_directory)
            _write_valid_scene_project(project_dir, image_size=(640, 480))
            checker = QualityChecker(QualityRules(10, 1000, 6.0, (), 2), FakeDurationProvider())  # type: ignore[arg-type]

            report = checker.check_project(project_dir, ImagePromptBuilder("realistic"), expected_scene_size=(1920, 1080))

            image_check = next(check for check in report.checks if check.check_name == "シーン画像")
            self.assertEqual(image_check.severity.value, "error")
            self.assertIn("解像度が不正です", image_check.message)

    def test_wrong_aspect_ratio_scene_image_is_reported_as_error(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            project_dir = Path(temporary_directory)
            # 解像度は期待値と異なるが、面積の比較だけでは検出できないアスペクト比崩れを再現する。
            _write_valid_scene_project(project_dir, image_size=(1080, 1920))
            checker = QualityChecker(QualityRules(10, 1000, 6.0, (), 2), FakeDurationProvider())  # type: ignore[arg-type]

            report = checker.check_project(project_dir, ImagePromptBuilder("realistic"), expected_scene_size=(1920, 1080))

            image_check = next(check for check in report.checks if check.check_name == "シーン画像")
            self.assertEqual(image_check.severity.value, "error")

    def test_expected_size_none_skips_resolution_and_aspect_checks(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            project_dir = Path(temporary_directory)
            _write_valid_scene_project(project_dir, image_size=(640, 480))
            checker = QualityChecker(QualityRules(10, 1000, 6.0, (), 2), FakeDurationProvider())  # type: ignore[arg-type]

            report = checker.check_project(project_dir, ImagePromptBuilder("realistic"))

            image_check = next(check for check in report.checks if check.check_name == "シーン画像")
            self.assertEqual(image_check.severity.value, "pass")


if __name__ == "__main__":
    unittest.main()
