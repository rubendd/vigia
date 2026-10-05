"""Integration tests against a real PostGIS database.

Run with:  VIGIA_TEST_DATABASE_URL=postgresql://vigia:vigia@localhost:5432/vigia pytest
Skipped automatically when the variable is not set. Uses (and clears) the hotspots/municipalities tables.
"""

import json
import os
from datetime import datetime, timedelta, timezone

import pytest

psycopg = pytest.importorskip("psycopg")

from vigia_ingest import db  # noqa: E402
from vigia_ingest.firms import Hotspot, hotspot_id  # noqa: E402

URL = os.environ.get("VIGIA_TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(not URL, reason="VIGIA_TEST_DATABASE_URL not set")

NOW = datetime.now(timezone.utc).replace(second=0, microsecond=0)


def _hotspot(lat, lon, confidence="high", hours_ago=1):
    t = NOW - timedelta(hours=hours_ago)
    return Hotspot(hotspot_id("VIIRS_SNPP_NRT", lat, lon, t), "VIIRS_SNPP_NRT", "N", lat, lon, t, 330.0, 9.5, confidence, "D")


def _square(x, y, d=0.1):
    return {"type": "Polygon", "coordinates": [[[x - d, y - d], [x + d, y - d], [x + d, y + d], [x - d, y + d], [x - d, y - d]]]}


@pytest.fixture
def conn(tmp_path):
    with psycopg.connect(URL) as c:
        c.execute("DELETE FROM hotspots")
        c.execute("DELETE FROM municipalities")
        c.commit()
        yield c


@pytest.fixture
def boundaries(tmp_path):
    path = tmp_path / "m.geojson"
    path.write_text(json.dumps({"type": "FeatureCollection", "features": [
        {"type": "Feature", "properties": {"NAMEUNIT": "Córdoba", "provincia": "Córdoba"}, "geometry": _square(-4.78, 37.88)},
        {"type": "Feature", "properties": {"NAMEUNIT": "Niebla", "provincia": "Huelva"}, "geometry": _square(-6.95, 37.25)},
    ]}))
    return str(path)


def test_insert_is_idempotent(conn):
    hs = [_hotspot(37.88, -4.78), _hotspot(37.25, -6.95)]
    assert db.save_hotspots(conn, hs) == 2
    assert db.save_hotspots(conn, hs) == 0


def test_loading_boundaries_keeps_hotspots_and_assigns_municipality(conn, boundaries):
    db.save_hotspots(conn, [_hotspot(37.88, -4.78), _hotspot(37.0, -5.5)])
    assert db.load_municipalities(conn, boundaries, "NAMEUNIT", "provincia") == 2
    rows = conn.execute(
        "SELECT m.name FROM hotspots h JOIN municipalities m ON m.id = h.municipality_id"
    ).fetchall()
    assert rows == [("Córdoba",)]  # point outside every municipality was removed, the other kept


def test_points_outside_boundaries_are_dropped(conn, boundaries):
    db.load_municipalities(conn, boundaries, "NAMEUNIT", "provincia")
    assert db.save_hotspots(conn, [_hotspot(37.1, -5.2)]) == 0
    assert db.save_hotspots(conn, [_hotspot(37.25, -6.95)]) == 1
