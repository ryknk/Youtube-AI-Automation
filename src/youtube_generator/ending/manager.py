"""テンプレート単位の共通エンディングを生成・再利用する。"""

import hashlib
import json
import random
import shutil
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Callable, Protocol

from youtube_generator.domain.audio_duration_provider import AudioDurationProvider
from youtube_generator.domain.quality import ProjectQualityReport
from youtube_generator.domain.template import VideoTemplate
from youtube_generator.ending.renderer import EndingRenderRequest
from youtube_generator.infrastructure.cache import CacheManager
from youtube_generator.logger import get_logger
from youtube_generator.plugins.base.text_generator import TextGenerator
from youtube_generator.plugins.base.tts_provider import TTSProvider
from youtube_generator.services.quality_checker import QualityChecker
from youtube_generator.services.srt_builder import SrtBuilder, SubtitleCue
from youtube_generator.services.template_service import TemplateManager


_ENDING_RENDER_STYLE_VERSION = "static-images-v1"


class EndingRenderer(Protocol):
    def render(self, request: EndingRenderRequest) -> None: ...
    def concat(self, main_video: Path, ending_video: Path, output_file: Path) -> None: ...


@dataclass(frozen=True, slots=True)
class EndingSettings:
    enabled: bool = True
    auto_append: bool = True
    min_duration: float = 5.0
    max_duration: float = 15.0
    max_reference_text_chars: int = 10_000
    image_mode: str = "sequence"
    subtitles_enabled: bool = True
    end_padding_seconds: float = 1.0

    @classmethod
    def from_config(cls, values: object) -> "EndingSettings":
        data = values if isinstance(values, dict) else {}
        settings = cls(
            enabled=bool(data.get("enabled", True)),
            auto_append=bool(data.get("auto_append", True)),
            min_duration=float(data.get("min_duration", 5)),
            max_duration=float(data.get("max_duration", 15)),
            max_reference_text_chars=int(data.get("max_reference_text_chars", 10_000)),
            image_mode=str(data.get("image_mode", "sequence")).lower(),
            subtitles_enabled=bool((data.get("subtitles", {}) or {}).get("enabled", True)) if isinstance(data.get("subtitles", {}), dict) else True,
            end_padding_seconds=float(data.get("end_padding_seconds", 1.0)),
        )
        if settings.min_duration <= 0 or settings.max_duration < settings.min_duration:
            raise ValueError("ending の秒数設定が不正です。")
        if settings.max_reference_text_chars <= 0 or settings.image_mode not in {"first", "random", "sequence"}:
            raise ValueError("ending の参照テキストまたは image_mode 設定が不正です。")
        if settings.end_padding_seconds < 0:
            raise ValueError("ending の end_padding_seconds 設定が不正です。")
        return settings


@dataclass(frozen=True, slots=True)
class TemplateMaterials:
    text_files: tuple[Path, ...]
    image_files: tuple[Path, ...]
    reference_text: str


@dataclass(frozen=True, slots=True)
class EndingAsset:
    template_id: str
    directory: Path
    video_file: Path
    audio_file: Path
    subtitle_file: Path
    script_file: Path
    metadata_file: Path
    cache_key: str
    reused: bool


