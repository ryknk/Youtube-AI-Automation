"""プロジェクト品質チェックのテスト。"""

import json
import tempfile
import unittest
from pathlib import Path

from youtube_generator.services.image_prompt_builder import ImagePromptBuilder
from youtube_generator.services.quality_checker import QualityChecker, QualityRules


class FakeDurationProvider:
    def get_duration_seconds(self, audio_file: Path) -> float:
        return 2.0


class QualityCheckerTests(unittest.TestCase):
    def test_checks_project_and_saves_json_and_html_reports(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            project_dir = Path(temporary_directory)
            project_dir.joinpath("script.txt").write_text(("これは安全な台本です。" * 10) + "\n" + ("これは別の台本です。" * 10), encoding="utf-8")
            project_dir.joinpath("scene01.txt").write_text("十分な長さを持つシーンの本文です。", encoding="utf-8")
            project_dir.joinpath("scene01.mp3").write_bytes(b"mp3")
            project_dir.joinpath("subtitles.srt").write_text(
                "1\n00:00:00,000 --> 00:00:02,000\n字幕\n", encoding="utf-8"
            )
            project_dir.joinpath("titles.txt").write_text("1. 適切なタイトル\n", encoding="utf-8")
            project_dir.joinpath("description.txt").write_text("説明文です。" * 30, encoding="utf-8")
            checker = QualityChecker(
                QualityRules(10, 1000, 6.0, (), 2), FakeDurationProvider()  # type: ignore[arg-type]
            )

            report = checker.check_project(project_dir, ImagePromptBuilder("realistic"))
            json_file, html_file = checker.save_report(report, project_dir)
            payload = json.loads(json_file.read_text(encoding="utf-8"))

            self.assertFalse(report.has_errors)
            self.assertTrue(html_file.is_file())
            self.assertIn("checks", payload)
            self.assertEqual(len(payload["checks"]), 13)

    def test_ng_word_creates_error(self) -> None:
        checker = QualityChecker(QualityRules(1, 1000, 6.0, ("禁止語",), 2))
        report = checker.check_project(Path("."), ImagePromptBuilder("realistic"))
        # script.txtが存在しないため、文字数チェックがERRORになる。
        self.assertTrue(report.has_errors)


if __name__ == "__main__":
    unittest.main()
