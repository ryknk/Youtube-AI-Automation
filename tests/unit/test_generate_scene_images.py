"""シーン画像生成ユースケースのユニットテスト。"""

import base64
import tempfile
import unittest
from pathlib import Path

from youtube_generator.app.generate_scene_images import GenerateSceneImagesUseCase
from youtube_generator.infrastructure.openai_image_generator import OpenAIImageGenerator
from youtube_generator.services.image_prompt_builder import ImagePromptBuilder
from youtube_generator.services.retry import RetryPolicy


class MockImageProvider:
    def __init__(self) -> None:
        self.prompts: list[str] = []

    def generate_image(self, prompt: str, output_file: Path) -> None:
        self.prompts.append(prompt)
        output_file.write_bytes(b"fake-png")


class FakeImageData:
    b64_json = base64.b64encode(b"fake-png").decode("ascii")


class FakeImageResult:
    data = [FakeImageData()]


class FakeImagesResource:
    def __init__(self) -> None:
        self.request: dict[str, object] | None = None

    def generate(self, **kwargs: object) -> FakeImageResult:
        self.request = kwargs
        return FakeImageResult()


class FakeOpenAIClient:
    def __init__(self) -> None:
        self.images = FakeImagesResource()


class GenerateSceneImagesUseCaseTests(unittest.TestCase):
    def test_execute_generates_png_for_all_scene_files_in_order(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            scenes_dir = Path(temporary_directory)
            (scenes_dir / "scene02.txt").write_text("2番目の場面", encoding="utf-8")
            (scenes_dir / "scene01.txt").write_text("1番目の場面", encoding="utf-8")
            generator = MockImageProvider()
            use_case = GenerateSceneImagesUseCase(
                ImagePromptBuilder("clean 2D digital illustration, non-photorealistic"), generator,
                min_display_seconds=5.0, max_display_seconds=10.0, characters_per_second=6.0,
            )

            image_files = use_case.execute(scenes_dir)

            self.assertEqual([file.name for file in image_files], ["scene01_01.png", "scene02_01.png"])
            self.assertEqual(len(generator.prompts), 2)
            self.assertIn("1番目の場面", generator.prompts[0])
            self.assertIn("clean 2D digital illustration", generator.prompts[0])
            self.assertNotIn("realistic photography", generator.prompts[0])
            self.assertIn("no text", generator.prompts[0])

    def test_long_scene_generates_multiple_images_split_by_sentence(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            scenes_dir = Path(temporary_directory)
            # characters_per_second=6.0のため、60文字は推定10秒。文単位に区切りつつ
            # min=5/max=10秒の範囲へグルーピングされ、複数枚に分割されることを確認する。
            long_text = "あ" * 30 + "。" + "い" * 30 + "。"
            (scenes_dir / "scene01.txt").write_text(long_text, encoding="utf-8")
            generator = MockImageProvider()
            use_case = GenerateSceneImagesUseCase(
                ImagePromptBuilder("clean 2D digital illustration, non-photorealistic"), generator,
                min_display_seconds=3.0, max_display_seconds=5.0, characters_per_second=6.0,
            )

            image_files = use_case.execute(scenes_dir)

            self.assertEqual([file.name for file in image_files], ["scene01_01.png", "scene01_02.png"])
            self.assertEqual(len(generator.prompts), 2)

    def test_invalid_display_seconds_raises_value_error(self) -> None:
        with self.assertRaises(ValueError):
            GenerateSceneImagesUseCase(
                ImagePromptBuilder("style"), MockImageProvider(),
                min_display_seconds=10.0, max_display_seconds=5.0, characters_per_second=6.0,
            )

    def test_openai_image_generator_requests_high_quality_landscape_png(self) -> None:
        client = FakeOpenAIClient()
        with tempfile.TemporaryDirectory() as temporary_directory:
            output_file = Path(temporary_directory) / "scene01.png"
            generator = OpenAIImageGenerator(
                api_key="test-key",
                model="gpt-image-2",
                size="2048x1152",
                quality="high",
                retry_policy=RetryPolicy(max_attempts=1),
                client=client,  # type: ignore[arg-type]
            )

            generator.generate("realistic scene", output_file)

            self.assertEqual(output_file.read_bytes(), b"fake-png")
            self.assertEqual(client.images.request["size"], "2048x1152")
            self.assertEqual(client.images.request["quality"], "high")
