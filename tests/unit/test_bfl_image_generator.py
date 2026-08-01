"""Black Forest Labs画像生成実装のユニットテスト。"""

import json
import tempfile
import unittest
from pathlib import Path

from youtube_generator.infrastructure.bfl_image_generator import BFLImageGenerator
from youtube_generator.services.retry import RetryPolicy


class FakeResponse:
    def __init__(self, body: bytes) -> None:
        self._body = body

    def __enter__(self):  # type: ignore[no-untyped-def]
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def read(self) -> bytes:
        return self._body


class FakeOpenUrl:
    def __init__(self) -> None:
        self.requests = []

    def __call__(self, request, **kwargs):  # type: ignore[no-untyped-def]
        self.requests.append(request)
        if request.full_url == "https://api.bfl.ai/v1/flux-2-pro":
            return FakeResponse(json.dumps({
                "id": "request-id", "polling_url": "https://api.bfl.ai/v1/get_result?id=request-id",
            }).encode())
        if "get_result" in request.full_url:
            return FakeResponse(json.dumps({
                "status": "Ready", "result": {"sample": "https://signed.example/image.png"},
            }).encode())
        return FakeResponse(b"png-data")


class BFLImageGeneratorTests(unittest.TestCase):
    def test_generate_submits_dimensions_polls_and_downloads_png(self) -> None:
        transport = FakeOpenUrl()
        generator = BFLImageGenerator(
            "test-key", "flux-2-pro", "1920x1080",
            RetryPolicy(max_attempts=1, timeout_seconds=1), open_url=transport,
        )
        with tempfile.TemporaryDirectory() as directory:
            output_file = Path(directory) / "scene01.png"

            generator.generate("cinematic landscape", output_file)

            self.assertEqual(output_file.read_bytes(), b"png-data")
            submission = json.loads(transport.requests[0].data.decode())
            self.assertEqual((submission["width"], submission["height"]), (1920, 1080))
            self.assertEqual(submission["output_format"], "png")
            self.assertEqual(submission["prompt"], "cinematic landscape")

    def test_prompt_suffix_is_appended_when_configured(self) -> None:
        transport = FakeOpenUrl()
        generator = BFLImageGenerator(
            "test-key", "flux-2-pro", "1920x1080",
            RetryPolicy(max_attempts=1, timeout_seconds=1), open_url=transport, prompt_suffix="No text.",
        )
        with tempfile.TemporaryDirectory() as directory:
            output_file = Path(directory) / "scene01.png"

            generator.generate("cinematic landscape", output_file)

            submission = json.loads(transport.requests[0].data.decode())
            self.assertEqual(submission["prompt"], "cinematic landscape, No text.")
