"""動画テンプレートを表すドメインモデル。"""

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True, slots=True)
class VideoTemplate:
    """ジャンル別のプロンプトと動画構成を保持する。"""

    template_id: str
    display_name: str
    script_instruction: str
    image_style: str
    scene_structure: tuple[str, ...]
    title_instruction: str = ""
    thumbnail_instruction: str = ""
    video_settings: dict[str, Any] | None = None
    # image_prompt.<provider>.txt / thumbnail_prompt.<provider>.txt があれば
    # プロバイダー名をキーとしてここへ格納する（未指定プロバイダーはimage_style/
    # thumbnail_instructionへフォールバック）。
    image_style_overrides: dict[str, str] = field(default_factory=dict)
    thumbnail_instruction_overrides: dict[str, str] = field(default_factory=dict)

    def image_style_for(self, provider_name: str) -> str:
        """指定プロバイダー専用の画像スタイルがあればそれを、なければ既定値を返す。"""
        return self.image_style_overrides.get(provider_name, self.image_style)

    def thumbnail_instruction_for(self, provider_name: str) -> str:
        """指定プロバイダー専用のサムネイル指示があればそれを、なければ既定値を返す。"""
        return self.thumbnail_instruction_overrides.get(provider_name, self.thumbnail_instruction)
