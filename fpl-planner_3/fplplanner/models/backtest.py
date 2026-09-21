"""Validering: er modellen bedre enn a gjette?

To tester, begge walk-forward - modellen far bare se kamper som var spilt da
prediksjonen skulle vart laget:

1. Clean sheet over en hel tidligere sesong. Dette er den beste testen vi har
   akkurat na, fordi den bruker 38 runder i stedet for de fire vi har spilt,
   og fordi P(CS) faller rett ut av lagstyrkemodellen uten a ga veien om
   minutter, andeler eller bonus.
2. Forventede poeng mot faktiske, for de rundene som er ferdigspilt denne
   sesongen. Tynt grunnlag forelopig, men det vokser med en runde i uka.

Malestokken for clean sheet er Brier-score: gjennomsnittlig kvadrert avvik
mellom sannsynlighet og utfall. Lavere er bedre, og referansen er a spa
ligagjennomsnittet hver gang. Slar vi ikke den, har modellen ingen verdi.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from sqlalchemy import select

from .. import db
from . import team_strength

MATCH_HALF_LIFE = 16.0
MIN_ROUNDS_BEFORE_PREDICTING = 5


def _read(stmt) -> pd.DataFrame:
    with db.get_engine().connect() as conn:
        return pd.read_sql(stmt, conn)


def season_matches(season: str) -> pd.DataFrame:
    """Lagets xG og faktiske baklengsmal per kamp i en tidligere sesong."""
    raw = _read(select(
        db.hist_player_gw.c.fixture, db.hist_player_gw.c.round,
        db.hist_player_gw.c.team, db.hist_player_gw.c.was_home,
        db.hist_player_gw.c.minutes, db.hist_player_gw.c.goals_conceded,
        db.hist_player_gw.c.expected_goals,
    ).where(db.hist_player_gw.c.season == season))

    played = raw[raw["minutes"] > 0]
    agg = (raw.groupby(["fixture", "round", "team", "was_home"], as_index=False)
              ["expected_goals"].sum().rename(columns={"expected_goals": "xg_for"}))
    conceded = (played.groupby(["fixture", "team"], as_index=False)["goals_conceded"]
                      .max().rename(columns={"goals_conceded": "conceded"}))
    agg = agg.merge(conceded, on=["fixture", "team"], how="left")

    pairs = agg.merge(agg, on=["fixture", "round"], suffixes=("", "_opp"))
    pairs = pairs[pairs["team"] != pairs["team_opp"]]
    return pairs.rename(columns={"team": "team_id", "team_opp": "opponent_id",
                                 "was_home": "is_home"})


def clean_sheet_backtest(season: str = "2025-26") -> dict[str, float]:
    """Walk-forward over en sesong: hvor godt treffer P(clean sheet)?"""
    matches = season_matches(season).dropna(subset=["conceded"])
    rounds = sorted(matches["round"].unique())

    probs: list[float] = []
    actual: list[int] = []

    for r in rounds[MIN_ROUNDS_BEFORE_PREDICTING:]:
        past = matches[matches["round"] < r].copy()
        past["weight"] = 0.5 ** ((r - past["round"]) / MATCH_HALF_LIFE)
        try:
            fitted = team_strength.fit(
                past[["team_id", "opponent_id", "is_home", "xg_for", "weight"]])
        except ValueError:
            continue

        for row in matches[matches["round"] == r].itertuples():
            # Motstanderens forventede mal er det laget vart risikerer a slippe inn.
            att = fitted.ratings["attack"].get(row.opponent_id, 1.0)
            dfc = fitted.ratings["defence"].get(row.team_id, 1.0)
            lam_against = fitted.mu * att * dfc * (
                1.0 if row.is_home else fitted.home_advantage)
            probs.append(float(np.exp(-lam_against)))
            actual.append(int(row.conceded == 0))

    p = np.array(probs)
    y = np.array(actual)
    base = y.mean()

    return {
        "n": int(len(y)),
        "base_rate": float(base),
        "mean_predicted": float(p.mean()),
        "brier": float(np.mean((p - y) ** 2)),
        "brier_baseline": float(np.mean((base - y) ** 2)),
        "skill": float(1 - np.mean((p - y) ** 2) / np.mean((base - y) ** 2)),
    }


def clean_sheet_calibration(season: str = "2025-26", bins: int = 5) -> pd.DataFrame:
    """Naar modellen sier 30 prosent - skjer det i 30 prosent av tilfellene?"""
    matches = season_matches(season).dropna(subset=["conceded"])
    rounds = sorted(matches["round"].unique())
    rows = []

    for r in rounds[MIN_ROUNDS_BEFORE_PREDICTING:]:
        past = matches[matches["round"] < r].copy()
        past["weight"] = 0.5 ** ((r - past["round"]) / MATCH_HALF_LIFE)
        try:
            fitted = team_strength.fit(
                past[["team_id", "opponent_id", "is_home", "xg_for", "weight"]])
        except ValueError:
            continue
        for row in matches[matches["round"] == r].itertuples():
            att = fitted.ratings["attack"].get(row.opponent_id, 1.0)
            dfc = fitted.ratings["defence"].get(row.team_id, 1.0)
            lam = fitted.mu * att * dfc * (1.0 if row.is_home else fitted.home_advantage)
            rows.append({"p": float(np.exp(-lam)), "y": int(row.conceded == 0)})

    frame = pd.DataFrame(rows)
    frame["bucket"] = pd.qcut(frame["p"], bins, duplicates="drop")
    out = frame.groupby("bucket", observed=True).agg(
        kamper=("y", "size"), spadd=("p", "mean"), faktisk=("y", "mean"))
    return out.round(3)


def points_check(event: int | None = None) -> dict[str, float]:
    """Forventede poeng mot faktiske, for ferdigspilte runder denne sesongen.

    Referansen er spillerens snittpoeng per kamp sa langt - i praksis det samme
    FPLs eget `ep_next` gjor, siden det feltet bare speiler form.
    """
    finished = _read(select(db.fixtures.c.id, db.fixtures.c.event)
                     .where(db.fixtures.c.finished == True))  # noqa: E712
    if finished.empty:
        return {"n": 0}

    actual = _read(select(db.player_gw.c.player_id, db.player_gw.c.fixture,
                          db.player_gw.c.round, db.player_gw.c.total_points,
                          db.player_gw.c.minutes))
    actual = actual[actual["fixture"].isin(finished["id"])]

    preds = _read(select(db.predictions.c.player_id, db.predictions.c.fixture,
                         db.predictions.c.exp_points))
    merged = actual.merge(preds, on=["player_id", "fixture"], how="inner")
    if merged.empty:
        return {"n": 0, "note": "ingen prediksjoner for ferdigspilte kamper"}

    baseline = (actual.groupby("player_id")["total_points"].mean()
                      .rename("baseline").reset_index())
    merged = merged.merge(baseline, on="player_id", how="left")

    return {
        "n": int(len(merged)),
        "mae_model": float((merged["exp_points"] - merged["total_points"]).abs().mean()),
        "mae_baseline": float((merged["baseline"] - merged["total_points"]).abs().mean()),
    }
