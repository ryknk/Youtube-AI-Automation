"""OpenAISceneVisualDescriberのユニットテスト。"""

import json
import unittest

from youtube_generator.exceptions import SceneDescriptionError
from youtube_generator.infrastructure.openai_scene_visual_describer import OpenAISceneVisualDescriber
from youtube_generator.services.retry import RetryPolicy


class FakeResponse:
    def __init__(self, payload: object) -> None:
        self.output_text = json.dumps(payload, ensure_ascii=False)


class FakeResponsesResource:
    def __init__(self, descriptions: list[str] | None = None) -> None:
        self.requests: list[dict[str, object]] = []
        self._descriptions = descriptions

    def create(self, **kwargs: object) -> FakeResponse:
        self.requests.append(kwargs)
        if self._descriptions is not None:
            return FakeResponse({"descriptions": self._descriptions})
        schema = kwargs["text"]["format"]["schema"]  # type: ignore[index]
        count = schema["properties"]["descriptions"]["minItems"]
        return FakeResponse({"descriptions": [f"A scene {i}." for i in range(1, count + 1)]})


class FakeOpenAIClient:
    def __init__(self, descriptions: list[str] | None = None) -> None:
        self.responses = FakeResponsesResource(descriptions)


class OpenAISceneVisualDescriberTests(unittest.TestCase):
    def test_describe_scenes_returns_descriptions_in_order(self) -> None:
        client = FakeOpenAIClient(["A quiet morning street.", "A busy evening market."])
        describer = OpenAISceneVisualDescriber(
            api_key="test-key", model="test-model", retry_policy=RetryPolicy(max_attempts=1),
            client=client,  # type: ignore[arg-type]
        )

        descriptions = describer.describe_scenes(("朝の静かな通り。", "夜の賑やかな市場。"))

        self.assertEqual(descriptions, ("A quiet morning street.", "A busy evening market."))
        self.assertEqual(len(client.responses.requests), 1)
        request = client.responses.requests[0]
        self.assertEqual(request["model"], "test-model")
        self.assertIn("朝の静かな通り。", request["input"])
        self.assertIn("夜の賑やかな市場。", request["input"])

    def test_describe_scenes_calls_api_exactly_once_regardless_of_scene_count(self) -> None:
        client = FakeOpenAIClient()
        describer = OpenAISceneVisualDescriber(
            api_key="test-key", model="test-model", retry_policy=RetryPolicy(max_attempts=1),
            client=client,  # type: ignore[arg-type]
        )

        descriptions = describer.describe_scenes(("場面1", "場面2", "場面3", "場面4"))

        self.assertEqual(len(descriptions), 4)
        self.assertEqual(len(client.responses.requests), 1)

    def test_describe_scenes_with_empty_input_skips_api_call(self) -> None:
        client = FakeOpenAIClient()
        describer = OpenAISceneVisualDescriber(
            api_key="test-key", model="test-model", retry_policy=RetryPolicy(max_attempts=1),
            client=client,  # type: ignore[arg-type]
        )

        descriptions = describer.describe_scenes(())

        self.assertEqual(descriptions, ())
        self.assertEqual(len(client.responses.requests), 0)

    def test_describe_scenes_rejects_blank_narration_text(self) -> None:
        describer = OpenAISceneVisualDescriber(
            api_key="test-key", model="test-model", retry_policy=RetryPolicy(max_attempts=1),
            client=FakeOpenAIClient(),  # type: ignore[arg-type]
        )

        with self.assertRaisesRegex(SceneDescriptionError, "空です"):
            describer.describe_scenes(("正常な場面", "   "))

    def test_describe_scenes_rejects_mismatched_response_count(self) -> None:
        client = FakeOpenAIClient(["説明が1件だけ"])
        describer = OpenAISceneVisualDescriber(
            api_key="test-key", model="test-model", retry_policy=RetryPolicy(max_attempts=1),
            client=client,  # type: ignore[arg-type]
        )

        with self.assertRaisesRegex(SceneDescriptionError, "2件"):
            describer.describe_scenes(("場面1", "場面2"))

    def test_describe_scenes_rejects_invalid_json_response(self) -> None:
        class BrokenResponsesResource:
            def create(self, **kwargs: object) -> object:
                return type("R", (), {"output_text": "not json"})()

        class BrokenClient:
            def __init__(self) -> None:
                self.responses = BrokenResponsesResource()

        describer = OpenAISceneVisualDescriber(
            api_key="test-key", model="test-model", retry_policy=RetryPolicy(max_attempts=1),
            client=BrokenClient(),  # type: ignore[arg-type]
        )

        with self.assertRaisesRegex(SceneDescriptionError, "JSON解析"):
            describer.describe_scenes(("場面1",))


if __name__ == "__main__":
    unittest.main()
