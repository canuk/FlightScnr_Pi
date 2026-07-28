"""Airport markers + OurAirports runway centerlines on the radar.

When "Show airports" is on:
  - ``airport.png`` marks large / medium / small airports in range (all map styles)
  - Runway centerlines draw on dark/light maps only (skipped on VFR charts)
"""

from __future__ import annotations

import logging
import math
import os
import threading
from typing import Any

import pygame

from display.round_touch import geo, theme

logger = logging.getLogger("flightscnr.display")

_ICON_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "..",
    "..",
    "assets",
    "airport.png",
)
# Base pin height in REF_SIZE (390) units; scaled via theme.s().
_ICON_HEIGHT = 16
# Opaque tip of airport.png sits near mid-bottom (~89% down, 50% across).
_ICON_ANCHOR_X = 0.50
_ICON_ANCHOR_Y = 0.89

_lock = threading.Lock()
_airports: list[dict[str, Any]] = []
_runways: list[dict[str, Any]] = []
_cache_key: tuple | None = None
_icon_cache: dict[int, pygame.Surface] = {}
_icon_warned = False


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
    if not _enabled():
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
        if _runways_allowed():
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


def _icon_height(airport: dict[str, Any]) -> int:
    """Slightly larger pins for large hubs, smaller for GA strips."""
    base = max(12, theme.s(_ICON_HEIGHT))
    atype = (airport.get("type") or "").strip().lower()
    if atype == "large_airport":
        return base + theme.s(3)
    if atype == "small_airport":
        return max(10, base - theme.s(2))
    return base


def airport_icon(height: int) -> pygame.Surface | None:
    """Load and scale airport.png to the given height (cached)."""
    global _icon_warned
    height = max(8, int(height))
    cached = _icon_cache.get(height)
    if cached is not None:
        return cached
    path = os.path.normpath(_ICON_PATH)
    try:
        image = pygame.image.load(path).convert_alpha()
    except (pygame.error, FileNotFoundError, OSError) as exc:
        if not _icon_warned:
            _icon_warned = True
            logger.warning("Could not load airport icon %s: %s", path, exc)
        return None
    src_w, src_h = image.get_size()
    if src_h <= 0:
        return None
    width = max(6, int(round(src_w * (height / float(src_h)))))
    scaled = pygame.transform.smoothscale(image, (width, height))
    _icon_cache[height] = scaled
    return scaled


def _blit_airport_icon(
    surface: pygame.Surface, icon: pygame.Surface, x: int, y: int
) -> None:
    """Place the pin so its tip sits on the airport lat/lon."""
    ax = int(round(icon.get_width() * _ICON_ANCHOR_X))
    ay = int(round(icon.get_height() * _ICON_ANCHOR_Y))
    surface.blit(icon, (int(x) - ax, int(y) - ay))


def _fallback_mark(surface: pygame.Surface, x: int, y: int) -> None:
    """Tiny cross if the PNG failed to load."""
    color = getattr(theme, "AIRPORT", (120, 150, 175))
    r = max(2, theme.s(3))
    pygame.draw.circle(surface, color, (int(x), int(y)), r, max(1, theme.s(1)))
    pygame.draw.line(surface, color, (x - r, y), (x + r, y), max(1, theme.s(1)))
    pygame.draw.line(surface, color, (x, y - r), (x, y + r), max(1, theme.s(1)))


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
    width = max(2, theme.s(3)) if _map_style() == "light" else max(1, theme.s(2))
    pygame.draw.line(surface, _runway_color(), (x0, y0), (x1, y1), width)


def _draw_marker(
    surface: pygame.Surface,
    airport: dict[str, Any],
    *,
    ox: int,
    oy: int,
    max_r: float,
    cx: int,
    cy: int,
) -> None:
    try:
        pos = _screen_xy(float(airport["lat"]), float(airport["lon"]))
    except (KeyError, TypeError, ValueError):
        return
    if pos is None:
        return
    x, y = int(pos[0]) + ox, int(pos[1]) + oy
    if math.hypot(x - cx, y - cy) > max_r:
        return
    icon = airport_icon(_icon_height(airport))
    if icon is not None:
        _blit_airport_icon(surface, icon, x, y)
    else:
        _fallback_mark(surface, x, y)


def draw_airports(
    surface: pygame.Surface, pan_offset: tuple[int, int] | None = None
) -> None:
    """Draw airport.png markers; runway centerlines on dark/light maps."""
    if not _enabled():
        return
    airports, runways = _ensure_cached()
    if not airports and not runways:
        return

    ox = int(pan_offset[0]) if pan_offset else 0
    oy = int(pan_offset[1]) if pan_offset else 0
    max_r = theme.VISIBLE_RADIUS - theme.s(2)
    cx, cy = theme.CENTER_X, theme.CENTER_Y

    if _runways_allowed():
        for seg in runways:
            _draw_runway(surface, seg, ox=ox, oy=oy, max_r=max_r, cx=cx, cy=cy)

    for airport in airports:
        _draw_marker(surface, airport, ox=ox, oy=oy, max_r=max_r, cx=cx, cy=cy)
