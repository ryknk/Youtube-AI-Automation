"""SQLiteジョブキューのテスト。"""

import os
import subprocess
import sys
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
                    root / "output" / "雑学" / f"{job_id}_{theme}"
                ),
            )

            job = manager.add("宇宙", "trivia")

            self.assertEqual(job.output_dir.parent.name, "雑学")
            self.assertEqual(job.output_dir.name, f"{job.job_id}_宇宙")

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

    def test_failure_is_logged_so_it_is_visible_without_querying_the_database(self) -> None:
        """run_pendingが例外をDBのerror_messageへ記録するだけで、コンソール/ログファイルへ
        一切出力しない問題（queue run実行時に何も表示されず失敗する）の回帰テスト。"""
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            manager = JobManager(root / "jobs.db", root / "output" / "jobs")
            job = manager.add("失敗", "trivia")

            def processor(job, update_stage):  # type: ignore[no-untyped-def]
                raise RuntimeError("画像生成に失敗しました")

            with self.assertLogs("youtube_generator.jobs.manager", level="ERROR") as logs:
                manager.run_pending(processor, stop_on_error=False)

            messages = [record.getMessage() for record in logs.records]
            self.assertTrue(any(job.job_id in message for message in messages))

    def test_recover_interrupted_job(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            manager = JobManager(Path(temporary_directory) / "jobs.db", Path(temporary_directory) / "jobs")
            job = manager.add("中断", "trivia")
            manager._update(job.job_id, status=JobStatus.RUNNING, stage=JobStage.VOICE_GENERATION)  # type: ignore[attr-defined]

            self.assertEqual(manager.recover_interrupted(), 1)
            self.assertEqual(manager.get(job.job_id).status, JobStatus.PENDING)

    def test_recover_interrupted_skips_job_whose_pid_is_still_alive(self) -> None:
        """PowerShellを閉じた際の強制終了と、別ターミナルで実際に`queue run`が稼働中の
        ケースを区別できることを確認する（後者はPENDINGへ巻き戻してはならない）。"""
        with tempfile.TemporaryDirectory() as temporary_directory:
            manager = JobManager(Path(temporary_directory) / "jobs.db", Path(temporary_directory) / "jobs")
            job = manager.add("実行中", "trivia")
            manager._update(  # type: ignore[attr-defined]
                job.job_id, status=JobStatus.RUNNING, stage=JobStage.VOICE_GENERATION, pid=os.getpid(),
            )

            self.assertEqual(manager.recover_interrupted(), 0)
            self.assertEqual(manager.get(job.job_id).status, JobStatus.RUNNING)

    def test_recover_interrupted_recovers_job_whose_pid_has_exited(self) -> None:
        """PowerShellを閉じてプロセスが強制終了された場合を模す: 記録されたPIDは既に
        存在しないため、RUNNINGのまま残ったジョブをPENDINGへ回収できる。"""
        with tempfile.TemporaryDirectory() as temporary_directory:
            manager = JobManager(Path(temporary_directory) / "jobs.db", Path(temporary_directory) / "jobs")
            job = manager.add("強制終了", "trivia")
            finished_process = subprocess.Popen([sys.executable, "-c", "pass"])
            finished_process.wait()
            manager._update(  # type: ignore[attr-defined]
                job.job_id, status=JobStatus.RUNNING, stage=JobStage.VOICE_GENERATION, pid=finished_process.pid,
            )

            self.assertEqual(manager.recover_interrupted(), 1)
            recovered = manager.get(job.job_id)
            self.assertEqual(recovered.status, JobStatus.PENDING)
            self.assertIsNone(recovered.pid)

    def test_recover_interrupted_job_can_then_be_cancelled_and_deleted(self) -> None:
        """回収前はRUNNINGのためcancel/deleteが拒否されるが、回収後は受け付けられる
        （PowerShellを閉じた後にretry/cancel/deleteが一切実行できない問題の回帰テスト）。"""
        with tempfile.TemporaryDirectory() as temporary_directory:
            manager = JobManager(Path(temporary_directory) / "jobs.db", Path(temporary_directory) / "jobs")
            job = manager.add("中断", "trivia")
            manager._update(  # type: ignore[attr-defined]
                job.job_id, status=JobStatus.RUNNING, stage=JobStage.VOICE_GENERATION, pid=None,
            )

            with self.assertRaises(ValueError):
                manager.cancel(job.job_id)

            manager.recover_interrupted()

            self.assertEqual(manager.cancel(job.job_id).status, JobStatus.CANCELLED)

    def test_is_process_alive_true_for_current_process(self) -> None:
        self.assertTrue(JobManager._is_process_alive(os.getpid()))  # type: ignore[attr-defined]

    def test_is_process_alive_false_for_exited_process(self) -> None:
        finished_process = subprocess.Popen([sys.executable, "-c", "pass"])
        finished_process.wait()
        self.assertFalse(JobManager._is_process_alive(finished_process.pid))  # type: ignore[attr-defined]

    def test_run_pending_records_pid_while_running(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            manager = JobManager(Path(temporary_directory) / "jobs.db", Path(temporary_directory) / "jobs")
            manager.add("記録", "trivia")
            observed_pid: list[int | None] = []

            def processor(job, update_stage):  # type: ignore[no-untyped-def]
                observed_pid.append(job.pid)

            manager.run_pending(processor)

            self.assertEqual(observed_pid, [os.getpid()])

    def test_delete_removes_job_but_keeps_output_directory(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            manager = JobManager(root / "jobs.db", root / "output")
            job = manager.add("削除テスト", "default")

            self.assertTrue(manager.delete(job.job_id))
            self.assertTrue(job.output_dir.is_dir())
            with self.assertRaises(KeyError):
                manager.get(job.job_id)

    def test_clear_removes_all_non_running_jobs(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            manager = JobManager(root / "jobs.db", root / "output")
            manager.add("テーマ1", "default")
            manager.add("テーマ2", "history")

            self.assertEqual(manager.clear(), 2)
            self.assertEqual(manager.list(), ())


if __name__ == "__main__":
    unittest.main()
