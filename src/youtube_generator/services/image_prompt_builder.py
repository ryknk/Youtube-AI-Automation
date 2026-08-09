"""シーン本文から統一感のある画像生成プロンプトを組み立てる。"""

import re

# セリフを示す引用記号。FLUXは引用符付き文言を画面内テキストとして描画する
# 指示と解釈するため（BFL公式プロンプトガイド準拠）、渡す前に除去する。
# FLUX以外のプロバイダーにはこの制約はなく、除去するとセリフのニュアンスが
# 失われるだけなので、FLUX系プロバイダー使用時のみ適用する。
_QUOTE_MARKERS = re.compile("[「」『』“”‘’\"']")
# plugin_manager.image_provider_name()が返す値のうち、FLUXモデルを使用するプロバイダー。
_FLUX_PROVIDER_NAMES = frozenset({"bfl", "flux_schnell_local"})


class ImagePromptBuilder:
    """テンプレートで指定された画像表現をすべてのシーンに適用する。"""

    def __init__(self, style: str, provider_name: str = "") -> None:
        self._style = style
        self._strip_quote_markers = provider_name in _FLUX_PROVIDER_NAMES

    def build(self, scene_text: str) -> str:
        """シーンの内容と共通スタイルを結合した画像プロンプトを返す。"""
        cleaned_text = scene_text.strip()
        if not cleaned_text:
            raise ValueError("画像化するシーン本文が空です。")
        narration_text = (
            _QUOTE_MARKERS.sub("", cleaned_text) if self._strip_quote_markers else cleaned_text
        )
        return (
            "Use case: a single wide illustration used as narrated video background art.\n"
            "Format: widescreen landscape illustration, image content filling the entire frame "
            "edge to edge.\n"
            f"Primary request: Visually depict the situation and mood of this Japanese narration "
            f"scene: {narration_text}\n"
            f"Style/medium: {self._style}. Follow this template-specific medium and style exactly.\n"
            "Composition/framing: polished widescreen composition, visually clear main subject, "
            "clear depth and balanced framing.\n"
            "Setting: depict exactly one physically coherent location, consistent throughout the "
            "frame. If indoors, show a fully enclosed room with visible walls and no direct opening "
            "to the outdoors; if outdoors, do not include indoor furniture or interior fixtures. If "
            "the narration is abstract or conceptual rather than a concrete scene, choose one "
            "concrete, representative real-world setting that fits its mood and depict only that "
            "single setting.\n"
            "Lighting/mood: colors and lighting appropriate to the scene and specified medium.\n"
            "Character depiction: when the scene depicts people, render each person with clearly "
            "distinguishable gender-appropriate features (male: masculine build, facial structure, "
            "and attire; female: feminine build, facial structure, and attire) matching the gender "
            "implied by the narration, so male and female characters are visually unambiguous. This "
            "video is for a Japanese audience, so depict every person with Japanese ethnicity facial "
            "features, hairstyles, and attire appropriate to the scene.\n"
            "Character interaction: convey the characters' emotional state and relationship purely "
            "through facial expression, gaze, posture, and body language.\n"
            "Product design: render any electronics, devices, or products shown as plain, generic, "
            "unbranded designs.\n"
            "Constraints: widescreen landscape image filling the entire frame edge to edge, "
            "maintain the specified style consistently across all scenes."
        )
