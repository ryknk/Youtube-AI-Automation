"""コード変更なしで動画設定を切り替えるためのTOMLローダー。"""

import hashlib
import yaml
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True, slots=True)
class VideoSettings:
    """config.yamlの内容と、キャッシュ判定用フィンガープリント。"""

    values: dict[str, Any]
    fingerprint: str


def load_video_settings(config_file: Path) -> VideoSettings:
    """config.yamlを読み込み、設定変更を識別できるハッシュを返す。"""
    try:
        raw_content = config_file.read_bytes()
        values: object = yaml.safe_load(raw_content.decode("utf-8"))
    except (OSError, UnicodeDecodeError, yaml.YAMLError) as error:
        raise ValueError(f"動画設定を読み込めません: {config_file}") from error
    if not isinstance(values, dict):
        raise ValueError("config.yaml の形式が不正です。")
    required_sections = {"video", "providers", "text", "audio", "image", "scenes", "bgm", "subtitles", "metadata", "quality", "retry", "cache", "queue", "youtube"}
    if not required_sections.issubset(values):
        missing = ", ".join(sorted(required_sections - values.keys()))
        raise ValueError(f"config.yaml の必須セクションがありません: {missing}")
    image_settings = values.get("image")
    if not isinstance(image_settings, dict):
        raise ValueError("config.yaml の image 設定が不正です。")
    required_image_settings = {"scene_size", "thumbnail_size"}
    if not required_image_settings.issubset(image_settings):
        missing = ", ".join(sorted(required_image_settings - image_settings.keys()))
        raise ValueError(f"config.yaml の image 設定がありません: {missing}")
    ending_settings = values.get("ending", {})
    if ending_settings and not isinstance(ending_settings, dict):
        raise ValueError("config.yaml の ending 設定が不正です。")
    return VideoSettings(values=values, fingerprint=hashlib.sha256(raw_content).hexdigest())
