"""コマンドラインからアプリケーションを起動する。"""

import argparse
import hashlib
import json
import shutil
import sys
from dataclasses import replace
from pathlib import Path
from uuid import uuid4

from pydantic import ValidationError
from openai import OpenAIError

from youtube_generator.app.generate_script import GenerateScriptUseCase
from youtube_generator.app.split_script import SplitScriptUseCase
from youtube_generator.app.generate_scene_audio import GenerateSceneAudioUseCase
from youtube_generator.app.generate_scene_descriptions import GenerateSceneDescriptionsUseCase
from youtube_generator.app.generate_scene_images import GenerateSceneImagesUseCase
from youtube_generator.app.generate_subtitles import GenerateSubtitlesUseCase
from youtube_generator.app.generate_video import GenerateVideoUseCase
from youtube_generator.app.generate_metadata import GenerateMetadataUseCase
from youtube_generator.app.generate_thumbnail import GenerateThumbnailUseCase
from youtube_generator.config import load_settings
from youtube_generator.exceptions import AlignmentGenerationError
from youtube_generator.infrastructure.cache import CacheManager
from youtube_generator.infrastructure.caching_scene_visual_describer import CachingSceneVisualDescriber
from youtube_generator.infrastructure.history import RunHistoryRecorder
from youtube_generator.logger import Logger, configure_logging, get_logger, set_active_logger
from youtube_generator.infrastructure.ffprobe_audio_duration_provider import FfprobeAudioDurationProvider
from youtube_generator.infrastructure.ffmpeg_video_renderer import FfmpegVideoRenderer, VideoRenderSettings
from youtube_generator.infrastructure.openai_quality_advisor import OpenAIQualityAdvisor
from youtube_generator.services.quality_checker import QualityChecker, ScriptQualityChecker, load_quality_rules
from youtube_generator.services.retry import RetryPolicy
from youtube_generator.services.image_prompt_builder import ImagePromptBuilder
from youtube_generator.services.srt_builder import SrtBuilder
from youtube_generator.services.subtitle_alignment import JsonSubtitleAlignmentProvider
from youtube_generator.services.subtitle_splitter import (
    SUBTITLE_SPLITTER_VERSION,
    SubtitleSettings,
    SubtitleSplitter,
)
from youtube_generator.services.template_service import TemplateManager
from youtube_generator.services.video_settings import load_video_settings
from youtube_generator.services.bgm_manager import BGMManager
from youtube_generator.infrastructure.final_bgm_renderer import FinalBGMRenderer, FinalRenderSettings
from youtube_generator.plugins.alignment.factory import create_alignment_provider
from youtube_generator.plugins.manager import PluginManager
from youtube_generator.cli.ending import run_ending
from youtube_generator.cli.ending import create_ending_manager
from youtube_generator.cli.bgm import run_bgm
from youtube_generator.cli.render import run_render
from youtube_generator.cli.image import run_image


# --generate-imagesが求めた生成キャッシュキーを--edit-imagesへ引き継ぐための一時ファイル名。
# scene*.pngの内容は編集で書き換わるためキャッシュキーの元にできない（二重編集を招く）が、
# この値は生成設定のみに由来し編集で変化しないため、編集キャッシュキーの安定した構成要素になる。
_IMAGE_CACHE_KEY_SIDECAR = ".image_cache_key"

# 画像1枚ごとの編集済みマーカーのファイル名接尾辞。scene*.png自体は編集で上書きされ
# 「未編集/編集済み」を内容から判別できないため、中断されたジョブの再試行時に二重編集
# （破壊的処理のため画質劣化を招く）を避ける目的でこのサイドカーへ編集時のキーを記録する。
_IMAGE_EDIT_MARKER_SUFFIX = ".edited"


def _edit_marker_file(image_file: Path) -> Path:
    return image_file.with_name(image_file.name + _IMAGE_EDIT_MARKER_SUFFIX)


def _is_already_edited(image_file: Path, resume_key: str) -> bool:
    """同じ編集設定で既に編集済みかどうかを、サイドカーマーカーの内容から判定する。"""
    marker_file = _edit_marker_file(image_file)
    if not marker_file.is_file():
        return False
    return marker_file.read_text(encoding="utf-8").strip() == resume_key


def _mark_edited(image_file: Path, resume_key: str) -> None:
    _edit_marker_file(image_file).write_text(resume_key, encoding="utf-8")


def _parse_image_size(size: str) -> tuple[int, int] | None:
    """"WxH"形式の画像サイズ設定を解析する。解析できない場合は品質チェックをスキップするためNoneを返す。"""
    try:
        width_text, height_text = size.lower().split("x", maxsplit=1)
        return int(width_text), int(height_text)
    except (ValueError, AttributeError):
        return None


def create_parser() -> argparse.ArgumentParser:
    """CLI引数パーサーを作成する。"""
    parser = argparse.ArgumentParser(description="Youtube AI Automation")
    input_group = parser.add_mutually_exclusive_group()
    input_group.add_argument("--theme", help="台本を生成する動画テーマ")
    input_group.add_argument("--split-script", type=Path, help="分割する script.txt のパス")
    input_group.add_argument("--generate-audio", type=Path, help="sceneNN.txt があるフォルダのパス")
    input_group.add_argument(
        "--generate-scene-descriptions", type=Path,
        help="sceneNN.txt があるフォルダのパス（画像プロンプト用の場面説明のみを生成）",
    )
    input_group.add_argument("--generate-images", type=Path, help="sceneNN.txt があるフォルダのパス")
    input_group.add_argument("--edit-images", type=Path, help="sceneNN_MM.png があるフォルダのパス")
    input_group.add_argument("--generate-subtitles", type=Path, help="sceneNN.mp3 があるフォルダのパス")
    input_group.add_argument("--generate-video", type=Path, help="シーン素材があるフォルダのパス")
    input_group.add_argument("--generate-metadata", type=Path, help="完成動画とscript.txtがあるフォルダのパス")
    input_group.add_argument("--generate-thumbnail", type=Path, help="script.txtがあるフォルダのパス")
    parser.add_argument("--template", default="default", help="テンプレートID（既定: default）")
    parser.add_argument("--topic", help="メタデータ生成に使用する動画テーマ")
    parser.add_argument("--list-templates", action="store_true", help="利用可能なテンプレートを表示して終了")
    parser.add_argument("--script", help="品質チェックする台本文。API生成後は生成台本を渡す想定です。")
    parser.add_argument(
        "--force", action="store_true",
        help=(
            "キャッシュ・既存ファイルを無視して強制的に再生成します"
            "（--generate-video/--generate-scene-descriptions/--generate-images/"
            "--edit-imagesで使用）。"
        ),
    )
    parser.add_argument("--version", action="version", version="Youtube AI Automation 0.1.0")
    parser.add_argument("--run-id", help=argparse.SUPPRESS)
    return parser


