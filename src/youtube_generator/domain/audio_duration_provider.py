"""音声ファイルの再生時間を取得する抽象インターフェース。"""

from pathlib import Path
from typing import Protocol


class AudioDurationProvider(Protocol):
    """音声ファイルの長さを秒単位で提供する。"""

    def get_duration_seconds(self, audio_file: Path) -> float:
        """正の再生時間（秒）を返す。"""
