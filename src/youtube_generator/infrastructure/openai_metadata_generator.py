"""OpenAI Responses APIでYouTubeメタデータを生成する。"""

import hashlib
import json
from typing import Any

from openai import APIConnectionError, APITimeoutError, InternalServerError, OpenAI, RateLimitError

from youtube_generator.domain.metadata_generator import (
    MetadataDetails,
    MetadataGenerationContext,
    MetadataGenerator,
    VideoMetadata,
)
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

    def generate(self, context: MetadataGenerationContext) -> VideoMetadata:
        titles = self.generate_titles(context)
        details = self.generate_details(context.script)
        return VideoMetadata(
            titles, details.description, details.tags, details.hashtags,
            details.thumbnail_copies,
        )

    def generate_titles(self, context: MetadataGenerationContext) -> tuple[str, ...]:
        self._validate_script(context.script)
        self._log_title_start(context)
        response = self._request(
            self._title_instructions(), self._title_input(context),
            "youtube_titles", self._titles_schema(),
        )
        titles = self._validate_titles(self._parse(response.output_text))
        self._logger.info("タイトル生成完了: template=%s, count=%d", context.template_name, len(titles))
        return titles

    def generate_details(self, script: str) -> MetadataDetails:
        self._validate_script(script)
        response = self._request(
            self._details_instructions(), script, "youtube_metadata_details", self._details_schema(),
        )
        return self._validate_details(self._parse(response.output_text))

    def _request(
        self, instructions: str, input_text: str, schema_name: str,
        schema: dict[str, Any],
    ):  # type: ignore[no-untyped-def]
        self._logger.debug("LLMへのメタデータ生成入力: %s", input_text)

        @retry_on_failure(
            self._retry_policy,
            (APIConnectionError, APITimeoutError, InternalServerError, RateLimitError),
            self._logger,
        )
        def request():  # type: ignore[no-untyped-def]
            return self._client.responses.create(
                model=self._model,
                instructions=instructions,
                input=input_text,
                text={"format": {"type": "json_schema", "name": schema_name, "strict": True, "schema": schema}},
            )

        try:
            return request()
        except Exception:
            self._logger.exception("メタデータ生成に失敗しました。")
            raise

    def _title_input(self, context: MetadataGenerationContext) -> str:
        return (
            f"{self._title_context(context)}\n\n"
            "【出力形式】\n"
            f"タイトル候補を{self._title_count}件、指定JSON形式で返してください。"
        )

    @staticmethod
    def _title_context(context: MetadataGenerationContext) -> str:
        title_prompt = (context.title_prompt or "").strip() or "（指定なし。共通ルールのみを使用）"
        return (
            "【使用テンプレート】\n"
            f"{context.template_name or '未指定'}\n\n"
            "【テンプレート固有のタイトル生成方針】\n"
            f"{title_prompt}\n\n"
            "【動画テーマ】\n"
            f"{context.topic or '未指定'}\n\n"
            "【完成した台本】\n"
            f"{context.script}"
        )

    @staticmethod
    def _title_instructions() -> str:
        return (
            "あなたはYouTubeタイトル作成の専門家です。動画のテーマと台本に一致する自然な日本語タイトルを生成してください。"
            "誤解を招く表現、過度な誇張、根拠のない断定を避けてください。"
            "テンプレート固有方針はできる限り強く反映しますが、安全性、事実性、出力JSON形式と矛盾する場合は共通ルールを優先してください。"
        )

    @staticmethod
    def _details_instructions() -> str:
        return (
            "あなたはYouTube SEOの専門家です。日本語台本に一致する概要欄、タグ、ハッシュタグ、サムネイル文言5件を生成してください。"
            "誤解を招く表現、過度な誇張、根拠のない断定を避け、ハッシュタグには先頭に#を付けてください。"
        )

    def _log_title_start(self, context: MetadataGenerationContext) -> None:
        prompt = (context.title_prompt or "").strip()
        prompt_hash = hashlib.sha256(prompt.encode("utf-8")).hexdigest()
        if not prompt:
            self._logger.warning(
                "title_promptが空のため共通タイトル生成ルールへフォールバックします: template=%s",
                context.template_name,
            )
        self._logger.info(
            "タイトル生成開始: template=%s, title_prompt_hash=%s, fallback=%s",
            context.template_name, prompt_hash, not bool(prompt),
        )

    @staticmethod
    def _validate_script(script: str) -> None:
        if not script.strip():
            raise ValueError("メタデータを生成する台本が空です。")

    @staticmethod
    def _parse(output_text: str) -> object:
        try:
            return json.loads(output_text)
        except json.JSONDecodeError as error:
            raise MetadataGenerationError("メタデータのJSON解析に失敗しました。") from error

    def _validate_titles(self, payload: object) -> tuple[str, ...]:
        try:
            if not isinstance(payload, dict):
                raise ValueError
            titles = payload["titles"]
            if (
                not isinstance(titles, list) or len(titles) != self._title_count
                or not all(isinstance(title, str) and title.strip() for title in titles)
            ):
                raise ValueError
            return tuple(title.strip() for title in titles)
        except (KeyError, ValueError) as error:
            raise MetadataGenerationError(f"タイトル{self._title_count}案を含む有効なデータではありません。") from error

    @staticmethod
    def _validate_details(payload: object) -> MetadataDetails:
        try:
            if not isinstance(payload, dict):
                raise ValueError
            description = payload["description"]
            tags = payload["tags"]
            hashtags = payload["hashtags"]
            copies = payload["thumbnail_copies"]
            values = (tags, hashtags, copies)
            if (
                not isinstance(description, str) or not description.strip()
                or not all(isinstance(items, list) and all(isinstance(item, str) and item.strip() for item in items) for items in values)
                or len(copies) != 5
            ):
                raise ValueError
            return MetadataDetails(
                description.strip(), tuple(tags), tuple(hashtags), tuple(copies)
            )
        except (KeyError, ValueError) as error:
            raise MetadataGenerationError("サムネイル文言5案を含む有効なメタデータではありません。") from error

    def _titles_schema(self) -> dict[str, Any]:
        return self._object_schema({"titles": self._titles_property()}, ["titles"])

    def _details_schema(self) -> dict[str, Any]:
        return self._object_schema(
            self._details_properties(), ["description", "tags", "hashtags", "thumbnail_copies"]
        )

    def _titles_property(self) -> dict[str, Any]:
        return {
            "type": "array", "items": {"type": "string"},
            "minItems": self._title_count, "maxItems": self._title_count,
        }

    @staticmethod
    def _details_properties() -> dict[str, Any]:
        return {
            "description": {"type": "string"},
            "tags": {"type": "array", "items": {"type": "string"}},
            "hashtags": {"type": "array", "items": {"type": "string"}},
            "thumbnail_copies": {
                "type": "array", "items": {"type": "string"}, "minItems": 5, "maxItems": 5,
            },
        }

    @staticmethod
    def _object_schema(properties: dict[str, Any], required: list[str]) -> dict[str, Any]:
        return {
            "type": "object", "properties": properties, "required": required,
            "additionalProperties": False,
        }
