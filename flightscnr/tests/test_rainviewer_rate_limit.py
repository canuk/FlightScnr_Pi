"""Tests for RainViewer safe rate limiting and precip provider fallback."""

from __future__ import annotations

import os
import sys
import time
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class TestRainViewerRateLimiter(unittest.TestCase):
    def test_enforces_min_gap(self):
        from display.round_touch.rainviewer_overlay import _RainViewerRateLimiter

        limiter = _RainViewerRateLimiter(max_per_minute=30, min_gap_s=0.05)
        t0 = time.monotonic()
        limiter.wait()
        limiter.wait()
        elapsed = time.monotonic() - t0
        self.assertGreaterEqual(elapsed, 0.045)

    def test_caps_per_minute(self):
        from display.round_touch.rainviewer_overlay import _RainViewerRateLimiter

        limiter = _RainViewerRateLimiter(max_per_minute=3, min_gap_s=0.0)
        # Pretend three requests already happened this minute.
        now = time.monotonic()
        limiter._times.extend([now - 1.0, now - 0.5, now - 0.1])
        limiter._last_at = now - 0.1

        slept = []

        def fake_sleep(seconds):
            slept.append(seconds)
            # Advance past the window so the next wait() succeeds.
            limiter._times.clear()

        with mock.patch("display.round_touch.rainviewer_overlay.time.sleep", side_effect=fake_sleep):
            limiter.wait()
        self.assertTrue(slept)
        self.assertGreater(slept[0], 0.0)

    def test_http_get_uses_limiter_and_handles_429(self):
        from display.round_touch import rainviewer_overlay as rv

        class FakeResp:
            status_code = 429
            headers = {"Retry-After": "1"}

            def raise_for_status(self):
                raise rv.requests.HTTPError("429")

        limiter = rv._RainViewerRateLimiter(max_per_minute=30, min_gap_s=0.0)
        with mock.patch.object(rv, "_rate_limiter", limiter), mock.patch.object(
            rv.requests, "get", return_value=FakeResp()
        ):
            with self.assertRaises(rv.requests.HTTPError):
                rv._http_get("https://example.test/tile")
            self.assertGreater(limiter._blocked_until, time.monotonic())


class TestRainViewerCadence(unittest.TestCase):
    def test_safe_budget_under_official_limit(self):
        from display.round_touch import rainviewer_overlay as rv

        self.assertLessEqual(rv.MAX_REQUESTS_PER_MINUTE, 100)
        self.assertGreaterEqual(rv.MIN_REQUEST_GAP_S, 1.0)
        # Metadata polls once a minute; tile downloads only when the frame changes.
        self.assertEqual(rv.METADATA_TTL_S, 60)
        self.assertLessEqual(rv.METADATA_TTL_S, 10 * 60)

    def test_same_frame_reuses_cache_without_tile_fetch(self):
        from display.round_touch import rainviewer_overlay as rv

        provider = rv.PROVIDERS[0]
        fake_meta = {
            "host": "https://api.librewxr.net",
            "radar": {"past": [{"time": 2000, "path": "/v2/radar/2000"}]},
        }
        key = (47.45, -122.31, 0, 2000, "librewxr")
        sentinel = object()

        with mock.patch.object(rv, "_fetch_metadata_for", return_value=fake_meta) as fetch_meta, mock.patch.object(
            rv, "_cache_key_for_scale", return_value=key
        ), mock.patch.object(rv, "scale") as scale_mod, mock.patch.object(
            rv, "_load_disk", return_value=None
        ), mock.patch.object(
            rv, "_build_overlay", return_value=sentinel
        ) as build, mock.patch.object(
            rv, "_save_disk"
        ), mock.patch.object(
            rv, "_prune_old_cache"
        ):
            scale_mod.active_index.return_value = 0
            # First resolve builds and caches.
            self.assertTrue(rv._resolve_provider_surface(provider, force_meta=True))
            self.assertEqual(build.call_count, 1)
            # Second resolve (same frame) must not download tiles again.
            self.assertTrue(rv._resolve_provider_surface(provider, force_meta=True))
            self.assertEqual(build.call_count, 1)
            self.assertEqual(fetch_meta.call_count, 2)

    def test_keeps_cache_when_metadata_poll_fails(self):
        from display.round_touch import rainviewer_overlay as rv

        provider = rv.PROVIDERS[0]
        fake_meta = {
            "host": "https://api.librewxr.net",
            "radar": {"past": [{"time": 3000, "path": "/v2/radar/3000"}]},
        }
        key = (47.45, -122.31, 0, 3000, "librewxr")
        sentinel = object()

        with mock.patch.object(
            rv, "_fetch_metadata_for", side_effect=[fake_meta, None]
        ), mock.patch.object(
            rv, "_cache_key_for_scale", return_value=key
        ), mock.patch.object(rv, "scale") as scale_mod, mock.patch.object(
            rv, "_load_disk", return_value=None
        ), mock.patch.object(
            rv, "_build_overlay", return_value=sentinel
        ) as build, mock.patch.object(
            rv, "_save_disk"
        ), mock.patch.object(
            rv, "_prune_old_cache"
        ):
            scale_mod.active_index.return_value = 0
            self.assertTrue(rv._resolve_provider_surface(provider, force_meta=True))
            self.assertEqual(build.call_count, 1)
            # Poll fails — still report ready via cached frame.
            self.assertTrue(rv._resolve_provider_surface(provider, force_meta=True))
            self.assertEqual(build.call_count, 1)
            self.assertEqual(rv._active_provider_id, "librewxr")
            self.assertTrue(rv._provider_available("librewxr"))


