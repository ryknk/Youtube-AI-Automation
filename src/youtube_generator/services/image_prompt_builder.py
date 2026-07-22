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
            "Constraints: 16:9 landscape image, maintain the specified style consistently across "
            "all scenes, no text, no subtitles, no logos, no watermark."
        )
