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


def test_base_exception_does_not_wedge_runner():
    import asyncio

    runner = JobRunner()

    def fn(progress):
        raise asyncio.CancelledError()

    job = runner.wait(runner.submit("cards", "测试书", fn).id)
    assert job.status == "failed"
    assert job.error.startswith("CancelledError")
    assert runner.wait(runner.submit("dedup", "测试书", lambda p: {}).id).status == "done"


def test_cancel_running_job():
    from ligaotai.jobs import JobCancelled  # noqa: F401  确认异常类存在

    runner = JobRunner()
    started, release = threading.Event(), threading.Event()

    def fn(progress):
        started.set()
        release.wait(5)
        progress(1, 2)  # 这里发现已请求暂停
        return {}

    job = runner.submit("cards", "测试书", fn)
    started.wait(5)
    assert runner.cancel(job.id) is job
    release.set()
    job = runner.wait(job.id)
    assert (job.status, job.error) == ("cancelled", "已暂停")
    assert runner.wait(runner.submit("x", "测试书", lambda p: {}).id).status == "done"


def test_cancel_finished_or_unknown_job():
    runner = JobRunner()
    job = runner.wait(runner.submit("x", "测试书", lambda p: {}).id)
    runner.cancel(job.id)
    assert job.status == "done" and job.cancel_requested is False
    assert runner.cancel("nope") is None
