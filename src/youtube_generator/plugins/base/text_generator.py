"""LLMテキスト生成プラグインの共通契約。"""

from typing import Protocol

from youtube_generator.domain.template import VideoTemplate


class TextGenerator(Protocol):
    def generate_text(self, theme: str, template: VideoTemplate) -> str:
        """テーマとテンプレートから動画台本を生成する。"""
