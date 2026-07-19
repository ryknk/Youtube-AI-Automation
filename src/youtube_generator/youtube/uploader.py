"""YouTubeのresumable動画アップロード。"""

import time

from youtube_generator.logger import get_logger
from youtube_generator.services.retry import RetryPolicy
from youtube_generator.youtube.models import UploadRequest, UploadResult
from youtube_generator.youtube.scheduler import validate_publish_at


class YouTubeUploader:
    def __init__(self, client, retry_policy: RetryPolicy | None = None) -> None:  # type: ignore[no-untyped-def]
        self._client = client
        self._retry_policy = retry_policy or RetryPolicy()
        self._logger = get_logger(__name__)

    def upload(self, request: UploadRequest) -> UploadResult:
        from googleapiclient.http import MediaFileUpload

        publish_at = validate_publish_at(request.publish_at, request.privacy)
        status = {"privacyStatus": request.privacy}
        if publish_at is not None:
            status["publishAt"] = publish_at
        body = {"snippet": {"title": request.title, "description": request.description, "tags": list(request.tags), "categoryId": request.category_id}, "status": status}
        media = MediaFileUpload(str(request.video_file), chunksize=8 * 1024 * 1024, resumable=True)
        operation = self._client.videos().insert(part="snippet,status", body=body, media_body=media)
        response = None
        attempts = 0
        while response is None:
            try:
                _, response = operation.next_chunk()
                attempts = 0
            except Exception as error:
                status_code = getattr(getattr(error, "resp", None), "status", None)
                if not isinstance(error, OSError) and status_code not in {500, 502, 503, 504}:
                    raise
                attempts += 1
                if attempts >= self._retry_policy.max_attempts:
                    raise
                wait_seconds = self._retry_policy.initial_wait_seconds * (self._retry_policy.backoff_multiplier ** (attempts - 1))
                self._logger.warning("job_id=%s: YouTubeアップロードを再試行します（%d/%d、%.1f秒後）。", request.job_id, attempts, self._retry_policy.max_attempts, wait_seconds)
                time.sleep(wait_seconds)
        video_id = response["id"]
        if request.thumbnail_file is not None and request.thumbnail_file.is_file():
            self._client.thumbnails().set(videoId=video_id, media_body=str(request.thumbnail_file)).execute()
        from datetime import UTC, datetime
        return UploadResult(video_id, datetime.now(UTC), request.privacy, request.publish_at)


class MockYouTubeUploader:
    """ネットワークなしで投稿フローを検証するテストダブル。"""
    def __init__(self) -> None:
        self.requests: list[UploadRequest] = []

    def upload(self, request: UploadRequest) -> UploadResult:
        from datetime import UTC, datetime
        self.requests.append(request)
        return UploadResult("mock-video-id", datetime.now(UTC), request.privacy, request.publish_at)
