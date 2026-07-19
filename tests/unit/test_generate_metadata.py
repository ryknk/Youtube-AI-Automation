"""メタデータ生成とtitle_prompt伝播のテスト。"""

import json
import tempfile
import unittest
from pathlib import Path

from youtube_generator.app.generate_metadata import GenerateMetadataUseCase
from youtube_generator.domain.metadata_generator import (
    MetadataDetails,
    MetadataGenerationContext,
    VideoMetadata,
)
from youtube_generator.infrastructure.cache import CacheManager
from youtube_generator.infrastructure.openai_metadata_generator import OpenAIMetadataGenerator
from youtube_generator.services.retry import RetryPolicy


class FakeMetadataGenerator:
    def __init__(self) -> None:
        self.full_calls: list[MetadataGenerationContext] = []
        self.title_calls: list[MetadataGenerationContext] = []
        self.detail_calls: list[str] = []

    def generate(self, context: MetadataGenerationContext) -> VideoMetadata:
        self.full_calls.append(context)
        return VideoMetadata(
            tuple(f"タイトル{i}" for i in range(1, 11)), "概要欄",
            ("タグ1", "タグ2"), ("#タグ1", "#タグ2"),
            tuple(f"コピー{i}" for i in range(1, 6)),
        )

    def generate_titles(self, context: MetadataGenerationContext) -> tuple[str, ...]:
        self.title_calls.append(context)
        return tuple(f"再生成タイトル{i}" for i in range(1, 11))

    def generate_details(self, script: str) -> MetadataDetails:
        self.detail_calls.append(script)
        return MetadataDetails("概要欄", ("タグ",), ("#タグ",), tuple(f"コピー{i}" for i in range(1, 6)))


class FakeResponse:
    def __init__(self, payload: dict[str, object]) -> None:
        self.output_text = json.dumps(payload, ensure_ascii=False)


class FakeResponsesResource:
    def __init__(self) -> None:
        self.requests: list[dict[str, object]] = []

    def create(self, **kwargs: object) -> FakeResponse:
        self.requests.append(kwargs)
        schema = kwargs["text"]["format"]["schema"]  # type: ignore[index]
        required = schema["required"]
        title_count = schema["properties"].get("titles", {}).get("minItems", 0)
        payload: dict[str, object] = {}
        if "titles" in required:
            payload["titles"] = [f"候補{i}" for i in range(1, title_count + 1)]
        if "description" in required:
            payload.update({
                "description": "概要", "tags": ["タグ"], "hashtags": ["#タグ"],
                "thumbnail_copies": [f"コピー{i}" for i in range(1, 6)],
            })
        return FakeResponse(payload)


class FakeOpenAIClient:
    def __init__(self) -> None:
        self.responses = FakeResponsesResource()


class GenerateMetadataTests(unittest.TestCase):
    def _generator(self, client: FakeOpenAIClient, title_count: int = 3) -> OpenAIMetadataGenerator:
        return OpenAIMetadataGenerator(
            "test-key", "test-model", RetryPolicy(max_attempts=1),
            client=client, title_count=title_count,  # type: ignore[arg-type]
        )

    def test_openai_generator_uses_configured_title_count_and_title_prompt(self) -> None:
        client = FakeOpenAIClient()
        generator = self._generator(client)
        context = MetadataGenerationContext(
            "徳川家康", "完成台本", "歴史", "人物名を明確に含める",
        )

        metadata = generator.generate(context)

        self.assertEqual(len(metadata.titles), 3)
        request = client.responses.requests[0]
        self.assertIn("人物名を明確に含める", request["input"])
        self.assertIn("徳川家康", request["input"])
        self.assertIn("完成台本", request["input"])
        self.assertIn("歴史", request["input"])
        titles_schema = request["text"]["format"]["schema"]["properties"]["titles"]  # type: ignore[index]
        self.assertEqual(titles_schema["minItems"], 3)
        self.assertEqual(titles_schema["maxItems"], 3)
        self.assertEqual(len(client.responses.requests), 2)
        self.assertNotIn("人物名を明確に含める", client.responses.requests[1]["input"])

    def test_different_title_prompts_create_different_llm_inputs(self) -> None:
        client = FakeOpenAIClient()
        generator = self._generator(client)
        common = {"topic": "共通テーマ", "script": "共通台本", "template_name": "テスト"}

        generator.generate_titles(MetadataGenerationContext(**common, title_prompt="短く意外性を出す"))
        generator.generate_titles(MetadataGenerationContext(**common, title_prompt="人物名と出来事を含める"))

        self.assertNotEqual(client.responses.requests[0]["input"], client.responses.requests[1]["input"])

    def test_empty_title_prompt_falls_back_to_common_rules(self) -> None:
        client = FakeOpenAIClient()
        generator = self._generator(client)

        with self.assertLogs("youtube_generator.infrastructure.openai_metadata_generator", level="WARNING") as logs:
            titles = generator.generate_titles(MetadataGenerationContext("テーマ", "台本", "default", None))

        self.assertEqual(len(titles), 3)
        self.assertIn("共通ルールのみを使用", client.responses.requests[0]["input"])
        self.assertTrue(any("フォールバック" in message for message in logs.output))

    def test_execute_saves_all_metadata_files_and_passes_context(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project_dir = Path(directory)
            (project_dir / "script.txt").write_text("台本", encoding="utf-8")
            fake = FakeMetadataGenerator()

            files = GenerateMetadataUseCase(fake).execute(
                project_dir, topic="宇宙", template_name="科学", title_prompt="正確に表現",
            )

            self.assertEqual(len(files), 5)
            self.assertEqual(fake.full_calls[0].title_prompt, "正確に表現")
            self.assertIn("10. タイトル10", (project_dir / "titles.txt").read_text(encoding="utf-8"))

    def test_title_prompt_change_regenerates_only_titles(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            project_dir = root / "project"
            project_dir.mkdir()
            (project_dir / "script.txt").write_text("同じ台本", encoding="utf-8")
            cache = CacheManager(root / "cache")
            fake = FakeMetadataGenerator()
            use_case = GenerateMetadataUseCase(fake)

            first = use_case.execute_cached(
                project_dir, cache, fingerprint="settings", topic="家康",
                template_id="history", template_name="歴史", title_prompt="人物名を含める",
            )
            same = use_case.execute_cached(
                project_dir, cache, fingerprint="settings", topic="家康",
                template_id="history", template_name="歴史", title_prompt="人物名を含める",
            )
            changed = use_case.execute_cached(
                project_dir, cache, fingerprint="settings", topic="家康",
                template_id="history", template_name="歴史", title_prompt="過度な煽りを避ける",
            )

            self.assertFalse(first.titles_cache_hit)
            self.assertTrue(same.titles_cache_hit)
            self.assertTrue(same.details_cache_hit)
            self.assertNotEqual(first.titles_cache_key, changed.titles_cache_key)
            self.assertEqual(first.details_cache_key, changed.details_cache_key)
            self.assertEqual(len(fake.full_calls), 1)
            self.assertEqual(len(fake.title_calls), 1)
            self.assertEqual(len(fake.detail_calls), 0)
            # このユースケースは台本・TTS・画像・動画の各生成処理を呼び出さない。
            self.assertEqual({path.name for path in changed.files}, {
                "titles.txt", "description.txt", "tags.txt", "hashtags.txt", "thumbnail_copies.txt",
            })


if __name__ == "__main__":
    unittest.main()
