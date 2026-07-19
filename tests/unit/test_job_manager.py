"""SQLiteジョブキューのテスト。"""

import tempfile
import unittest
from pathlib import Path

from youtube_generator.jobs.manager import JobManager, JobStage, JobStatus


class JobManagerTests(unittest.TestCase):
    def test_add_uses_configured_output_directory_factory(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            manager = JobManager(
                root / "jobs.db", root / "output",
                output_directory_factory=lambda theme, template, job_id: (
                    root / "output" / "雑学" / f"{job_id}_{template}_{theme}"
                ),
            )

            job = manager.add("宇宙", "trivia")

            self.assertEqual(job.output_dir.parent.name, "雑学")
            self.assertEqual(job.output_dir.name, f"{job.job_id}_trivia_宇宙")

    def test_add_import_and_run_in_creation_order(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            manager = JobManager(root / "data" / "jobs.db", root / "output" / "jobs")
            first = manager.add("宇宙", "trivia")
            second = manager.add("歴史", "history")
            processed: list[str] = []

            self.assertEqual(first.output_dir.name, f"{first.job_id}_trivia_宇宙")
            self.assertEqual(second.output_dir.name, f"{second.job_id}_history_歴史")

            def processor(job, update_stage):  # type: ignore[no-untyped-def]
                processed.append(job.job_id)
                update_stage(JobStage.SCRIPT_GENERATION)

            manager.run_pending(processor)

            self.assertEqual(processed, [first.job_id, second.job_id])
            self.assertTrue(all(job.status is JobStatus.COMPLETED for job in manager.list()))
            self.assertTrue((first.output_dir / "metadata").is_dir())

    def test_default_output_directory_sanitizes_theme(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            manager = JobManager(root / "jobs.db", root / "output" / "jobs")

            job = manager.add('星/宇宙:*? ', "雑学/豆知識")

            self.assertEqual(
                job.output_dir.name,
                f"{job.job_id}_雑学_豆知識_星_宇宙___",
            )

    def test_failure_does_not_stop_next_job_and_retry_recovers(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            manager = JobManager(root / "jobs.db", root / "output" / "jobs")
            failed = manager.add("失敗", "trivia")
            completed = manager.add("成功", "trivia")

            def processor(job, update_stage):  # type: ignore[no-untyped-def]
                if job.job_id == failed.job_id:
                    raise RuntimeError("expected")
                update_stage(JobStage.COMPLETED)

            manager.run_pending(processor, stop_on_error=False)
            self.assertEqual(manager.get(failed.job_id).status, JobStatus.FAILED)
            self.assertEqual(manager.get(completed.job_id).status, JobStatus.COMPLETED)
            self.assertEqual(manager.retry(failed.job_id).status, JobStatus.PENDING)

    def test_recover_interrupted_job(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            manager = JobManager(Path(temporary_directory) / "jobs.db", Path(temporary_directory) / "jobs")
            job = manager.add("中断", "trivia")
            manager._update(job.job_id, status=JobStatus.RUNNING, stage=JobStage.VOICE_GENERATION)  # type: ignore[attr-defined]

            self.assertEqual(manager.recover_interrupted(), 1)
            self.assertEqual(manager.get(job.job_id).status, JobStatus.PENDING)


if __name__ == "__main__":
    unittest.main()
