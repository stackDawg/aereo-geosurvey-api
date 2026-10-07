from collections.abc import Iterator
from typing import Annotated

from fastapi import Depends, Query, Request, Security
from fastapi.security import APIKeyHeader
from sqlalchemy.orm import Session, sessionmaker

from app.config import Settings
from app.errors import UnauthorizedError
from app.models import ApiClient
from app.services import auth as auth_service
from app.services.tasks import ProcessingDispatcher

api_key_header = APIKeyHeader(
    name="X-API-Key",
    auto_error=False,
    description="Create a key with `POST /api/auth/keys/`.",
)


def get_settings(request: Request) -> Settings:
    return request.app.state.settings


def get_session_factory(request: Request) -> sessionmaker:
    return request.app.state.session_factory


def get_dispatcher(request: Request) -> ProcessingDispatcher:
    return request.app.state.dispatcher


def get_session(
    session_factory: Annotated[sessionmaker, Depends(get_session_factory)],
) -> Iterator[Session]:
    with session_factory() as session:
        yield session


SessionDep = Annotated[Session, Depends(get_session)]


def get_current_client(
    session: SessionDep, api_key: Annotated[str | None, Security(api_key_header)]
) -> ApiClient:
    if not api_key:
        raise UnauthorizedError("Missing API key: send it in the X-API-Key header.")
    client = auth_service.authenticate(session, api_key)
    if client is None:
        raise UnauthorizedError("Invalid API key.")
    return client


SettingsDep = Annotated[Settings, Depends(get_settings)]
DispatcherDep = Annotated[ProcessingDispatcher, Depends(get_dispatcher)]
ClientDep = Annotated[ApiClient, Depends(get_current_client)]
LimitParam = Annotated[int, Query(ge=1, le=10_000, description="Maximum number of items.")]
OffsetParam = Annotated[int, Query(ge=0, description="Number of items to skip.")]
