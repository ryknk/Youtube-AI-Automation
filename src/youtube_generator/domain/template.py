"""動画テンプレートを表すドメインモデル。"""

from dataclasses import dataclass
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
