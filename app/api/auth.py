from fastapi import APIRouter, status

from app.api.deps import ClientDep, SessionDep, SettingsDep
from app.errors import ForbiddenError
from app.schemas import ApiClientRead, ApiKeyCreate, ApiKeyCreated, ErrorResponse
from app.services import auth as auth_service

router = APIRouter(prefix="/api/auth", tags=["auth"])


@router.post(
    "/keys/",
    status_code=status.HTTP_201_CREATED,
    response_model=ApiKeyCreated,
    responses={403: {"model": ErrorResponse, "description": "Self-service keys are disabled"}},
)
def create_key(body: ApiKeyCreate, session: SessionDep, settings: SettingsDep) -> ApiKeyCreated:
    """Create an API key. Store it: it is returned only once. Files uploaded with a key are
    visible only to that key."""
    if not settings.allow_key_signup:
        raise ForbiddenError("Self-service API keys are disabled; ask an administrator for one.")
    client, key = auth_service.create_client(session, body.name)
    return ApiKeyCreated(
        id=client.id,
        name=client.name,
        key_prefix=client.key_prefix,
        created_at=client.created_at,
        api_key=key,
    )


@router.get(
    "/me/",
    response_model=ApiClientRead,
    responses={401: {"model": ErrorResponse, "description": "Missing or invalid API key"}},
)
def whoami(client: ClientDep) -> ApiClientRead:
    """The API client that owns the key in `X-API-Key`."""
    return ApiClientRead.model_validate(client)
