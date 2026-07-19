"""テンプレート単位のBGM設定解決・検証を担う。"""

import hashlib
import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Literal

from youtube_generator.domain.template import VideoTemplate
from youtube_generator.logger import get_logger
from youtube_generator.services.template_service import TemplateManager


BgmTarget = Literal["main", "ending", "final"]


@dataclass(frozen=True, slots=True)
class BgmSettings:
    enabled: bool
    file: Path | None = None
    volume: float = 0.08
    loop: bool = True
    fade_in: float = 0.0
    fade_out: float = 0.0
    source: str = "disabled"
    missing_file_behavior: str = "fallback"

    @property
    def cache_fingerprint(self) -> str:
        payload = asdict(self)
        payload["file"] = str(self.file) if self.file else None
        if self.file and self.file.is_file():
            payload["file_hash"] = hashlib.sha256(self.file.read_bytes()).hexdigest()
        return hashlib.sha256(json.dumps(payload, sort_keys=True).encode("utf-8")).hexdigest()


class BGMManager:
    """テンプレート、default、グローバルの順にBGM設定を解決する。"""

    _EXTENSIONS = {".mp3", ".wav", ".m4a", ".aac", ".ogg"}
    _MISSING_BEHAVIORS = {"fallback", "disable", "error"}

    def __init__(self, templates: TemplateManager, global_settings: dict[str, Any], project_root: Path) -> None:
        self._templates = templates
        self._global = global_settings
        self._project_root = project_root
        self._logger = get_logger(__name__)

    def resolve(self, template: VideoTemplate | str, target: BgmTarget) -> BgmSettings:
        selected = self._templates.get(template) if isinstance(template, str) else template
        own = self._from_template(selected, target)
        if own is not None:
            return self._handle_missing(own, selected.template_id, target, allow_fallback=True)
        if selected.template_id != "default":
            default = self._from_template(self._templates.get("default"), target)
            if default is not None:
                return self._handle_missing(default, "default", target, allow_fallback=True)
        global_bgm = self._from_global(target)
        return self._handle_missing(global_bgm, "global", target, allow_fallback=False)

    def render_mode(self, template: VideoTemplate | str) -> str:
        """BGMの適用タイミングを返す。既定は既存互換のper_section。"""
        selected = self._templates.get(template) if isinstance(template, str) else template
        values = (selected.video_settings or {}).get("bgm", {})
        mode = values.get("render_mode", self._global.get("render_mode", "per_section")) if isinstance(values, dict) else "per_section"
        normalized = str(mode).lower()
        if normalized not in {"per_section", "final_mix"}:
            raise ValueError("bgm.render_mode は per_section または final_mix を指定してください。")
        return normalized

    def validate(self, template: VideoTemplate | str, target: BgmTarget = "main") -> tuple[bool, str, BgmSettings]:
        setting = self.resolve(template, target)
        if not setting.enabled:
            return True, "BGMは無効です。", setting
        if setting.file is None:
            return False, "BGMファイルが設定されていません。", setting
        if setting.file.suffix.lower() not in self._EXTENSIONS:
            return False, f"未対応のBGM形式です: {setting.file.suffix}", setting
        if not setting.file.is_file():
            return False, f"BGMファイルが見つかりません: {setting.file}", setting
        return True, "BGMファイルを確認しました。", setting

    def _from_template(self, template: VideoTemplate, target: BgmTarget) -> BgmSettings | None:
        data = template.video_settings or {}
        bgm = data.get("bgm")
        if not isinstance(bgm, dict):
            return None
        if bgm.get("enabled") is False:
            return BgmSettings(enabled=False, source=f"template:{template.template_id}")
        target_values = bgm.get(target, data.get(target, {}))
        if target_values is None:
            target_values = {}
        if not isinstance(target_values, dict):
            raise ValueError(f"テンプレート {template.template_id} の {target} BGM設定が不正です。")
        merged = {key: value for key, value in bgm.items() if key not in {"main", "ending", "final"}}
        merged.update(target_values)
        if "file" not in merged and "path" not in merged:
            return None
        return self._build(merged, self._templates.directory_for(template.template_id), f"template:{template.template_id}")

    def _from_global(self, target: BgmTarget) -> BgmSettings:
        if self._global.get("enabled") is False:
            return BgmSettings(enabled=False, source="global")
        values = dict(self._global)
        nested = values.get(target)
        if isinstance(nested, dict):
            values.update(nested)
        if "file" not in values and "path" not in values and "default_file" not in values:
            return BgmSettings(enabled=False, source="global")
        if "default_file" in values and "file" not in values and "path" not in values:
            values["file"] = values["default_file"]
        if "default_volume" in values and "volume" not in values:
            values["volume"] = values["default_volume"]
        return self._build(values, self._project_root, "global")

    def _build(self, values: dict[str, Any], base_dir: Path, source: str) -> BgmSettings:
        enabled = bool(values.get("enabled", True))
        raw_file = values.get("file", values.get("path"))
        file_path = None if raw_file in (None, "") else Path(str(raw_file))
        if file_path is not None and not file_path.is_absolute():
            file_path = base_dir / file_path
        volume = float(values.get("volume", 0.08))
        fade_in = float(values.get("fade_in", 0.0))
        fade_out = float(values.get("fade_out", 0.0))
        behavior = str(values.get("missing_file_behavior", "fallback")).lower()
        if not 0.0 <= volume <= 1.0:
            raise ValueError(f"BGM音量は0.0〜1.0で指定してください: {volume}")
        if fade_in < 0 or fade_out < 0 or behavior not in self._MISSING_BEHAVIORS:
            raise ValueError("BGMのフェード時間または missing_file_behavior が不正です。")
        return BgmSettings(enabled, file_path, volume, bool(values.get("loop", True)), fade_in, fade_out, source, behavior)

    def _handle_missing(self, setting: BgmSettings, template_id: str, target: BgmTarget, allow_fallback: bool) -> BgmSettings:
        if not setting.enabled or (setting.file is not None and setting.file.is_file() and setting.file.suffix.lower() in self._EXTENSIONS):
            return setting
        message = f"BGMを利用できません: template={template_id}, target={target}, file={setting.file}"
        if setting.missing_file_behavior == "error":
            raise FileNotFoundError(message)
        self._logger.warning("%s", message)
        if setting.missing_file_behavior == "disable":
            return BgmSettings(enabled=False, source=f"{setting.source}:missing-disabled")
        if allow_fallback:
            return self.resolve("default", target) if template_id != "default" else self._from_global(target)
        return BgmSettings(enabled=False, source=f"{setting.source}:missing-disabled")
