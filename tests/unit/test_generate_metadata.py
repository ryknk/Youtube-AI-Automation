"""メタデータ保存のユニットテスト。"""

import tempfile
import unittest
import json
from pathlib import Path

from youtube_generator.app.generate_metadata import GenerateMetadataUseCase
from youtube_generator.domain.metadata_generator import VideoMetadata
from youtube_generator.infrastructure.openai_metadata_generator import OpenAIMetadataGenerator
from youtube_generator.services.retry import RetryPolicy


class FakeMetadataGenerator:
    def generate(self, script: str) -> VideoMetadata:
        return VideoMetadata(tuple(f"タイトル{i}" for i in range(1, 11)), "概要欄", ("タグ1", "タグ2"), ("#タグ1", "#タグ2"), tuple(f"コピー{i}" for i in range(1, 6)))


class FakeResponse:
    output_text = json.dumps({
        "titles": ["候補1", "候補2", "候補3"], "description": "概要",
        "tags": ["タグ"], "hashtags": ["#タグ"],
        "thumbnail_copies": ["コピー1", "コピー2", "コピー3", "コピー4", "コピー5"],
    }, ensure_ascii=False)


class FakeResponsesResource:
    def __init__(self) -> None:
        self.request: dict[str, object] | None = None

    def create(self, **kwargs: object) -> FakeResponse:
        self.request = kwargs
        return FakeResponse()


class FakeOpenAIClient:
    def __init__(self) -> None:
        self.responses = FakeResponsesResource()


class GenerateMetadataTests(unittest.TestCase):
    def test_openai_generator_uses_configured_title_count(self) -> None:
        client = FakeOpenAIClient()
        generator = OpenAIMetadataGenerator(
            "test-key", "test-model", RetryPolicy(max_attempts=1),
            client=client, title_count=3,  # type: ignore[arg-type]
        )

        metadata = generator.generate("台本")

        self.assertEqual(len(metadata.titles), 3)
        text = client.responses.request["text"]  # type: ignore[index]
        titles_schema = text["format"]["schema"]["properties"]["titles"]  # type: ignore[index]
        self.assertEqual(titles_schema["minItems"], 3)
        self.assertEqual(titles_schema["maxItems"], 3)

    def test_execute_saves_all_metadata_files(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project_dir = Path(directory)
            (project_dir / "script.txt").write_text("台本", encoding="utf-8")
            files = GenerateMetadataUseCase(FakeMetadataGenerator()).execute(project_dir)
            self.assertEqual(len(files), 5)
            self.assertIn("10. タイトル10", (project_dir / "titles.txt").read_text(encoding="utf-8"))
            self.assertEqual((project_dir / "hashtags.txt").read_text(encoding="utf-8"), "#タグ1 #タグ2\n")
