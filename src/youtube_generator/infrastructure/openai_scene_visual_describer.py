"""OpenAI Responses APIで、シーン画像プロンプト用の英語場面説明をまとめて生成する。"""

import json
from typing import Any

from openai import APIConnectionError, APITimeoutError, InternalServerError, OpenAI, RateLimitError

from youtube_generator.exceptions import SceneDescriptionError
from youtube_generator.logger import get_logger
from youtube_generator.services.retry import RetryPolicy, retry_on_failure


class OpenAISceneVisualDescriber:
    """1動画分の日本語ナレーション文群から、画像生成プロンプト用の短い英語場面説明群を
    1回のAPI呼び出しでまとめて生成する。

    Qwen-Image等の文字レンダリング精度が高い画像生成モデルは、プロンプトに含まれる
    完結した日本語の文章をそのまま字幕のように画面へ描画してしまうことがある。生の
    ナレーション文の代わりにこの英語場面説明を画像プロンプトへ渡すことで、その挙動を回避する。
    シーン画像枚数分APIを呼び出すとAPI課金が線形に増えるため、1動画1回のバッチ呼び出しに
    まとめている。
    """

    def __init__(
        self, api_key: str, model: str, retry_policy: RetryPolicy, client: OpenAI | None = None,
    ) -> None:
        self._client = client or OpenAI(api_key=api_key, max_retries=0)
        self._model = model
        self._retry_policy = retry_policy
        self._logger = get_logger(__name__)

    def describe_scenes(self, narration_texts: tuple[str, ...]) -> tuple[str, ...]:
        if not narration_texts:
            return ()
        cleaned_texts = tuple(text.strip() for text in narration_texts)
        if any(not text for text in cleaned_texts):
            raise SceneDescriptionError("場面説明を生成するナレーション文が空です。")
        response = self._create_response(cleaned_texts)
        descriptions = self._parse(response.output_text, len(cleaned_texts))
        self._logger.info("場面説明を生成しました: %d件", len(descriptions))
        return descriptions

    def _create_response(self, narration_texts: tuple[str, ...]):  # type: ignore[no-untyped-def]
        @retry_on_failure(
            policy=self._retry_policy,
            retryable_exceptions=(APIConnectionError, APITimeoutError, InternalServerError, RateLimitError),
            logger=self._logger,
        )
        def request():  # type: ignore[no-untyped-def]
            return self._client.responses.create(
                model=self._model,
                instructions=self._instructions(),
                input=self._input(narration_texts),
                text={
                    "format": {
                        "type": "json_schema", "name": "scene_visual_descriptions", "strict": True,
                        "schema": self._schema(len(narration_texts)),
                    }
                },
            )

        return request()

    @staticmethod
    def _instructions() -> str:
        return (
            "あなたは画像生成AIへ渡すプロンプトを書く映像ディレクターです。"
            "与えられた日本語のナレーション文はそれぞれ独立した1つの場面を表します。"
            "各ナレーション文が描く状況・雰囲気・登場人物の様子を、1〜2文の英語で視覚的に"
            "説明してください。各説明は必ず英語の平文のみとし、日本語や引用符、Markdown、"
            "見出しは含めないでください。ナレーション文そのものの翻訳や引用ではなく、画面に"
            "映る情景の描写にしてください。字幕・テロップ・文字・ロゴ・透かしなど、画面内に"
            "文字として表示される要素には一切言及しないでください。"
            "指定JSON形式で、入力と同じ順序・同じ件数の配列を返してください。"
        )

    @staticmethod
    def _input(narration_texts: tuple[str, ...]) -> str:
        numbered = "\n".join(f"{index}. {text}" for index, text in enumerate(narration_texts, 1))
        return f"ナレーション文（{len(narration_texts)}件）:\n{numbered}"

    @staticmethod
    def _schema(count: int) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "descriptions": {
                    "type": "array", "items": {"type": "string"},
                    "minItems": count, "maxItems": count,
                },
            },
            "required": ["descriptions"],
            "additionalProperties": False,
        }

    @staticmethod
    def _parse(output_text: str, expected_count: int) -> tuple[str, ...]:
        try:
            payload = json.loads(output_text)
        except json.JSONDecodeError as error:
            raise SceneDescriptionError("場面説明のJSON解析に失敗しました。") from error
        if not isinstance(payload, dict):
            raise SceneDescriptionError("場面説明の応答形式が不正です。")
        descriptions = payload.get("descriptions")
        if (
            not isinstance(descriptions, list) or len(descriptions) != expected_count
            or not all(isinstance(item, str) and item.strip() for item in descriptions)
        ):
            raise SceneDescriptionError(
                f"場面説明を{expected_count}件含む有効な応答ではありません。"
            )
        return tuple(item.strip() for item in descriptions)
