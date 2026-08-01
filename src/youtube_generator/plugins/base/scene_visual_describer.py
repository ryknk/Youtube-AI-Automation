"""シーン場面説明プラグインの共通契約。"""

from typing import Protocol


class SceneVisualDescriber(Protocol):
    def describe_scenes(self, narration_texts: tuple[str, ...]) -> tuple[str, ...]:
        """1動画分の日本語ナレーション文群から、画像生成プロンプト用の短い英語場面説明群を
        まとめて1回のAPI呼び出しで生成する。戻り値はnarration_textsと同じ順序・同じ要素数。"""
