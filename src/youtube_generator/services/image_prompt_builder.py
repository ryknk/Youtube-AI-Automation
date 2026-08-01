"""シーン本文から統一感のある画像生成プロンプトを組み立てる。"""

import re

# セリフを示す引用記号。FLUXは引用符付き文言を画面内テキストとして描画する
# 指示と解釈するため（BFL公式プロンプトガイド準拠）、渡す前に除去する。
_QUOTE_MARKERS = re.compile("[「」『』“”‘’\"']")


class ImagePromptBuilder:
    """テンプレートで指定された画像表現をすべてのシーンに適用する。"""

    def __init__(self, style: str) -> None:
        self._style = style

    def build(self, scene_text: str) -> str:
        """シーンの内容と共通スタイルを結合した画像プロンプトを返す。"""
        cleaned_text = scene_text.strip()
        if not cleaned_text:
            raise ValueError("画像化するシーン本文が空です。")
        narration_text = _QUOTE_MARKERS.sub("", cleaned_text)
        return (
            "Use case: a single wide illustration used as narrated video background art.\n"
            "Format: 16:9 landscape illustration.\n"
            f"Primary request: Visually depict the situation and mood of this Japanese narration "
            f"scene: {narration_text}\n"
            f"Style/medium: {self._style}. Follow this template-specific medium and style exactly.\n"
            "Composition/framing: polished widescreen composition, visually clear main subject, "
            "clear depth and balanced framing.\n"
            "Lighting/mood: colors and lighting appropriate to the scene and specified medium.\n"
            "Character depiction: when the scene depicts people, render each person with clearly "
            "distinguishable gender-appropriate features (male: masculine build, facial structure, "
            "and attire; female: feminine build, facial structure, and attire) matching the gender "
            "implied by the narration, so male and female characters are visually unambiguous. This "
            "video is for a Japanese audience, so depict every person with Japanese ethnicity facial "
            "features, hairstyles, and attire appropriate to the scene.\n"
            "Dialogue/thoughts: convey any spoken lines or inner thoughts purely through facial "
            "expression, gaze, posture, body language, and the surrounding situation.\n"
            "Constraints: 16:9 landscape image, maintain the specified style consistently across "
            "all scenes."
        )
