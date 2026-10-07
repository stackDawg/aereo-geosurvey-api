"""Scheduling of file processing.

Two interchangeable dispatchers:

* :class:`InProcessDispatcher` (default) runs processing in the API process after the response
  is sent, using FastAPI background tasks. Zero infrastructure, ideal for development and small
  deployments, but work is lost if the process restarts.
* :class:`RQDispatcher` (when ``GEOAPI_REDIS_URL`` is set) puts a job on a Redis queue for
  ``rq worker`` processes. Jobs survive API restarts, and workers scale independently.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

from fastapi import BackgroundTasks
from sqlalchemy.orm import sessionmaker

from app.config import Settings
from app.services.processing import process_file

if TYPE_CHECKING:
    from rq import Queue

# Imported by name in the worker, so the API does not need to import worker code.
JOB_FUNCTION = "app.worker.process_file_job"


class DispatchError(Exception):
    """Processing could not be scheduled (e.g. Redis is unreachable)."""


class ProcessingDispatcher(Protocol):
    def dispatch(self, file_id: str, background_tasks: BackgroundTasks) -> None: ...


class InProcessDispatcher:
    def __init__(self, session_factory: sessionmaker, settings: Settings) -> None:
        self.session_factory = session_factory
        self.settings = settings

    def dispatch(self, file_id: str, background_tasks: BackgroundTasks) -> None:
        background_tasks.add_task(process_file, file_id, self.session_factory, self.settings)


class RQDispatcher:
    def __init__(self, queue: Queue, job_timeout: int) -> None:
        self.queue = queue
        self.job_timeout = job_timeout

    def dispatch(self, file_id: str, background_tasks: BackgroundTasks) -> None:
        from redis.exceptions import RedisError

        try:
            self.queue.enqueue(
                JOB_FUNCTION,
                file_id,
                job_id=f"process-{file_id}",  # traceable back to the file
                job_timeout=self.job_timeout,
                description=f"Process file {file_id}",
            )
        except RedisError as exc:
            raise DispatchError(f"Could not queue file {file_id}: {exc}") from exc


def create_dispatcher(settings: Settings, session_factory: sessionmaker) -> ProcessingDispatcher:
    if not settings.redis_url:
        return InProcessDispatcher(session_factory, settings)

    from redis import Redis
    from rq import Queue

    queue = Queue(settings.queue_name, connection=Redis.from_url(settings.redis_url))
    return RQDispatcher(queue, settings.job_timeout_seconds)
