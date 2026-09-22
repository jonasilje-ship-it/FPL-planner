"""Vaktposter mot at FPL endrer APIet under foettene paa oss.

Feiler disse, er det APIet som har endret seg - ikke koden vaar.
Kjor uten nett: pytest -m "not network"
"""

import pytest

pytestmark = pytest.mark.network

REQUIRED_PLAYER_FIELDS = {
    "id", "web_name", "team", "element_type", "now_cost", "status",
    "selected_by_percent", "form", "total_points", "minutes", "starts",
    "expected_goals", "expected_assists", "expected_goals_conceded",
    "chance_of_playing_next_round", "ep_next", "penalties_order",
}

REQUIRED_HISTORY_FIELDS = {
    "fixture", "round", "opponent_team", "was_home", "minutes", "starts",
    "total_points", "expected_goals", "expected_assists",
    "expected_goals_conceded", "bps", "value",
}


@pytest.fixture(scope="module")
def client():
    from fplplanner.ingest.client import FPLClient
    return FPLClient()


def test_bootstrap_has_fields_we_depend_on(client):
    data = client.bootstrap()
    assert len(data["teams"]) == 20
    assert len(data["events"]) == 38
    missing = REQUIRED_PLAYER_FIELDS - set(data["elements"][0])
    assert not missing, f"FPL har fjernet felter: {missing}"


def test_element_summary_has_per_gameweek_xg(client):
    """Hele fase 2 hviler paa at xG finnes per kamp, ikke bare per sesong."""
    summary = client.element_summary(1)
    assert {"history", "fixtures", "history_past"} <= set(summary)
    if summary["history"]:
        missing = REQUIRED_HISTORY_FIELDS - set(summary["history"][0])
        assert not missing, f"FPL har fjernet felter: {missing}"


def test_entry_endpoints_are_public(client):
    entry = client.entry(3486140)
    assert entry["id"] == 3486140
    assert "summary_overall_points" in entry
