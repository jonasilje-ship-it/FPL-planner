"""Tester for effektiv eierskap (EO). Ingen database, ingen nett."""

import pandas as pd
from pytest import approx as pytest_approx

from fplplanner.analysis import basics
from fplplanner.models.ownership import ManagerPick, aggregate_eo


def _pick(entry_id, player_id, captain=False, chip=None):
    return ManagerPick(entry_id=entry_id, player_id=player_id,
                       is_captain=captain, active_chip=chip)


def test_empty_sample_gives_empty_frame():
    out = aggregate_eo([])
    assert out.empty


def test_squad_pct_is_share_of_sample_that_owns_the_player():
    picks = [_pick(1, 100), _pick(2, 100), _pick(3, 200)]
    out = aggregate_eo(picks)
    assert out.loc[100, "squad_pct"] == pytest_approx(100 * 2 / 3)
    assert out.loc[200, "squad_pct"] == pytest_approx(100 * 1 / 3)


def test_captaincy_adds_on_top_of_ownership():
    # Alle tre eier spiller 100, men bare en kapteiner ham.
    picks = [_pick(1, 100, captain=True), _pick(2, 100), _pick(3, 100)]
    out = aggregate_eo(picks)
    row = out.loc[100]
    assert row["squad_pct"] == 100.0
    assert row["captain_pct"] == pytest_approx(100 / 3)
    assert row["eo"] == pytest_approx(100.0 + 100 / 3)


def test_triple_captain_counts_double_the_extra_weight():
    # En manager triple-kapteinerer 100 - det skal telle som +2x, ikke +1x.
    picks = [_pick(1, 100, captain=True, chip="3xc"), _pick(2, 100)]
    out = aggregate_eo(picks)
    row = out.loc[100]
    assert row["squad_pct"] == 100.0
    assert row["captain_pct"] == 0.0          # TC-manageren telles ikke som vanlig kaptein
    assert row["tc_pct"] == pytest_approx(50.0)
    assert row["eo"] == pytest_approx(100.0 + 2 * 50.0)


def test_player_nobody_owns_is_simply_absent():
    picks = [_pick(1, 100)]
    out = aggregate_eo(picks)
    assert 999 not in out.index


def test_sorted_highest_eo_first():
    picks = [_pick(1, 100), _pick(1, 200), _pick(2, 200)]
    out = aggregate_eo(picks)
    assert list(out.index)[0] == 200


# --- rank_risk (analysis-laget, fremdeles ren) ------------------------

def _eo_frame(rows):
    return pd.DataFrame(rows)


def test_rank_risk_excludes_players_you_already_own():
    eo = _eo_frame([
        {"player_id": 1, "web_name": "A", "team": "ARS", "pos": "MID", "pris": 8.0,
         "eo": 60.0, "squad_pct": 55.0, "captain_pct": 5.0, "selected_by_percent": 50.0},
        {"player_id": 2, "web_name": "B", "team": "LIV", "pos": "FWD", "pris": 9.0,
         "eo": 40.0, "squad_pct": 40.0, "captain_pct": 0.0, "selected_by_percent": 35.0},
    ])
    out = basics.rank_risk({1}, eo, top=5)
    assert list(out["web_name"]) == ["B"]


def test_rank_risk_ranks_by_eo_not_raw_ownership():
    eo = _eo_frame([
        {"player_id": 1, "web_name": "Low", "team": "ARS", "pos": "MID", "pris": 8.0,
         "eo": 20.0, "squad_pct": 20.0, "captain_pct": 0.0, "selected_by_percent": 45.0},
        {"player_id": 2, "web_name": "High", "team": "LIV", "pos": "FWD", "pris": 9.0,
         "eo": 70.0, "squad_pct": 50.0, "captain_pct": 20.0, "selected_by_percent": 30.0},
    ])
    out = basics.rank_risk(set(), eo, top=5)
    assert list(out["web_name"]) == ["High", "Low"]


def test_rank_risk_on_empty_eo_is_empty():
    assert basics.rank_risk({1}, pd.DataFrame(), top=5).empty
