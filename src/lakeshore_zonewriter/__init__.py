"""CLI helpers for Lake Shore 336 zone table import and export."""

from importlib.metadata import PackageNotFoundError as _PackageNotFoundError
from importlib.metadata import version as _version

try:
    __version__ = _version("lakeshore-zonewriter")
except _PackageNotFoundError:
    __version__ = "0+unknown"

__all__ = ["__version__"]
