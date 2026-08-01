"""OpenAI Images APIを利用したPNG画像生成実装。"""

import base64
from pathlib import Path

from openai import APIConnectionError, APITimeoutError, InternalServerError, OpenAI, RateLimitError

from youtube_generator.domain.image_generator import ImageGenerator
from youtube_generator.exceptions import ImageGenerationError
from youtube_generator.logger import get_logger
from youtube_generator.services.retry import RetryPolicy, retry_on_failure


class OpenAIImageGenerator(ImageGenerator):
    """OpenAI Images APIで高品質な16:9 PNGを生成する。"""

    def __init__(
        self,
        api_key: str,
        model: str,
        size: str,
        quality: str,
        retry_policy: RetryPolicy,
        client: OpenAI | None = None,
        prompt_suffix: str = "",
    ) -> None:
        self._client = client or OpenAI(api_key=api_key, max_retries=0)
        self._model = model
        self._size = size
        self._quality = quality
        self._retry_policy = retry_policy
        # config.yamlで指定された任意の文字列をポジティブプロンプト末尾に付加する。既定は空文字列。
        self._prompt_suffix = prompt_suffix
        self._logger = get_logger(__name__)

    def generate(self, prompt: str, output_file: Path) -> None:
        """プロンプトに対応するPNG画像を生成・保存する。"""
        if not prompt.strip():
            raise ImageGenerationError("画像生成プロンプトが空です。")
        effective_prompt = f"{prompt}, {self._prompt_suffix}" if self._prompt_suffix else prompt
        result = self._request_image(effective_prompt)
        try:
            image_base64 = result.data[0].b64_json
            if not image_base64:
                raise ValueError("b64_json が空です。")
            image_bytes = base64.b64decode(image_base64, validate=True)
        except (AttributeError, IndexError, TypeError, ValueError) as error:
            raise ImageGenerationError("OpenAI APIから画像データを取得できませんでした。") from error

        output_file.parent.mkdir(parents=True, exist_ok=True)
        output_file.write_bytes(image_bytes)
        if output_file.stat().st_size == 0:
            raise ImageGenerationError(f"PNGファイルを保存できませんでした: {output_file}")

    def _request_image(self, prompt: str):  # type: ignore[no-untyped-def]
        @retry_on_failure(
            policy=self._retry_policy,
            retryable_exceptions=(APIConnectionError, APITimeoutError, InternalServerError, RateLimitError),
            logger=self._logger,
        )
        def request():  # type: ignore[no-untyped-def]
            return self._client.images.generate(
                model=self._model,
                prompt=prompt,
                size=self._size,
                quality=self._quality,
            )

        return request()
