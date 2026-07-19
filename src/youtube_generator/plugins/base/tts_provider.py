"""TTSプラグインの共通契約。"""

from pathlib import Path
from typing import Protocol


class TTSProvider(Protocol):
    def generate_speech(self, text: str, output_file: Path) -> None:
        """テキストを音声ファイルとして保存する。"""
