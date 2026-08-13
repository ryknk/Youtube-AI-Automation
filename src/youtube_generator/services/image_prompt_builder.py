"""シーン本文から統一感のある画像生成プロンプトを組み立てる。"""

import random
import re

# セリフを示す引用記号。FLUXは引用符付き文言を画面内テキストとして描画する
# 指示と解釈するため（BFL公式プロンプトガイド準拠）、渡す前に除去する。
# FLUX以外のプロバイダーにはこの制約はなく、除去するとセリフのニュアンスが
# 失われるだけなので、FLUX系プロバイダー使用時のみ適用する。
_QUOTE_MARKERS = re.compile("[「」『』“”‘’\"']")
# plugin_manager.image_provider_name()が返す値のうち、FLUXモデルを使用するプロバイダー。
_FLUX_PROVIDER_NAMES = frozenset({"bfl", "flux_schnell_local"})

# 同一画像内に同性の人物が複数登場した際、全員が似た髪型で生成される問題への対策。
# 「差別化して」という抽象的な指示より、具体的な髪型を人物順に直接割り当てる方が
# 画像生成モデルに伝わりやすいため、build()の呼び出しごとにここからランダムに
# 抽出して割り当てる（毎回同じ組み合わせだと、その組み合わせ自体をモデルが学習・
# 固定化するリスクがあるため）。
_FEMALE_HAIRSTYLES = (
    "a short bob",
    "long straight hair",
    "hair tied in a ponytail",
    "hair tied in a bun",
    "wavy shoulder-length hair",
    "hair with side-swept bangs",
)
_MALE_HAIRSTYLES = (
    "a short crew cut",
    "neatly combed short hair",
    "textured medium-length hair",
    "a side-parted hairstyle",
    "slightly tousled short hair",
    "a buzz cut",
)
# 1画像内で同性の人物が同時に映る現実的な人数を想定した割り当て数。
_HAIRSTYLE_ASSIGNMENT_COUNT = 3


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
        female_hairstyles = ", then ".join(
            random.sample(_FEMALE_HAIRSTYLES, _HAIRSTYLE_ASSIGNMENT_COUNT)
        )
        male_hairstyles = ", then ".join(
            random.sample(_MALE_HAIRSTYLES, _HAIRSTYLE_ASSIGNMENT_COUNT)
        )
        return (
            "Use case: a single wide illustration used as narrated video background art.\n"
            "Format: widescreen landscape illustration, image content filling the entire frame "
            "edge to edge.\n"
            f"Primary request: Visually depict the situation and mood of this Japanese narration "
            f"scene: {narration_text}\n"
            f"Style/medium: {self._style} Follow this template-specific medium and style exactly.\n"
            "Composition/framing: polished widescreen composition, visually clear main subject, "
            "clear depth and balanced framing.\n"
            "Setting: when a physical location is shown, keep it structurally coherent. If indoors, "
            "show a fully enclosed room, with walls and ceiling intact on every side, and any view "
            "to the outdoors only through a window set in a wall. If outdoors, do not include indoor "
            "furniture or interior fixtures.\n"
            "Lighting/mood: colors and lighting appropriate to the scene and specified medium.\n"
            "Character depiction: when the scene depicts people, render each person with clearly "
            "distinguishable gender-appropriate features matching the gender implied by the "
            "narration, so male and female characters are visually unambiguous. This video is for "
            "a Japanese audience, so depict every person with Japanese ethnicity facial features "
            "and attire appropriate to the scene. Male characters: masculine build and facial "
            f"structure; if multiple male characters appear in the same image, give them these "
            f"male hairstyles in this exact order as they appear (e.g. left to right): "
            f"{male_hairstyles}. Female characters: feminine build and facial structure; if "
            f"multiple female characters appear in the same image, give them these female "
            f"hairstyles in this exact order as they appear: {female_hairstyles}. For any "
            "additional people of the same gender beyond the list for their gender, keep varying "
            "hair length and style so none of them duplicate each other or the people already "
            "listed. Never give a female character a male hairstyle, and never give a male "
            "character a female hairstyle.\n"
            "Character interaction: convey the characters' emotional state and relationship purely "
            "through facial expression, gaze, posture, and body language.\n"
            "Text/writing: whenever any surface would naturally display writing, render that content "
            "as abstract, illegible marks or wavy lines that do not form real readable characters, "
            "words, or numbers, rather than attempting to render actual text.\n"
            "Constraints: widescreen landscape image filling the entire frame edge to edge, "
            "maintain the specified style consistently across all scenes."
        )
