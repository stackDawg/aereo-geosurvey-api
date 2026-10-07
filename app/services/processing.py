"""File-processing pipeline: read features -> measure -> persist.

Runs outside the request (as a FastAPI background task today). It only needs a file ID, a
session factory and settings, so it can be moved to a Celery/RQ worker unchanged.
"""

from __future__ import annotations

import logging
import time
from collections import Counter
from dataclasses import replace
from pathlib import Path
from typing import Any

from pyproj import CRS
from shapely.geometry import mapping
from sqlalchemy import delete, insert
from sqlalchemy.orm import Session, sessionmaker

from app.config import Settings
from app.geo.crs import ProjectionStrategy, crs_to_string, get_strategy, parse_crs
from app.geo.errors import InvalidGeoFileError
from app.geo.measure import Measurement, MeasurementStatus, measure_geometry
from app.geo.readers import get_reader
from app.geo.types import SourceFeature
from app.models import Feature, FileStatus, GeoFile, utcnow
from app.services.files import archive_limits, mark_failed

logger = logging.getLogger(__name__)

INSERT_BATCH_SIZE = 1000


def process_file(file_id: str, session_factory: sessionmaker, settings: Settings) -> None:
    """Process an uploaded file, moving it to COMPLETED or FAILED. Never raises."""
    started = time.perf_counter()
    with session_factory() as session:
        geo_file = session.get(GeoFile, file_id)
        if geo_file is None:
            logger.warning("File %s was deleted before it could be processed", file_id)
            return
        geo_file.status = FileStatus.PROCESSING
        session.commit()

        try:
            _process(session, geo_file, settings)
        except InvalidGeoFileError as exc:
            logger.info("File %s could not be read: %s", file_id, exc)
            _mark_failed(session, file_id, str(exc))
        except Exception:
            logger.exception("Unexpected error while processing file %s", file_id)
            _mark_failed(session, file_id, "Unexpected error while processing the file.")
        else:
            logger.info(
                "Processed file %s: %d features in %.2fs",
                file_id,
                geo_file.feature_count,
                time.perf_counter() - started,
            )


def _process(session: Session, geo_file: GeoFile, settings: Settings) -> None:
    strategy = get_strategy(settings.measurement_crs_strategy)
    fallback_crs = parse_crs(geo_file.source_crs) if geo_file.source_crs else None

    # Start from a clean slate so that re-processing a file is idempotent.
    session.execute(delete(Feature).where(Feature.file_id == geo_file.id))

    counts: Counter[str] = Counter()
    batch: list[dict[str, Any]] = []
    reader_cls = get_reader(geo_file.file_type)
    with reader_cls(Path(geo_file.storage_path), archive_limits(settings)) as reader:
        for index, source in enumerate(reader.features()):
            batch.append(
                _feature_row(geo_file.id, index, source, source.crs or fallback_crs, strategy)
            )
            counts[source.layer] += 1
            if len(batch) >= INSERT_BATCH_SIZE:
                session.execute(insert(Feature), batch)
                batch.clear()
        if batch:
            session.execute(insert(Feature), batch)
        declared_crs = dict(reader.layers)
        warnings = list(reader.warnings)

    layers = [
        {
            "name": name,
            "crs": _crs_string(crs or fallback_crs),
            "feature_count": counts[name],
        }
        for name, crs in declared_crs.items()
    ]
    if any(crs is None for crs in declared_crs.values()):
        if fallback_crs is not None:
            warnings.append(
                f"Using the supplied source_crs {geo_file.source_crs} where none is declared."
            )
        else:
            warnings.append(
                "Features without a known CRS were not measured. Re-upload with the "
                "`source_crs` form field to measure them."
            )
    layer_crs = {layer["crs"] for layer in layers}
    if len(layer_crs) > 1:
        warnings.append("Layers use different CRSs; see `layers` for each layer's CRS.")

    geo_file.crs = layer_crs.pop() if len(layer_crs) == 1 else None
    geo_file.layers = layers
    geo_file.warnings = warnings
    geo_file.feature_count = counts.total()
    geo_file.status = FileStatus.COMPLETED
    geo_file.error = None
    geo_file.processed_at = utcnow()
    session.commit()


def _mark_failed(session: Session, file_id: str, error: str) -> None:
    session.rollback()
    geo_file = session.get(GeoFile, file_id)
    if geo_file is not None:
        mark_failed(session, geo_file, error)


def _crs_string(crs: CRS | None) -> str | None:
    return crs_to_string(crs) if crs is not None else None


def measure_feature(
    source: SourceFeature, crs: CRS | None, strategy: ProjectionStrategy
) -> Measurement:
    if source.unsupported_reason:
        return Measurement(MeasurementStatus.UNSUPPORTED, message=source.unsupported_reason)
    if source.geometry is None and source.issue:
        return Measurement(MeasurementStatus.FAILED, message=source.issue)
    measurement = measure_geometry(source.geometry, crs, strategy)
    if source.issue:
        message = " ".join(m for m in (source.issue, measurement.message) if m)
        measurement = replace(measurement, message=message)
    return measurement


def _feature_row(
    file_id: str,
    index: int,
    source: SourceFeature,
    crs: CRS | None,
    strategy: ProjectionStrategy,
) -> dict[str, Any]:
    measurement = measure_feature(source, crs, strategy)
    return {
        "file_id": file_id,
        "feature_index": index,
        "layer": source.layer,
        "feature_id": source.feature_id,
        "geometry_type": source.geometry_type,
        "crs": _crs_string(crs),
        "geometry": mapping(source.geometry) if source.geometry is not None else None,
        "properties": source.properties,
        "measurement_status": measurement.status,
        "area_m2": measurement.area_m2,
        "perimeter_m": measurement.perimeter_m,
        "length_m": measurement.length_m,
        "measurement_crs": measurement.measurement_crs,
        "measurement_message": measurement.message,
    }
