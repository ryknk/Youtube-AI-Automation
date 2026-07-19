"""YouTube投稿のネットワークなしテスト。"""

import tempfile
import unittest
from datetime import UTC, datetime, timedelta
from pathlib import Path

from youtube_generator.youtube.models import UploadRequest
from youtube_generator.youtube.scheduler import validate_publish_at
from youtube_generator.youtube.uploader import MockYouTubeUploader


class YouTubeUploaderTests(unittest.TestCase):
    def test_mock_uploader_does_not_call_network(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            video = Path(temporary_directory) / "video.mp4"
            video.write_bytes(b"video")
            request = UploadRequest("job", video, None, "title", "description", ("tag",), "private", "22")
            uploader = MockYouTubeUploader()
            result = uploader.upload(request)
        self.assertEqual(result.video_id, "mock-video-id")
        self.assertEqual(len(uploader.requests), 1)

    def test_schedule_requires_private_future_timestamp(self) -> None:
        future = datetime.now(UTC) + timedelta(days=1)
        self.assertTrue(validate_publish_at(future, "private").endswith("Z"))
        with self.assertRaises(ValueError):
            validate_publish_at(future, "public")


if __name__ == "__main__":
    unittest.main()
