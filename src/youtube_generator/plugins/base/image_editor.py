"""画像編集プラグインの共通契約。"""

from pathlib import Path
from typing import Protocol


class ImageEditor(Protocol):
    def edit(self, image_file: Path) -> None:
        """指定画像ファイルを読み込み、編集結果で上書き保存する。"""
