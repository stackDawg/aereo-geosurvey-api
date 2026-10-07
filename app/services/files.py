"""Use cases behind the /api/files endpoints: storing uploads and querying results.

Every query is scoped to the owner: a file that belongs to another API client is reported as
not found, so its existence is not revealed.
"""

from __future__ import annotations

import shutil
import uuid
from pathlib import Path, PurePosixPath
from typing import Any, BinaryIO

from pyproj import CRS
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import Settings
from app.errors import (
    ConflictError,
    FileTooLargeError,
    InvalidRequestError,
    InvalidUploadError,
    NotFoundError,
    UnsupportedFileTypeError,
)
from app.geo.crs import ProjectionError, crs_to_string, parse_crs, reproject_geojson
from app.geo.errors import InvalidCRSError, InvalidGeoFileError
from app.geo.measure import MeasurementStatus
from app.geo.readers import ArchiveLimits, get_reader
from app.geo.types import SUPPORTED_EXTENSIONS, FileType
from app.models import Feature, FileStatus, GeoFile, utcnow

CHUNK_SIZE = 1024 * 1024
MAX_FILENAME_LENGTH = 255


def archive_limits(settings: Settings) -> ArchiveLimits:
    return ArchiveLimits(settings.max_archive_members, settings.max_extracted_bytes)


def create_file(
    session: Session,
    settings: Settings,
    *,
    owner_id: str,
    filename: str,
    stream: BinaryIO,
    source_crs: str | None = None,
) -> GeoFile:
    """Validate and store an upload, and register it for processing (status PENDING)."""
    name = PurePosixPath((filename or "").replace("\\", "/")).name
    file_type = FileType.from_filename(name)
    if file_type is None:
        raise UnsupportedFileTypeError(
            f"Unsupported file '{name}'. Upload one of: {', '.join(SUPPORTED_EXTENSIONS)} "
            "(a Shapefile must be uploaded as a .zip)."
        )

    normalized_crs = None
    if source_crs and source_crs.strip():
        try:
            normalized_crs = crs_to_string(parse_crs(source_crs.strip()))
        except InvalidCRSError as exc:
            raise InvalidUploadError(str(exc)) from exc

    file_id = uuid.uuid4().hex
    directory = (settings.storage_dir / file_id).resolve()
    path = directory / f"original{PurePosixPath(name).suffix.lower()}"
    try:
        size = _save_stream(stream, path, settings.max_upload_bytes)
        if size == 0:
            raise InvalidUploadError("The uploaded file is empty.")
        get_reader(file_type).validate(path, archive_limits(settings))
    except InvalidGeoFileError as exc:
        shutil.rmtree(directory, ignore_errors=True)
        raise InvalidUploadError(str(exc)) from exc
    except BaseException:
        shutil.rmtree(directory, ignore_errors=True)
        raise

    geo_file = GeoFile(
        id=file_id,
        owner_id=owner_id,
        filename=name[-MAX_FILENAME_LENGTH:],
        file_type=file_type,
        size_bytes=size,
        storage_path=str(path),
        status=FileStatus.PENDING,
        source_crs=normalized_crs,
    )
    session.add(geo_file)
    session.commit()
    return geo_file


def _save_stream(stream: BinaryIO, path: Path, max_bytes: int) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    size = 0
    with path.open("wb") as out:
        while chunk := stream.read(CHUNK_SIZE):
            size += len(chunk)
            if size > max_bytes:
                raise FileTooLargeError(
                    f"File exceeds the {max_bytes // CHUNK_SIZE} MB upload limit."
                )
            out.write(chunk)
    return size


def mark_failed(session: Session, geo_file: GeoFile, error: str) -> None:
    geo_file.status = FileStatus.FAILED
    geo_file.error = error
    geo_file.processed_at = utcnow()
    session.commit()


def get_file(session: Session, file_id: str, owner_id: str) -> GeoFile:
    geo_file = session.get(GeoFile, file_id)
    if geo_file is None or geo_file.owner_id != owner_id:
        raise NotFoundError(f"File '{file_id}' not found.")
    return geo_file


