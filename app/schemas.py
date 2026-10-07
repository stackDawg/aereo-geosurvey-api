from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.geo.measure import MeasurementStatus
from app.geo.types import FileType
from app.models import Feature, FileStatus


class LayerRead(BaseModel):
    name: str
    crs: str | None
    feature_count: int


class FileRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    filename: str
    file_type: FileType
    size_bytes: int
    status: FileStatus
    crs: str | None = Field(description="CRS of the file's features; null if unknown or mixed.")
    source_crs: str | None = Field(description="CRS supplied at upload for files without one.")
    feature_count: int | None
    layers: list[LayerRead]
    warnings: list[str]
    error: str | None
    created_at: datetime
    processed_at: datetime | None


class Page(BaseModel):
    total: int
    limit: int
    offset: int


class FileList(Page):
    items: list[FileRead]


class Measurement(BaseModel):
    status: MeasurementStatus
    area_m2: float | None = Field(description="Area in square metres (polygons).")
    perimeter_m: float | None = Field(description="Perimeter in metres, holes included.")
    length_m: float | None = Field(description="Length in metres (lines).")
    measurement_crs: str | None = Field(description="Projected CRS the geometry was measured in.")
    message: str | None


def _measurement(feature: Feature) -> dict[str, Any]:
    return {
        "status": feature.measurement_status,
        "area_m2": feature.area_m2,
        "perimeter_m": feature.perimeter_m,
        "length_m": feature.length_m,
        "measurement_crs": feature.measurement_crs,
        "message": feature.measurement_message,
    }


class FeatureRef(BaseModel):
    feature_index: int = Field(description="0-based position of the feature in the file.")
    feature_id: str | None = Field(description="Identifier from the source file, if any.")
    layer: str
    geometry_type: str | None


class FeatureRead(FeatureRef):
    crs: str | None = Field(description="CRS of `geometry`.")
    geometry: dict[str, Any] | None = Field(description="GeoJSON geometry, in `crs`.")
    properties: dict[str, Any]
    measurement: Measurement

    @classmethod
    def from_model(
        cls, feature: Feature, geometry: dict[str, Any] | None, crs: str | None
    ) -> FeatureRead:
        return cls(
            feature_index=feature.feature_index,
            feature_id=feature.feature_id,
            layer=feature.layer,
            geometry_type=feature.geometry_type,
            crs=crs,
            geometry=geometry,
            properties=feature.properties,
            measurement=Measurement(**_measurement(feature)),
        )


class FeatureList(Page):
    items: list[FeatureRead]


# Pydantic orders inherited fields base-last-first, so the feature reference comes first.
class FeatureMeasurement(Measurement, FeatureRef):
    @classmethod
    def from_model(cls, feature: Feature) -> FeatureMeasurement:
        return cls(
            feature_index=feature.feature_index,
            feature_id=feature.feature_id,
            layer=feature.layer,
            geometry_type=feature.geometry_type,
            **_measurement(feature),
        )


class MeasurementSummary(BaseModel):
    feature_count: int
    measured_count: int
    total_area_m2: float
    total_length_m: float
    by_status: dict[MeasurementStatus, int]
    by_geometry_type: dict[str, int]


class MeasurementList(Page):
    file_id: str
    summary: MeasurementSummary
    items: list[FeatureMeasurement]


class ErrorResponse(BaseModel):
    detail: str


class ApiKeyCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100, description="Who the key is for.")


class ApiClientRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    key_prefix: str
    created_at: datetime


class ApiKeyCreated(ApiClientRead):
    api_key: str = Field(description="Send as the X-API-Key header. Shown only once.")
