"""品質レポートに対するGPT改善案の生成。"""

from openai import OpenAI

from youtube_generator.domain.quality import ProjectQualityReport
from youtube_generator.services.retry import RetryPolicy, retry_on_failure
from youtube_generator.logger import get_logger


class OpenAIQualityAdvisor:
    """ERROR/WARNINGを改善するための短い提案をResponses APIで生成する。"""

    def __init__(self, api_key: str, model: str, retry_policy: RetryPolicy) -> None:
        self._client = OpenAI(api_key=api_key, max_retries=0)
        self._model = model
        self._retry_policy = retry_policy
        self._logger = get_logger(__name__)

    def generate(self, report: ProjectQualityReport) -> tuple[str, ...]:
        findings = "\n".join(
            f"- [{check.severity.value.upper()}] {check.check_name}: {check.message}"
            for check in report.checks if check.severity.value != "pass"
        )
        if not findings:
            return ()

        @retry_on_failure(self._retry_policy, (), self._logger)
        def request():  # type: ignore[no-untyped-def]
            return self._client.responses.create(
                model=self._model,
                instructions="YouTube動画品質の改善案を日本語で3件以内、各行1案で返してください。",
                input=findings,
            )

        response = request()
        return tuple(line.strip("- ・\t ") for line in response.output_text.splitlines() if line.strip())
