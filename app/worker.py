"""RQ worker entry point.

Run a worker with::

    rq worker --url "$GEOAPI_REDIS_URL" geo-processing

Workers need the same ``GEOAPI_DATABASE_URL`` as the API and access to the same upload storage.
"""

from __future__ import annotations

import logging
from functools import lru_cache

from sqlalchemy.orm import sessionmaker

from app.config import Settings, get_settings
from app.database import create_db_engine, create_session_factory
from app.services.processing import process_file


@lru_cache
def _context() -> tuple[sessionmaker, Settings]:
    settings = get_settings()
    logging.basicConfig(
        level=settings.log_level.upper(),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    return create_session_factory(create_db_engine(settings.database_url)), settings


def process_file_job(file_id: str) -> None:
    session_factory, settings = _context()
    process_file(file_id, session_factory, settings)
