"""VOICEVOX Engine HTTP APIを利用するローカルTTSプラグイン。"""

import json
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from youtube_generator.logger import get_logger
from youtube_generator.services.retry import Retry, RetryPolicy


class VoicevoxHTTPError(RuntimeError):
    def __init__(self, status_code: int, message: str) -> None:
        super().__init__(message)
        self.status_code = status_code


class VOICEVOXTTSProvider:
    def __init__(self, base_url: str, speaker_id: int, timeout: float, query_settings: dict[str, float], retry_policy: RetryPolicy) -> None:
        self._base_url = base_url.rstrip("/")
        self._speaker_id = speaker_id
        self._timeout = timeout
        self._query_settings = query_settings
        self._logger = get_logger(__name__)
        self._request_with_retry = Retry(retry_policy, self._logger)(self._request)

    def generate_speech(self, text: str, output_file: Path) -> None:
        self._logger.info("VOICEVOX音声生成を開始します: speaker_id=%s", self._speaker_id)
        audio_query_parameters = urlencode({"text": text, "speaker": self._speaker_id})
        query = self._request_with_retry(
            "/audio_query", b"", None, audio_query_parameters,
        )
        payload = json.loads(query.decode("utf-8"))
        payload.update(self._query_settings)
        wav = self._request_with_retry("/synthesis", json.dumps(payload).encode("utf-8"), "application/json", f"speaker={self._speaker_id}")
        output_file.parent.mkdir(parents=True, exist_ok=True)
        output_file.write_bytes(wav)
        if output_file.stat().st_size == 0:
            raise RuntimeError("VOICEVOXから空の音声データが返されました。")
        self._logger.info("VOICEVOX音声生成を終了しました: %s", output_file)

    def check_connection(self) -> None:
        try:
            self._request("/version", None, None)
        except (ConnectionError, TimeoutError, VoicevoxHTTPError) as error:
            raise ConnectionError(f"VOICEVOX Engineに接続できません。起動と接続先を確認してください: {self._base_url}") from error

    def _request(self, path: str, body: bytes | None, content_type: str | None, query: str = "") -> bytes:
        url = f"{self._base_url}{path}" + (f"?{query}" if query else "")
        request = Request(url, data=body, method="POST" if body is not None else "GET")
        if content_type:
            request.add_header("Content-Type", content_type)
        try:
            with urlopen(request, timeout=self._timeout) as response:
                return response.read()
        except HTTPError as error:
            detail = error.read().decode("utf-8", errors="replace").strip()
            message = f"VOICEVOX APIエラー: HTTP {error.code}"
            if detail:
                message += f" - {detail[:1000]}"
            raise VoicevoxHTTPError(error.code, message) from error
        except URLError as error:
            raise ConnectionError(f"VOICEVOX Engineへ接続できません: {url}") from error
