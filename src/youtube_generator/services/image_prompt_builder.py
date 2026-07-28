"""シーン本文から統一感のある画像生成プロンプトを組み立てる。"""


class ImagePromptBuilder:
    """テンプレートで指定された画像表現をすべてのシーンに適用する。"""

    def __init__(self, style: str) -> None:
        self._style = style

    def build(self, scene_text: str) -> str:
        """シーンの内容と共通スタイルを結合した画像プロンプトを返す。"""
        cleaned_text = scene_text.strip()
        if not cleaned_text:
            raise ValueError("画像化するシーン本文が空です。")
        return (
            "Use case: template-directed visual.\n"
            "Asset type: 16:9 YouTube video scene background.\n"
            f"Primary request: Visually depict this Japanese narration scene: {cleaned_text}\n"
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
            "Dialogue/thoughts: if the narration includes spoken lines or inner thoughts, express "
            "them purely through facial expression, gaze, posture, and body language. Do not render "
            "the words themselves anywhere in the image.\n"
            "Constraints: 16:9 landscape image, maintain the specified style consistently across "
            "all scenes, no text, no subtitles, no logos, no watermark, no speech bubbles, no "
            "chat/message bubbles, no on-screen UI text, no readable text on signs, banners, "
            "posters, screens, papers, or products."
        )
