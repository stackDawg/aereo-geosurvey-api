"""Processing dispatch: in-process (default) and Redis/RQ."""

import os

import fakeredis
import pytest
from redis import Redis
from redis.backoff import NoBackoff
from redis.retry import Retry
from rq import Queue

from app import worker
from app.services.tasks import InProcessDispatcher, RQDispatcher, create_dispatcher
from tests.test_api import SURVEY_KML, upload


@pytest.fixture
def use_test_context(app, monkeypatch):
    """Make RQ jobs use the test app's database instead of the environment's."""
    monkeypatch.setattr(worker, "_context", lambda: (app.state.session_factory, app.state.settings))


def test_default_dispatcher_is_in_process(settings, app):
    assert isinstance(app.state.dispatcher, InProcessDispatcher)


def test_redis_url_selects_rq(settings, app):
    settings.redis_url = "redis://localhost:6379/0"
    dispatcher = create_dispatcher(settings, app.state.session_factory)

    assert isinstance(dispatcher, RQDispatcher)
    assert dispatcher.queue.name == "geo-processing"


def test_upload_is_processed_by_rq_job(app, client, use_test_context):
    # A synchronous queue runs the job as soon as it is enqueued, exercising the real job path.
    queue = Queue("geo-processing", connection=fakeredis.FakeRedis(), is_async=False)
    app.state.dispatcher = RQDispatcher(queue, job_timeout=60)

    file_id = upload(client, "survey.kml", SURVEY_KML).json()["id"]

    job = queue.fetch_job(f"process-{file_id}")
    assert job.func_name == "app.worker.process_file_job"
    assert job.args == (file_id,)
    assert client.get(f"/api/files/{file_id}/").json()["status"] == "COMPLETED"


def test_upload_fails_cleanly_when_queue_is_unreachable(app, client):
    unreachable = Redis(
        host="127.0.0.1", port=1, socket_connect_timeout=0.2, retry=Retry(NoBackoff(), 0)
    )
    app.state.dispatcher = RQDispatcher(Queue("geo-processing", connection=unreachable), 60)

    response = upload(client, "survey.kml", SURVEY_KML)

    assert response.status_code == 503
    [geo_file] = client.get("/api/files/").json()["items"]
    assert geo_file["status"] == "FAILED"
    assert "queued" in geo_file["error"]


@pytest.mark.skipif(
    not os.environ.get("GEOAPI_TEST_REDIS_URL"), reason="needs a Redis server (runs in CI)"
)
def test_rq_worker_processes_queued_upload(app, client, use_test_context):
    from rq import SimpleWorker

    redis = Redis.from_url(os.environ["GEOAPI_TEST_REDIS_URL"])
    queue = Queue(f"test-{os.getpid()}", connection=redis)
    app.state.dispatcher = RQDispatcher(queue, job_timeout=60)

    file_id = upload(client, "survey.kml", SURVEY_KML).json()["id"]
    assert client.get(f"/api/files/{file_id}/").json()["status"] == "PENDING"

    SimpleWorker([queue], connection=redis).work(burst=True)

    assert client.get(f"/api/files/{file_id}/").json()["status"] == "COMPLETED"