def run() -> None:
    """アプリケーションを起動し、将来の生成フローの入口を提供する。"""
    if len(sys.argv) > 1 and sys.argv[1] == "ending":
        run_ending(sys.argv[2:])
        return
    if len(sys.argv) > 1 and sys.argv[1] == "bgm":
        run_bgm(sys.argv[2:])
        return
    if len(sys.argv) > 1 and sys.argv[1] == "render":
        run_render(sys.argv[2:])
        return
    if len(sys.argv) > 1 and sys.argv[1] == "image":
        run_image(sys.argv[2:])
        return
    args = create_parser().parse_args()

    try:
        settings = load_settings()
    except (OSError, ValidationError) as error:
        print(f"設定の読み込みに失敗しました: {error}", file=sys.stderr)
        raise SystemExit(1) from error

    configure_logging(settings.log_level, settings.log_dir)
    logger = get_logger(__name__)

    templates = TemplateManager(settings.templates_dir)
    if args.list_templates:
        for template in templates.list():
            print(f"{template.template_id}: {template.display_name}")
        return

    run_id = args.run_id or uuid4().hex
    history = RunHistoryRecorder(settings.history_file)
    execution_logger = Logger(run_id, settings.output_dir)
    execution_logger.start(args.theme)
    set_active_logger(execution_logger)
    history.record(run_id, "run_started", theme=args.theme, template_id=args.template)

    try:
        template = templates.get(args.template)
        video_settings = load_video_settings(settings.config_dir / "config.yaml")
        provider_settings = video_settings.values["providers"]
        text_settings = video_settings.values["text"]
        if not isinstance(provider_settings, dict):
            raise ValueError("config.yaml の providers 設定が不正です。")
        if not isinstance(text_settings, dict):
            raise ValueError("config.yaml の text 設定が不正です。")
        plugin_manager = PluginManager(settings, provider_settings, text_settings)
        cache_settings = video_settings.values["cache"]
        if not isinstance(cache_settings, dict):
            raise ValueError("config.yaml の cache 設定が不正です。")
        cache_enabled = bool(cache_settings["enabled"])
        cache_manager = CacheManager(settings.cache_dir) if cache_enabled else None
        if cache_manager is not None:
            removed_count = cache_manager.remove_expired(int(cache_settings["expiration_days"]))
            if removed_count:
                logger.info("期限切れキャッシュを %d 件削除しました。", removed_count)
        logger.info("%s を起動しました。実行ID: %s", settings.app_name, run_id)
        logger.info("テンプレート: %s (%s)", template.display_name, template.template_id)
        logger.info(
            "title_prompt読み込み成功: template=%s, hash=%s",
            template.template_id,
            hashlib.sha256(template.title_instruction.encode("utf-8")).hexdigest(),
        )
        logger.info("出力先: %s", settings.output_dir)
        logger.info("動画設定: %sx%s / %sfps", video_settings.values["video"]["width"], video_settings.values["video"]["height"], video_settings.values["video"]["fps"])
        if args.theme:
            logger.info("受け取ったテーマ: %s", args.theme)
            if settings.openai_api_key is None:
                raise ValueError("OPENAI_API_KEY が未設定です。.env に設定してください。")
        if args.split_script:
            logger.info("分割対象の台本: %s", args.split_script)
            if settings.openai_api_key is None:
                raise ValueError("OPENAI_API_KEY が未設定です。.env に設定してください。")
        if args.generate_audio:
            logger.info("音声化対象のフォルダ: %s", args.generate_audio)
            if settings.openai_api_key is None:
                raise ValueError("OPENAI_API_KEY が未設定です。.env に設定してください。")
        if args.generate_scene_descriptions:
            logger.info("場面説明生成対象のフォルダ: %s", args.generate_scene_descriptions)
        if args.generate_images:
            logger.info("画像化対象のフォルダ: %s", args.generate_images)
        if args.edit_images:
            logger.info("画像編集対象のフォルダ: %s", args.edit_images)
        if args.generate_subtitles:
            logger.info("字幕生成対象のフォルダ: %s", args.generate_subtitles)
        if args.generate_video:
            logger.info("動画生成対象のフォルダ: %s", args.generate_video)
        if args.generate_metadata:
            logger.info("メタデータ生成対象のフォルダ: %s", args.generate_metadata)
            if settings.openai_api_key is None:
                raise ValueError("OPENAI_API_KEY が未設定です。.env に設定してください。")
        if args.generate_thumbnail:
            logger.info("サムネイル生成対象のフォルダ: %s", args.generate_thumbnail)

        if args.generate_thumbnail:
            retry_settings = video_settings.values["retry"]
            image_settings = video_settings.values["image"]
            if not isinstance(retry_settings, dict) or not isinstance(image_settings, dict):
                raise ValueError("config.yaml の retry または image 設定が不正です。")
            image_generator = plugin_manager.create_image_provider(
                image_settings, RetryPolicy.from_settings(retry_settings),
                size_setting="thumbnail_size",
            )
            thumbnail_file = GenerateThumbnailUseCase(
                image_generator, template.thumbnail_instruction_for(plugin_manager.image_provider_name("thumbnail"))
            ).execute(args.generate_thumbnail)
            release_image_generator = getattr(image_generator, "release", None)
            if callable(release_image_generator):
                release_image_generator()
            logger.info("サムネイル画像を保存しました: %s", thumbnail_file)
            history.record(run_id, "thumbnail_generated", thumbnail_file=str(thumbnail_file))
            history.record(run_id, "run_completed")
            execution_logger.add_generated_file(thumbnail_file)
            execution_logger.finish(success=True)
            set_active_logger(None)
            return

        if args.generate_metadata:
            retry_settings = video_settings.values["retry"]
            if not isinstance(retry_settings, dict):
                raise ValueError("config.yaml の retry 設定が不正です。")
            metadata_settings = video_settings.values["metadata"]
            if not isinstance(metadata_settings, dict):
                raise ValueError("config.yaml の metadata 設定が不正です。")
            generator = plugin_manager.create_metadata_generator(
                RetryPolicy.from_settings(retry_settings),
                title_count=int(metadata_settings["title_count"]),
            )
            topic = (args.topic or "").strip()
            if not topic:
                logger.warning("動画テーマが未指定のため、タイトル生成でテーマを「未指定」として扱います。")
            title_prompt = template.title_instruction
            use_case = GenerateMetadataUseCase(generator)
            # fingerprintはタイトル・詳細情報の両方に影響するtext設定、title_fingerprintは
            # タイトル生成のみに影響するmetadata設定（title_count等）に限定する。
            metadata_fingerprint = CacheManager.make_key(
                str(provider_settings.get("text")),
                json.dumps(text_settings, ensure_ascii=False, sort_keys=True),
            )
            title_fingerprint = json.dumps(metadata_settings, ensure_ascii=False, sort_keys=True)
            cache_result = use_case.execute_cached(
                args.generate_metadata, cache_manager,
                fingerprint=metadata_fingerprint, title_fingerprint=title_fingerprint, topic=topic,
                template_id=template.template_id, template_name=template.display_name,
                title_prompt=title_prompt,
            )
            logger.info(
                "タイトルキャッシュキー: %s (title_prompt_hash=%s)",
                cache_result.titles_cache_key, cache_result.title_prompt_hash,
            )
            if cache_result.titles_cache_hit:
                logger.info("タイトルをキャッシュから復元しました。")
                history.record(
                    run_id, "cache_hit", artifact="metadata_titles",
                    cache_key=cache_result.titles_cache_key,
                )
            if cache_result.details_cache_hit:
                logger.info("タイトル以外のメタデータをキャッシュから復元しました。")
                history.record(
                    run_id, "cache_hit", artifact="metadata_details",
                    cache_key=cache_result.details_cache_key,
                )
            metadata_files = cache_result.files
            logger.info("%d件のメタデータファイルを保存しました。", len(metadata_files))
            history.record(run_id, "metadata_generated", file_count=len(metadata_files))
            history.record(run_id, "run_completed")
            for file_path in metadata_files:
                execution_logger.add_generated_file(file_path)
            execution_logger.finish(success=True)
            set_active_logger(None)
            return

        if args.generate_video:
            video_values = video_settings.values["video"]
            bgm_values = video_settings.values["bgm"]
            image_values = video_settings.values["image"]
            global_subtitle_values = video_settings.values["subtitles"]
            quality_values = video_settings.values["quality"]
            if not isinstance(video_values, dict) or not isinstance(bgm_values, dict):
                raise ValueError("config.yaml の video または bgm 設定が不正です。")
            if not isinstance(image_values, dict):
                raise ValueError("config.yaml の image 設定が不正です。")
            if not isinstance(global_subtitle_values, dict):
                raise ValueError("config.yaml の subtitles 設定が不正です。")
            subtitle_values = templates.subtitle_settings(
                global_subtitle_values, template.template_id,
            )
            if not isinstance(quality_values, dict):
                raise ValueError("config.yaml の quality 設定が不正です。")
            ending_values = video_settings.values.get("ending", {})
            ending_auto_append_enabled = (
                isinstance(ending_values, dict)
                and bool(ending_values.get("enabled", True))
                and bool(ending_values.get("auto_append", True))
            )
            # エンディングを結合しない場合、最後のシーンを延長する意味がないため間隔は0秒とする。
            main_gap_seconds = float(ending_values.get("gap_seconds", 1.0)) if ending_auto_append_enabled else 0.0
            duration_provider = FfprobeAudioDurationProvider(settings.ffprobe_executable)
            quality_checker = QualityChecker(
                load_quality_rules(quality_values), duration_provider
            )
            expected_scene_size = _parse_image_size(str(image_values.get("scene_size", "")))
            scene_provider_name = plugin_manager.image_provider_name("scene")
            quality_report = quality_checker.check_project(
                args.generate_video,
                ImagePromptBuilder(template.image_style_for(scene_provider_name), scene_provider_name),
                expected_scene_size=expected_scene_size,
            )
            if quality_report.has_errors and settings.openai_api_key is not None:
                retry_settings = video_settings.values["retry"]
                if not isinstance(retry_settings, dict):
                    raise ValueError("config.yaml の retry 設定が不正です。")
                try:
                    improvements = OpenAIQualityAdvisor(
                        settings.openai_api_key.get_secret_value(), str(text_settings["script_model"]),
                        RetryPolicy.from_settings(retry_settings),
                    ).generate(quality_report)
                    quality_report = replace(quality_report, improvements=improvements)
                except OpenAIError:
                    logger.exception("GPTによる品質改善案を生成できませんでした。")
            quality_files = quality_checker.save_report(quality_report, args.generate_video)
            for quality_file in quality_files:
                execution_logger.add_generated_file(quality_file)
            for check in quality_report.checks:
                logger.info("品質 [%s] %s: %s", check.severity.value.upper(), check.check_name, check.message)
            if quality_report.has_errors:
                raise RuntimeError("品質チェックで重大なERRORを検出したため、動画生成を停止しました。")
            bgm_manager = BGMManager(templates, bgm_values, settings.config_dir.parent)
            render_mode = bgm_manager.render_mode(template)
            bgm_setting = bgm_manager.resolve(template, "main")
            if render_mode == "final_mix":
                bgm_setting = replace(bgm_setting, enabled=False)
            logger.info(
                "BGM適用: template=%s, file=%s, source=%s, volume=%s, loop=%s, fade_in=%s, fade_out=%s",
                template.template_id, bgm_setting.file, bgm_setting.source, bgm_setting.volume,
                bgm_setting.loop, bgm_setting.fade_in, bgm_setting.fade_out,
            )
            renderer = FfmpegVideoRenderer(
                duration_provider=duration_provider,
                settings=VideoRenderSettings(
                    width=int(video_values["width"]), height=int(video_values["height"]), fps=int(video_values["fps"]),
                    bgm_enabled=bgm_setting.enabled, bgm_file=bgm_setting.file or settings.config_dir.parent / "assets" / "bgm.mp3",
                    bgm_volume=bgm_setting.volume, bgm_loop=bgm_setting.loop,
                    bgm_fade_in=bgm_setting.fade_in, bgm_fade_out=bgm_setting.fade_out,
                    gap_seconds=main_gap_seconds,
                    subtitle_font=str(subtitle_values["font"]), subtitle_size=int(subtitle_values["size"]),
                    subtitle_color=str(subtitle_values["color"]),
                    subtitle_position=str(subtitle_values.get("position", "bottom")),
                    subtitle_alignment=str(subtitle_values.get("alignment", "center")),
                    subtitle_bottom_margin=int(subtitle_values.get("bottom_margin", 80)),
                    subtitle_box_enabled=bool(subtitle_values.get("box_enabled", False)),
                    subtitle_background_color=str(
                        subtitle_values.get("background_color", "&H00000000")
                    ),
                    subtitle_background_opacity=float(
                        subtitle_values.get("background_opacity", 0.6)
                    ),
                ),
                alignment_provider=JsonSubtitleAlignmentProvider(),
            )
            video_inputs = (
                tuple(sorted(args.generate_video.glob("scene*.png")))
                + tuple(sorted(args.generate_video.glob("scene*.mp3")))
                + tuple(sorted(args.generate_video.glob("subtitles.srt")))
            )
            # bgm_setting.cache_fingerprintはBGMファイル内容のハッシュを既に含むため、
            # video_inputs側でBGMファイルを重複してハッシュする必要はない。
            video_fingerprint = CacheManager.make_key(
                json.dumps({
                    "width": video_values["width"], "height": video_values["height"],
                    "fps": video_values["fps"], "output_format": video_values["output_format"],
                    "gap_seconds": main_gap_seconds,
                }, sort_keys=True),
                json.dumps(subtitle_values, ensure_ascii=False, sort_keys=True),
                bgm_setting.cache_fingerprint,
            )
            video_cache_key = CacheManager.make_file_key("video", video_inputs, video_fingerprint)
            if not args.force and cache_manager is not None and cache_manager.exists(video_cache_key, "video"):
                video_file = cache_manager.restore_files(video_cache_key, "video", args.generate_video)[0]
                logger.info("動画をキャッシュから復元しました。")
                history.record(run_id, "cache_hit", artifact="video", cache_key=video_cache_key)
            else:
                video_file = GenerateVideoUseCase(renderer).execute(args.generate_video, str(video_values["output_format"]))
                if cache_manager is not None:
                    cache_manager.save_files(video_cache_key, "video", (video_file,))
            if ending_auto_append_enabled:
                main_file = args.generate_video / "main.mp4"
                ending_file = args.generate_video / "ending.mp4"
                final_file = args.generate_video / "final.mp4"
                shutil.copy2(video_file, main_file)
                ending_manager = create_ending_manager()
                ending_asset = ending_manager.ensure(template.template_id)
                if ending_asset is not None:
                    shutil.copy2(ending_asset.video_file, ending_file)
                    if render_mode == "final_mix":
                        final_bgm = bgm_manager.resolve(template, "final")
                        video_file = FinalBGMRenderer(
                            FinalRenderSettings(
                                width=int(video_values["width"]), height=int(video_values["height"]), fps=int(video_values["fps"]),
                                keep_intermediate=bool(video_settings.values.get("final_render", {}).get("keep_intermediate", True)),
                            ), cache_manager, ffprobe_executable=settings.ffprobe_executable,
                        ).render(main_file, ending_file, args.generate_video, final_bgm)
                    else:
                        video_file = ending_manager.append_to(main_file, template.template_id, final_file)
            logger.info("MP4動画を保存しました: %s", video_file)
            history.record(run_id, "video_generated", video_file=str(video_file))
            history.record(run_id, "run_completed")
            execution_logger.add_generated_file(video_file)
            execution_logger.finish(success=True)
            set_active_logger(None)
            return

        if args.generate_subtitles:
            global_subtitle_values = video_settings.values["subtitles"]
            if not isinstance(global_subtitle_values, dict):
                raise ValueError("config.yaml の subtitles 設定が不正です。")
            subtitle_values = templates.subtitle_settings(
                global_subtitle_values, template.template_id,
            )
            logger.info(
                "テンプレート別字幕設定: template=%s, font=%s, size=%s, "
                "segmentation_mode=%s, timing_mode=%s",
                template.template_id, subtitle_values.get("font"),
                subtitle_values.get("size"), subtitle_values.get("segmentation_mode"),
                subtitle_values.get("timing_mode"),
            )
            subtitle_inputs = (
                tuple(sorted(args.generate_subtitles.glob("scene*.mp3")))
                + tuple(sorted(args.generate_subtitles.glob("scene*.txt")))
                + tuple(sorted(args.generate_subtitles.glob("scene*.alignment.json")))
            )
            subtitle_fingerprint = CacheManager.make_key(
                json.dumps(subtitle_values, ensure_ascii=False, sort_keys=True),
                SUBTITLE_SPLITTER_VERSION,
            )
            subtitle_cache_key = CacheManager.make_file_key(
                "subtitle", subtitle_inputs, subtitle_fingerprint,
            )
            if cache_manager is not None and cache_manager.exists(subtitle_cache_key, "subtitle"):
                subtitle_file = cache_manager.restore_files(
                    subtitle_cache_key, "subtitle", args.generate_subtitles
                )[0]
                logger.info("字幕をキャッシュから復元しました。")
                history.record(run_id, "cache_hit", artifact="subtitle", cache_key=subtitle_cache_key)
            else:
                subtitle_file = GenerateSubtitlesUseCase(
                    FfprobeAudioDurationProvider(settings.ffprobe_executable),
                    SrtBuilder(),
                    SubtitleSplitter(SubtitleSettings(
                        segmentation_mode=str(subtitle_values.get("segmentation_mode", "scene")),
                        max_lines=int(subtitle_values.get("max_lines", 2)),
                        max_chars_per_line=int(subtitle_values.get("max_chars_per_line", 20)),
                        min_chars_per_segment=int(subtitle_values.get("min_chars_per_segment", 6)),
                    )),
                    timing_mode=str(subtitle_values.get("timing_mode", "character_ratio")),
                ).execute(args.generate_subtitles)
                if cache_manager is not None:
                    cache_manager.save_files(subtitle_cache_key, "subtitle", (subtitle_file,))
            logger.info("SRT字幕を保存しました: %s", subtitle_file)
            history.record(run_id, "subtitles_generated", subtitle_file=str(subtitle_file))
            history.record(run_id, "run_completed")
            execution_logger.add_generated_file(subtitle_file)
            execution_logger.finish(success=True)
            set_active_logger(None)
            return

        if args.split_script:
            retry_settings = video_settings.values["retry"]
            if not isinstance(retry_settings, dict):
                raise ValueError("config.yaml の retry 設定が不正です。")
            scene_settings = video_settings.values["scenes"]
            if not isinstance(scene_settings, dict):
                raise ValueError("config.yaml の scenes 設定が不正です。")
            splitter = plugin_manager.create_scene_splitter(
                RetryPolicy.from_settings(retry_settings),
                max_scenes=int(scene_settings["max_count"]),
            )
            scene_fingerprint = CacheManager.make_key(
                str(provider_settings.get("text")),
                json.dumps(text_settings, ensure_ascii=False, sort_keys=True),
                json.dumps(scene_settings, ensure_ascii=False, sort_keys=True),
            )
            scene_cache_key = CacheManager.make_file_key("scene", (args.split_script,), scene_fingerprint)
            if cache_manager is not None and cache_manager.exists(scene_cache_key, "scene"):
                scene_files = cache_manager.restore_files(scene_cache_key, "scene", args.split_script.parent)
                logger.info("シーンをキャッシュから復元しました。")
                history.record(run_id, "cache_hit", artifact="scene", cache_key=scene_cache_key)
            else:
                scene_files = SplitScriptUseCase(splitter).execute(args.split_script)
                if cache_manager is not None:
                    cache_manager.save_files(scene_cache_key, "scene", scene_files)
            logger.info("台本を%dシーンに分割しました。", len(scene_files))
            history.record(run_id, "script_split", scene_count=len(scene_files))
            history.record(run_id, "run_completed")
            for file_path in scene_files:
                execution_logger.add_generated_file(file_path)
            execution_logger.finish(success=True)
            set_active_logger(None)
            return

        if args.generate_audio:
            retry_settings = video_settings.values["retry"]
            audio_settings = video_settings.values["audio"]
            if not isinstance(retry_settings, dict) or not isinstance(audio_settings, dict):
                raise ValueError("config.yaml の retry または audio 設定が不正です。")
            if str(provider_settings.get("tts", "")).lower() == "voicevox":
                audio_settings = templates.voicevox_audio_settings(
                    audio_settings, template.template_id,
                )
                voicevox_settings = audio_settings["voicevox"]
                logger.info(
                    "テンプレート別VOICEVOX設定: template=%s, speaker_id=%s, "
                    "speed_scale=%s, pitch_scale=%s, intonation_scale=%s, volume_scale=%s",
                    template.template_id, voicevox_settings.get("speaker_id", 3),
                    voicevox_settings.get("speed_scale", 1.0),
                    voicevox_settings.get("pitch_scale", 0.0),
                    voicevox_settings.get("intonation_scale", 1.0),
                    voicevox_settings.get("volume_scale", 1.0),
                )
            synthesizer = plugin_manager.create_tts_provider(
                audio_settings, RetryPolicy.from_settings(retry_settings)
            )
            audio_inputs = tuple(sorted(args.generate_audio.glob("scene*.txt")))
            audio_fingerprint = CacheManager.make_key(
                str(provider_settings.get("tts")),
                json.dumps(audio_settings, ensure_ascii=False, sort_keys=True),
            )
            audio_cache_key = CacheManager.make_file_key(
                "voice", audio_inputs, audio_fingerprint,
            )
            if cache_manager is not None and cache_manager.exists(audio_cache_key, "voice"):
                audio_files = cache_manager.restore_files(audio_cache_key, "voice", args.generate_audio)
                logger.info("音声をキャッシュから復元しました。")
                history.record(run_id, "cache_hit", artifact="voice", cache_key=audio_cache_key)
            else:
                audio_files = GenerateSceneAudioUseCase(synthesizer).execute(args.generate_audio)
                if cache_manager is not None:
                    cache_manager.save_files(audio_cache_key, "voice", audio_files)
            logger.info("%d件のMP3ファイルを生成しました。", len(audio_files))
            history.record(run_id, "scene_audio_generated", audio_count=len(audio_files))

            global_subtitle_values = video_settings.values["subtitles"]
            if not isinstance(global_subtitle_values, dict):
                raise ValueError("config.yaml の subtitles 設定が不正です。")
            subtitle_values = templates.subtitle_settings(global_subtitle_values, template.template_id)
            if str(subtitle_values.get("timing_mode", "character_ratio")) == "alignment":
                alignment_provider_settings = subtitle_values.get("alignment_provider", {})
                if not isinstance(alignment_provider_settings, dict):
                    raise ValueError("config.yaml の subtitles.alignment_provider 設定が不正です。")
                scene_text_files = tuple(sorted(args.generate_audio.glob("scene*.txt")))
                alignment_fingerprint = CacheManager.make_key(
                    str(alignment_provider_settings.get("provider", "stable_ts")),
                    str(alignment_provider_settings.get("model", "base")),
                    str(alignment_provider_settings.get("language", "ja")),
                )
                alignment_cache_key = CacheManager.make_file_key(
                    "alignment", audio_files + scene_text_files, alignment_fingerprint,
                )
                if cache_manager is not None and cache_manager.exists(alignment_cache_key, "alignment"):
                    cache_manager.restore_files(alignment_cache_key, "alignment", args.generate_audio)
                    logger.info("アライメント結果をキャッシュから復元しました。")
                    history.record(run_id, "cache_hit", artifact="alignment", cache_key=alignment_cache_key)
                else:
                    alignment_provider = create_alignment_provider(alignment_provider_settings)
                    alignment_files: list[Path] = []
                    for audio_file in audio_files:
                        script_text = audio_file.with_suffix(".txt").read_text(encoding="utf-8")
                        alignment_file = audio_file.with_suffix(".alignment.json")
                        try:
                            alignment_provider.align(audio_file, script_text, alignment_file)
                            alignment_files.append(alignment_file)
                        except AlignmentGenerationError:
                            logger.exception(
                                "アライメント生成に失敗したため、該当シーンはcharacter_ratioへ"
                                "フォールバックします: %s",
                                audio_file,
                            )
                    if alignment_files and cache_manager is not None:
                        cache_manager.save_files(alignment_cache_key, "alignment", tuple(alignment_files))
                    history.record(run_id, "alignment_generated", alignment_count=len(alignment_files))
                    for file_path in alignment_files:
                        execution_logger.add_generated_file(file_path)

            history.record(run_id, "run_completed")
            for file_path in audio_files:
                execution_logger.add_generated_file(file_path)
            execution_logger.finish(success=True)
            set_active_logger(None)
            return

        if args.generate_scene_descriptions:
            retry_settings = video_settings.values["retry"]
            image_settings = video_settings.values["image"]
            quality_values = video_settings.values["quality"]
            if not isinstance(retry_settings, dict) or not isinstance(image_settings, dict):
                raise ValueError("config.yaml の retry または image 設定が不正です。")
            if not isinstance(quality_values, dict):
                raise ValueError("config.yaml の quality 設定が不正です。")
            scene_visual_describer = plugin_manager.create_scene_visual_describer(
                image_settings, RetryPolicy.from_settings(retry_settings),
            )
            # --generate-imagesと異なりCachingSceneVisualDescriberでは包まない。この工程自体が
            # sceneNN_MM.description.txt単位のキャッシュ層であり、--forceはOpenAI APIへの
            # 再呼び出しを保証する必要があるため（内側にコンテンツハッシュキャッシュを挟むと
            # --force指定時でも同じナレーション文からの再呼び出しがキャッシュヒットしてしまう）。
            use_case = GenerateSceneDescriptionsUseCase(
                scene_visual_describer,
                min_display_seconds=float(image_settings.get("min_display_seconds", 5.0)),
                max_display_seconds=float(image_settings.get("max_display_seconds", 10.0)),
                characters_per_second=float(quality_values["characters_per_second"]),
                max_images=int(image_settings["max_count"]),
            )
            description_files = use_case.execute(args.generate_scene_descriptions, force=args.force)
            logger.info("%d件の場面説明ファイルを生成しました。", len(description_files))
            history.record(
                run_id, "scene_descriptions_generated", description_count=len(description_files),
            )
            history.record(run_id, "run_completed")
            for file_path in description_files:
                execution_logger.add_generated_file(file_path)
            execution_logger.finish(success=True)
            set_active_logger(None)
            return

        if args.generate_images:
            retry_settings = video_settings.values["retry"]
            image_settings = video_settings.values["image"]
            quality_values = video_settings.values["quality"]
            if not isinstance(retry_settings, dict) or not isinstance(image_settings, dict):
                raise ValueError("config.yaml の retry または image 設定が不正です。")
            if not isinstance(quality_values, dict):
                raise ValueError("config.yaml の quality 設定が不正です。")
            retry_policy = RetryPolicy.from_settings(retry_settings)
            image_generator = plugin_manager.create_image_provider(image_settings, retry_policy)
            scene_visual_describer = plugin_manager.create_scene_visual_describer(
                image_settings, retry_policy,
            )
            # scene_description.modelがnullの場合はtext.scene_split_modelへフォールバックするため
            # （create_scene_visual_describer参照）、実際に使用されるモデル名を明示的に含める。
            scene_description_enabled = scene_visual_describer is not None
            scene_description_model = (
                str(image_settings.get("scene_description", {}).get("model") or text_settings.get("scene_split_model"))
                if scene_description_enabled else ""
            )
            if scene_visual_describer is not None and cache_manager is not None:
                # シーン画像自体のキャッシュ（image_cache_key）は画像生成側の設定変更でも
                # 無効化されるが、場面説明（OpenAI API呼び出し・追加課金あり）はナレーション文と
                # scene_description設定が変わらない限り再実行不要なため、独立してキャッシュする。
                # これにより「画像生成の設定だけを変えて--generate-imagesを再実行する」場面でも、
                # 不要なAPI呼び出しが発生しなくなる。
                description_fingerprint = CacheManager.make_key(
                    "scene-description-cache-v1", scene_description_model,
                )
                scene_visual_describer = CachingSceneVisualDescriber(
                    scene_visual_describer, cache_manager, description_fingerprint,
                )
            scene_provider_name = plugin_manager.image_provider_name("scene")
            image_style = template.image_style_for(scene_provider_name) or str(image_settings["style"])
            use_case = GenerateSceneImagesUseCase(
                ImagePromptBuilder(image_style, scene_provider_name),
                image_generator,
                min_display_seconds=float(image_settings.get("min_display_seconds", 5.0)),
                max_display_seconds=float(image_settings.get("max_display_seconds", 10.0)),
                characters_per_second=float(quality_values["characters_per_second"]),
                max_images=int(image_settings["max_count"]),
                scene_visual_describer=scene_visual_describer,
            )
            image_inputs = tuple(sorted(args.generate_images.glob("scene*.txt")))
            # thumbnail_model/thumbnail_sizeはシーン画像に影響しないため、
            # サムネイル専用設定の変更でシーン画像キャッシュを無効化しないようfingerprintから除外する。
            # scene_editは--edit-images側の独立した工程・キャッシュが担うため、生成キャッシュには含めない。
            scene_image_settings = {
                key: value for key, value in image_settings.items()
                if key not in {"thumbnail_model", "thumbnail_size", "scene_edit"}
            }
            image_fingerprint = CacheManager.make_key(
                scene_provider_name,
                json.dumps(scene_image_settings, ensure_ascii=False, sort_keys=True),
                "image-prompt-v4", image_style,
                str(quality_values["characters_per_second"]),
                "scene-description", str(scene_description_enabled), scene_description_model,
            )
            image_cache_key = CacheManager.make_file_key("image", image_inputs, image_fingerprint)
            # --edit-imagesが同じ生成結果に対して再現性のある編集キャッシュキーを組み立てられるよう、
            # 生成キャッシュキーをsidecarファイルへ書き出す（scene*.pngの内容は編集で書き換わるため、
            # png自体のハッシュを編集キャッシュキーの元にすると再実行時に二重編集してしまう）。
            (args.generate_images / _IMAGE_CACHE_KEY_SIDECAR).write_text(image_cache_key, encoding="utf-8")
            existing_scene_images = tuple(args.generate_images.glob("scene*.png"))
            if args.force:
                # --force指定時は既存ファイル・キャッシュの有無を無視し、常に全件生成し直す。
                image_files = use_case.execute(args.generate_images, force=True)
                if cache_manager is not None:
                    cache_manager.save_files(image_cache_key, "image", image_files)
            elif existing_scene_images:
                # 中断されたジョブの再試行などでこのフォルダに一部の画像が既に生成・編集済みの
                # 場合、キャッシュから復元すると編集済みの内容が生成直後の状態で上書きされて
                # しまうため復元は行わず、既存ファイルを活かして未生成分のみ生成する
                # （未生成分の判定はGenerateSceneImagesUseCase.executeの存在チェックに委ねる）。
                image_files = use_case.execute(args.generate_images)
                # 過去に完了済みバッチのキャッシュが既にある場合、ここでの再保存は編集済み
                # 内容で「生成直後」キャッシュを汚染しうるため、未キャッシュ時のみ保存する。
                if cache_manager is not None and not cache_manager.exists(image_cache_key, "image"):
                    cache_manager.save_files(image_cache_key, "image", image_files)
            elif cache_manager is not None and cache_manager.exists(image_cache_key, "image"):
                image_files = cache_manager.restore_files(image_cache_key, "image", args.generate_images)
                logger.info("画像をキャッシュから復元しました。")
                history.record(run_id, "cache_hit", artifact="image", cache_key=image_cache_key)
            else:
                image_files = use_case.execute(args.generate_images)
                if cache_manager is not None:
                    cache_manager.save_files(image_cache_key, "image", image_files)
            release_image_generator = getattr(image_generator, "release", None)
            if callable(release_image_generator):
                release_image_generator()
            logger.info("%d件のPNGファイルを生成しました。", len(image_files))
            history.record(run_id, "scene_images_generated", image_count=len(image_files))
            history.record(run_id, "run_completed")
            for file_path in image_files:
                execution_logger.add_generated_file(file_path)
            execution_logger.finish(success=True)
            set_active_logger(None)
            return

        if args.edit_images:
            retry_settings = video_settings.values["retry"]
            image_settings = video_settings.values["image"]
            if not isinstance(retry_settings, dict) or not isinstance(image_settings, dict):
                raise ValueError("config.yaml の retry または image 設定が不正です。")
            retry_policy = RetryPolicy.from_settings(retry_settings)
            scene_edit_settings = image_settings.get("scene_edit", {})
            if not isinstance(scene_edit_settings, dict):
                raise ValueError("config.yaml の image.scene_edit 設定が不正です。")
            edit_provider_name = str(scene_edit_settings.get("provider", "qwen_image_edit_nunchaku_local")).lower()
            if edit_provider_name == "qwen_image_edit_nunchaku_local":
                # テンプレート単位でreference_image・prompt等を上書きできるようにする
                # （templates/<template>/video.yamlのimage.qwen_image_edit_nunchaku_local）。
                image_settings = {
                    **image_settings,
                    "qwen_image_edit_nunchaku_local": templates.image_edit_settings(
                        image_settings, args.template,
                    ),
                }
            image_editor = plugin_manager.create_image_editor(image_settings, retry_policy)
            if image_editor is None:
                logger.info("image.scene_edit.enabled が false のため画像編集をスキップします。")
                history.record(run_id, "run_completed")
                execution_logger.finish(success=True)
                set_active_logger(None)
                return

            image_files = tuple(sorted(args.edit_images.glob("scene*.png")))
            if not image_files:
                raise FileNotFoundError(f"scene*.png が見つかりません: {args.edit_images}")

            edit_provider_settings = image_settings.get(edit_provider_name, {})
            edit_fingerprint = CacheManager.make_key(
                edit_provider_name,
                json.dumps(scene_edit_settings, ensure_ascii=False, sort_keys=True),
                json.dumps(edit_provider_settings, ensure_ascii=False, sort_keys=True),
                "image-edit-v1",
            )
            # 生成キャッシュキー（--generate-imagesが書き出したsidecar）と編集設定から編集キャッシュ
            # キーを求める。scene*.png自体の内容は編集によって書き換わるため、その内容をハッシュ元に
            # すると再実行時に既に編集済みの画像を再度編集してしまう（二重編集）。生成キャッシュキーは
            # 編集で変化しない安定した値のため、これを使うことで再実行時も同じキーを再利用できる。
            sidecar_file = args.edit_images / _IMAGE_CACHE_KEY_SIDECAR
            generation_cache_key = sidecar_file.read_text(encoding="utf-8").strip() if sidecar_file.is_file() else None
            edit_cache_key = (
                CacheManager.make_key(generation_cache_key, edit_fingerprint)
                if generation_cache_key else None
            )

            # 生成キャッシュキーが得られない場合（sidecar未生成等）でも、編集設定単体の
            # フィンガープリントを再開判定に使えるようフォールバックする。
            resume_key = edit_cache_key or edit_fingerprint

            if (
                not args.force and edit_cache_key is not None and cache_manager is not None
                and cache_manager.exists(edit_cache_key, "image_edited")
            ):
                image_files = cache_manager.restore_files(edit_cache_key, "image_edited", args.edit_images)
                logger.info("編集済み画像をキャッシュから復元しました。")
                history.record(run_id, "cache_hit", artifact="image_edited", cache_key=edit_cache_key)
            else:
                total = len(image_files)
                # 中断されたジョブの再試行等で一部の画像が同じ編集設定で既に編集済みの場合、
                # 二重編集（破壊的処理のため画質劣化を招く）を避けるためスキップする。
                # --force指定時はこの判定を無視し、常に全件編集し直す。
                pending_files = image_files if args.force else [
                    image_file for image_file in image_files
                    if not _is_already_edited(image_file, resume_key)
                ]
                skipped = total - len(pending_files)
                if skipped:
                    logger.info("編集済みの画像 %d/%d 件をスキップします。", skipped, total)
                for progress, image_file in enumerate(pending_files, 1):
                    image_editor.edit(image_file)
                    _mark_edited(image_file, resume_key)
                    logger.info("画像編集: (%d/%d)", skipped + progress, total)
                if edit_cache_key is not None and cache_manager is not None:
                    cache_manager.save_files(edit_cache_key, "image_edited", image_files)

            release_image_editor = getattr(image_editor, "release", None)
            if callable(release_image_editor):
                release_image_editor()
            logger.info("%d件のPNGファイルを編集しました。", len(image_files))
            history.record(run_id, "scene_images_edited", image_count=len(image_files))
            history.record(run_id, "run_completed")
            for file_path in image_files:
                execution_logger.add_generated_file(file_path)
            execution_logger.finish(success=True)
            set_active_logger(None)
            return

        if args.script:
            quality_values = video_settings.values["quality"]
            if not isinstance(quality_values, dict):
                raise ValueError("config.yaml の quality 設定が不正です。")
            checker = ScriptQualityChecker(load_quality_rules(quality_values))
            report = checker.check(args.script)
            logger.info("品質チェック: %s文字 / 想定%.1f秒 / 指摘%d件", report.character_count, report.estimated_duration_seconds, len(report.issues))
            for issue in report.issues:
                logger.warning("[%s] %s", issue.severity, issue.message)
            history.record(run_id, "quality_checked", acceptable=report.is_acceptable, issue_count=len(report.issues))

        if args.theme:
            retry_settings = video_settings.values["retry"]
            if not isinstance(retry_settings, dict):
                raise ValueError("config.yaml の retry 設定が不正です。")
            generator = plugin_manager.create_text_generator(RetryPolicy.from_settings(retry_settings))
            script_cache_key = CacheManager.make_key(
                "script", args.theme, template.template_id,
                str(provider_settings.get("text")),
                json.dumps(text_settings, ensure_ascii=False, sort_keys=True),
            )
            script_output_dir = GenerateScriptUseCase.output_directory(
                settings.output_dir, args.theme, template, run_id
            )
            if cache_manager is not None and cache_manager.exists(script_cache_key, "script"):
                script_file = cache_manager.restore_files(script_cache_key, "script", script_output_dir)[0]
                logger.info("台本をキャッシュから復元しました。")
                history.record(run_id, "cache_hit", artifact="script", cache_key=script_cache_key)
            else:
                script_file = GenerateScriptUseCase(generator, settings.output_dir).execute(
                    args.theme,
                    template,
                    run_id,
                )
                if cache_manager is not None:
                    cache_manager.save_files(script_cache_key, "script", (script_file,))
            logger.info("台本を保存しました: %s", script_file)
            history.record(run_id, "script_generated", script_file=str(script_file))
            execution_logger.add_generated_file(script_file)

        logger.info("台本生成処理が完了しました。")
        history.record(run_id, "run_completed")
        execution_logger.finish(success=True)
        set_active_logger(None)
    except (OSError, OpenAIError, RuntimeError, ValueError) as error:
        logger.exception("初期化処理に失敗しました。")
        history.record(run_id, "run_failed", error=str(error))
        execution_logger.finish(success=False, error=error)
        set_active_logger(None)
        raise SystemExit(1) from error
