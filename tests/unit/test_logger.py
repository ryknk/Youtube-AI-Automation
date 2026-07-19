"""実行ログと JSON 履歴のテスト。"""

import json
import logging
import re
import tempfile
import unittest
from pathlib import Path

from youtube_generator.logger import Logger, configure_logging


class LoggerTest(unittest.TestCase):
    def test_finish_appends_required_history_fields(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            output_dir = Path(temporary_directory) / "output"
            run_logger = Logger("test-run", output_dir)
            video_file = output_dir / "video.mp4"
            title_file = output_dir / "titles.txt"
            output_dir.mkdir(parents=True)
            video_file.touch()
            title_file.write_text("タイトル案\n", encoding="utf-8")
            configure_logging("INFO", output_dir / "logs")

            run_logger.start("テストテーマ")
            run_logger.add_generated_file(video_file)
            run_logger.add_generated_file(title_file)
            run_logger.increment_api_calls()
            run_logger.increment_retries()
            run_logger.finish(success=True)

            history = json.loads((output_dir / "history.json").read_text(encoding="utf-8"))
            logging.shutdown()
            logging.getLogger().handlers.clear()

        self.assertEqual(len(history), 1)
        self.assertEqual(history[0]["theme"], "テストテーマ")
        self.assertEqual(history[0]["video_path"], str(video_file))
        self.assertIsNone(history[0]["thumbnail_path"])
        self.assertEqual(history[0]["title"], "タイトル案")
        self.assertTrue(history[0]["success"])

    def test_configure_logging_creates_windows_safe_timestamp_file(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            log_file = configure_logging("INFO", Path(temporary_directory))
            logging.shutdown()
            logging.getLogger().handlers.clear()

        self.assertRegex(log_file.name, re.compile(r"^\d{4}-\d{2}-\d{2}_\d{2}-\d{2}-\d{2}\.log$"))


if __name__ == "__main__":
    unittest.main()
