"""ジョブキューCLI。"""

import argparse
from pathlib import Path

from youtube_generator.config import load_settings
from youtube_generator.jobs.manager import JobManager
from youtube_generator.jobs.pipeline import ExistingPipelineRunner
from youtube_generator.logger import configure_logging, get_logger
from youtube_generator.services.video_settings import load_video_settings
from youtube_generator.services.template_service import TemplateManager
from youtube_generator.app.generate_script import GenerateScriptUseCase


def run_queue(arguments: list[str]) -> None:
    parser = argparse.ArgumentParser(prog="main.py queue")
    subcommands = parser.add_subparsers(dest="command", required=True)
    add = subcommands.add_parser("add")
    add.add_argument("theme")
    add.add_argument("--template", default="default")
    import_command = subcommands.add_parser("import")
    import_command.add_argument("source", type=Path)
    subcommands.add_parser("list")
    run = subcommands.add_parser("run")
    run.add_argument(
        "--force", action="store_true",
        help="キャッシュ・既存ファイルを無視し、全ジョブの全工程を強制的に再生成する",
    )
    subcommands.add_parser("status")
    retry = subcommands.add_parser("retry")
    retry.add_argument("job_id")
    cancel = subcommands.add_parser("cancel")
    cancel.add_argument("job_id")
    delete = subcommands.add_parser("delete")
    delete.add_argument("job_id")
    clear = subcommands.add_parser("clear")
    clear.add_argument("--yes", action="store_true", help="確認を省略してキューを一括クリアする")
    args = parser.parse_args(arguments)

    settings = load_settings()
    configure_logging(settings.log_level, settings.log_dir)
    logger = get_logger(__name__)
    templates = TemplateManager(settings.templates_dir)

    def output_directory(theme: str, template_id: str, job_id: str) -> Path:
        template = templates.get(template_id)
        return GenerateScriptUseCase.output_directory(settings.output_dir, theme, template, job_id)

    manager = JobManager(
        settings.data_dir / "jobs.db", settings.output_dir,
        output_directory_factory=output_directory,
    )
    # PowerShellを閉じる等でプロセスが強制終了され、RUNNINGのまま残ったジョブが
    # retry/cancel/delete等を受け付けられなくなる問題を防ぐため、有効なコマンドの
    # 実行前に必ず中断ジョブを回収する（実際に稼働中のPIDを持つジョブは対象外）。
    recovered_count = manager.recover_interrupted()
    if recovered_count:
        logger.info("前回実行が中断されたジョブ %d 件を再実行待ちへ戻しました。", recovered_count)

    if args.command == "add":
        job = manager.add(args.theme, args.template)
        print(job.job_id)
    elif args.command == "import":
        print(f"{len(manager.import_file(args.source))} 件登録しました。")
    elif args.command in ("list", "status"):
        for job in manager.list():
            try:
                genre_name = templates.get(job.template).display_name
            except ValueError:
                genre_name = job.template
            print(
                f"{job.job_id} | {job.status} | {job.stage or '-'} | "
                f"ジャンル: {genre_name} | テーマ: {job.theme}"
            )
    elif args.command == "retry":
        print(manager.retry(args.job_id).job_id)
    elif args.command == "cancel":
        print(manager.cancel(args.job_id).job_id)
    elif args.command == "delete":
        manager.delete(args.job_id)
        print(f"削除しました: {args.job_id}")
    elif args.command == "clear":
        if not args.yes:
            print("キュー内の全ジョブを削除します。Continue? [y/N] ", flush=True)
        if not args.yes and input().strip().lower() != "y":
            print("キューのクリアを中止しました。")
            return
        print(f"{manager.clear()} 件のジョブを削除しました。")
    elif args.command == "run":
        queue_settings = load_video_settings(settings.config_dir / "config.yaml").values["queue"]
        if not isinstance(queue_settings, dict):
            raise ValueError("config.yaml の queue 設定が不正です。")
        skip_thumbnail = bool(queue_settings.get("skip_thumbnail", False))
        def processor(job, update_stage):  # type: ignore[no-untyped-def]
            logger.info("job_id=%s: ジョブを開始します。", job.job_id)
            def logged_update(stage):  # type: ignore[no-untyped-def]
                logger.info("job_id=%s: 工程=%s", job.job_id, stage.value)
                update_stage(stage)
            def logged_progress(message):  # type: ignore[no-untyped-def]
                logger.info("job_id=%s: %s", job.job_id, message)
            ExistingPipelineRunner(skip_thumbnail=skip_thumbnail, force=args.force)(job, logged_update, logged_progress)
            logger.info("job_id=%s: ジョブを完了しました。", job.job_id)
        manager.run_pending(processor, stop_on_error=bool(queue_settings["stop_on_error"]))
