"""OpenAI Images APIプラグイン。"""

from pathlib import Path

from youtube_generator.infrastructure.openai_image_generator import OpenAIImageGenerator
from youtube_generator.plugins.base.image_provider import ImageProvider
from youtube_generator.services.retry import RetryPolicy


class OpenAIImageProvider(ImageProvider):
    def __init__(
        self, api_key: str, model: str, size: str, quality: str, retry_policy: RetryPolicy,
        prompt_suffix: str = "",
    ) -> None:
        self._generator = OpenAIImageGenerator(
            api_key, model, size, quality, retry_policy, prompt_suffix=prompt_suffix,
        )

    def generate_image(self, prompt: str, output_file: Path) -> None:
        self._generator.generate(prompt, output_file)
