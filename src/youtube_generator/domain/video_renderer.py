"""動画レンダリングの抽象インターフェース。"""

from pathlib import Path
from typing import Protocol


class VideoRenderer(Protocol):
    """シーン素材から最終動画を生成する。"""

    def render(self, scenes_dir: Path, output_file: Path) -> None:
        """指定フォルダ内の素材をMP4として出力する。"""
