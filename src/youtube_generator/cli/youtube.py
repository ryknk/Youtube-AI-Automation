"""明示操作だけで実行するYouTube投稿CLI。"""

import argparse
from datetime import datetime
from pathlib import Path

from youtube_generator.config import load_settings
from youtube_generator.jobs.manager import JobManager
from youtube_generator.logger import configure_logging, get_logger
from youtube_generator.services.video_settings import load_video_settings
from youtube_generator.services.retry import RetryPolicy
from youtube_generator.youtube.client import build_youtube_client
from youtube_generator.youtube.models import UploadRequest
from youtube_generator.youtube.uploader import YouTubeUploader


def run_youtube(arguments: list[str]) -> None:
    parser = argparse.ArgumentParser(prog="main.py youtube")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("auth")
    for name in ("upload", "schedule", "status"):
        command = commands.add_parser(name)
        command.add_argument("job_id")
        if name != "status":
            command.add_argument("--privacy", choices=("private", "unlisted", "public"))
            command.add_argument("--yes", action="store_true")
            command.add_argument("--force", action="store_true")
        if name == "schedule":
            command.add_argument("--publish-at", required=True)
    args = parser.parse_args(arguments)
    settings = load_settings()
    configure_logging(settings.log_level, settings.log_dir)
    logger = get_logger(__name__)
    manager = JobManager(settings.data_dir / "jobs.db", settings.output_dir / "jobs")
    if args.command == "auth":
        build_youtube_client(settings.youtube_client_secrets_file, settings.youtube_token_file)
        print("OAuth認証が完了しました。")
        return
    if args.command == "status":
        print(manager.get_youtube_upload(args.job_id) or "未投稿")
        return
    config = load_video_settings(settings.config_dir / "config.yaml").values["youtube"]
    if not isinstance(config, dict) or not bool(config["upload_enabled"]):
        raise PermissionError("youtube.upload_enabled が false のためアップロードは禁止されています。")
    if manager.get_youtube_upload(args.job_id) is not None and not args.force:
        raise RuntimeError("このジョブはすでに投稿済みです。--force を指定すると再投稿できます。")
    privacy = args.privacy or str(config["default_privacy"])
    publish_at = datetime.fromisoformat(args.publish_at) if args.command == "schedule" else None
    request = _build_request(manager, args.job_id, privacy, str(config["category_id"]), publish_at)
    print(f"動画: {request.video_file}\nタイトル: {request.title}\n概要欄: {request.description}\n公開設定: {request.privacy}\n予約日時: {request.publish_at}")
    if not args.yes and input("Continue? [y/N] ").strip().lower() != "y":
        print("投稿を中止しました。")
        return
    logger.info("job_id=%s: YouTubeアップロードを開始します。", args.job_id)
    retry_settings = load_video_settings(settings.config_dir / "config.yaml").values["retry"]
    if not isinstance(retry_settings, dict):
        raise ValueError("config.yaml の retry 設定が不正です。")
    result = YouTubeUploader(
        build_youtube_client(settings.youtube_client_secrets_file, settings.youtube_token_file), RetryPolicy.from_settings(retry_settings)
    ).upload(request)
    manager.save_youtube_upload(args.job_id, result.video_id, result.privacy, result.publish_at.isoformat() if result.publish_at else None, "UPLOADED")
    logger.info("job_id=%s: YouTubeアップロードが完了しました。", args.job_id)
    print(result.url)


def _build_request(manager: JobManager, job_id: str, privacy: str, category_id: str, publish_at: datetime | None) -> UploadRequest:
    job = manager.get(job_id)
    root = job.output_dir
    video = root / "video" / "video.mp4"
    if not video.is_file():
        raise FileNotFoundError(f"動画が見つかりません: {video}")
    metadata = root / "metadata"
    title = _first_line(metadata / "titles.txt")
    description = (metadata / "description.txt").read_text(encoding="utf-8").strip()
    tags = tuple(tag.strip() for tag in (metadata / "tags.txt").read_text(encoding="utf-8").split(",") if tag.strip())
    thumbnails = tuple((root / "thumbnail").glob("*"))
    return UploadRequest(job_id, video, thumbnails[0] if thumbnails else None, title, description, tags, privacy, category_id, publish_at)  # type: ignore[arg-type]


def _first_line(file: Path) -> str:
    line = next((value.strip() for value in file.read_text(encoding="utf-8").splitlines() if value.strip()), "")
    return line.split(". ", 1)[-1]
