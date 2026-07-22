"""音声アライメントプラグインの共通契約。"""

from pathlib import Path
from typing import Protocol


class AlignmentProvider(Protocol):
    def align(self, audio_file: Path, script_text: str, output_file: Path) -> None:
        """音声と元台本を整合させ、結果をJSONとしてoutput_fileへ保存する。"""
