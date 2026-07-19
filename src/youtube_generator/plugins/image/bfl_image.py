"""Black Forest Labs画像生成プラグイン。"""

from pathlib import Path

from youtube_generator.infrastructure.bfl_image_generator import BFLImageGenerator
from youtube_generator.plugins.base.image_provider import ImageProvider
from youtube_generator.services.retry import RetryPolicy


class BFLImageProvider(ImageProvider):
    def __init__(
        self, api_key: str, model: str, size: str, retry_policy: RetryPolicy
    ) -> None:
        self._generator = BFLImageGenerator(api_key, model, size, retry_policy)

    def generate_image(self, prompt: str, output_file: Path) -> None:
        self._generator.generate(prompt, output_file)
