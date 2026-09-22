"""Tester for transfer-optimizeren, mot sma problemer med kjent fasit."""

import pandas as pd
import pytest

from fplplanner.optimize import objective, transfer_lp

GK, DEF, MID, FWD = 1, 2, 3, 4
POSITION_PLAN = [GK] * 4 + [DEF] * 10 + [MID] * 10 + [FWD] * 6


def _league(values: dict[int, float] | None = None, price: int = 50,
            clubs: int = 10) -> pd.DataFrame:
    """En liten spillerpool med gyldig posisjonsfordeling."""
    rows = []
    for i, position in enumerate(POSITION_PLAN, start=1):
        rows.append({"player_id": i, "element_type": position,
                     "team_id": (i % clubs) + 1, "price": price,
                     "sell_price": price})
    frame = pd.DataFrame(rows).set_index("player_id")
    if values:
        for pid, p in values.items():
            frame.loc[pid, "price"] = p
            frame.loc[pid, "sell_price"] = p
    return frame


def _values(players: pd.DataFrame, events: list[int],
            overrides: dict[int, float] | None = None) -> pd.DataFrame:
    frame = pd.DataFrame(1.0, index=players.index, columns=events)
    for pid, value in (overrides or {}).items():
        frame.loc[pid] = value
    return frame


def _starting_squad(players: pd.DataFrame) -> list[int]:
    """Forste gyldige tropp: 2 keepere, 5 forsvarere, 5 midtbane, 3 spisser."""
    picks = []
    for position, count in transfer_lp.SQUAD_SIZE.items():
        picks += players[players["element_type"] == position].index[:count].tolist()
    return [int(p) for p in picks]


def _problem(**kwargs) -> transfer_lp.Problem:
    players = kwargs.pop("players", None)
    if players is None:
        players = _league()
    events = kwargs.pop("events", [5])
    values = kwargs.pop("values", None)
    if values is None:
        values = _values(players, events)
    base = dict(players=players, values=values,
                current_squad=_starting_squad(players), bank=0,
                free_transfers=1)
    base.update(kwargs)
    return transfer_lp.Problem(**base)


# --- struktur --------------------------------------------------------

def test_solution_respects_squad_and_lineup_rules():
    solution = transfer_lp.solve(_problem())
    assert solution.status == "Optimal"

    move = solution.first
    players = _league()
    assert len(move.lineup) == transfer_lp.LINEUP_SIZE
    assert len(move.lineup) + len(move.bench) == 15

    positions = players.loc[move.lineup, "element_type"].value_counts()
    assert positions.get(GK, 0) == 1
    assert positions.get(DEF, 0) >= 3
    assert positions.get(MID, 0) >= 2
    assert positions.get(FWD, 0) >= 1
    assert move.captain in move.lineup


def test_never_more_than_three_from_one_club():
    """Selv naar ett lag har alle de beste spillerne."""
    players = _league(clubs=10)
    one_club = players[players["team_id"] == 1].index.tolist()
    values = _values(players, [5], {int(p): 20.0 for p in one_club})

    solution = transfer_lp.solve(_problem(players=players, values=values,
                                          bank=200, free_transfers=5))
    squad = solution.first.lineup + solution.first.bench
    assert (players.loc[squad, "team_id"] == 1).sum() <= transfer_lp.CLUB_LIMIT


# --- penger ----------------------------------------------------------

def test_cannot_buy_what_the_bank_cannot_cover():
    players = _league()
    target = int(players[players["element_type"] == MID].index[-1])
    players.loc[target, ["price", "sell_price"]] = 120     # 12,0 mill
    values = _values(players, [5], {target: 50.0})

    # Bank 0 og alle andre koster 5,0: a selge en midtbane gir 5,0, ikke 12,0.
    solution = transfer_lp.solve(_problem(players=players, values=values, bank=0))
    squad = solution.first.lineup + solution.first.bench
    assert target not in squad

    # Med nok penger i banken kjopes han med en gang.
    solution = transfer_lp.solve(_problem(players=players, values=values, bank=70))
    squad = solution.first.lineup + solution.first.bench
    assert target in squad


def test_bank_is_tracked_across_the_horizon():
    players = _league()
    cheap = int(players[players["element_type"] == FWD].index[-1])
    players.loc[cheap, ["price", "sell_price"]] = 40
    values = _values(players, [5, 6], {cheap: 30.0})

    solution = transfer_lp.solve(_problem(players=players, values=values,
                                          events=[5, 6], bank=0))
    # Solgt en spiller til 5,0 og kjopt en til 4,0 gir 1,0 igjen i banken.
    assert solution.first.bank_after == 10


