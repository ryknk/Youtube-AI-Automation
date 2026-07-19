"""pytest共通fixtureと外部API保護。"""

import os
from pathlib import Path

import pytest

from youtube_generator.jobs.manager import JobManager
from youtube_generator.youtube.uploader import MockYouTubeUploader


class MockTextGenerator:
    def generate_text(self, theme, template):  # type: ignore[no-untyped-def]
        return f"{theme}についての安全なテスト台本です。\n十分な説明を含みます。"


class MockTTSProvider:
    def generate_speech(self, text, output_file):  # type: ignore[no-untyped-def]
        output_file.write_bytes(b"mock-mp3")


class MockImageProvider:
    def generate_image(self, prompt, output_file):  # type: ignore[no-untyped-def]
        output_file.write_bytes(b"mock-png")


@pytest.fixture
def temp_output_dir(tmp_path: Path) -> Path:
    return tmp_path / "output"


@pytest.fixture
def temp_cache_dir(tmp_path: Path) -> Path:
    return tmp_path / "cache"


@pytest.fixture
def temp_database(tmp_path: Path) -> Path:
    return tmp_path / "data" / "jobs.db"


@pytest.fixture
def job_manager(temp_database: Path, temp_output_dir: Path) -> JobManager:
    return JobManager(temp_database, temp_output_dir / "jobs")


@pytest.fixture
def mock_text_provider() -> MockTextGenerator:
    return MockTextGenerator()


@pytest.fixture
def mock_tts_provider() -> MockTTSProvider:
    return MockTTSProvider()


@pytest.fixture
def mock_image_provider() -> MockImageProvider:
    return MockImageProvider()


@pytest.fixture
def mock_youtube_uploader() -> MockYouTubeUploader:
    return MockYouTubeUploader()


def pytest_collection_modifyitems(items):  # type: ignore[no-untyped-def]
    for item in items:
        path = str(item.fspath).replace("\\", "/")
        if "/integration/" in path:
            item.add_marker(pytest.mark.integration)
        elif "/unit/" in path:
            item.add_marker(pytest.mark.unit)


def pytest_runtest_setup(item):  # type: ignore[no-untyped-def]
    if item.get_closest_marker("external") and os.getenv("RUN_EXTERNAL_TESTS") != "true":
        pytest.skip("外部APIテストは RUN_EXTERNAL_TESTS=true の場合のみ実行します。")