def get_processed_file(session: Session, file_id: str, owner_id: str) -> GeoFile:
    """Like :func:`get_file`, but the file's features must be available."""
    geo_file = get_file(session, file_id, owner_id)
    if geo_file.status == FileStatus.FAILED:
        raise ConflictError(f"Processing of file '{file_id}' failed: {geo_file.error}")
    if geo_file.status != FileStatus.COMPLETED:
        raise ConflictError(
            f"File '{file_id}' is {geo_file.status}; results are available once it is COMPLETED."
        )
    return geo_file


def list_files(
    session: Session, owner_id: str, *, limit: int, offset: int
) -> tuple[list[GeoFile], int]:
    owned = GeoFile.owner_id == owner_id
    total = session.scalar(select(func.count()).select_from(GeoFile).where(owned)) or 0
    files = session.scalars(
        select(GeoFile).where(owned).order_by(GeoFile.created_at.desc()).limit(limit).offset(offset)
    ).all()
    return list(files), total


def delete_file(session: Session, file_id: str, owner_id: str) -> None:
    geo_file = get_file(session, file_id, owner_id)
    if geo_file.status in (FileStatus.PENDING, FileStatus.PROCESSING):
        raise ConflictError(f"File '{file_id}' is {geo_file.status} and cannot be deleted yet.")
    storage_dir = Path(geo_file.storage_path).parent
    session.delete(geo_file)
    session.commit()
    shutil.rmtree(storage_dir, ignore_errors=True)


def list_features(
    session: Session, file_id: str, owner_id: str, *, limit: int, offset: int
) -> tuple[list[Feature], int]:
    geo_file = get_processed_file(session, file_id, owner_id)
    features = session.scalars(
        select(Feature)
        .where(Feature.file_id == file_id)
        .order_by(Feature.feature_index)
        .limit(limit)
        .offset(offset)
    ).all()
    return list(features), geo_file.feature_count or 0


def parse_output_crs(value: str | None) -> CRS | None:
    if not value:
        return None
    try:
        return parse_crs(value)
    except InvalidCRSError as exc:
        raise InvalidRequestError(str(exc)) from exc


def feature_geometry(
    feature: Feature, target: CRS | None
) -> tuple[dict[str, Any] | None, str | None]:
    """The feature's GeoJSON geometry and its CRS, reprojected to ``target`` where possible.

    Features whose CRS is unknown, or that cannot be transformed, keep their source geometry
    and CRS, so clients can tell which geometries were reprojected.
    """
    if target is None or feature.geometry is None or feature.crs is None:
        return feature.geometry, feature.crs
    try:
        geometry = reproject_geojson(feature.geometry, parse_crs(feature.crs), target)
    except (InvalidCRSError, ProjectionError):
        return feature.geometry, feature.crs
    return geometry, crs_to_string(target)


def summarize_measurements(session: Session, file_id: str, owner_id: str) -> dict[str, Any]:
    """Totals across all of a file's features (independent of pagination)."""
    get_processed_file(session, file_id, owner_id)
    count, total_area, total_length = session.execute(
        select(func.count(), func.sum(Feature.area_m2), func.sum(Feature.length_m)).where(
            Feature.file_id == file_id
        )
    ).one()
    by_status = dict(
        session.execute(
            select(Feature.measurement_status, func.count())
            .where(Feature.file_id == file_id)
            .group_by(Feature.measurement_status)
        ).all()
    )
    by_geometry_type = {
        geometry_type or "None": n
        for geometry_type, n in session.execute(
            select(Feature.geometry_type, func.count())
            .where(Feature.file_id == file_id)
            .group_by(Feature.geometry_type)
        ).all()
    }
    return {
        "feature_count": count,
        "measured_count": by_status.get(MeasurementStatus.MEASURED, 0),
        "total_area_m2": round(total_area or 0.0, 3),
        "total_length_m": round(total_length or 0.0, 3),
        "by_status": by_status,
        "by_geometry_type": by_geometry_type,
    }
