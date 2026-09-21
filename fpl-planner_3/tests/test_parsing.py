from datetime import datetime

from fplplanner.ingest.jobs import _dt, _f, _i


def test_floats_handle_api_quirks():
    # APIet sender tall som strenger, og tomme felter paa tre forskjellige maater.
    assert _f("4.5") == 4.5
    assert _f("") is None
    assert _f(None) is None
    assert _f("None") is None


def test_ints_handle_api_quirks():
    assert _i("75") == 75
    assert _i("") is None
    assert _i(None) is None


def test_datetime_parses_zulu():
    assert _dt("2026-09-13T14:00:00Z") == datetime(2026, 9, 13, 14, 0)
    assert _dt(None) is None
