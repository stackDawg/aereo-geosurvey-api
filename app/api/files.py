from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, File, Form, Query, Response, UploadFile, status

from app.api.deps import (
    ClientDep,
    DispatcherDep,
    LimitParam,
    OffsetParam,
    SessionDep,
    SettingsDep,
)
from app.errors import FileTooLargeError, ServiceUnavailableError
from app.schemas import (
    ErrorResponse,
    FeatureList,
    FeatureMeasurement,
    FeatureRead,
    FileList,
    FileRead,
    MeasurementList,
)
from app.services import files as file_service
from app.services.tasks import DispatchError

router = APIRouter(
    prefix="/api/files",
    tags=["files"],
    responses={401: {"model": ErrorResponse, "description": "Missing or invalid API key"}},
)

NOT_FOUND = {404: {"model": ErrorResponse, "description": "File not found"}}
NOT_READY = {409: {"model": ErrorResponse, "description": "File not processed (yet)"}}


@router.post(
    "/",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=FileRead,
    responses={
        413: {"model": ErrorResponse, "description": "File too large"},
        415: {"model": ErrorResponse, "description": "Unsupported file type"},
        422: {"model": ErrorResponse, "description": "Invalid file or CRS"},
        503: {"model": ErrorResponse, "description": "Processing queue unavailable"},
    },
)
def upload_file(
    response: Response,
    background_tasks: BackgroundTasks,
    client: ClientDep,
    session: SessionDep,
    settings: SettingsDep,
    dispatcher: DispatcherDep,
    file: Annotated[UploadFile, File(description="A .zip Shapefile, .kml or .kmz file.")],
    source_crs: Annotated[
        str | None,
        Form(
            description="CRS to assume for data that does not declare one, e.g. a Shapefile "
            "without a .prj. Any pyproj-readable definition, e.g. `EPSG:32643`.",
        ),
    ] = None,
) -> FileRead:
    """Upload a geospatial file. It is validated immediately and processed in the background:
    poll `GET /api/files/{id}/` until `status` is `COMPLETED` (or `FAILED`)."""
    if file.size is not None and file.size > settings.max_upload_bytes:
        # Cheap early exit; create_file enforces the limit again while copying.
        raise FileTooLargeError(f"File exceeds the {settings.max_upload_size_mb} MB upload limit.")
    geo_file = file_service.create_file(
        session,
        settings,
        owner_id=client.id,
        filename=file.filename or "",
        stream=file.file,
        source_crs=source_crs,
    )
    try:
        dispatcher.dispatch(geo_file.id, background_tasks)
    except DispatchError as exc:
        file_service.mark_failed(session, geo_file, "The file could not be queued for processing.")
        raise ServiceUnavailableError("Processing queue unavailable; try again later.") from exc
    response.headers["Location"] = f"{router.prefix}/{geo_file.id}/"
    return FileRead.model_validate(geo_file)


@router.get("/", response_model=FileList)
def list_files(
    client: ClientDep, session: SessionDep, limit: LimitParam = 50, offset: OffsetParam = 0
) -> FileList:
    """Your uploaded files, newest first."""
    files, total = file_service.list_files(session, client.id, limit=limit, offset=offset)
    return FileList(
        total=total,
        limit=limit,
        offset=offset,
        items=[FileRead.model_validate(f) for f in files],
    )


@router.get("/{file_id}/", response_model=FileRead, responses=NOT_FOUND)
def get_file(file_id: str, client: ClientDep, session: SessionDep) -> FileRead:
    """Processing status and metadata of an uploaded file."""
    return FileRead.model_validate(file_service.get_file(session, file_id, client.id))


@router.delete(
    "/{file_id}/", status_code=status.HTTP_204_NO_CONTENT, responses={**NOT_FOUND, **NOT_READY}
)
def delete_file(file_id: str, client: ClientDep, session: SessionDep) -> None:
    """Delete a file, its stored upload and its features."""
    file_service.delete_file(session, file_id, client.id)


@router.get(
    "/{file_id}/features/",
    response_model=FeatureList,
    responses={**NOT_FOUND, **NOT_READY, 422: {"model": ErrorResponse}},
)
def list_features(
    file_id: str,
    client: ClientDep,
    session: SessionDep,
    limit: LimitParam = 1000,
    offset: OffsetParam = 0,
    crs: Annotated[
        str | None,
        Query(
            description="Reproject geometries to this CRS, e.g. `EPSG:4326` for web maps. "
            "Defaults to each feature's source CRS.",
        ),
    ] = None,
) -> FeatureList:
    """Features with their geometry (GeoJSON), properties and measurement."""
    target = file_service.parse_output_crs(crs)
    features, total = file_service.list_features(
        session, file_id, client.id, limit=limit, offset=offset
    )
    return FeatureList(
        total=total,
        limit=limit,
        offset=offset,
        items=[
            FeatureRead.from_model(f, *file_service.feature_geometry(f, target)) for f in features
        ],
    )


@router.get(
    "/{file_id}/measurements/",
    response_model=MeasurementList,
    responses={**NOT_FOUND, **NOT_READY},
)
def list_measurements(
    file_id: str,
    client: ClientDep,
    session: SessionDep,
    limit: LimitParam = 1000,
    offset: OffsetParam = 0,
) -> MeasurementList:
    """Per-feature measurements plus totals for the whole file.

    Areas are in square metres and lengths in metres, measured in the projected CRS reported
    for each feature."""
    summary = file_service.summarize_measurements(session, file_id, client.id)
    features, total = file_service.list_features(
        session, file_id, client.id, limit=limit, offset=offset
    )
    return MeasurementList(
        file_id=file_id,
        summary=summary,
        total=total,
        limit=limit,
        offset=offset,
        items=[FeatureMeasurement.from_model(f) for f in features],
    )
