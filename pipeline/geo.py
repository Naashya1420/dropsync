"""Small geometry helpers shared by the pipeline and the backend.

All heavy geometry is done in a local metric projection (UTM zone chosen from
the study area) so distances are in metres.
"""
from __future__ import annotations

import math
from functools import lru_cache

import numpy as np
from pyproj import Transformer

EARTH_R = 6_371_000.0


def haversine_m(lat1, lon1, lat2, lon2):
    """Vectorised great-circle distance in metres."""
    lat1, lon1, lat2, lon2 = map(np.radians, (lat1, lon1, lat2, lon2))
    dlat = lat2 - lat1
    dlon = lon2 - lon1
    a = np.sin(dlat / 2) ** 2 + np.cos(lat1) * np.cos(lat2) * np.sin(dlon / 2) ** 2
    return 2 * EARTH_R * np.arcsin(np.sqrt(a))


def utm_epsg(lat: float, lon: float) -> int:
    zone = int((lon + 180) // 6) + 1
    return (32600 if lat >= 0 else 32700) + zone


@lru_cache(maxsize=8)
def _transformers(epsg: int):
    fwd = Transformer.from_crs(4326, epsg, always_xy=True)
    inv = Transformer.from_crs(epsg, 4326, always_xy=True)
    return fwd, inv


class LocalProjection:
    """lon/lat <-> metric x/y for one study area."""

    def __init__(self, lat: float, lon: float):
        self.epsg = utm_epsg(lat, lon)
        self._fwd, self._inv = _transformers(self.epsg)

    def to_xy(self, lon, lat):
        return self._fwd.transform(lon, lat)

    def to_lonlat(self, x, y):
        return self._inv.transform(x, y)


def offset_m(lat: float, lon: float, dx: float, dy: float) -> tuple[float, float]:
    """Move (lat, lon) by dx metres east and dy metres north (small offsets)."""
    dlat = dy / 111_320.0
    dlon = dx / (111_320.0 * math.cos(math.radians(lat)))
    return lat + dlat, lon + dlon
