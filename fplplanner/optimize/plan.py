"""Henter grunnlaget fra databasen og gjor optimizerens svar lesbart.

Eneste modul i optimize/ som snakker med databasen.
"""

from __future__ import annotations

import logging

import pandas as pd
from sqlalchemy import select

from .. import db
from ..analysis import basics
from . import objective, transfer_lp

log = logging.getLogger(__name__)

DEFAULT_HORIZON = 4
POSITIONS = {1: "GK", 2: "DEF", 3: "MID", 4: "FWD"}

# En spiller som knapt spiller er ikke et alternativ, uansett hvor billig han er.
MIN_MINUTES_TO_BUY = 120
UNAVAILABLE = {"i", "s", "u", "n"}


def _read(stmt) -> pd.DataFrame:
    with db.get_engine().connect() as conn:
        return pd.read_sql(stmt, conn)


def build(entry_id: int, horizon: int = DEFAULT_HORIZON, risk: float = 0.0,
          free_transfers: int = 1, candidate_pool: int = 260
          ) -> tuple[transfer_lp.Problem, pd.DataFrame]:
    """Sett sammen problemet: kandidater, verdier, tropp og penger."""
    current = basics.current_event()
    start = basics.next_event()
    events = list(range(start, start + horizon))

    squad = basics.load_my_squad(entry_id, current)
    if squad.empty:
        raise ValueError(f"ingen picks lagret for GW{current}")
    owned = [int(p) for p in squad["player_id"]]

    preds = _read(select(db.predictions).where(db.predictions.c.event.in_(events)))
    if preds.empty:
        raise ValueError("ingen prediksjoner - kjor `run_ingest.py predict` forst")

    players = _read(select(db.players, db.teams.c.short_name.label("team"))
                    .select_from(db.players.join(db.teams,
                                                 db.teams.c.id == db.players.c.team_id)))
    players = players.set_index("id")

    values = objective.to_matrix(preds, risk=risk)

    # Kandidatutvalg: hele troppen, pluss de beste pa hver posisjon. Uten dette
    # far CBC 650 spillere ganger fire runder a bryne seg pa, og bruker minutter
    # pa a bekrefte det den allerede vet om tredjekeepere i bunnlaget.
    totals = values.sum(axis=1).rename("total")
    pool = players.join(totals, how="inner")
    eligible = pool[(pool["minutes"] >= MIN_MINUTES_TO_BUY)
                    & (~pool["status"].isin(UNAVAILABLE))]
    per_position = max(candidate_pool // 4, 20)
    shortlist = (eligible.groupby("element_type", group_keys=False)
                         .apply(lambda g: g.nlargest(per_position, "total"),
                                include_groups=False))
    keep = sorted(set(shortlist.index) | set(owned))

    frame = players.loc[keep].copy()
    frame["price"] = frame["now_cost"].astype(int)
    # Uten innlogging ser vi ikke faktisk salgspris. Naapris er en god
    # tilnaerming - avviket er hoyst 0,1-0,2 per spiller som har steget.
    frame["sell_price"] = frame["price"]

    entry = basics.load_entry(entry_id)
    bank = int(entry["bank"]) if entry is not None else 0

    problem = transfer_lp.Problem(
        players=frame[["element_type", "team_id", "price", "sell_price"]],
        values=values.reindex(index=keep, columns=events).fillna(0.0),
        current_squad=owned, bank=bank, free_transfers=free_transfers,
    )
    return problem, players


def describe(solution: transfer_lp.Solution, players: pd.DataFrame,
             true_values: pd.DataFrame | None = None) -> pd.DataFrame:
    """Planen som en lesbar tabell, en rad per runde."""
    rows = []
    for move in solution.moves:
        def names(ids):
            return ", ".join(players.loc[i, "web_name"] for i in ids) or "–"

        expected = move.expected_points
        if true_values is not None:
            expected = sum(float(true_values.at[p, move.event])
                           for p in move.lineup if p in true_values.index)
            if move.captain in true_values.index:
                expected += float(true_values.at[move.captain, move.event])

        rows.append({
            "GW": move.event,
            "Inn": names(move.transfers_in),
            "Ut": names(move.transfers_out),
            "Hit": -4 * move.hits if move.hits else 0,
            "Kaptein": players.loc[move.captain, "web_name"] if move.captain else "–",
            "xP": round(expected, 2),
            "Bank": round(move.bank_after / 10, 1),
        })
    return pd.DataFrame(rows)


def run(entry_id: int, horizon: int = DEFAULT_HORIZON, risk: float = 0.0,
        free_transfers: int = 1, time_limit: int = 60) -> dict:
    """Bygg, los og beskriv. Returnerer bade planen og tallene bak."""
    problem, players = build(entry_id, horizon, risk, free_transfers)
    solution = transfer_lp.solve(problem, time_limit=time_limit)

    # Rapporter alltid ekte forventede poeng, ogsaa naar optimizeren har
    # maksimert noe annet.
    events = problem.events
    preds = _read(select(db.predictions).where(db.predictions.c.event.in_(events)))
    true_values = objective.to_matrix(preds, risk=0.0)

    plan = describe(solution, players, true_values)
    return {
        "status": solution.status,
        "objective": solution.objective,
        "risk": risk,
        "plan": plan,
        "solution": solution,
        "players": players,
        "true_values": true_values,
    }


def no_transfer_baseline(entry_id: int, horizon: int = DEFAULT_HORIZON,
                         free_transfers: int = 1) -> dict:
    """Samme problem, men uten lov til a bytte noen.

    Dette er referansen ethvert forslag maa slaa: hva laget ditt er verdt hvis
    du lar det sta.
    """
    problem, players = build(entry_id, horizon, risk=0.0,
                             free_transfers=free_transfers)
    problem.max_transfers_per_gw = 0
    solution = transfer_lp.solve(problem)
    return {"status": solution.status, "solution": solution,
            "plan": describe(solution, players), "players": players}
