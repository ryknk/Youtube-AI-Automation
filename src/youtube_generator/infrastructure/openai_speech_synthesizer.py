"""OpenAI Audio Speech APIを利用したMP3音声合成実装。"""

from pathlib import Path

from openai import APIConnectionError, APITimeoutError, InternalServerError, OpenAI, RateLimitError

from youtube_generator.domain.speech_synthesizer import SpeechSynthesizer
from youtube_generator.exceptions import SpeechSynthesisError
from youtube_generator.logger import get_logger
from youtube_generator.services.retry import RetryPolicy, retry_on_failure


class OpenAITTSSynthesizer(SpeechSynthesizer):
    """OpenAI TTSでテキストをMP3へストリーミング保存する。"""

    def __init__(
        self,
        api_key: str,
        model: str,
        voice: str,
        speed: float,
        instructions: str,
        retry_policy: RetryPolicy,
        client: OpenAI | None = None,
    ) -> None:
        self._client = client or OpenAI(api_key=api_key, max_retries=0)
        self._model = model
        self._voice = voice
        self._speed = speed
        self._instructions = instructions
        self._retry_policy = retry_policy
        self._logger = get_logger(__name__)

    def synthesize(self, text: str, output_file: Path) -> None:
        """テキストを音声化し、同名のMP3ファイルとして保存する。"""
        if not text.strip():
            raise SpeechSynthesisError("音声化するシーン本文が空です。")
        output_file.parent.mkdir(parents=True, exist_ok=True)
        self._request_and_save(text, output_file)
        if not output_file.is_file() or output_file.stat().st_size == 0:
            raise SpeechSynthesisError(f"MP3ファイルを保存できませんでした: {output_file}")

    def _request_and_save(self, text: str, output_file: Path) -> None:
        @retry_on_failure(
            policy=self._retry_policy,
            retryable_exceptions=(APIConnectionError, APITimeoutError, InternalServerError, RateLimitError),
            logger=self._logger,
        )
        def request() -> None:
            with self._client.audio.speech.with_streaming_response.create(
                model=self._model,
                voice=self._voice,
                input=text,
                instructions=self._instructions,
                speed=self._speed,
                response_format="mp3",
            ) as response:
                response.stream_to_file(output_file)

        request()
