"""台本分割ユースケースのユニットテスト。"""

import json
import tempfile
import unittest
from pathlib import Path

from youtube_generator.app.split_script import SplitScriptUseCase
from youtube_generator.infrastructure.openai_scene_splitter import OpenAISceneSplitter
from youtube_generator.services.retry import RetryPolicy


class FakeSceneSplitter:
    def split(self, script: str) -> tuple[str, ...]:
        return ("導入の内容", "本編の内容", "結びの内容")


class FakeResponse:
    output_text = json.dumps({"scenes": ["導入", "本編", "結び"]}, ensure_ascii=False)


class FakeResponsesResource:
    def __init__(self) -> None:
        self.request: dict[str, object] | None = None

    def create(self, **kwargs: object) -> FakeResponse:
        self.request = kwargs
        return FakeResponse()


class FakeOpenAIClient:
    def __init__(self) -> None:
        self.responses = FakeResponsesResource()


class SplitScriptUseCaseTests(unittest.TestCase):
    def test_execute_creates_numbered_scene_files(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            script_file = Path(temporary_directory) / "script.txt"
            script_file.write_text("台本本文", encoding="utf-8")

            scene_files = SplitScriptUseCase(FakeSceneSplitter()).execute(script_file)

            self.assertEqual([file.name for file in scene_files], ["scene01.txt", "scene02.txt", "scene03.txt"])
            self.assertEqual(scene_files[1].read_text(encoding="utf-8"), "本編の内容\n")

    def test_openai_splitter_requests_strict_json_schema(self) -> None:
        client = FakeOpenAIClient()
        splitter = OpenAISceneSplitter(
            api_key="test-key",
            model="test-model",
            retry_policy=RetryPolicy(max_attempts=1),
            client=client,  # type: ignore[arg-type]
        )

        scenes = splitter.split("導入。本編。結び。")

        self.assertEqual(scenes, ("導入", "本編", "結び"))
        self.assertIsNotNone(client.responses.request)
        text = client.responses.request["text"]
        self.assertEqual(text["format"]["type"], "json_schema")  # type: ignore[index]
        self.assertTrue(text["format"]["strict"])  # type: ignore[index]
        self.assertEqual(text["format"]["schema"]["properties"]["scenes"]["maxItems"], 30)  # type: ignore[index]
