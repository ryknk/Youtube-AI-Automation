"""シーン音声生成ユースケースのユニットテスト。"""

import tempfile
import unittest
from pathlib import Path

from youtube_generator.app.generate_scene_audio import GenerateSceneAudioUseCase
from youtube_generator.infrastructure.openai_speech_synthesizer import OpenAITTSSynthesizer
from youtube_generator.services.retry import RetryPolicy


class MockTTSProvider:
    def __init__(self) -> None:
        self.inputs: list[str] = []

    def generate_speech(self, text: str, output_file: Path) -> None:
        self.inputs.append(text)
        output_file.write_bytes(b"fake-mp3")


class FakeStreamingResponse:
    def __enter__(self) -> "FakeStreamingResponse":
        return self

    def __exit__(self, exception_type: object, exception: object, traceback: object) -> None:
        return None

    def stream_to_file(self, output_file: Path) -> None:
        output_file.write_bytes(b"fake-mp3")


class FakeStreamingSpeech:
    def __init__(self) -> None:
        self.request: dict[str, object] | None = None

    def create(self, **kwargs: object) -> FakeStreamingResponse:
        self.request = kwargs
        return FakeStreamingResponse()


class FakeOpenAIClient:
    def __init__(self) -> None:
        streaming_speech = FakeStreamingSpeech()
        self.audio = type("Audio", (), {})()
        self.audio.speech = type("Speech", (), {})()
        self.audio.speech.with_streaming_response = streaming_speech
        self.streaming_speech = streaming_speech


class GenerateSceneAudioUseCaseTests(unittest.TestCase):
    def test_execute_generates_mp3_for_all_scene_files_in_order(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            scenes_dir = Path(temporary_directory)
            (scenes_dir / "scene02.txt").write_text("2番目", encoding="utf-8")
            (scenes_dir / "scene01.txt").write_text("1番目", encoding="utf-8")
            synthesizer = MockTTSProvider()

            audio_files = GenerateSceneAudioUseCase(synthesizer).execute(scenes_dir)

            self.assertEqual([file.name for file in audio_files], ["scene01.mp3", "scene02.mp3"])
            self.assertEqual(synthesizer.inputs, ["1番目", "2番目"])

    def test_openai_synthesizer_requests_mp3_streaming_response(self) -> None:
        client = FakeOpenAIClient()
        with tempfile.TemporaryDirectory() as temporary_directory:
            output_file = Path(temporary_directory) / "scene01.mp3"
            synthesizer = OpenAITTSSynthesizer(
                api_key="test-key",
                model="gpt-4o-mini-tts",
                voice="alloy",
                speed=1.0,
                instructions="自然に話してください。",
                retry_policy=RetryPolicy(max_attempts=1),
                client=client,  # type: ignore[arg-type]
            )

            synthesizer.synthesize("テスト本文", output_file)

            self.assertTrue(output_file.is_file())
            self.assertEqual(client.streaming_speech.request["response_format"], "mp3")
            self.assertEqual(client.streaming_speech.request["voice"], "alloy")
