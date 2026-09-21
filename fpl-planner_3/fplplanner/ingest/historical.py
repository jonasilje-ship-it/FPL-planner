"""Historiske sesonger fra vaastavs aapne FPL-datasett.

FPL-APIet gir per-kamp-historikk kun for inneverende sesong. Med fire spilte
runder er lagstyrke-estimater rene gjettinger, saa vi henter tidligere
sesonger herfra i stedet. Datasettet gir oss to ting paa en gang: en prior
til lagstyrkemodellen, og et grunnlag for aa backteste den.

Kilde: https://github.com/vaastav/Fantasy-Premier-League (CSV, ingen skraping)
"""

from __future__ import annotations

import logging

import pandas as pd

from .. import db

log = logging.getLogger(__name__)

BASE = "https://raw.githubusercontent.com/vaastav/Fantasy-Premier-League/master/data"

COLUMNS = {
    "element": "element", "name": "name", "position": "position", "team": "team",
    "round": "round", "fixture": "fixture", "opponent_team": "opponent_team",
    "was_home": "was_home", "minutes": "minutes", "starts": "starts",
    "total_points": "total_points", "goals_scored": "goals_scored",
    "assists": "assists", "clean_sheets": "clean_sheets",
    "goals_conceded": "goals_conceded", "expected_goals": "expected_goals",
    "expected_assists": "expected_assists",
    "expected_goals_conceded": "expected_goals_conceded", "value": "value",
    "bonus": "bonus", "bps": "bps",
}


def load_season(season: str = "2025-26") -> int:
    """Last en sesong inn i hist_player_gw. Sesong pa formen '2024-25'."""
    url = f"{BASE}/{season}/gws/merged_gw.csv"
    log.info("henter %s", url)
    frame = pd.read_csv(url)

    missing = [c for c in COLUMNS if c not in frame.columns]
    if missing:
        raise ValueError(f"{season}: mangler kolonner {missing}")

    frame = frame[list(COLUMNS)].rename(columns=COLUMNS)
    frame["season"] = season
    frame["was_home"] = frame["was_home"].astype(bool)

    # Managere ble spillbare i 2024-25 og har egne kolonner; de har ingen
    # plass i en spillermodell, saa de lukes ut her.
    frame = frame[frame["position"].isin(["GK", "GKP", "DEF", "MID", "FWD"])]
    frame = frame.drop_duplicates(subset=["season", "element", "round", "fixture"])

    rows = frame.where(pd.notnull(frame), None).to_dict("records")
    n = db.replace_where(db.hist_player_gw, db.hist_player_gw.c.season == season, rows)
    log.info("%s: %s rader", season, n)
    return n


def load_seasons(seasons: list[str]) -> dict[str, int]:
    return {s: load_season(s) for s in seasons}
