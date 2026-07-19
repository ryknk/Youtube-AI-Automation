"""Black Forest Labs FLUX APIを利用した画像生成実装。"""

import json
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from youtube_generator.exceptions import ImageGenerationError
from youtube_generator.logger import get_logger
from youtube_generator.services.retry import Retry, RetryPolicy


OpenUrl = Callable[..., Any]


class BFLImageGenerator:
    """FLUX.2へ生成要求を送り、完了画像をローカルへ保存する。"""

    def __init__(
        self, api_key: str, model: str, size: str, retry_policy: RetryPolicy,
        open_url: OpenUrl = urlopen, sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        try:
            width_text, height_text = size.lower().split("x", maxsplit=1)
            self._width, self._height = int(width_text), int(height_text)
        except (ValueError, AttributeError) as error:
            raise ValueError(f"画像サイズの形式が不正です: {size}") from error
        if self._width < 256 or self._height < 256:
            raise ValueError("BFL画像サイズは縦横とも256ピクセル以上にしてください。")
        self._api_key = api_key
        self._model = model
        self._retry_policy = retry_policy
        self._open_url = open_url
        self._sleep = sleep
        self._logger = get_logger(__name__)

    def generate(self, prompt: str, output_file: Path) -> None:
        if not prompt.strip():
            raise ImageGenerationError("画像生成プロンプトが空です。")
        submission = Retry(self._retry_policy, self._logger)(self._submit)(prompt)
        polling_url = submission.get("polling_url")
        if not isinstance(polling_url, str) or not polling_url.startswith("https://"):
            raise ImageGenerationError("BFL APIから有効なpolling_urlを取得できませんでした。")
        image_url = self._wait_for_result(polling_url)
        image_bytes = Retry(self._retry_policy, self._logger)(self._download)(image_url)
        if not image_bytes:
            raise ImageGenerationError("BFL APIから空の画像データが返されました。")
        output_file.parent.mkdir(parents=True, exist_ok=True)
        output_file.write_bytes(image_bytes)

    def _submit(self, prompt: str) -> dict[str, Any]:
        return self._request_json(
            Request(
                f"https://api.bfl.ai/v1/{self._model}",
                data=json.dumps({
                    "prompt": prompt, "width": self._width, "height": self._height,
                    "output_format": "png",
                }).encode("utf-8"),
                headers=self._headers(content_type=True), method="POST",
            )
        )

    def _wait_for_result(self, polling_url: str) -> str:
        deadline = time.monotonic() + self._retry_policy.timeout_seconds
        while time.monotonic() < deadline:
            result = Retry(self._retry_policy, self._logger)(self._poll)(polling_url)
            status = result.get("status")
            if status == "Ready":
                sample = result.get("result", {}).get("sample")
                if isinstance(sample, str) and sample.startswith("https://"):
                    return sample
                raise ImageGenerationError("BFL APIの画像URLが不正です。")
            if status in {"Error", "Failed"}:
                raise ImageGenerationError(f"BFL画像生成に失敗しました: {result}")
            self._sleep(0.5)
        raise ImageGenerationError("BFL画像生成の完了待機がタイムアウトしました。")

    def _poll(self, polling_url: str) -> dict[str, Any]:
        return self._request_json(Request(polling_url, headers=self._headers()))

    def _download(self, image_url: str) -> bytes:
        try:
            with self._open_url(Request(image_url), timeout=self._retry_policy.timeout_seconds) as response:
                return response.read()
        except (HTTPError, URLError, TimeoutError, OSError) as error:
            raise ConnectionError("BFL生成画像をダウンロードできませんでした。") from error

    def _request_json(self, request: Request) -> dict[str, Any]:
        try:
            with self._open_url(request, timeout=self._retry_policy.timeout_seconds) as response:
                value: object = json.loads(response.read().decode("utf-8"))
        except HTTPError as error:
            if error.code in {429, 500, 502, 503, 504}:
                raise ConnectionError(f"BFL API一時エラー: HTTP {error.code}") from error
            raise ImageGenerationError(f"BFL APIエラー: HTTP {error.code}") from error
        except (URLError, TimeoutError, OSError) as error:
            raise ConnectionError("BFL APIへ接続できませんでした。") from error
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise ImageGenerationError("BFL APIの応答を解析できませんでした。") from error
        if not isinstance(value, dict):
            raise ImageGenerationError("BFL APIの応答形式が不正です。")
        return value

    def _headers(self, content_type: bool = False) -> dict[str, str]:
        headers = {"accept": "application/json", "x-key": self._api_key}
        if content_type:
            headers["Content-Type"] = "application/json"
        return headers
