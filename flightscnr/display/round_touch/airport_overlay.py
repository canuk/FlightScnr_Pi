"""OurAirports runway centerlines on the radar (dark/light maps; skipped on VFR)."""

from __future__ import annotations

import logging
import math
import threading
from typing import Any

import pygame

from display.round_touch import geo, theme

logger = logging.getLogger("flightscnr.display")

_lock = threading.Lock()
_airports: list[dict[str, Any]] = []
_runways: list[dict[str, Any]] = []
_cache_key: tuple | None = None


def _enabled() -> bool:
    try:
        from display.round_touch import settings

        return bool(settings.show_airports())
    except Exception:
        return False


def _map_style() -> str:
    try:
        from display.round_touch import settings

        return str(settings.map_style() or "dark").strip().lower()
    except Exception:
        return "dark"


def _runways_allowed() -> bool:
    """VFR charts already depict runways — skip our overlay there."""
    return _map_style() != "vfr"


def _query_key() -> tuple | None:
    try:
        from config import LOCATION_HOME, location_configured
        from display.round_touch import settings

        if not location_configured():
            return None
        return (
            round(float(LOCATION_HOME[0]), 4),
            round(float(LOCATION_HOME[1]), 4),
            round(float(geo.fetch_max_km()), 2),
            bool(settings.show_airports()),
            int(settings.scale_index()),
            _map_style(),
        )
    except Exception:
        return None


def invalidate() -> None:
    """Drop the nearby-airport / runway cache (toggle / home / scale change)."""
    global _airports, _runways, _cache_key
    with _lock:
        _airports = []
        _runways = []
        _cache_key = None


def _ensure_cached() -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    global _airports, _runways, _cache_key
    if not _enabled() or not _runways_allowed():
        return [], []
    key = _query_key()
    if key is None:
        return [], []
    with _lock:
        if _cache_key == key:
            return list(_airports), list(_runways)
    points: list[dict[str, Any]] = []
    segs: list[dict[str, Any]] = []
    try:
        from config import LOCATION_HOME
        from utilities.airports import iter_airports_near
        from utilities.runways import runways_for_idents

        points = iter_airports_near(
            float(LOCATION_HOME[0]),
            float(LOCATION_HOME[1]),
            float(geo.fetch_max_km()),
        )
        segs = runways_for_idents(ap.get("ident") for ap in points)
    except Exception:
        logger.exception("airport overlay query failed")
        points, segs = [], []
    with _lock:
        _airports = points
        _runways = segs
        _cache_key = key
        return list(_airports), list(_runways)


def _screen_xy(lat: float, lon: float) -> tuple[int, int] | None:
    try:
        from display.round_touch import map_bg

        pos = map_bg.lat_lon_to_basemap_screen(lat, lon)
        if pos is not None:
            return pos
    except Exception:
        pass
    try:
        return geo.lat_lon_to_screen(lat, lon)
    except Exception:
        return None


def _runway_color():
    if _map_style() == "light":
        return getattr(theme, "RUNWAY_LIGHT", (35, 55, 95))
    return getattr(theme, "RUNWAY", theme.AIRPORT)


def _draw_runway(
    surface: pygame.Surface,
    seg: dict[str, Any],
    *,
    ox: int,
    oy: int,
    max_r: float,
    cx: int,
    cy: int,
) -> None:
    try:
        p0 = _screen_xy(float(seg["le_lat"]), float(seg["le_lon"]))
        p1 = _screen_xy(float(seg["he_lat"]), float(seg["he_lon"]))
    except (KeyError, TypeError, ValueError):
        return
    if p0 is None or p1 is None:
        return
    x0, y0 = int(p0[0]) + ox, int(p0[1]) + oy
    x1, y1 = int(p1[0]) + ox, int(p1[1]) + oy
    if math.hypot(x0 - cx, y0 - cy) > max_r and math.hypot(x1 - cx, y1 - cy) > max_r:
        return
    # Slightly thicker on light maps so centerlines stay readable.
    width = max(2, theme.s(3)) if _map_style() == "light" else max(1, theme.s(2))
    pygame.draw.line(surface, _runway_color(), (x0, y0), (x1, y1), width)


def draw_airports(
    surface: pygame.Surface, pan_offset: tuple[int, int] | None = None
) -> None:
    """Draw OurAirports runway centerlines (skipped on VFR; no point markers)."""
    if not _enabled() or not _runways_allowed():
        return
    _airports_list, runways = _ensure_cached()
    if not runways:
        return

    ox = int(pan_offset[0]) if pan_offset else 0
    oy = int(pan_offset[1]) if pan_offset else 0
    max_r = theme.VISIBLE_RADIUS - theme.s(2)
    cx, cy = theme.CENTER_X, theme.CENTER_Y

    for seg in runways:
        _draw_runway(surface, seg, ox=ox, oy=oy, max_r=max_r, cx=cx, cy=cy)
