"""Stable standardization module boundary.

The current implementation remains in ``app.import_services`` until parity
coverage permits moving the algorithm without changing the public contract.
"""

from . import service

__all__ = ["service"]
