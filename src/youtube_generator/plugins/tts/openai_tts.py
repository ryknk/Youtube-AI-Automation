"""OpenAI TTSプラグイン。"""

from pathlib import Path

from youtube_generator.infrastructure.openai_speech_synthesizer import OpenAITTSSynthesizer
from youtube_generator.plugins.base.tts_provider import TTSProvider
from youtube_generator.services.retry import RetryPolicy


class OpenAITTSProvider(TTSProvider):
    def __init__(self, api_key: str, model: str, voice: str, speed: float, instructions: str, retry_policy: RetryPolicy) -> None:
        self._synthesizer = OpenAITTSSynthesizer(api_key, model, voice, speed, instructions, retry_policy)

    def generate_speech(self, text: str, output_file: Path) -> None:
        self._synthesizer.synthesize(text, output_file)
