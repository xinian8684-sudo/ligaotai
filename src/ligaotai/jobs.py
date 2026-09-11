"""后台任务队列：一次只跑一个任务，跑在单独的线程里。"""

from __future__ import annotations

import logging
import threading
import traceback
import uuid
from dataclasses import asdict, dataclass
from typing import Callable

from .book import now_iso

log = logging.getLogger(__name__)


@dataclass
class Job:
    id: str
    name: str
    book: str
    status: str = "queued"  # queued / running / done / failed / cancelled
    done: int = 0
    total: int = 0
    message: str = ""
    error: str = ""
    result: dict | None = None
    started: str = ""
    finished: str = ""
    cancel_requested: bool = False

    def to_dict(self) -> dict:
        return asdict(self)


class BusyError(RuntimeError):
    pass


class JobCancelled(Exception):
    """作者点了暂停。已经做完的部分都落了盘，重跑会接着做。"""


class JobRunner:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._jobs: dict[str, Job] = {}
        self._threads: dict[str, threading.Thread] = {}
        self._current: Job | None = None

    def submit(self, name: str, book: str, fn: Callable[[Callable], dict]) -> Job:
        with self._lock:
            cur = self._current
            if cur is not None and cur.status in ("queued", "running"):
                raise BusyError(f"已有任务在跑：{cur.name}（{cur.book}）")
            job = Job(id=uuid.uuid4().hex[:8], name=name, book=book)
            self._jobs[job.id] = job
            self._current = job
            thread = threading.Thread(target=self._run, args=(job, fn), daemon=True)
            self._threads[job.id] = thread
        thread.start()
        return job

    def _run(self, job: Job, fn: Callable[[Callable], dict]) -> None:
        job.status = "running"
        job.started = now_iso()

        def progress(done: int, total: int, message: str = "") -> None:
            if job.cancel_requested:
                raise JobCancelled("已暂停")
            job.done, job.total = done, total
            if message:
                job.message = message

        try:
            job.result = fn(progress)
            job.finished = now_iso()
            job.status = "done"
        except JobCancelled:
            job.error = "已暂停"
            job.finished = now_iso()
            job.status = "cancelled"
        except BaseException as e:  # 含 asyncio.CancelledError，漏接会让任务永远卡在 running
            job.error = f"{type(e).__name__}: {e}"
            job.finished = now_iso()
            job.status = "failed"
            log.error("任务失败 %s\n%s", job.name, traceback.format_exc())

    def cancel(self, job_id: str) -> Job | None:
        job = self._jobs.get(job_id)
        if job is not None and job.status in ("queued", "running"):
            job.cancel_requested = True
        return job

    def get(self, job_id: str) -> Job | None:
        return self._jobs.get(job_id)

    def current(self) -> Job | None:
        return self._current

    def wait(self, job_id: str, timeout: float = 30.0) -> Job:
        thread = self._threads.get(job_id)
        if thread is not None:
            thread.join(timeout)
        return self._jobs[job_id]