class TestPrecipProviders(unittest.TestCase):
    def setUp(self):
        from display.round_touch import rainviewer_overlay as rv

        rv.invalidate()
        rv._provider_fail_until.clear()

    def tearDown(self):
        from display.round_touch import rainviewer_overlay as rv

        rv.invalidate()
        rv._provider_fail_until.clear()

    def test_librewxr_is_preferred(self):
        from display.round_touch import rainviewer_overlay as rv

        self.assertEqual(rv.PROVIDERS[0]["id"], "librewxr")
        self.assertEqual(rv.PROVIDERS[1]["id"], "rainviewer")
        self.assertEqual(rv.PROVIDERS[0]["tile_mode"], "slippy")
        self.assertEqual(rv.PROVIDERS[1]["tile_mode"], "maps")

    def test_slippy_tile_range_covers_home(self):
        from display.round_touch import rainviewer_overlay as rv

        # Oshkosh — same sample used when verifying LibreWXR XYZ tiles.
        x0, x1, y0, y1, left, top = rv._slippy_tile_range(43.9844, -88.5570, 7)
        self.assertEqual((x0, x1, y0, y1), (32, 33, 46, 47))
        self.assertLess(left, 33 * rv.TILE_SIZE)
        self.assertLess(top, 47 * rv.TILE_SIZE)

    def test_falls_back_when_librewxr_metadata_fails(self):
        from display.round_touch import rainviewer_overlay as rv

        lw = rv.PROVIDERS[0]
        rv_prov = rv.PROVIDERS[1]
        fake_meta = {
            "host": "https://tilecache.example",
            "radar": {"past": [{"time": 1000, "path": "/v2/radar/abc"}]},
        }
        sentinel = object()

        with mock.patch.object(rv, "_fetch_metadata_for", side_effect=[None, fake_meta]) as fetch_meta, mock.patch.object(
            rv, "_cache_key_for_scale", return_value=(1.0, 2.0, 0, 1000, "rainviewer")
        ), mock.patch.object(rv, "scale") as scale_mod, mock.patch.object(
            rv, "_load_disk", return_value=None
        ), mock.patch.object(
            rv, "_build_overlay", return_value=sentinel
        ) as build, mock.patch.object(
            rv, "_save_disk"
        ), mock.patch.object(
            rv, "_store_surface"
        ), mock.patch.object(
            rv, "_prune_old_cache"
        ):
            scale_mod.active_index.return_value = 0
            ok = rv._resolve_provider_surface(lw, force_meta=True)
            self.assertFalse(ok)
            ok2 = rv._resolve_provider_surface(rv_prov, force_meta=True)
            self.assertTrue(ok2)
            self.assertEqual(fetch_meta.call_count, 2)
            build.assert_called_once()
            self.assertEqual(rv._active_provider_id, "rainviewer")

    def test_provider_cooldown_skips_failed(self):
        from display.round_touch import rainviewer_overlay as rv

        rv._mark_provider_failed("librewxr")
        self.assertFalse(rv._provider_available("librewxr"))
        self.assertTrue(rv._provider_available("rainviewer"))
        rv._mark_provider_ok("librewxr")
        self.assertTrue(rv._provider_available("librewxr"))


if __name__ == "__main__":
    unittest.main()
