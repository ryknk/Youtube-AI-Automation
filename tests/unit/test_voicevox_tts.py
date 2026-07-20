import json
from urllib.parse import parse_qs

from youtube_generator.plugins.tts.voicevox_tts import VOICEVOXTTSProvider
from youtube_generator.services.retry import RetryPolicy


def test_voicevox_queries_then_synthesizes_wav(tmp_path):
    class FakeVoicevox(VOICEVOXTTSProvider):
        def __init__(self):
            super().__init__("http://localhost:50021", 3, 1, {"speedScale": 1.2, "pitchScale": 0.0}, RetryPolicy(max_attempts=1))
            self.calls = []
        def _request(self, path, body, content_type, query=""):
            self.calls.append((path, body, query))
            return json.dumps({}).encode() if path == "/audio_query" else b"RIFFfakeWAVE"

    provider = FakeVoicevox()
    output = tmp_path / "scene01.wav"
    provider.generate_speech("テスト", output)
    assert output.read_bytes().startswith(b"RIFF")
    assert provider.calls[0][0] == "/audio_query"
    assert provider.calls[0][1] == b""
    assert parse_qs(provider.calls[0][2]) == {"text": ["テスト"], "speaker": ["3"]}
    assert provider.calls[1][0] == "/synthesis"
    assert provider.calls[1][2] == "speaker=3"
