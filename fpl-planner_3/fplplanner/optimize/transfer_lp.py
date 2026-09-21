"""Transfer-optimizeren: et heltallsproblem losst med PuLP og CBC.

Problemet er a velge, for hver runde i horisonten, hvilke 15 spillere du eier,
hvilke 11 som starter og hvem som far bindet - slik at summen av poeng over
horisonten blir storst mulig, gitt budsjett, klubbgrense, formasjonsregler og
prisen pa a bruke flere bytter enn du har gratis.

Hits er modellert eksplisitt som -4 i malfunksjonen. Det betyr at optimizeren
ikke blir *fortalt* om et hit lonner seg - den regner det ut, og tar det bare
naar gevinsten over horisonten er storre enn fire poeng.

Fremtidige runder diskonteres. En prediksjon fem uker fram bygger pa lagoppstillinger,
skader og form vi ikke kjenner enda, og skal ikke veie like tungt som neste runde.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd
import pulp

GK, DEF, MID, FWD = 1, 2, 3, 4

SQUAD_SIZE = {GK: 2, DEF: 5, MID: 5, FWD: 3}
LINEUP_MIN = {GK: 1, DEF: 3, MID: 2, FWD: 1}
LINEUP_MAX = {GK: 1, DEF: 5, MID: 5, FWD: 3}
CLUB_LIMIT = 3
LINEUP_SIZE = 11
MAX_FREE_TRANSFERS = 5      # 1 per runde, inntil 4 kan spares opp


@dataclass
class Problem:
    """Alt optimizeren trenger a vite.

    `players` maa ha player_id som indeks og kolonnene element_type, team_id,
    price og sell_price (begge i tideler, slik FPL oppgir dem).
    `values` har spillere som rader og gameweeks som kolonner.
    """

    players: pd.DataFrame
    values: pd.DataFrame
    current_squad: list[int]
    bank: int
    free_transfers: int = 1
    hit_cost: float = 4.0
    discount: float = 0.84
    bench_weight: float = 0.1
    max_transfers_per_gw: int = 3
    banned: list[int] = field(default_factory=list)
    locked: list[int] = field(default_factory=list)

    @property
    def events(self) -> list[int]:
        return sorted(self.values.columns)


@dataclass
class Move:
    event: int
    transfers_in: list[int]
    transfers_out: list[int]
    hits: int
    lineup: list[int]
    bench: list[int]
    captain: int
    bank_after: int
    expected_points: float


@dataclass
class Solution:
    status: str
    objective: float
    moves: list[Move]

    @property
    def first(self) -> Move | None:
        return self.moves[0] if self.moves else None


def solve(problem: Problem, time_limit: int = 60, msg: bool = False) -> Solution:
    """Los problemet og returner planen runde for runde."""
    events = problem.events
    if not events:
        raise ValueError("ingen gameweeks a optimere over")

    players = problem.players
    ids = [int(p) for p in players.index]
    unknown = set(problem.current_squad) - set(ids)
    if unknown:
        raise ValueError(f"spillere mangler i grunnlaget: {sorted(unknown)}")

    value = problem.values.reindex(index=ids, columns=events).fillna(0.0)
    pos = players["element_type"].astype(int).to_dict()
    club = players["team_id"].astype(int).to_dict()
    price = players["price"].astype(int).to_dict()
    sell = players.get("sell_price", players["price"]).astype(int).to_dict()
    owned_now = {p: int(p in set(problem.current_squad)) for p in ids}

    model = pulp.LpProblem("fpl_transfers", pulp.LpMaximize)

    squad = pulp.LpVariable.dicts("squad", (ids, events), cat="Binary")
    lineup = pulp.LpVariable.dicts("lineup", (ids, events), cat="Binary")
    captain = pulp.LpVariable.dicts("captain", (ids, events), cat="Binary")
    buy = pulp.LpVariable.dicts("buy", (ids, events), cat="Binary")
    sell_v = pulp.LpVariable.dicts("sell", (ids, events), cat="Binary")
    bank = pulp.LpVariable.dicts("bank", events, lowBound=0, cat="Continuous")
    free = pulp.LpVariable.dicts("free", events, lowBound=1,
                                 upBound=MAX_FREE_TRANSFERS, cat="Integer")
    used = pulp.LpVariable.dicts("used", events, lowBound=0,
                                 upBound=MAX_FREE_TRANSFERS, cat="Integer")
    hits = pulp.LpVariable.dicts("hits", events, lowBound=0, cat="Integer")

    # --- malfunksjon ---------------------------------------------------
    terms = []
    for k, gw in enumerate(events):
        weight = problem.discount ** k
        for p in ids:
            v = float(value.at[p, gw])
            # Benken teller litt: en tom benk er en risiko, ikke en besparelse.
            terms.append(weight * v * problem.bench_weight * squad[p][gw])
            terms.append(weight * v * (1 - problem.bench_weight) * lineup[p][gw])
            terms.append(weight * v * captain[p][gw])
        terms.append(-problem.hit_cost * hits[gw])
    model += pulp.lpSum(terms)

    # --- troppen -------------------------------------------------------
    for gw_index, gw in enumerate(events):
        model += pulp.lpSum(squad[p][gw] for p in ids) == sum(SQUAD_SIZE.values())
        for position, count in SQUAD_SIZE.items():
            model += pulp.lpSum(squad[p][gw] for p in ids if pos[p] == position) == count

        for team in set(club.values()):
            model += pulp.lpSum(squad[p][gw] for p in ids if club[p] == team) <= CLUB_LIMIT

        model += pulp.lpSum(lineup[p][gw] for p in ids) == LINEUP_SIZE
        for position in (GK, DEF, MID, FWD):
            in_position = [lineup[p][gw] for p in ids if pos[p] == position]
            model += pulp.lpSum(in_position) >= LINEUP_MIN[position]
            model += pulp.lpSum(in_position) <= LINEUP_MAX[position]

        model += pulp.lpSum(captain[p][gw] for p in ids) == 1

        for p in ids:
            model += lineup[p][gw] <= squad[p][gw]
            model += captain[p][gw] <= lineup[p][gw]

            previous = owned_now[p] if gw_index == 0 else squad[p][events[gw_index - 1]]
            model += squad[p][gw] == previous + buy[p][gw] - sell_v[p][gw]
            model += buy[p][gw] + sell_v[p][gw] <= 1

        # --- penger ----------------------------------------------------
        incoming = pulp.lpSum(sell[p] * sell_v[p][gw] for p in ids)
        outgoing = pulp.lpSum(price[p] * buy[p][gw] for p in ids)
        previous_bank = problem.bank if gw_index == 0 else bank[events[gw_index - 1]]
        model += bank[gw] == previous_bank + incoming - outgoing

        # --- bytter og hits --------------------------------------------
        transfers = pulp.lpSum(buy[p][gw] for p in ids)
        model += transfers <= problem.max_transfers_per_gw

        # `used` er hvor mange av de gratis byttene som faktisk gaar med.
        # Uten det mellomleddet ville et hit tvinge antall gratis bytter under
        # en - som er umulig i FPL - og optimizeren kunne aldri tatt et hit i
        # det hele tatt.
        model += used[gw] <= transfers
        model += used[gw] <= free[gw]
        model += hits[gw] >= transfers - used[gw]

        if gw_index == 0:
            model += free[gw] == min(problem.free_transfers, MAX_FREE_TRANSFERS)
        else:
            prev = events[gw_index - 1]
            # Ubrukte bytter spares opp, men taket er fem.
            model += free[gw] <= free[prev] - used[prev] + 1

    for p in problem.banned:
        for gw in events:
            model += squad[p][gw] == 0
    for p in problem.locked:
        for gw in events:
            model += squad[p][gw] == 1

    solver = pulp.PULP_CBC_CMD(msg=msg, timeLimit=time_limit)
    model.solve(solver)
    status = pulp.LpStatus[model.status]

    moves: list[Move] = []
    for gw in events:
        chosen = [p for p in ids if squad[p][gw].value() > 0.5]
        starting = [p for p in ids if lineup[p][gw].value() > 0.5]
        skipper = next((p for p in ids if captain[p][gw].value() > 0.5), None)
        expected = sum(float(value.at[p, gw]) for p in starting)
        expected += float(value.at[skipper, gw]) if skipper else 0.0
        moves.append(Move(
            event=gw,
            transfers_in=[p for p in ids if buy[p][gw].value() > 0.5],
            transfers_out=[p for p in ids if sell_v[p][gw].value() > 0.5],
            hits=int(round(hits[gw].value() or 0)),
            lineup=starting,
            bench=[p for p in chosen if p not in starting],
            captain=skipper,
            bank_after=int(round((bank[gw].value() or 0))),
            expected_points=expected,
        ))

    return Solution(status=status,
                    objective=float(pulp.value(model.objective) or 0.0),
                    moves=moves)
