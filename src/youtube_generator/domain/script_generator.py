"""台本生成の抽象インターフェース。"""

from typing import Protocol

from youtube_generator.domain.template import VideoTemplate


class ScriptGenerator(Protocol):
    """テーマとテンプレートから動画台本を生成する。"""

    def generate(self, theme: str, template: VideoTemplate) -> str:
        """空でない台本文を返す。"""
