"""テンプレートBGMを確認するための読み取り専用CLI。"""

import argparse

from youtube_generator.config import load_settings
from youtube_generator.logger import configure_logging
from youtube_generator.services.bgm_manager import BGMManager
from youtube_generator.services.template_service import TemplateManager
from youtube_generator.services.video_settings import load_video_settings


def run_bgm(arguments: list[str]) -> None:
    parser = argparse.ArgumentParser(prog="main.py bgm")
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("show", "validate"):
        command = commands.add_parser(name)
        command.add_argument("--template", default="default")
    commands.add_parser("list")
    commands.add_parser("validate-all")
    args = parser.parse_args(arguments)
    settings = load_settings()
    configure_logging(settings.log_level, settings.log_dir)
    values = load_video_settings(settings.config_dir / "config.yaml").values
    global_bgm = values["bgm"]
    if not isinstance(global_bgm, dict):
        raise ValueError("config.yaml の bgm 設定が不正です。")
    templates = TemplateManager(settings.templates_dir)
    manager = BGMManager(templates, global_bgm, settings.config_dir.parent)
    if args.command in {"show", "validate"}:
        template = templates.get(args.template)
        _print_settings(manager, template.template_id)
        if args.command == "validate":
            _validate(manager, template.template_id)
        return
    for template in templates.list():
        if args.command == "list":
            _print_settings(manager, template.template_id)
        else:
            _validate(manager, template.template_id)


def _print_settings(manager: BGMManager, template_id: str) -> None:
    for target in ("main", "ending"):
        setting = manager.resolve(template_id, target)
        print(
            f"{template_id} [{target}] enabled={setting.enabled} file={setting.file} "
            f"volume={setting.volume} loop={setting.loop} fade_in={setting.fade_in} "
            f"fade_out={setting.fade_out} source={setting.source}"
        )


def _validate(manager: BGMManager, template_id: str) -> None:
    valid = True
    for target in ("main", "ending"):
        ok, message, setting = manager.validate(template_id, target)
        print(f"{template_id} [{target}] {'PASS' if ok else 'ERROR'}: {message} ({setting.file})")
        valid = valid and ok
    if not valid:
        raise SystemExit(1)
