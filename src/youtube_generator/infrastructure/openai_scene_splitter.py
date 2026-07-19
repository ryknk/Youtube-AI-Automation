"""OpenAI Responses APIを利用した意味単位の台本分割実装。"""

import json
from typing import Any

from openai import APIConnectionError, APITimeoutError, InternalServerError, OpenAI, RateLimitError

from youtube_generator.domain.scene_splitter import SceneSplitter
from youtube_generator.exceptions import SceneSplitError
from youtube_generator.logger import get_logger
from youtube_generator.services.retry import RetryPolicy, retry_on_failure


class OpenAISceneSplitter(SceneSplitter):
    """GPTに意味的な切れ目を判断させ、設定された最大数までシーン分割する。"""

    def __init__(
        self,
        api_key: str,
        model: str,
        retry_policy: RetryPolicy,
        client: OpenAI | None = None,
        max_scenes: int = 30,
    ) -> None:
        if max_scenes < 1:
            raise ValueError("最大シーン数は1以上である必要があります。")
        self._client = client or OpenAI(api_key=api_key, max_retries=0)
        self._model = model
        self._retry_policy = retry_policy
        self._max_scenes = max_scenes
        self._logger = get_logger(__name__)

    def split(self, script: str) -> tuple[str, ...]:
        """JSON Schemaに従うシーン配列を取得・検証する。"""
        if not script.strip():
            raise ValueError("分割する台本が空です。")

        response = self._create_response(script)
        try:
            payload: object = json.loads(response.output_text)
        except json.JSONDecodeError as error:
            raise SceneSplitError("OpenAI APIの分割結果をJSONとして解析できませんでした。") from error
        return self._validate_scenes(payload)

    def _create_response(self, script: str):  # type: ignore[no-untyped-def]
        @retry_on_failure(
            policy=self._retry_policy,
            retryable_exceptions=(APIConnectionError, APITimeoutError, InternalServerError, RateLimitError),
            logger=self._logger,
        )
        def request():  # type: ignore[no-untyped-def]
            return self._client.responses.create(
                model=self._model,
                instructions=(
                    "あなたはYouTube動画の編集者です。与えられた日本語台本を、"
                    "内容の話題・論点・場面が自然に切り替わる境目で分割してください。"
                    "文字数を均等にするための分割は禁止です。"
                    "台本の文を要約、追加、削除、並べ替え、重複してはいけません。"
                    f"1から{self._max_scenes}個のシーンに分けてください。"
                ),
                input=script,
                text={
                    "format": {
                        "type": "json_schema",
                        "name": "scene_split",
                        "strict": True,
                        "schema": self._scene_schema(),
                    }
                },
            )

        return request()

    def _validate_scenes(self, payload: object) -> tuple[str, ...]:
        if not isinstance(payload, dict):
            raise SceneSplitError("分割結果の形式が不正です。")
        scenes = payload.get("scenes")
        if not isinstance(scenes, list) or not 1 <= len(scenes) <= self._max_scenes:
            raise SceneSplitError(f"シーン数は1から{self._max_scenes}の範囲である必要があります。")
        if not all(isinstance(scene, str) and scene.strip() for scene in scenes):
            raise SceneSplitError("空または文字列以外のシーンが含まれています。")
        return tuple(scene.strip() for scene in scenes)

    def _scene_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "scenes": {
                    "type": "array", "items": {"type": "string"},
                    "minItems": 1, "maxItems": self._max_scenes,
                }
            },
            "required": ["scenes"],
            "additionalProperties": False,
        }
