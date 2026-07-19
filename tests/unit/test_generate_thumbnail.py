"""サムネイル生成ユースケースのユニットテスト。"""

import tempfile
import unittest
from pathlib import Path

from youtube_generator.app.generate_thumbnail import GenerateThumbnailUseCase


class MockImageProvider:
    def __init__(self) -> None:
        self.prompt = ""

    def generate_image(self, prompt: str, output_file: Path) -> None:
        self.prompt = prompt
        output_file.write_bytes(b"thumbnail")


class GenerateThumbnailUseCaseTests(unittest.TestCase):
    def test_execute_generates_thumbnail_from_script(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            project_dir = Path(temporary_directory)
            (project_dir / "script.txt").write_text("富士山の意外な歴史", encoding="utf-8")
            generator = MockImageProvider()

            output_file = GenerateThumbnailUseCase(
                generator, "意外な事実を短く示す構図"
            ).execute(project_dir)

            self.assertEqual(output_file.name, "thumbnail.png")
            self.assertEqual(output_file.read_bytes(), b"thumbnail")
            self.assertIn("富士山の意外な歴史", generator.prompt)
            self.assertIn("YouTube thumbnail", generator.prompt)
            self.assertIn("意外な事実を短く示す構図", generator.prompt)
