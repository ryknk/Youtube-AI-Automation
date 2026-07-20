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
from youtube_generator.app.generate_scene_images import GenerateSceneImagesUseCase
from youtube_generator.app.generate_subtitles import GenerateSubtitlesUseCase
from youtube_generator.app.generate_video import GenerateVideoUseCase
from youtube_generator.app.generate_metadata import GenerateMetadataUseCase
from youtube_generator.app.generate_thumbnail import GenerateThumbnailUseCase
from youtube_generator.config import load_settings
from youtube_generator.infrastructure.cache import CacheManager
from youtube_generator.infrastructure.history import RunHistoryRecorder
from youtube_generator.logger import Logger, configure_logging, get_logger, set_active_logger
from youtube_generator.infrastructure.ffprobe_audio_duration_provider import FfprobeAudioDurationProvider
from youtube_generator.infrastructure.ffmpeg_video_renderer import FfmpegVideoRenderer, VideoRenderSettings
from youtube_generator.infrastructure.openai_quality_advisor import OpenAIQualityAdvisor
from youtube_generator.services.quality_checker import QualityChecker, ScriptQualityChecker, load_quality_rules
from youtube_generator.services.retry import RetryPolicy
from youtube_generator.services.image_prompt_builder import ImagePromptBuilder
from youtube_generator.services.srt_builder import SrtBuilder
from youtube_generator.services.subtitle_splitter import SubtitleSettings, SubtitleSplitter
from youtube_generator.services.template_service import TemplateManager
from youtube_generator.services.video_settings import load_video_settings
from youtube_generator.services.bgm_manager import BGMManager
from youtube_generator.infrastructure.final_bgm_renderer import FinalBGMRenderer, FinalRenderSettings
from youtube_generator.plugins.manager import PluginManager
from youtube_generator.cli.ending import run_ending
from youtube_generator.cli.ending import create_ending_manager
from youtube_generator.cli.bgm import run_bgm
from youtube_generator.cli.render import run_render


def create_parser() -> argparse.ArgumentParser:
    """CLI引数パーサーを作成する。"""
    parser = argparse.ArgumentParser(description="Youtube AI Automation")
    input_group = parser.add_mutually_exclusive_group()
    input_group.add_argument("--theme", help="台本を生成する動画テーマ")
    input_group.add_argument("--split-script", type=Path, help="分割する script.txt のパス")
    input_group.add_argument("--generate-audio", type=Path, help="sceneNN.txt があるフォルダのパス")
    input_group.add_argument("--generate-images", type=Path, help="sceneNN.txt があるフォルダのパス")
    input_group.add_argument("--generate-subtitles", type=Path, help="sceneNN.mp3 があるフォルダのパス")
    input_group.add_argument("--generate-video", type=Path, help="シーン素材があるフォルダのパス")
    input_group.add_argument("--generate-metadata", type=Path, help="完成動画とscript.txtがあるフォルダのパス")
    input_group.add_argument("--generate-thumbnail", type=Path, help="script.txtがあるフォルダのパス")
    parser.add_argument("--template", default="default", help="テンプレートID（既定: default）")
    parser.add_argument("--topic", help="メタデータ生成に使用する動画テーマ")
    parser.add_argument("--list-templates", action="store_true", help="利用可能なテンプレートを表示して終了")
    parser.add_argument("--script", help="品質チェックする台本文。API生成後は生成台本を渡す想定です。")
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
        if args.generate_images:
            logger.info("画像化対象のフォルダ: %s", args.generate_images)
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
                image_generator, template.thumbnail_instruction
            ).execute(args.generate_thumbnail)
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
            cache_result = use_case.execute_cached(
                args.generate_metadata, cache_manager,
                fingerprint=video_settings.fingerprint, topic=topic,
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
            duration_provider = FfprobeAudioDurationProvider(settings.ffprobe_executable)
            quality_checker = QualityChecker(
                load_quality_rules(quality_values), duration_provider
            )
            quality_report = quality_checker.check_project(
                args.generate_video, ImagePromptBuilder(template.image_style)
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
                    subtitle_font=str(subtitle_values["font"]), subtitle_size=int(subtitle_values["size"]),
                    subtitle_color=str(subtitle_values["color"]),
                    subtitle_position=str(subtitle_values.get("position", "bottom")),
                    subtitle_alignment=str(subtitle_values.get("alignment", "center")),
                    subtitle_bottom_margin=int(subtitle_values.get("bottom_margin", 80)),
                ),
            )
            video_file = GenerateVideoUseCase(renderer).execute(args.generate_video, str(video_values["output_format"]))
            ending_values = video_settings.values.get("ending", {})
            if isinstance(ending_values, dict) and bool(ending_values.get("enabled", True)) and bool(ending_values.get("auto_append", True)):
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
            subtitle_inputs = tuple(sorted(args.generate_subtitles.glob("scene*.mp3"))) + tuple(
                sorted(args.generate_subtitles.glob("scene*.txt"))
            )
            subtitle_fingerprint = CacheManager.make_key(
                video_settings.fingerprint,
                json.dumps(subtitle_values, ensure_ascii=False, sort_keys=True),
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
            scene_cache_key = CacheManager.make_file_key("scene", (args.split_script,), video_settings.fingerprint)
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
                video_settings.fingerprint,
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
            history.record(run_id, "run_completed")
            for file_path in audio_files:
                execution_logger.add_generated_file(file_path)
            execution_logger.finish(success=True)
            set_active_logger(None)
            return

        if args.generate_images:
            retry_settings = video_settings.values["retry"]
            image_settings = video_settings.values["image"]
            if not isinstance(retry_settings, dict) or not isinstance(image_settings, dict):
                raise ValueError("config.yaml の retry または image 設定が不正です。")
            image_generator = plugin_manager.create_image_provider(
                image_settings, RetryPolicy.from_settings(retry_settings)
            )
            use_case = GenerateSceneImagesUseCase(
                ImagePromptBuilder(template.image_style or str(image_settings["style"])),
                image_generator,
                max_images=int(image_settings["max_count"]),
            )
            image_inputs = tuple(sorted(args.generate_images.glob("scene*.txt")))
            image_cache_key = CacheManager.make_file_key("image", image_inputs, video_settings.fingerprint)
            if cache_manager is not None and cache_manager.exists(image_cache_key, "image"):
                image_files = cache_manager.restore_files(image_cache_key, "image", args.generate_images)
                logger.info("画像をキャッシュから復元しました。")
                history.record(run_id, "cache_hit", artifact="image", cache_key=image_cache_key)
            else:
                image_files = use_case.execute(args.generate_images)
                if cache_manager is not None:
                    cache_manager.save_files(image_cache_key, "image", image_files)
            logger.info("%d件のPNGファイルを生成しました。", len(image_files))
            history.record(run_id, "scene_images_generated", image_count=len(image_files))
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
                "script", args.theme, template.template_id, video_settings.fingerprint
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
