"""テンプレート共通エンディングの明示的なCLI操作。"""

import argparse

from youtube_generator.config import load_settings
from youtube_generator.ending.manager import EndingManager, EndingSettings
from youtube_generator.ending.renderer import FfmpegEndingRenderer
from youtube_generator.infrastructure.cache import CacheManager
from youtube_generator.infrastructure.ffmpeg_video_renderer import VideoRenderSettings
from youtube_generator.infrastructure.ffprobe_audio_duration_provider import FfprobeAudioDurationProvider
from youtube_generator.logger import configure_logging, get_logger
from youtube_generator.plugins.manager import PluginManager
from youtube_generator.services.quality_checker import QualityChecker, load_quality_rules
from youtube_generator.services.retry import RetryPolicy
from youtube_generator.services.srt_builder import SrtBuilder
from youtube_generator.services.template_service import TemplateManager
from youtube_generator.services.video_settings import load_video_settings
from youtube_generator.services.bgm_manager import BGMManager


def create_ending_manager() -> EndingManager:
    settings = load_settings()
    config = load_video_settings(settings.config_dir / "config.yaml")
    values = config.values
    providers, text, audio, video, bgm, subtitles, quality, retry = (
        values["providers"], values["text"], values["audio"], values["video"], values["bgm"],
        values["subtitles"], values["quality"], values["retry"],
    )
    if not all(isinstance(item, dict) for item in (providers, text, audio, video, bgm, subtitles, quality, retry)):
        raise ValueError("config.yaml のエンディング関連設定が不正です。")
    retry_policy = RetryPolicy.from_settings(retry)
    plugin_manager = PluginManager(settings, providers, text)
    configured_bgm = str(bgm["path"])
    bgm_file = settings.config_dir.parent / configured_bgm
    renderer_settings = VideoRenderSettings(
        width=int(video["width"]), height=int(video["height"]), fps=int(video["fps"]),
        bgm_enabled=bool(bgm["enabled"]), bgm_file=bgm_file, bgm_volume=float(bgm["volume"]),
        subtitle_font=str(subtitles["font"]), subtitle_size=int(subtitles["size"]),
        subtitle_color=str(subtitles["color"]),
    )
    cache_values = values["cache"]
    cache = CacheManager(settings.cache_dir) if isinstance(cache_values, dict) and bool(cache_values["enabled"]) else None
    templates = TemplateManager(settings.templates_dir)
    bgm_manager = BGMManager(templates, bgm, settings.config_dir.parent)

    def renderer_for_template(template_id: str) -> FfmpegEndingRenderer:
        bgm_setting = bgm_manager.resolve(template_id, "ending")
        if bgm_manager.render_mode(template_id) == "final_mix":
            bgm_setting = bgm_setting.__class__(enabled=False, source="final_mix")
        return FfmpegEndingRenderer(VideoRenderSettings(
            width=renderer_settings.width, height=renderer_settings.height, fps=renderer_settings.fps,
            bgm_enabled=bgm_setting.enabled, bgm_file=bgm_setting.file or bgm_file,
            bgm_volume=bgm_setting.volume, bgm_loop=bgm_setting.loop,
            bgm_fade_in=bgm_setting.fade_in, bgm_fade_out=bgm_setting.fade_out,
            subtitle_font=renderer_settings.subtitle_font, subtitle_size=renderer_settings.subtitle_size,
            subtitle_color=renderer_settings.subtitle_color,
        ))

    return EndingManager(
        templates, settings.config_dir.parent / "generated_assets" / "endings",
        plugin_manager.create_text_generator(retry_policy), plugin_manager.create_tts_provider(audio, retry_policy),
        FfprobeAudioDurationProvider(settings.ffprobe_executable), SrtBuilder(), FfmpegEndingRenderer(renderer_settings),
        QualityChecker(load_quality_rules(quality)), EndingSettings.from_config(values.get("ending", {})),
        cache, config.fingerprint, renderer_for_template,
        lambda template_id: (
            "final_mix_without_section_bgm"
            if bgm_manager.render_mode(template_id) == "final_mix"
            else bgm_manager.resolve(template_id, "ending").cache_fingerprint
        ),
    )


def run_ending(arguments: list[str]) -> None:
    parser = argparse.ArgumentParser(prog="main.py ending")
    commands = parser.add_subparsers(dest="command", required=True)
    generate = commands.add_parser("generate")
    generate.add_argument("--template", default="default")
    generate.add_argument("--force", action="store_true")
    commands.add_parser("generate-all")
    commands.add_parser("list")
    delete = commands.add_parser("delete")
    delete.add_argument("--template", required=True)
    args = parser.parse_args(arguments)
    settings = load_settings()
    configure_logging(settings.log_level, settings.log_dir)
    manager = create_ending_manager()
    logger = get_logger(__name__)
    if args.command == "generate":
        asset = manager.ensure(args.template, force=args.force)
        print("エンディングは無効です。" if asset is None else asset.video_file)
        return
    if args.command == "generate-all":
        for template in TemplateManager(settings.templates_dir).list():
            asset = manager.ensure(template.template_id)
            if asset is not None:
                print(f"{template.template_id}: {asset.video_file}")
        return
    if args.command == "list":
        for asset in manager.list_assets():
            print(f"{asset.template_id}: {asset.video_file}")
        return
    if manager.delete(args.template):
        logger.info("エンディングを削除しました: template=%s", args.template)
        print(f"削除しました: {args.template}")
    else:
        print(f"エンディングは存在しません: {args.template}")