class EndingManager:
    """素材・設定ハッシュでテンプレート共通エンディングを管理する。

    参照テキスト（ending*.txt）が存在する場合はLLMで書き換えずそのまま読み上げ、
    存在しない場合のみtext_generatorでナレーションを生成する。
    """

    _TEXT_SUFFIXES = {".txt"}
    _IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp"}
    _MATERIAL_PREFIX = "ending"

    def __init__(
        self,
        templates: TemplateManager,
        generated_root: Path,
        text_generator: TextGenerator,
        tts_provider: TTSProvider,
        duration_provider: AudioDurationProvider,
        subtitle_builder: SrtBuilder,
        renderer: EndingRenderer,
        quality_checker: QualityChecker,
        settings: EndingSettings,
        cache_manager: CacheManager | None = None,
        settings_fingerprint: str = "",
        renderer_for_template: Callable[[str], EndingRenderer] | None = None,
        asset_fingerprint_for_template: Callable[[str], str] | None = None,
        tts_provider_for_template: Callable[[str], TTSProvider] | None = None,
    ) -> None:
        self._templates = templates
        self._generated_root = generated_root
        self._text_generator = text_generator
        self._tts_provider = tts_provider
        self._duration_provider = duration_provider
        self._subtitle_builder = subtitle_builder
        self._renderer = renderer
        self._quality_checker = quality_checker
        self._settings = settings
        self._cache = cache_manager
        self._settings_fingerprint = settings_fingerprint
        self._renderer_for_template = renderer_for_template
        self._asset_fingerprint_for_template = asset_fingerprint_for_template
        self._tts_provider_for_template = tts_provider_for_template
        self._logger = get_logger(__name__)

    def collect_materials(self, template_id: str) -> TemplateMaterials:
        template_dir = self._templates.directory_for(template_id)
        text_files = tuple(sorted((
            path for path in template_dir.rglob("*")
            if self._is_ending_material(path, self._TEXT_SUFFIXES)
        ), key=lambda item: str(item).lower()))
        image_files = tuple(sorted((
            path for path in template_dir.rglob("*")
            if self._is_ending_material(path, self._IMAGE_SUFFIXES)
        ), key=lambda item: str(item).lower()))
        remaining = self._settings.max_reference_text_chars
        chunks: list[str] = []
        for file_path in text_files:
            if remaining <= 0:
                break
            text = file_path.read_text(encoding="utf-8-sig", errors="replace")
            chunks.append(text[:remaining])
            remaining -= len(text)
        return TemplateMaterials(text_files, image_files, "\n\n".join(chunks).strip())

    def ensure(self, template_id: str, force: bool = False) -> EndingAsset | None:
        if not self._settings.enabled:
            self._logger.info("エンディングは無効です: template=%s", template_id)
            return None
        template = self._templates.get(template_id)
        subtitles_enabled = self._templates.ending_subtitles_enabled(
            template.template_id, default=self._settings.subtitles_enabled
        )
        materials = self.collect_materials(template.template_id)
        cache_key = self._cache_key(template, materials)
        asset_dir = self._generated_root / template.template_id
        existing = self._load_existing(template.template_id, asset_dir, cache_key)
        if existing is not None and not force:
            self._logger.info("エンディングを再利用します: template=%s", template.template_id)
            return existing
        if self._cache is not None and not force and self._cache.exists(cache_key, "ending"):
            self._cache.restore_files(cache_key, "ending", asset_dir)
            restored = self._load_existing(template.template_id, asset_dir, cache_key)
            if restored is not None:
                self._logger.info("エンディングをキャッシュから復元しました: template=%s", template.template_id)
                return restored

        self._logger.info("エンディング生成を開始します: template=%s", template.template_id)
        asset_dir.mkdir(parents=True, exist_ok=True)
        if materials.reference_text:
            # 参照テキストが存在する場合は、LLMで書き換えずそのまま読み上げる。
            narration = materials.reference_text.strip()
        else:
            narration = self._text_generator.generate_ending_narration(
                template, materials.reference_text, self._settings.min_duration, self._settings.max_duration
            ).strip()
        report = self._quality_checker.check_ending(narration, self._settings.min_duration, self._settings.max_duration)
        self._raise_if_invalid(report)
        script_file = asset_dir / "ending_script.txt"
        audio_file = asset_dir / "ending_audio.mp3"
        subtitle_file = asset_dir / "ending_subtitle.srt"
        video_file = asset_dir / "ending.mp4"
        script_file.write_text(narration + "\n", encoding="utf-8")
        self._tts_provider_for(template.template_id).generate_speech(narration, audio_file)
        duration = self._duration_provider.get_duration_seconds(audio_file)
        if subtitles_enabled:
            self._logger.info("エンディング字幕を生成します: template=%s", template.template_id)
            subtitle_file.write_text(self._subtitle_builder.build((SubtitleCue(narration, duration),)), encoding="utf-8")
        else:
            self._logger.info("Ending subtitles disabled by template configuration: template=%s", template.template_id)
            subtitle_file.unlink(missing_ok=True)
        selected_images = self._select_images(materials.image_files, cache_key)
        self._renderer_for(template.template_id).render(
            EndingRenderRequest(
                audio_file, subtitle_file if subtitles_enabled else None, selected_images, video_file, duration,
                self._settings.end_padding_seconds,
            )
        )
        report = self._quality_checker.check_ending(
            narration, self._settings.min_duration, self._settings.max_duration, audio_file, video_file
        )
        self._raise_if_invalid(report)
        metadata_file = asset_dir / "metadata.json"
        metadata_file.write_text(json.dumps({
            "template_id": template.template_id,
            "cache_key": cache_key,
            "text_files": [str(path.relative_to(self._templates.directory_for(template.template_id))) for path in materials.text_files],
            "image_files": [str(path.relative_to(self._templates.directory_for(template.template_id))) for path in selected_images],
            "duration_seconds": duration,
            "settings": asdict(self._settings),
        }, ensure_ascii=False, indent=2), encoding="utf-8")
        files = tuple(file for file in (video_file, audio_file, subtitle_file, script_file, metadata_file) if file.is_file())
        if self._cache is not None:
            self._cache.save_files(cache_key, "ending", files)
        self._logger.info("エンディング生成を終了しました: template=%s", template.template_id)
        return EndingAsset(template.template_id, asset_dir, video_file, audio_file, subtitle_file, script_file, metadata_file, cache_key, False)

    def append_to(self, main_video: Path, template_id: str, output_file: Path, force: bool = False) -> Path:
        if not self._settings.auto_append:
            return main_video
        asset = self.ensure(template_id, force=force)
        if asset is None:
            return main_video
        self._logger.info("動画結合を開始します: template=%s", template_id)
        self._renderer_for(template_id).concat(main_video, asset.video_file, output_file)
        self._logger.info("動画結合を終了しました: output=%s", output_file)
        return output_file

    def list_assets(self) -> tuple[EndingAsset, ...]:
        if not self._generated_root.is_dir():
            return ()
        assets: list[EndingAsset] = []
        for directory in sorted((item for item in self._generated_root.iterdir() if item.is_dir()), key=lambda item: item.name):
            metadata_file = directory / "metadata.json"
            if not metadata_file.is_file():
                continue
            try:
                key = str(json.loads(metadata_file.read_text(encoding="utf-8"))["cache_key"])
            except (OSError, KeyError, json.JSONDecodeError, TypeError):
                continue
            asset = self._load_existing(directory.name, directory, key)
            if asset is not None:
                assets.append(asset)
        return tuple(assets)

    def delete(self, template_id: str) -> bool:
        directory = self._generated_root / self._templates.get(template_id).template_id
        if not directory.exists():
            return False
        cache_key: str | None = None
        metadata_file = directory / "metadata.json"
        try:
            cache_key = str(json.loads(metadata_file.read_text(encoding="utf-8"))["cache_key"])
        except (OSError, KeyError, TypeError, json.JSONDecodeError):
            pass
        shutil.rmtree(directory)
        if self._cache is not None and cache_key is not None:
            self._cache.delete(cache_key)
        self._logger.info("エンディングを削除しました: template=%s", template_id)
        return True

    def _cache_key(self, template: VideoTemplate, materials: TemplateMaterials) -> str:
        digest = hashlib.sha256()
        digest.update(template.template_id.encode("utf-8"))
        digest.update(_ENDING_RENDER_STYLE_VERSION.encode("utf-8"))
        digest.update(materials.reference_text.encode("utf-8"))
        digest.update(json.dumps(asdict(self._settings), sort_keys=True).encode("utf-8"))
        digest.update(self._settings_fingerprint.encode("utf-8"))
        digest.update(str(self._templates.ending_subtitles_enabled(template.template_id, default=self._settings.subtitles_enabled)).encode("utf-8"))
        if self._asset_fingerprint_for_template is not None:
            digest.update(self._asset_fingerprint_for_template(template.template_id).encode("utf-8"))
        for image in materials.image_files:
            digest.update(str(image.relative_to(self._templates.directory_for(template.template_id))).encode("utf-8"))
            digest.update(image.read_bytes())
        return digest.hexdigest()

    def _load_existing(self, template_id: str, directory: Path, cache_key: str) -> EndingAsset | None:
        required = {
            "video": directory / "ending.mp4", "audio": directory / "ending_audio.mp3",
            "script": directory / "ending_script.txt",
            "metadata": directory / "metadata.json",
        }
        if not all(path.is_file() and path.stat().st_size > 0 for path in required.values()):
            return None
        try:
            metadata = json.loads(required["metadata"].read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
        if metadata.get("cache_key") != cache_key:
            return None
        return EndingAsset(template_id, directory, required["video"], required["audio"], directory / "ending_subtitle.srt", required["script"], required["metadata"], cache_key, True)

    def _select_images(self, images: tuple[Path, ...], cache_key: str) -> tuple[Path, ...]:
        if not images:
            return ()
        if self._settings.image_mode == "first":
            return (images[0],)
        if self._settings.image_mode == "random":
            return (random.Random(cache_key).choice(images),)
        return images

    def _renderer_for(self, template_id: str) -> EndingRenderer:
        return self._renderer_for_template(template_id) if self._renderer_for_template else self._renderer

    def _tts_provider_for(self, template_id: str) -> TTSProvider:
        return self._tts_provider_for_template(template_id) if self._tts_provider_for_template else self._tts_provider

    @classmethod
    def _is_ending_material(cls, file_path: Path, extensions: set[str]) -> bool:
        """`ending` で始まる対象拡張子のファイルだけを素材として採用する。"""
        return (
            file_path.is_file()
            and file_path.suffix.lower() in extensions
            and file_path.stem.lower().startswith(cls._MATERIAL_PREFIX)
        )

    @staticmethod
    def _raise_if_invalid(report: ProjectQualityReport) -> None:
        if report.has_errors:
            messages = "; ".join(check.message for check in report.checks if check.severity.value == "error")
            raise RuntimeError(f"エンディング品質チェックでERRORを検出しました: {messages}")
