"""Task execution port for Celery servers and local desktop runtimes."""

from __future__ import annotations

import uuid
from collections.abc import Callable
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass
from functools import lru_cache
from typing import Any, Protocol, runtime_checkable

from app.core.config import get_settings


@dataclass(frozen=True, slots=True)
class JobSubmission:
    id: str
    backend: str


@runtime_checkable
class JobRunner(Protocol):
    def submit(self, task: Callable[..., Any], **kwargs: Any) -> JobSubmission: ...

    def shutdown(self) -> None: ...


class InProcessJobRunner:
    """Run short local jobs serially without Redis or a separate worker."""

    def __init__(self, max_workers: int = 1) -> None:
        self._executor = ThreadPoolExecutor(
            max_workers=max_workers,
            thread_name_prefix="lifetree-local-job",
        )
        self._futures: dict[str, Future[Any]] = {}

    def submit(self, task: Callable[..., Any], **kwargs: Any) -> JobSubmission:
        job_id = str(uuid.uuid4())
        future = self._executor.submit(task, **kwargs)
        self._futures[job_id] = future
        future.add_done_callback(lambda _future: self._futures.pop(job_id, None))
        return JobSubmission(id=job_id, backend="in_process")

    def shutdown(self) -> None:
        self._executor.shutdown(wait=False, cancel_futures=True)


class CeleryJobRunner:
    def submit(self, task: Callable[..., Any], **kwargs: Any) -> JobSubmission:
        delay = getattr(task, "delay", None)
        if not callable(delay):
            raise TypeError("CeleryJobRunner requires a Celery task")
        result = delay(**kwargs)
        return JobSubmission(id=str(result.id), backend="celery")

    def shutdown(self) -> None:
        return None


@lru_cache(maxsize=1)
def get_job_runner() -> JobRunner:
    if get_settings().lifetree_storage_mode == "local":
        return InProcessJobRunner()
    return CeleryJobRunner()


def close_job_runner() -> None:
    if get_job_runner.cache_info().currsize:
        get_job_runner().shutdown()
    get_job_runner.cache_clear()


__all__ = [
    "CeleryJobRunner",
    "InProcessJobRunner",
    "JobRunner",
    "JobSubmission",
    "close_job_runner",
    "get_job_runner",
]
