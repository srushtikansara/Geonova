class ProcessingError(Exception):
    """Base class. Messages must never contain absolute local paths or secrets."""


class InputError(ProcessingError):
    """Missing/invalid input files or metadata."""


class GridError(ProcessingError):
    """Rasters cannot be combined (incompatible CRS/grid/overlap)."""
