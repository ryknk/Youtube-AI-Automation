"""テンプレートBGM設定の解決・検証テスト。"""

from pathlib import Path

import pytest

from youtube_generator.services.bgm_manager import BGMManager
from youtube_generator.services.template_service import TemplateManager


def _template(root: Path, template_id: str, yaml: str) -> Path:
    directory = root / template_id
    directory.mkdir(parents=True)
    for name in ("prompt.txt", "image_prompt.txt", "title_prompt.txt", "thumbnail_prompt.txt"):
        (directory / name).write_text("test", encoding="utf-8")
    (directory / "video.yaml").write_text(f"scene_structure: [test]\n{yaml}", encoding="utf-8")
    return directory


def _manager(tmp_path: Path, history_yaml: str = "") -> tuple[BGMManager, Path]:
    templates = tmp_path / "templates"
    default = _template(templates, "default", "")
    (default / "bgm").mkdir()
    (default / "bgm" / "default.mp3").write_bytes(b"default")
    (default / "video.yaml").write_text(
        "scene_structure: [test]\nbgm:\n  file: bgm/default.mp3\n  volume: 0.1\n", encoding="utf-8"
    )
    history = _template(templates, "history", history_yaml)
    return BGMManager(TemplateManager(templates), {"enabled": True, "default_file": "global.mp3", "default_volume": 0.2}, tmp_path), history


def test_reads_template_specific_main_and_ending_bgm(tmp_path):
    manager, history = _manager(tmp_path, """bgm:
  file: bgm/history.mp3
  volume: 0.08
  main:
    fade_in: 1.0
  ending:
    volume: 0.12
    fade_out: 1.5
""")
    (history / "bgm").mkdir()
    (history / "bgm" / "history.mp3").write_bytes(b"history")

    main = manager.resolve("history", "main")
    ending = manager.resolve("history", "ending")

    assert main.file == history / "bgm" / "history.mp3"
    assert main.volume == 0.08 and main.fade_in == 1.0
    assert ending.volume == 0.12 and ending.fade_out == 1.5


def test_falls_back_to_default_then_global(tmp_path):
    manager, _ = _manager(tmp_path)
    assert manager.resolve("history", "main").source == "template:default"

    templates = tmp_path / "templates"
    (templates / "default" / "bgm" / "default.mp3").unlink()
    (tmp_path / "global.mp3").write_bytes(b"global")
    assert manager.resolve("history", "main").source == "global"


def test_enabled_false_does_not_fallback(tmp_path):
    manager, _ = _manager(tmp_path, "bgm:\n  enabled: false\n")
    assert manager.resolve("history", "main").enabled is False


@pytest.mark.parametrize("behavior,expected_enabled,raises", [
    ("fallback", True, False), ("disable", False, False), ("error", False, True),
])
def test_missing_file_behavior(tmp_path, behavior, expected_enabled, raises):
    manager, _ = _manager(tmp_path, f"bgm:\n  file: bgm/missing.mp3\n  missing_file_behavior: {behavior}\n")
    if raises:
        with pytest.raises(FileNotFoundError):
            manager.resolve("history", "main")
    else:
        assert manager.resolve("history", "main").enabled is expected_enabled


def test_invalid_volume_is_rejected(tmp_path):
    manager, _ = _manager(tmp_path, "bgm:\n  file: bgm/test.mp3\n  volume: 1.1\n")
    with pytest.raises(ValueError, match="0.0〜1.0"):
        manager.resolve("history", "main")


def test_bgm_content_change_changes_cache_fingerprint(tmp_path):
    manager, history = _manager(tmp_path, "bgm:\n  file: bgm/history.mp3\n")
    (history / "bgm").mkdir()
    file = history / "bgm" / "history.mp3"
    file.write_bytes(b"before")
    before = manager.resolve("history", "ending").cache_fingerprint
    file.write_bytes(b"after")
    after = manager.resolve("history", "ending").cache_fingerprint
    assert before != after


def test_final_settings_override_common_settings(tmp_path):
    manager, history = _manager(tmp_path, """bgm:
  file: bgm/history.mp3
  volume: 0.08
  final:
    volume: 0.12
""")
    (history / "bgm").mkdir()
    (history / "bgm" / "history.mp3").write_bytes(b"history")
    assert manager.resolve("history", "final").volume == 0.12
