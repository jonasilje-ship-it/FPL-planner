"""Tester for endringsdetektoren.

Det viktigste denne skal bevise er at den holder kjeft. En detektor som
rapporterer alt er like ubrukelig som en som ikke rapporterer noe.
"""

import pandas as pd
import pytest

from fplplanner.brief import changes


def _world(**overrides) -> pd.DataFrame:
    """En spiller i dagens tilstand. Feltnavnene folger players-tabellen."""
    base = dict(id=1, web_name="Testesen", status="a",
                chance_of_playing_next_round=None, now_cost=60,
                selected_by_percent=20.0, xp_horizon=12.0, fixtures_ahead=3,
                news="", price_change_percent=0.0)
    base.update(overrides)
    return pd.DataFrame([base])


def _previous(**overrides) -> pd.DataFrame:
    base = dict(player_id=1, status="a", chance=None, now_cost=60,
                selected_by_percent=20.0, xp_horizon=12.0, fixtures_ahead=3, news="")
    base.update(overrides)
    return pd.DataFrame([base])


MINE = {1}


def test_nothing_changed_means_nothing_reported():
    assert changes.detect(_world(), _previous(), MINE) == []


def test_first_run_reports_nothing():
    """Uten et forrige verdensbilde finnes det ingen endringer a finne."""
    assert changes.detect(_world(), pd.DataFrame(), MINE) == []


def test_injury_to_my_player_is_top_severity():
    found = changes.detect(_world(status="i", news="Kneskade, ute i tre uker"),
                           _previous(), MINE)
    assert len(found) == 1
    assert found[0].kind == "skade"
    assert found[0].severity == 3
    assert "Kneskade" in found[0].text


def test_injury_to_someone_elses_player_is_a_footnote():
    found = changes.detect(_world(status="i"), _previous(), set())
    assert found[0].severity == 1


def test_obscure_player_injury_is_ignored_entirely():
    """En spiller ingen eier og som ingen vurderer er ikke en nyhet."""
    found = changes.detect(_world(status="i", selected_by_percent=0.4),
                           _previous(selected_by_percent=0.4), set())
    assert found == []


def test_returning_from_injury_is_reported():
    found = changes.detect(_world(status="a"), _previous(status="i"), MINE)
    assert found[0].kind == "tilbake"


def test_price_drop_on_my_player_outranks_a_rise():
    dropped = changes.detect(_world(now_cost=59), _previous(), MINE)
    rose = changes.detect(_world(now_cost=61), _previous(), MINE)
    assert dropped[0].severity > rose[0].severity


def test_small_xp_drift_is_noise():
    quiet = changes.detect(_world(xp_horizon=12.4), _previous(), MINE)
    assert [c for c in quiet if c.kind == "xp"] == []


def test_large_xp_swing_is_reported_with_direction():
    found = changes.detect(_world(xp_horizon=9.0), _previous(), MINE)
    swing = [c for c in found if c.kind == "xp"]
    assert len(swing) == 1
    assert "ned" in swing[0].text
    assert swing[0].detail["swing"] == pytest.approx(-3.0)


def test_a_moved_fixture_is_always_material():
    """Dobbelt- og blankuker er det som faktisk snur en plan."""
    found = changes.detect(_world(fixtures_ahead=4), _previous(), MINE)
    fixture = [c for c in found if c.kind == "kamp"]
    assert fixture[0].severity == 3


def test_ownership_drift_is_reported_but_low_priority():
    found = changes.detect(_world(selected_by_percent=26.0), _previous(), MINE)
    own = [c for c in found if c.kind == "eierskap"]
    assert own[0].severity == 1


def test_changes_are_sorted_by_severity():
    world = _world(status="i", now_cost=61, selected_by_percent=26.0)
    found = changes.detect(world, _previous(), MINE)
    severities = [c.severity for c in found]
    assert severities == sorted(severities, reverse=True)


# --- prisvarsler -----------------------------------------------------

def test_price_alert_fires_close_to_the_threshold():
    alerts = changes.price_alerts(_world(price_change_percent=95.0), MINE)
    assert len(alerts) == 1
    assert "stigning" in alerts[0].text


def test_no_alert_far_from_the_threshold():
    assert changes.price_alerts(_world(price_change_percent=40.0), MINE) == []


def test_falling_price_only_matters_for_players_i_own():
    mine = changes.price_alerts(_world(price_change_percent=-95.0), MINE)
    theirs = changes.price_alerts(_world(price_change_percent=-95.0), set())
    assert mine and "fall" in mine[0].text
    assert theirs == []
