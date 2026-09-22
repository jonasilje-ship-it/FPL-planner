"""Laget satt opp som pa banen, med modellens tall per spiller.

Samler troppen, prediksjonene for neste runde og situasjonen de neste tre, i
en form bade Streamlit-siden og den publiserte oversikten kan tegne.
"""

from __future__ import annotations

import pandas as pd
from sqlalchemy import select

from .. import db
from . import basics

POSITION_ROWS = {1: "GK", 2: "DEF", 3: "MID", 4: "FWD"}


def _read(stmt) -> pd.DataFrame:
    with db.get_engine().connect() as conn:
        return pd.read_sql(stmt, conn)


def predictions(events: list[int]) -> pd.DataFrame:
    """Prediksjoner for gitte runder, med motstander og hjemme/borte."""
    frame = _read(select(db.predictions).where(db.predictions.c.event.in_(events)))
    teams = _read(select(db.teams.c.id, db.teams.c.short_name))
    short = dict(zip(teams["id"], teams["short_name"]))
    frame["opponent"] = frame["opponent_team"].map(short)
    frame["label"] = frame.apply(
        lambda r: f"{r['opponent']} ({'H' if r['was_home'] else 'B'})", axis=1)
    return frame


def squad_with_model(entry_id: int, squad_event: int, next_event: int,
                     horizon: int = 3) -> pd.DataFrame:
    """Troppen med xP for neste runde og for horisonten.

    Dobbeltuker handteres ved at prediksjonene summeres per runde: to kamper i
    samme runde gir to rader som legges sammen, en blank runde gir null.
    """
    squad = basics.load_my_squad(entry_id, squad_event)
    if squad.empty:
        return squad

    window = list(range(next_event, next_event + horizon))
    preds = predictions(window)
    preds = preds[preds["player_id"].isin(squad["player_id"])]

    nxt = preds[preds["event"] == next_event]
    per_player = nxt.groupby("player_id").agg(
        xp_next=("exp_points", "sum"),
        p_blank=("p_blank", "min"),
        p_haul=("p_haul", "max"),
        p_clean_sheet=("p_clean_sheet", "max"),
        p_goal=("p_goal", "max"),
        p_60=("p_60", "max"),
        exp_minutes=("exp_minutes", "sum"),
        kamper_neste=("fixture", "count"),
    ).reset_index()

    horizon_sum = (preds.groupby("player_id")["exp_points"].sum()
                        .rename("xp_horizon").reset_index())

    fixtures = (preds.sort_values(["event", "fixture"])
                     .groupby("player_id")
                     .apply(lambda g: list(zip(g["event"], g["label"])),
                            include_groups=False)
                     .rename("kamper").reset_index())

    out = (squad.merge(per_player, on="player_id", how="left")
                .merge(horizon_sum, on="player_id", how="left")
                .merge(fixtures, on="player_id", how="left"))

    out["xp_next"] = out["xp_next"].fillna(0.0)
    out["xp_horizon"] = out["xp_horizon"].fillna(0.0)
    out["kamper_neste"] = out["kamper_neste"].fillna(0).astype(int)
    out["xp_per_mill"] = (out["xp_horizon"] / out["pris"]).round(2)
    out["rad"] = out["element_type"].map(POSITION_ROWS)
    return out.sort_values("position")


def formation(squad: pd.DataFrame) -> dict[str, pd.DataFrame]:
    """Del startellevern i linjer, og hold benken for seg."""
    starters = squad[squad["position"] <= 11]
    return {
        "GK": starters[starters["element_type"] == 1],
        "DEF": starters[starters["element_type"] == 2],
        "MID": starters[starters["element_type"] == 3],
        "FWD": starters[starters["element_type"] == 4],
        "BENCH": squad[squad["position"] > 11],
    }


def captain_advice(squad: pd.DataFrame) -> pd.DataFrame:
    """Rangering av kapteinskandidater.

    Kaptein dobler poengene, saa valget handler om forventning - men ogsaa om
    hvor tung halen er: to spillere med samme xP er ikke like gode valg hvis
    den ene oftere leverer haul.
    """
    starters = squad[squad["position"] <= 11].copy()
    starters["xp_kaptein"] = starters["xp_next"] * 2
    cols = ["web_name", "team", "rad", "xp_next", "xp_kaptein", "p_haul",
            "p_blank", "rolle"]
    return starters.nlargest(5, "xp_next")[cols].reset_index(drop=True)


def bench_check(squad: pd.DataFrame) -> pd.DataFrame:
    """Benkespillere med hoyere xP enn noen i startellevern."""
    starters = squad[squad["position"] <= 11]
    bench = squad[squad["position"] > 11]
    if starters.empty or bench.empty:
        return pd.DataFrame()

    rows = []
    for b in bench.itertuples():
        # En keeper kan bare bytte med den andre keeperen.
        pool = starters[starters["element_type"] == 1] if b.element_type == 1 \
            else starters[starters["element_type"] != 1]
        worse = pool[pool["xp_next"] < b.xp_next]
        for w in worse.itertuples():
            rows.append({"inn": b.web_name, "inn_xp": round(b.xp_next, 2),
                         "ut": w.web_name, "ut_xp": round(w.xp_next, 2),
                         "gevinst": round(b.xp_next - w.xp_next, 2)})
    return pd.DataFrame(rows).sort_values("gevinst", ascending=False) if rows \
        else pd.DataFrame()
