"""シーン本文から統一感のある画像生成プロンプトを組み立てる。"""


class ImagePromptBuilder:
    """すべてのシーンに共通するリアル調の画像表現を適用する。"""

    def __init__(self, style: str) -> None:
        self._style = style

    def build(self, scene_text: str) -> str:
        """シーンの内容と共通スタイルを結合した画像プロンプトを返す。"""
        cleaned_text = scene_text.strip()
        if not cleaned_text:
            raise ValueError("画像化するシーン本文が空です。")
        return (
            "Use case: photorealistic-natural.\n"
            "Asset type: 16:9 YouTube video scene background.\n"
            f"Primary request: Visually depict this Japanese narration scene: {cleaned_text}\n"
            f"Style/medium: {self._style}, high-detail realistic photography.\n"
            "Composition/framing: cinematic widescreen composition, visually clear main subject, "
            "natural depth and balanced framing.\n"
            "Lighting/mood: realistic cinematic lighting appropriate to the scene.\n"
            "Constraints: 16:9 landscape image, maintain a consistent photorealistic style across "
            "all scenes, no text, no subtitles, no logos, no watermark."
        )
