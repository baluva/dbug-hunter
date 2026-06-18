"""DBug Hunter — a database bug & data-quality scanner."""
from .detector import scan_database

__version__ = "1.0.0"
__all__ = ["scan_database"]
