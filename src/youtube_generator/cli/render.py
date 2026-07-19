"""既存のmain/endingを再利用する最終BGMレンダリングCLI。"""

import argparse

from youtube_generator.config import load_settings
from youtube_generator.infrastructure.cache import CacheManager
from youtube_generator.infrastructure.final_bgm_renderer import FinalBGMRenderer, FinalRenderSettings
from youtube_generator.jobs.manager import JobManager
from youtube_generator.logger import configure_logging
from youtube_generator.services.bgm_manager import BGMManager
from youtube_generator.services.template_service import TemplateManager
from youtube_generator.services.video_settings import load_video_settings


def run_render(arguments: list[str]) -> None:
    parser = argparse.ArgumentParser(prog="main.py render")
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("final", "remix-bgm"):
        command = commands.add_parser(name)
        command.add_argument("job_id")
        command.add_argument("--force", action="store_true")
    args = parser.parse_args(arguments)
    settings = load_settings()
    configure_logging(settings.log_level, settings.log_dir)
    values = load_video_settings(settings.config_dir / "config.yaml").values
    video, bgm, cache = values["video"], values["bgm"], values["cache"]
    if not isinstance(video, dict) or not isinstance(bgm, dict) or not isinstance(cache, dict):
        raise ValueError("config.yaml の動画・BGM・キャッシュ設定が不正です。")
    job = JobManager(settings.data_dir / "jobs.db", settings.output_dir).get(args.job_id)
    templates = TemplateManager(settings.templates_dir)
    bgm_manager = BGMManager(templates, bgm, settings.config_dir.parent)
    video_dir = job.output_dir / "video"
    main = next((path for path in (video_dir / "main.mp4", video_dir / "video.mp4", job.output_dir / "main.mp4", job.output_dir / "video.mp4") if path.is_file()), None)
    if main is None:
        raise FileNotFoundError(f"ジョブのmain.mp4が見つかりません: {video_dir}")
    ending = next((path for path in (video_dir / "ending.mp4", job.output_dir / "ending.mp4") if path.is_file()), None)
    renderer = FinalBGMRenderer(
        FinalRenderSettings(int(video["width"]), int(video["height"]), int(video["fps"]), bool(values.get("final_render", {}).get("keep_intermediate", True))),
        CacheManager(settings.cache_dir) if bool(cache["enabled"]) else None,
        ffprobe_executable=settings.ffprobe_executable,
    )
    result = renderer.render(main, ending, video_dir, bgm_manager.resolve(job.template, "final"), force=args.force)
    print(result)
