import threading

import pytest

from ligaotai.jobs import BusyError, JobRunner


def test_job_runs_and_records_result():
    runner = JobRunner()

    def fn(progress):
        progress(1, 2, "一半")
        progress(2, 2)
        return {"ok": 1}

    job = runner.submit("split", "测试书", fn)
    job = runner.wait(job.id)
    assert job.status == "done"
    assert job.result == {"ok": 1}
    assert (job.done, job.total, job.message) == (2, 2, "一半")
    assert job.started and job.finished
    assert runner.get(job.id) is job
    assert runner.current() is job


def test_job_failure_is_captured():
    runner = JobRunner()

    def fn(progress):
        raise RuntimeError("boom")

    job = runner.wait(runner.submit("dedup", "测试书", fn).id)
    assert job.status == "failed"
    assert job.error == "RuntimeError: boom"


def test_only_one_job_at_a_time():
    runner = JobRunner()
    gate = threading.Event()
    first = runner.submit("split", "测试书", lambda p: gate.wait(5) and {})
    with pytest.raises(BusyError):
        runner.submit("dedup", "测试书", lambda p: {})
    gate.set()
    runner.wait(first.id)
    second = runner.wait(runner.submit("dedup", "测试书", lambda p: {}).id)
    assert second.status == "done"


def test_get_unknown():
    assert JobRunner().get("nope") is None
    assert JobRunner().current() is None
