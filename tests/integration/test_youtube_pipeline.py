"""YouTube投稿フローのネットワークなし統合テスト。"""

from youtube_generator.youtube.models import UploadRequest


def test_mock_upload_persists_video_id_and_prevents_duplicate(job_manager, mock_youtube_uploader):
    job = job_manager.add("投稿テスト", "default")
    video_file = job.output_dir / "video" / "video.mp4"
    video_file.write_bytes(b"test-video")
    request = UploadRequest(job.job_id, video_file, None, "タイトル", "概要欄", ("tag",), "private", "22")

    result = mock_youtube_uploader.upload(request)
    job_manager.save_youtube_upload(job.job_id, result.video_id, result.privacy, None, "UPLOADED")

    assert job_manager.get_youtube_upload(job.job_id)["video_id"] == "mock-video-id"
    assert job_manager.get_youtube_upload(job.job_id) is not None
