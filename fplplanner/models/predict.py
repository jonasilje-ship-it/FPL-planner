"""Binder modellene sammen og skriver prediksjoner til databasen.

Dette er den eneste modulen i models/ som snakker med databasen. Resten er
rene funksjoner, slik at de kan testes uten at noe er lastet inn.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

import numpy as np
import pandas as pd
from sqlalchemy import select

from .. import db
from . import rates, team_strength
from .minutes import estimate as estimate_minutes
from .simulate import PlayerInput, simulate_fixture

log = logging.getLogger(__name__)

# Lag som har byttet navn mellom datasettene.
TEAM_ALIASES = {"Ipswich": "Ipswich Town", "Nott'm Forest": "Nott'm Forest"}

MATCH_HALF_LIFE = 16.0     # kamper - styrer hvor fort gamle kamper mister vekt
DEFAULT_HORIZON = 5


def _read(stmt) -> pd.DataFrame:
    with db.get_engine().connect() as conn:
        return pd.read_sql(stmt, conn)


# --- datagrunnlag ----------------------------------------------------

def team_match_xg(current_event: int) -> pd.DataFrame:
    """Lagets xG per kamp, denne sesongen og de to forrige.

    Lagets xG i en kamp er summen av spillernes xG. Motstanderens xG i samme
    kamp er det laget slapp til - saa forsvarssiden faller ut gratis.
    """
    teams = _read(select(db.teams.c.id, db.teams.c.name))
    by_name = {TEAM_ALIASES.get(n, n): i for i, n in zip(teams["id"], teams["name"])}
    by_name.update({n: i for i, n in zip(teams["id"], teams["name"])})

    # Denne sesongen: spiller-xG summert per lag og kamp. Laget hentes fra
    # kampen, ikke fra spillerens naaverende klubb - ellers havner kampene til
    # en spiller som har byttet klubb hos feil lag.
    cur = _read(
        select(db.player_gw.c.fixture, db.player_gw.c.round,
               db.player_gw.c.was_home, db.player_gw.c.expected_goals,
               db.fixtures.c.team_h, db.fixtures.c.team_a)
        .select_from(db.player_gw.join(db.fixtures,
                                       db.fixtures.c.id == db.player_gw.c.fixture))
        .where(db.fixtures.c.finished == True)  # noqa: E712
    )
    cur["team_id"] = np.where(cur["was_home"].astype(bool),
                              cur["team_h"], cur["team_a"])
    cur = (cur.groupby(["fixture", "round", "team_id"], as_index=False)["expected_goals"]
              .sum().rename(columns={"expected_goals": "xg_for"}))
    cur["age"] = current_event - cur["round"]
    cur["key"] = "cur-" + cur["fixture"].astype(str)

    # Tidligere sesonger fra det historiske datasettet.
    hist = _read(select(db.hist_player_gw.c.season, db.hist_player_gw.c.fixture,
                        db.hist_player_gw.c.round, db.hist_player_gw.c.team,
                        db.hist_player_gw.c.was_home,
                        db.hist_player_gw.c.expected_goals))
    hist["team_id"] = hist["team"].map(lambda n: by_name.get(TEAM_ALIASES.get(n, n)))
    hist = hist.dropna(subset=["team_id"])
    hist["team_id"] = hist["team_id"].astype(int)
    hist = (hist.groupby(["season", "fixture", "round", "team_id", "was_home"],
                         as_index=False)["expected_goals"].sum()
                .rename(columns={"expected_goals": "xg_for"}))
    season_offset = {"2025-26": 0, "2024-25": 38}
    hist["age"] = (current_event + (38 - hist["round"])
                   + hist["season"].map(season_offset).fillna(76))
    hist["key"] = hist["season"] + "-" + hist["fixture"].astype(str)

    cur["was_home"] = None
    frame = pd.concat([cur[["key", "team_id", "xg_for", "age", "was_home"]],
                       hist[["key", "team_id", "xg_for", "age", "was_home"]]],
                      ignore_index=True)

    # Motstanderen er det andre laget i samme kamp.
    pairs = frame.merge(frame, on="key", suffixes=("", "_opp"))
    pairs = pairs[pairs["team_id"] != pairs["team_id_opp"]]
    pairs = pairs.rename(columns={"team_id_opp": "opponent_id"})

    # Hjemmebane: fra fixtures for inneverende sesong, fra was_home-flagget i
    # historikken. Uten dette blir hjemmefordelen ren stoy.
    fixtures = _read(select(db.fixtures.c.id, db.fixtures.c.team_h))
    home_of = dict(zip("cur-" + fixtures["id"].astype(str), fixtures["team_h"]))
    pairs["is_home"] = [
        bool(home_of[k] == t) if k in home_of else bool(h)
        for k, t, h in zip(pairs["key"], pairs["team_id"], pairs["was_home"])
    ]

    pairs["weight"] = 0.5 ** (pairs["age"] / MATCH_HALF_LIFE)
    return pairs[["team_id", "opponent_id", "is_home", "xg_for", "weight", "age"]]


def player_history() -> pd.DataFrame:
    """Spillerkamper denne sesongen, med lagets samlede xG i hver kamp."""
    frame = _read(
        select(db.player_gw, db.players.c.element_type,
               db.fixtures.c.team_h, db.fixtures.c.team_a)
        .select_from(db.player_gw
                     .join(db.players, db.players.c.id == db.player_gw.c.player_id)
                     .join(db.fixtures, db.fixtures.c.id == db.player_gw.c.fixture))
        # Bare ferdigspilte kamper. En runde som pagar na har 0 minutter pa
        # alle som ikke har spilt enda, og uten dette filteret ville modellen
        # lest det som at halve ligaen nettopp ble benket.
        .where(db.fixtures.c.finished == True)  # noqa: E712
    )
    frame["team_id"] = np.where(frame["was_home"].astype(bool),
                                frame["team_h"], frame["team_a"])
    team_xg = (frame.groupby(["fixture", "team_id"])["expected_goals"]
                    .sum().rename("team_xg").reset_index())
    frame = frame.merge(team_xg, on=["fixture", "team_id"], how="left")
    frame["yellow_cards"] = 0  # felles skjema med historikken; ikke lagret per GW
    return frame.sort_values("round", ascending=False)


def bonus_lookup() -> dict:
    """Empirisk bonusfordeling fra to tidligere sesonger pluss denne."""
    hist = _read(select(
        db.hist_player_gw.c.position, db.hist_player_gw.c.minutes,
        db.hist_player_gw.c.goals_scored, db.hist_player_gw.c.assists,
        db.hist_player_gw.c.clean_sheets, db.hist_player_gw.c.bonus))
    pos_map = {"GK": 1, "GKP": 1, "DEF": 2, "MID": 3, "FWD": 4}
    hist["element_type"] = hist["position"].map(pos_map)
    hist = hist.dropna(subset=["element_type"])
    hist["element_type"] = hist["element_type"].astype(int)
    return rates.bonus_table(hist)


def _calibrate_to_goals(strength: team_strength.TeamStrength) -> team_strength.TeamStrength:
    """Skaler ligasnittet slik at modellen treffer faktiske mal, ikke bare xG.

    Summen av spillernes xG ligger systematisk under antall scorede mal -
    selvmal telles ikke, og spillere uten registrert xG faller utenfor. Uten
    denne justeringen ville alle poengestimater ligget for lavt.
    """
    played = _read(select(db.fixtures.c.team_h_score, db.fixtures.c.team_a_score)
                   .where(db.fixtures.c.finished == True))  # noqa: E712
    if played.empty:
        return strength
    actual = float(pd.concat([played["team_h_score"],
                              played["team_a_score"]]).mean())
    factor = float(np.clip(actual / max(strength.mu, 1e-6), 0.85, 1.35))
    log.info("kalibrering mot faktiske mal: %.3f -> %.3f (x%.3f)",
             strength.mu, strength.mu * factor, factor)
    return team_strength.TeamStrength(ratings=strength.ratings,
                                      mu=strength.mu * factor,
                                      home_advantage=strength.home_advantage)


# --- hovedjobb -------------------------------------------------------

def run(horizon: int = DEFAULT_HORIZON, n_sims: int = 10_000,
        seed: int = 20260913) -> dict[str, int]:
    """Fit lagstyrke, simuler alle kamper i horisonten, skriv prediksjoner."""
    rng = np.random.default_rng(seed)
    now = datetime.now(timezone.utc).replace(tzinfo=None)

    events = _read(select(db.events))
    current = events[events["is_current"] == True]  # noqa: E712
    current_event = int(current.iloc[0]["id"]) if not current.empty else 1
    nxt = events[events["is_next"] == True]        # noqa: E712
    start = int(nxt.iloc[0]["id"]) if not nxt.empty else current_event + 1

    strength = team_strength.fit(team_match_xg(current_event))
    strength = _calibrate_to_goals(strength)
    log.info("lagstyrke: mu=%.2f hjemmefordel=%.3f", strength.mu, strength.home_advantage)

    db.upsert_rows(db.team_params, [{
        "team_id": int(t), "as_of_event": current_event,
        "attack": float(r["attack"]), "defence": float(r["defence"]),
        "matches": int(r["matches"]),
        "xg_for_per_match": float(r["xg_for_per_match"]),
        "xg_against_per_match": float(r["xg_against_per_match"]),
        "updated_at": now,
    } for t, r in strength.ratings.iterrows()])

    players = _read(select(db.players))
    history = player_history()
    bonus = bonus_lookup()

    # Minutt- og andelsmodellene kjores en gang per spiller, ikke per kamp.
    inputs: dict[int, PlayerInput] = {}
    for row in players.itertuples():
        own = history[history["player_id"] == row.id]
        season_start_rate = (row.starts / max(row.minutes / 90.0, 1)
                             if row.minutes else None)
        mins = estimate_minutes(
            own[["minutes", "starts"]], status=row.status,
            chance=row.chance_of_playing_next_round,
            season_start_rate=min(season_start_rate, 1.0) if season_start_rate else None)
        share = rates.player_shares(own, int(row.element_type))
        inputs[int(row.id)] = PlayerInput(
            player_id=int(row.id), element_type=int(row.element_type), mins=mins,
            goal_share=share["goal_share"], assist_share=share["assist_share"],
            cards_per_90=share["cards_per_90"],
            def_actions_per_90=share["def_actions_per_90"],
            saves_per_90=share["saves_per_90"])

    # Laaneklausuler: FPL flagger i `scout_risks` at en spiller ikke kan moete
    # moderklubben sin i en bestemt runde. Det er en garantert nullscore, og
    # den staar ingen andre steder i dataene.
    blocked: dict[int, set[int]] = {}
    for row in players.itertuples():
        raw = row.loan_blocked_events
        if raw is None or (isinstance(raw, float) and pd.isna(raw)):
            continue
        rounds = {int(x) for x in str(raw).split(",") if x.strip().isdigit()}
        if rounds:
            blocked[int(row.id)] = rounds
    if blocked:
        log.info("laanesperrer for %s spillere", len(blocked))

    by_team: dict[int, list[int]] = {}
    for pid, team in zip(players["id"], players["team_id"]):
        by_team.setdefault(int(team), []).append(int(pid))

    fixtures = _read(select(db.fixtures).where(
        db.fixtures.c.event >= start, db.fixtures.c.event < start + horizon))

    rows: list[dict] = []
    for fx in fixtures.itertuples():
        lam_h, lam_a = strength.lambdas(int(fx.team_h), int(fx.team_a))
        for team, opp, home, lam, lam_opp in (
            (int(fx.team_h), int(fx.team_a), True, lam_h, lam_a),
            (int(fx.team_a), int(fx.team_h), False, lam_a, lam_h),
        ):
            squad = [inputs[p] for p in by_team.get(team, [])
                     if p in inputs and int(fx.event) not in blocked.get(p, ())]
            if not squad:
                continue
            for outcome in simulate_fixture(lam, lam_opp, squad, bonus,
                                            n_sims=n_sims, rng=rng):
                rows.append({
                    "player_id": outcome.player_id, "fixture": int(fx.id),
                    "event": int(fx.event), "opponent_team": opp, "was_home": home,
                    "team_lambda": lam, "opp_lambda": lam_opp,
                    "p_start": inputs[outcome.player_id].mins.p_start,
                    "p_60": inputs[outcome.player_id].mins.p_long,
                    "updated_at": now, **outcome.summary(),
                })

    n = db.replace_where(db.predictions, db.predictions.c.event >= start, rows)
    log.info("skrev %s prediksjoner for GW%s-%s", n, start, start + horizon - 1)
    return {"predictions": n, "teams": len(strength.ratings), "from_event": start}
