"""Generate the sample Shapefile archives in samples/.

Usage: python scripts/make_samples.py
"""

from __future__ import annotations

import tempfile
import zipfile
from pathlib import Path

import numpy as np
import shapely
from pyogrio.raw import write
from pyproj import Transformer
from shapely.geometry import LineString, Polygon, box

SAMPLES = Path(__file__).resolve().parent.parent / "samples"


def write_zip(
    archive: Path,
    layer: str,
    geometries: list,
    fields: dict[str, list],
    crs: str,
    keep_prj: bool = True,
) -> None:
    with tempfile.TemporaryDirectory() as tmp:
        shp = Path(tmp) / f"{layer}.shp"
        write(
            shp,
            geometry=np.array([shapely.to_wkb(g) for g in geometries], dtype=object),
            field_data=[np.array(values) for values in fields.values()],
            fields=list(fields),
            geometry_type=geometries[0].geom_type,
            crs=crs,
            driver="ESRI Shapefile",
        )
        with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as zf:
            for part in sorted(Path(tmp).iterdir()):
                if part.suffix == ".prj" and not keep_prj:
                    continue
                zf.write(part, f"{layer}/{part.name}")
    print(f"wrote {archive.relative_to(SAMPLES.parent)}")


def main() -> None:
    SAMPLES.mkdir(exist_ok=True)

    # Land parcels in WGS 84 longitude/latitude (EPSG:4326), near Hosakote, Karnataka.
    parcels = [
        box(77.7950, 13.0700, 77.7962, 13.0711),
        box(77.7964, 13.0700, 77.7980, 13.0711),
        Polygon(
            [(77.7950, 13.0713), (77.7968, 13.0713), (77.7975, 13.0722), (77.7950, 13.0724)],
            [[(77.7955, 13.0716), (77.7958, 13.0716), (77.7958, 13.0719), (77.7955, 13.0719)]],
        ),
    ]
    write_zip(
        SAMPLES / "parcels_wgs84.zip",
        "parcels",
        parcels,
        {
            "survey_no": [201, 202, 203],
            "owner": ["A. Kumar", "R. Devi", "Gram Panchayat"],
            "land_use": ["orchard", "paddy", "common land"],
        },
        "EPSG:4326",
    )

    # Irrigation pipelines in a projected CRS (WGS 84 / UTM zone 43N, metres).
    to_utm = Transformer.from_crs("EPSG:4326", "EPSG:32643", always_xy=True)

    def utm_line(*lonlat: tuple[float, float]) -> LineString:
        return LineString([to_utm.transform(lon, lat) for lon, lat in lonlat])

    pipelines = [
        utm_line((77.7950, 13.0712), (77.7980, 13.0712)),
        utm_line((77.7963, 13.0700), (77.7963, 13.0712), (77.7970, 13.0724)),
    ]
    write_zip(
        SAMPLES / "pipelines_utm43n.zip",
        "pipelines",
        pipelines,
        {"pipe_id": ["P-1", "P-2"], "dia_mm": [110, 90]},
        "EPSG:32643",
    )

    # The same pipelines without a .prj, to demonstrate the `source_crs` upload field.
    write_zip(
        SAMPLES / "pipelines_no_prj.zip",
        "pipelines",
        pipelines,
        {"pipe_id": ["P-1", "P-2"], "dia_mm": [110, 90]},
        "EPSG:32643",
        keep_prj=False,
    )


if __name__ == "__main__":
    main()
