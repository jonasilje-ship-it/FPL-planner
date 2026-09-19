"""Kampprogram-rutenettet maa taale dobbeltuker og blanke runder.

Dette er den vanligste kilden til stille feil i FPL-verktoy: kode som antar
noeyaktig en kamp per lag per runde gir feil svar akkurat i de rundene der
det betyr mest.
"""

import pandas as pd


def _seed(db):
    db.replace_table(db.teams, [
        {"id": 1, "short_name": "ARS", "name": "Arsenal"},
        {"id": 2, "short_name": "CHE", "name": "Chelsea"},
        {"id": 3, "short_name": "LIV", "name": "Liverpool"},
    ])
    db.replace_table(db.fixtures, [
        # GW5: ARS hjemme mot CHE
        {"id": 1, "event": 5, "team_h": 1, "team_a": 2,
         "team_h_difficulty": 2, "team_a_difficulty": 4},
        # GW6: dobbeltuke for ARS (to kamper), LIV har blank
        {"id": 2, "event": 6, "team_h": 1, "team_a": 3,
         "team_h_difficulty": 4, "team_a_difficulty": 5},
        {"id": 3, "event": 6, "team_h": 2, "team_a": 1,
         "team_h_difficulty": 3, "team_a_difficulty": 3},
    ])


def test_double_gameweek_shows_both_opponents(temp_db):
    from fplplanner.analysis import basics
    _seed(temp_db)
    text, fdr = basics.fixture_grid(start_event=5, horizon=2)

    assert text.at[1, 5] == "CHE (H)"
    assert "LIV (H)" in text.at[1, 6] and "CHE (B)" in text.at[1, 6]
    assert fdr.at[1, 6] == 3.5          # snitt av 4 og 3


def test_blank_gameweek_is_empty_not_zero(temp_db):
    from fplplanner.analysis import basics
    _seed(temp_db)
    text, fdr = basics.fixture_grid(start_event=5, horizon=2)

    assert text.at[3, 5] == ""
    assert pd.isna(fdr.at[3, 5])
    # En blank runde skal straffes, ikke ignoreres.
    assert basics.fixture_score(fdr).loc[3] > basics.fixture_score(fdr).loc[1]
