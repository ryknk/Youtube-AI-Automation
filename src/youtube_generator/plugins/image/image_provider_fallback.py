"""明示設定時のみ有効化する画像プロバイダーのフォールバック合成。

Self-host生成が失敗した場合でも、設定で明示されない限りAPIプロバイダーへは
切り替えない（意図しないAPI課金を避けるため）。Pipeline側にプロバイダー固有の
分岐を持ち込まないよう、ImageProviderの合成として実装する。
"""

from pathlib import Path

from youtube_generator.exceptions import ImageGenerationError
from youtube_generator.logger import get_logger
from youtube_generator.plugins.base.image_provider import ImageProvider


class FallbackImageProvider(ImageProvider):
    """主プロバイダーの失敗時に、設定で明示されたフォールバックへ切り替える。"""

    def __init__(self, primary: ImageProvider, fallback: ImageProvider, fallback_name: str) -> None:
        self._primary = primary
        self._fallback = fallback
        self._fallback_name = fallback_name
        self._logger = get_logger(__name__)

    def generate_image(self, prompt: str, output_file: Path) -> None:
        try:
            self._primary.generate_image(prompt, output_file)
        except ImageGenerationError:
            self._logger.exception(
                "画像生成に失敗したため、設定済みのfallback_provider(%s)へ切り替えます。"
                "API料金が発生する可能性があります。",
                self._fallback_name,
            )
            self._fallback.generate_image(prompt, output_file)
