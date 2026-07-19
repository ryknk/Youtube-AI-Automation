"""画像生成プラグインの共通契約。"""

from pathlib import Path
from typing import Protocol


class ImageProvider(Protocol):
    def generate_image(self, prompt: str, output_file: Path) -> None:
        """プロンプトから画像を保存する。"""
