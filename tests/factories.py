"""Builders for test input files."""

from __future__ import annotations

import io
import zipfile
from pathlib import Path

import numpy as np
import shapely
from pyogrio.raw import write
from shapely.geometry.base import BaseGeometry

KML_NS = "http://www.opengis.net/kml/2.2"


def kml(body: str, namespace: str = KML_NS) -> bytes:
    return (
        f'<?xml version="1.0" encoding="UTF-8"?>\n'
        f'<kml xmlns="{namespace}" xmlns:gx="http://www.google.com/kml/ext/2.2">'
        f"{body}</kml>"
    ).encode()


def placemark(geometry: str, name: str = "pm", extra: str = "", pm_id: str | None = None) -> str:
    id_attr = f' id="{pm_id}"' if pm_id else ""
    return f"<Placemark{id_attr}><name>{name}</name>{extra}{geometry}</Placemark>"


def kml_polygon(coords: list[tuple[float, float]], holes: list[list] | None = None) -> str:
    def ring(points: list[tuple[float, float]]) -> str:
        text = " ".join(f"{x},{y},0" for x, y in points)
        return f"<LinearRing><coordinates>{text}</coordinates></LinearRing>"

    inner = "".join(f"<innerBoundaryIs>{ring(h)}</innerBoundaryIs>" for h in holes or [])
    return f"<Polygon><outerBoundaryIs>{ring(coords)}</outerBoundaryIs>{inner}</Polygon>"


def write_shapefile(
    directory: Path,
    name: str,
    geometries: list[BaseGeometry | None],
    crs: str | None = "EPSG:4326",
    fields: dict[str, list] | None = None,
    geometry_type: str | None = None,
) -> Path:
    """Write a shapefile with GDAL and return the path of its .shp."""
    directory.mkdir(parents=True, exist_ok=True)
    fields = fields or {"name": [f"feature-{i}" for i in range(len(geometries))]}
    wkb = np.array([shapely.to_wkb(g) if g is not None else None for g in geometries], dtype=object)
    if geometry_type is None:
        geometry_type = next(g.geom_type for g in geometries if g is not None)
    path = directory / f"{name}.shp"
    write(
        path,
        geometry=wkb,
        field_data=[np.array(values) for values in fields.values()],
        fields=list(fields),
        geometry_type=geometry_type,
        crs=crs or "EPSG:4326",  # a missing .prj is simulated by deleting it below
        driver="ESRI Shapefile",
    )
    if crs is None:
        path.with_suffix(".prj").unlink(missing_ok=True)
    return path


def zip_files(files: dict[str, bytes]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, content in files.items():
            archive.writestr(name, content)
    return buffer.getvalue()


def shapefile_members(shp_path: Path, prefix: str = "") -> dict[str, bytes]:
    """The files making up a shapefile, keyed by their name inside a zip."""
    return {
        f"{prefix}{part.name}": part.read_bytes()
        for part in shp_path.parent.glob(f"{shp_path.stem}.*")
    }


def shapefile_zip(tmp_path: Path, name: str = "parcels", prefix: str = "", **kwargs) -> bytes:
    shp = write_shapefile(tmp_path / "shp" / name, name, **kwargs)
    return zip_files(shapefile_members(shp, prefix))
