"""OpenAI Responses APIでYouTubeメタデータを生成する。"""

import json
from typing import Any

from openai import APIConnectionError, APITimeoutError, InternalServerError, OpenAI, RateLimitError

from youtube_generator.domain.metadata_generator import MetadataGenerator, VideoMetadata
from youtube_generator.exceptions import MetadataGenerationError
from youtube_generator.logger import get_logger
from youtube_generator.services.retry import RetryPolicy, retry_on_failure


class OpenAIMetadataGenerator(MetadataGenerator):
    def __init__(
        self, api_key: str, model: str, retry_policy: RetryPolicy,
        client: OpenAI | None = None, title_count: int = 10,
    ) -> None:
        if title_count < 1:
            raise ValueError("タイトル生成数は1以上である必要があります。")
        self._client = client or OpenAI(api_key=api_key, max_retries=0)
        self._model = model
        self._retry_policy = retry_policy
        self._title_count = title_count
        self._logger = get_logger(__name__)

    def generate(self, script: str) -> VideoMetadata:
        if not script.strip():
            raise ValueError("メタデータを生成する台本が空です。")
        response = self._request(script)
        try:
            payload: object = json.loads(response.output_text)
        except json.JSONDecodeError as error:
            raise MetadataGenerationError("メタデータのJSON解析に失敗しました。") from error
        return self._validate(payload)

    def _request(self, script: str):  # type: ignore[no-untyped-def]
        @retry_on_failure(self._retry_policy, (APIConnectionError, APITimeoutError, InternalServerError, RateLimitError), self._logger)
        def request():  # type: ignore[no-untyped-def]
            return self._client.responses.create(
                model=self._model,
                instructions="あなたはYouTube SEOの専門家です。日本語台本を基に、誇張や断定を避けた魅力的なメタデータを生成してください。ハッシュタグには先頭に#を付けてください。",
                input=script,
                text={"format": {"type": "json_schema", "name": "youtube_metadata", "strict": True, "schema": self._metadata_schema()}},
            )
        return request()

    def _validate(self, payload: object) -> VideoMetadata:
        if not isinstance(payload, dict):
            raise MetadataGenerationError("メタデータ形式が不正です。")
        try:
            titles = payload["titles"]
            copies = payload["thumbnail_copies"]
            if not isinstance(titles, list) or len(titles) != self._title_count or not isinstance(copies, list) or len(copies) != 5:
                raise ValueError
            values = (titles, payload["tags"], payload["hashtags"], copies)
            if not all(isinstance(items, list) and all(isinstance(item, str) and item.strip() for item in items) for items in values):
                raise ValueError
            description = payload["description"]
            if not isinstance(description, str) or not description.strip():
                raise ValueError
            return VideoMetadata(tuple(titles), description.strip(), tuple(payload["tags"]), tuple(payload["hashtags"]), tuple(copies))
        except (KeyError, ValueError) as error:
            raise MetadataGenerationError(
                f"タイトル{self._title_count}案またはコピー5案を含む有効なメタデータではありません。"
            ) from error

    def _metadata_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "titles": {
                    "type": "array", "items": {"type": "string"},
                    "minItems": self._title_count, "maxItems": self._title_count,
                },
                "description": {"type": "string"},
                "tags": {"type": "array", "items": {"type": "string"}},
                "hashtags": {"type": "array", "items": {"type": "string"}},
                "thumbnail_copies": {
                    "type": "array", "items": {"type": "string"},
                    "minItems": 5, "maxItems": 5,
                },
            },
            "required": ["titles", "description", "tags", "hashtags", "thumbnail_copies"],
            "additionalProperties": False,
        }
