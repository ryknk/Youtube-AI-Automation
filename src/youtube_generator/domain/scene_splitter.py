"""意味単位の台本分割を行う抽象インターフェース。"""

from typing import Protocol


class SceneSplitter(Protocol):
    """台本を動画シーン単位に分割する。"""

    def split(self, script: str) -> tuple[str, ...]:
        """1件以上、設定された最大件数までのシーン本文を返す。"""
