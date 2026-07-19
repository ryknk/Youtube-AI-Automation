"""逐次ジョブ実行の統合テスト。"""

import pytest

from youtube_generator.jobs.manager import JobStage, JobStatus


@pytest.mark.integration
def test_queue_continues_after_failure_when_configured(job_manager):
    first = job_manager.add("成功1", "default")
    failed = job_manager.add("失敗", "default")
    third = job_manager.add("成功2", "default")

    def processor(job, update_stage):
        update_stage(JobStage.SCRIPT_GENERATION)
        if job.job_id == failed.job_id:
            raise RuntimeError("simulated failure")

    job_manager.run_pending(processor, stop_on_error=False)

    assert job_manager.get(first.job_id).status is JobStatus.COMPLETED
    assert job_manager.get(failed.job_id).status is JobStatus.FAILED
    assert job_manager.get(third.job_id).status is JobStatus.COMPLETED


@pytest.mark.integration
def test_queue_stops_after_failure_when_configured(job_manager):
    failed = job_manager.add("失敗", "default")
    pending = job_manager.add("未実行", "default")
    job_manager.run_pending(lambda job, stage: (_ for _ in ()).throw(RuntimeError("failure")), stop_on_error=True)

    assert job_manager.get(failed.job_id).status is JobStatus.FAILED
    assert job_manager.get(pending.job_id).status is JobStatus.PENDING
