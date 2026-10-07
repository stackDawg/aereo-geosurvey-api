from app.geo.readers.base import ArchiveLimits, FeatureReader
from app.geo.readers.kml import KMLReader, KMZReader
from app.geo.readers.shapefile import ShapefileReader
from app.geo.types import FileType

READERS: dict[FileType, type[FeatureReader]] = {
    FileType.SHAPEFILE: ShapefileReader,
    FileType.KML: KMLReader,
    FileType.KMZ: KMZReader,
}


def get_reader(file_type: FileType) -> type[FeatureReader]:
    return READERS[file_type]


__all__ = ["READERS", "ArchiveLimits", "FeatureReader", "get_reader"]
