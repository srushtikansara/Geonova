"""GEONOVA backend."""
import os as _os
from importlib.util import find_spec as _find_spec


def _use_bundled_proj_data() -> None:
    """Point PROJ at the data bundled with rasterio.

    A PostgreSQL/PostGIS install on Windows sets PROJ_LIB/PROJ_DATA to its own (older) proj.db, which makes
    rasterio fail with 'The EPSG code is unknown'. The bundled data matches the installed rasterio.
    """
    try:
        spec = _find_spec("rasterio")
        for base in (spec.submodule_search_locations or []) if spec else []:
            d = _os.path.join(base, "proj_data")
            if _os.path.isfile(_os.path.join(d, "proj.db")):
                _os.environ["PROJ_DATA"] = d
                _os.environ["PROJ_LIB"] = d
                return
    except Exception:  # never block start-up because of this
        pass


_use_bundled_proj_data()