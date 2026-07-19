"""LLMテキスト生成プラグインの共通契約。"""

from typing import Protocol

from youtube_generator.domain.template import VideoTemplate


class TextGenerator(Protocol):
    def generate_text(self, theme: str, template: VideoTemplate) -> str:
        """テーマとテンプレートから動画台本を生成する。"""

    def generate_ending_narration(
        self,
        template: VideoTemplate,
        reference_text: str,
        min_duration_seconds: float,
        max_duration_seconds: float,
    ) -> str:
        """テンプレート共通で利用する短いエンディング文を生成する。"""