# --- bytter og hits --------------------------------------------------

def test_no_transfer_when_the_squad_is_already_best():
    """Et bytte som ikke gir noe skal ikke gjores."""
    solution = transfer_lp.solve(_problem())
    assert solution.first.transfers_in == []
    assert solution.first.hits == 0


def test_takes_a_hit_only_when_it_pays_for_itself():
    """Det er det *andre* byttet som maa forsvare hitet, ikke summen.

    Det forste byttet er gratis og far i tillegg kapteinsbindet, saa det er
    verdt dobbelt. Nummer to maa alene gi mer enn fire poeng.
    """
    players = _league()
    spare = [int(p) for p in players[players["element_type"] == MID].index[-2:]]

    # Hver av dem gir 5 poeng mer enn den de erstatter: nummer to er verdt hitet.
    worth_it = _values(players, [5], {spare[0]: 6.0, spare[1]: 6.0})
    solution = transfer_lp.solve(_problem(players=players, values=worth_it))
    assert solution.first.hits == 1
    assert len(solution.first.transfers_in) == 2

    # Na gir hver av dem bare 3 poeng mer. Det forste byttet gjores fortsatt,
    # fordi det er gratis - men det andre er ikke verdt fire poeng.
    not_worth_it = _values(players, [5], {spare[0]: 4.0, spare[1]: 4.0})
    solution = transfer_lp.solve(_problem(players=players, values=not_worth_it))
    assert solution.first.hits == 0
    assert len(solution.first.transfers_in) == 1


def test_two_free_transfers_cost_nothing():
    players = _league()
    spare = [int(p) for p in players[players["element_type"] == MID].index[-2:]]
    values = _values(players, [5], {spare[0]: 4.0, spare[1]: 4.0})

    solution = transfer_lp.solve(_problem(players=players, values=values,
                                          free_transfers=2))
    assert len(solution.first.transfers_in) == 2
    assert solution.first.hits == 0


def test_both_targets_are_in_place_by_the_week_they_matter():
    """To spillere er verdilose i GW5 og gode i GW6.

    Optimizeren skal ha begge inne til GW6 uten a ta et hit - enten ved a
    spare byttet, eller ved a hente den ene tidlig. Testen bryr seg om
    utfallet, ikke om hvilken av de to veiene den velger.
    """
    players = _league()
    spare = [int(p) for p in players[players["element_type"] == MID].index[-2:]]
    values = _values(players, [5, 6])
    values.loc[spare[0], 6] = 5.0
    values.loc[spare[1], 6] = 5.0

    solution = transfer_lp.solve(_problem(players=players, values=values,
                                          events=[5, 6], free_transfers=1))
    second = solution.moves[1]
    squad = set(second.lineup + second.bench)

    assert set(spare) <= squad
    assert sum(move.hits for move in solution.moves) == 0


# --- risikojustering -------------------------------------------------

def test_risk_zero_is_plain_expected_points():
    frame = pd.DataFrame({"exp_points": [4.0, 4.0], "p10": [0.0, 2.0],
                          "p90": [12.0, 6.0]})
    assert objective.risk_adjusted(frame, 0.0).tolist() == [4.0, 4.0]


def test_positive_risk_prefers_the_long_tail():
    """To spillere med samme xP: den med tyngst hale skal vinne."""
    frame = pd.DataFrame({"exp_points": [4.0, 4.0], "p10": [0.0, 2.0],
                          "p90": [12.0, 6.0]})
    values = objective.risk_adjusted(frame, 0.5)
    assert values[0] > values[1]


def test_negative_risk_prefers_the_safe_floor():
    frame = pd.DataFrame({"exp_points": [4.0, 4.0], "p10": [0.0, 2.0],
                          "p90": [12.0, 6.0]})
    values = objective.risk_adjusted(frame, -0.5)
    assert values[1] > values[0]


def test_risk_outside_the_range_is_rejected():
    frame = pd.DataFrame({"exp_points": [4.0], "p10": [1.0], "p90": [9.0]})
    with pytest.raises(ValueError):
        objective.risk_adjusted(frame, 1.5)


def test_double_gameweeks_are_summed_per_round():
    """To kamper i samme runde skal legges sammen, ikke telles som en."""
    preds = pd.DataFrame({
        "player_id": [1, 1, 2], "event": [5, 5, 5],
        "exp_points": [3.0, 2.5, 4.0], "p10": [0, 0, 0], "p90": [9, 8, 10],
    })
    matrix = objective.to_matrix(preds, risk=0.0)
    assert matrix.at[1, 5] == pytest.approx(5.5)
    assert matrix.at[2, 5] == pytest.approx(4.0)
