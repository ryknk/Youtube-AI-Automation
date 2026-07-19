"""テンプレートからタイトル生成までの統合テスト。"""

import json
from pathlib import Path

from youtube_generator.domain.metadata_generator import MetadataGenerationContext
from youtube_generator.infrastructure.openai_metadata_generator import OpenAIMetadataGenerator
from youtube_generator.jobs.manager import Job, JobStatus
from youtube_generator.jobs.pipeline import ExistingPipelineRunner
from youtube_generator.services.retry import RetryPolicy
from youtube_generator.services.template_service import TemplateManager


class MockResponse:
    def __init__(self, count: int) -> None:
        self.output_text = json.dumps(
            {"titles": [f"タイトル{i}" for i in range(1, count + 1)]},
            ensure_ascii=False,
        )


class MockResponses:
    def __init__(self) -> None:
        self.inputs: list[str] = []

    def create(self, **kwargs: object) -> MockResponse:
        self.inputs.append(str(kwargs["input"]))
        schema = kwargs["text"]["format"]["schema"]  # type: ignore[index]
        return MockResponse(schema["properties"]["titles"]["minItems"])


class MockTextGeneratorClient:
    def __init__(self) -> None:
        self.responses = MockResponses()


def _write_template(root: Path, template_id: str, display_name: str, title_prompt: str) -> None:
    directory = root / template_id
    directory.mkdir(parents=True)
    (directory / "prompt.txt").write_text("台本方針", encoding="utf-8")
    (directory / "image_prompt.txt").write_text("画像方針", encoding="utf-8")
    (directory / "title_prompt.txt").write_text(title_prompt, encoding="utf-8")
    (directory / "thumbnail_prompt.txt").write_text("サムネイル方針", encoding="utf-8")
    (directory / "video.yaml").write_text(
        f"display_name: {display_name}\nscene_structure: []\n", encoding="utf-8",
    )


def test_two_templates_reach_title_llm_with_different_prompts(tmp_path: Path) -> None:
    templates_dir = tmp_path / "templates"
    _write_template(templates_dir, "zatsugaku", "雑学", "短く意外性を感じさせ、答えを明かさない")
    _write_template(templates_dir, "history", "歴史", "人物名や出来事を明確に含め、煽りを避ける")
    manager = TemplateManager(templates_dir)
    client = MockTextGeneratorClient()
    generator = OpenAIMetadataGenerator(
        "test-key", "test-model", RetryPolicy(max_attempts=1),
        client=client, title_count=2,  # type: ignore[arg-type]
    )

    for template_id in ("zatsugaku", "history"):
        template = manager.get(template_id)
        generator.generate_titles(MetadataGenerationContext(
            "同じテーマ", "同じ完成台本", template.display_name,
            template.title_instruction,
        ))

    assert manager.get("zatsugaku").title_instruction in client.responses.inputs[0]
    assert manager.get("history").title_instruction in client.responses.inputs[1]
    assert client.responses.inputs[0] != client.responses.inputs[1]


def test_job_metadata_arguments_include_jobs_template_and_topic(tmp_path: Path) -> None:
    job = Job(
        job_id="job-id", theme="徳川家康", template="history",
        created_at="2026-01-01T00:00:00+00:00", started_at=None, finished_at=None,
        status=JobStatus.PENDING, stage=None, output_dir=tmp_path / "job",
        error_message=None, retry_count=0,
    )

    arguments = ExistingPipelineRunner._metadata_arguments(job, tmp_path / "job" / ".work")

    assert arguments[-4:] == ("--template", "history", "--topic", "徳川家康")
