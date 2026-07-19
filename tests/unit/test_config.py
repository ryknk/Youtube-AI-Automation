"""YAML設定のpytestテスト。"""

from pathlib import Path

import pytest

from youtube_generator.services.video_settings import load_video_settings


def test_loads_valid_yaml_configuration():
    config = load_video_settings(Path(__file__).parents[1] / "fixtures" / "sample_config.yaml")

    assert config.values["video"]["width"] == 320
    assert config.values["youtube"]["upload_enabled"] is False


def test_rejects_missing_required_configuration(tmp_path):
    config_file = tmp_path / "config.yaml"
    config_file.write_text("video: {}\n", encoding="utf-8")

    with pytest.raises(ValueError, match="必須"):
        load_video_settings(config_file)
