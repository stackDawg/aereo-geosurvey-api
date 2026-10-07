class InvalidGeoFileError(Exception):
    """The uploaded file cannot be read as the declared geospatial format."""


class InvalidCRSError(ValueError):
    """A CRS definition could not be understood."""
