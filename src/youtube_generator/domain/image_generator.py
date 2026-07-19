"""画像生成の抽象インターフェース。"""

from pathlib import Path
from typing import Protocol


class ImageGenerator(Protocol):
    """プロンプトからPNG画像を生成する。"""

    def generate(self, prompt: str, output_file: Path) -> None:
        """指定の出力先にPNG画像を保存する。"""
