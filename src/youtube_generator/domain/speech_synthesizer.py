"""音声合成の抽象インターフェース。"""

from pathlib import Path
from typing import Protocol


class SpeechSynthesizer(Protocol):
    """テキストをMP3ファイルとして音声化する。"""

    def synthesize(self, text: str, output_file: Path) -> None:
        """指定した出力先へ音声ファイルを保存する。"""
