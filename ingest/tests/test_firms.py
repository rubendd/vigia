from datetime import datetime, timezone
from pathlib import Path

import pytest

from vigia_ingest.firms import (
    ANDALUCIA_BBOX,
    REGIONS,
    FirmsError,
    Hotspot,
    get_region,
    build_url,
    deduplicate,
    normalise_confidence,
    parse_csv,
    within_bbox,
)

SAMPLE = (Path(__file__).parent / "fixtures" / "viirs_sample.csv").read_text()


def test_parse_skips_malformed_rows():
    hotspots = parse_csv(SAMPLE, "VIIRS_SNPP_NRT")
    assert len(hotspots) == 4  # 5 data rows, 1 malformed


def test_parse_fields_and_utc_time():
    h = parse_csv(SAMPLE, "VIIRS_SNPP_NRT")[0]
    assert h.latitude == pytest.approx(37.88412)
    assert h.longitude == pytest.approx(-4.77931)
    assert h.acquired_at == datetime(2026, 8, 14, 13, 12, tzinfo=timezone.utc)
    assert h.frp == pytest.approx(8.4)
    assert h.confidence == "nominal"
    assert h.daynight == "D"


def test_short_acq_time_is_zero_padded():
    night = parse_csv(SAMPLE, "VIIRS_SNPP_NRT")[2]
    assert night.acquired_at.hour == 1 and night.acquired_at.minute == 48


def test_duplicates_share_id_and_are_removed():
    hotspots = parse_csv(SAMPLE, "VIIRS_SNPP_NRT")
    assert hotspots[0].id == hotspots[1].id
    assert len(deduplicate(hotspots)) == 3


def test_bbox_keeps_andalucia_and_drops_madrid():
    hotspots = deduplicate(parse_csv(SAMPLE, "VIIRS_SNPP_NRT"))
    inside = [h for h in hotspots if within_bbox(h, ANDALUCIA_BBOX)]
    assert len(inside) == 2
    assert all(h.latitude < 38.75 for h in inside)


@pytest.mark.parametrize(
    "raw,expected",
    [("l", "low"), ("n", "nominal"), ("h", "high"), ("15", "low"), ("50", "nominal"), ("95", "high"), ("", "low")],
)
def test_confidence_normalisation(raw, expected):
    assert normalise_confidence(raw) == expected


def test_error_text_raises():
    with pytest.raises(FirmsError):
        parse_csv("Invalid MAP_KEY.", "VIIRS_SNPP_NRT")


def test_build_url():
    url = build_url("abc123", "VIIRS_SNPP_NRT", days=2)
    assert url.endswith("/abc123/VIIRS_SNPP_NRT/-7.55,35.9,-1.6,38.75/2")


@pytest.mark.parametrize("kwargs", [{"map_key": ""}, {"source": "FOO"}, {"days": 0}, {"days": 11}])
def test_build_url_validation(kwargs):
    args = {"map_key": "k", "source": "VIIRS_SNPP_NRT", "days": 1, **kwargs}
    with pytest.raises(ValueError):
        build_url(args["map_key"], args["source"], days=args["days"])


def _at(lat, lon):
    t = datetime(2026, 8, 14, tzinfo=timezone.utc)
    return Hotspot("x", "VIIRS_SNPP_NRT", "N", lat, lon, t, None, None, "high", "D")


def _in_region(h, region):
    return any(within_bbox(h, box) for box in get_region(region))


@pytest.mark.parametrize(
    "place,lat,lon,andalucia,espana",
    [
        ("Córdoba", 37.88, -4.78, True, True),
        ("Madrid", 40.42, -3.70, False, True),
        ("Santiago de Compostela", 42.88, -8.54, False, True),
        ("Palma", 39.57, 2.65, False, True),
        ("Tenerife", 28.29, -16.63, False, True),
        ("Melilla", 35.29, -2.94, False, True),
        ("Paris", 48.86, 2.35, False, False),
        ("Atlantic between Peninsula and Canaries", 32.0, -14.0, False, False),
    ],
)
def test_regions_cover_expected_places(place, lat, lon, andalucia, espana):
    h = _at(lat, lon)
    assert _in_region(h, "andalucia") is andalucia, place
    assert _in_region(h, "espana") is espana, place


def test_get_region_is_case_insensitive_and_validates():
    assert get_region("ESPANA") == REGIONS["espana"]
    with pytest.raises(ValueError):
        get_region("portugal")
