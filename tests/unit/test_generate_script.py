"""台本生成ユースケースのユニットテスト。"""

import tempfile
import unittest
from pathlib import Path

from youtube_generator.app.generate_script import GenerateScriptUseCase
from youtube_generator.config import PROJECT_ROOT, Settings
from youtube_generator.domain.template import VideoTemplate
from youtube_generator.infrastructure.openai_script_generator import OpenAIScriptGenerator
from youtube_generator.services.retry import RetryPolicy


class FakeScriptGenerator:
    def generate_text(self, theme: str, template: VideoTemplate) -> str:
        return f"{theme}の台本"


class FakeResponse:
    output_text = "生成された台本"


class FakeResponsesResource:
    def __init__(self) -> None:
        self.request: dict[str, str] | None = None

    def create(self, **kwargs: str) -> FakeResponse:
        self.request = kwargs
        return FakeResponse()


class FakeOpenAIClient:
    def __init__(self) -> None:
        self.responses = FakeResponsesResource()


class GenerateScriptUseCaseTests(unittest.TestCase):
    def test_execute_saves_script_as_utf8_text(self) -> None:
        template = VideoTemplate("trivia", "雑学", "指示", "画像", ("導入", "本編"))
        with tempfile.TemporaryDirectory() as temporary_directory:
            script_file = GenerateScriptUseCase(
                FakeScriptGenerator(), Path(temporary_directory)
            ).execute("宇宙", template, "run-001")

            self.assertEqual(script_file.name, "script.txt")
            self.assertEqual(script_file.read_text(encoding="utf-8"), "宇宙の台本\n")
            self.assertEqual(script_file.parent.name, "run-001_宇宙")
            self.assertEqual(script_file.parent.parent.name, "雑学")

    def test_output_directory_replaces_windows_invalid_characters(self) -> None:
        template = VideoTemplate("trivia", "雑学/豆知識", "指示", "画像", ("導入",))

        output_dir = GenerateScriptUseCase.output_directory(
            Path("output"), "星:宇宙?*", template, "run-002"
        )

        self.assertEqual(output_dir, Path("output") / "雑学_豆知識" / "run-002_星_宇宙__")

    def test_openai_generator_uses_responses_api(self) -> None:
        template = VideoTemplate("trivia", "雑学", "指示", "画像", ("導入", "本編"))
        client = FakeOpenAIClient()
        generator = OpenAIScriptGenerator(
            api_key="test-key",
            model="test-model",
            retry_policy=RetryPolicy(max_attempts=1),
            client=client,  # type: ignore[arg-type]
        )

        script = generator.generate("宇宙", template)

        self.assertEqual(script, "生成された台本")
        self.assertIsNotNone(client.responses.request)
        self.assertEqual(client.responses.request["model"], "test-model")
        self.assertIn("動画テーマ: 宇宙", client.responses.request["input"])

    def test_settings_resolve_relative_output_path_from_project_root(self) -> None:
        settings = Settings(output_dir="custom-output")

        self.assertEqual(settings.output_dir, PROJECT_ROOT / "custom-output")
