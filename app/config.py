from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict

MB = 1024 * 1024


class Settings(BaseSettings):
    """Runtime configuration, read from ``GEOAPI_*`` environment variables or a ``.env`` file."""

    model_config = SettingsConfigDict(env_prefix="GEOAPI_", env_file=".env", extra="ignore")

    database_url: str = "sqlite:///./data/geoapi.db"
    storage_dir: Path = Path("./data/uploads")

    # Upload / archive limits. The archive limits guard against zip bombs.
    max_upload_size_mb: int = 100
    max_extracted_size_mb: int = 500
    max_archive_members: int = 1000

    # How the projected CRS used for measuring is chosen; see app/geo/crs.py.
    measurement_crs_strategy: Literal["utm", "laea"] = "utm"

    # With a Redis URL, uploads are processed by RQ workers (`rq worker geo-processing`);
    # without one, they are processed in the API process after the response is sent.
    redis_url: str | None = None
    queue_name: str = "geo-processing"
    job_timeout_seconds: int = 1800

    # Let anyone create an API key with POST /api/auth/keys/ (convenient for a public demo).
    # When disabled, keys are created with `python -m app.cli create-key NAME`.
    allow_key_signup: bool = True

    # Built map viewer (frontend/) served at "/" when present.
    frontend_dir: Path = Path("./frontend/dist")

    log_level: str = "INFO"

    @property
    def max_upload_bytes(self) -> int:
        return self.max_upload_size_mb * MB

    @property
    def max_extracted_bytes(self) -> int:
        return self.max_extracted_size_mb * MB


@lru_cache
def get_settings() -> Settings:
    return Settings()
