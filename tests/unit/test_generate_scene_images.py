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
            use_case = GenerateSceneImagesUseCase(ImagePromptBuilder("realistic"), generator)

            image_files = use_case.execute(scenes_dir)

            self.assertEqual([file.name for file in image_files], ["scene01.png", "scene02.png"])
            self.assertEqual(len(generator.prompts), 2)
            self.assertIn("1番目の場面", generator.prompts[0])
            self.assertIn("no text", generator.prompts[0])

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
