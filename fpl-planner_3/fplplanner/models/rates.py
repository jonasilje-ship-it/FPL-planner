"""Spillerens andel av lagets sjanser, og de smaa ratene rundt.

Lagstyrkemodellen sier hvor mange mal laget forventes a score. Denne modulen
sier hvor stor del av dem som gar gjennom hver enkelt spiller, uttrykt som en
andel per 90 minutter, slik at andelen ikke blir kunstig lav for en spiller
som har spilt halve kamper.

Andelene krympes mot et posisjonssnitt. Uten det ville en forsvarer som scoret
i sin eneste kamp fatt 100 prosent av lagets mal tilskrevet seg.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from .scoring import DEF, FWD, GK, MID

# Typisk andel av lagets xG og xA per 90 minutter, brukt som prior.
GOAL_SHARE_PRIOR = {GK: 0.001, DEF: 0.045, MID: 0.10, FWD: 0.19}
ASSIST_SHARE_PRIOR = {GK: 0.005, DEF: 0.06, MID: 0.11, FWD: 0.09}
SHARE_PRIOR_MATCHES = 3.0

# Andel av mal som gir en assist. Resten er solomal, dodballer rett i mal,
# returer og selvmal.
ASSISTED_FRACTION = 0.74

CARD_PRIOR_PER_90 = 0.13
SAVES_PER_XGA = 2.6       # redninger per forventet baklengsmal for keeperen
DEF_ACTION_PRIOR = {GK: 0.0, DEF: 5.6, MID: 4.4, FWD: 2.2}


def _shrunk_rate(observed_sum: float, exposure_90: float, prior: float,
                 prior_matches: float = SHARE_PRIOR_MATCHES) -> float:
    """Krymp en rate mot en prior basert pa hvor mye spilletid vi har sett."""
    if exposure_90 <= 0:
        return prior
    raw = observed_sum / exposure_90
    weight = exposure_90 / (exposure_90 + prior_matches)
    return float(weight * raw + (1 - weight) * prior)


def player_shares(history: pd.DataFrame, element_type: int) -> dict[str, float]:
    """Andel av lagets mal og assists per 90, pluss kort- og forsvarsrater.

    `history` er spillerens kamper med kolonnene minutes, expected_goals,
    expected_assists, team_xg (lagets samlede xG i den kampen),
    yellow_cards, defensive_contribution og saves.
    """
    if history.empty:
        return {
            "goal_share": GOAL_SHARE_PRIOR[element_type],
            "assist_share": ASSIST_SHARE_PRIOR[element_type],
            "cards_per_90": CARD_PRIOR_PER_90,
            "def_actions_per_90": DEF_ACTION_PRIOR[element_type],
            "saves_per_90": 3.0 if element_type == GK else 0.0,
            "minutes_seen": 0.0,
        }

    minutes = history["minutes"].fillna(0).to_numpy(dtype=float)
    played_90 = minutes.sum() / 90.0

    # Eksponering males i "lagkamper spilt": 45 minutter i en kamp der laget
    # hadde 2.0 i xG teller som 1.0 av den kampens sjanser.
    team_xg = history["team_xg"].fillna(0).to_numpy(dtype=float)
    exposure_xg = float((minutes / 90.0 * team_xg).sum())

    goal_share = _shrunk_rate(
        float(history["expected_goals"].fillna(0).sum()), exposure_xg,
        GOAL_SHARE_PRIOR[element_type], SHARE_PRIOR_MATCHES * 1.4)
    assist_share = _shrunk_rate(
        float(history["expected_assists"].fillna(0).sum()), exposure_xg,
        ASSIST_SHARE_PRIOR[element_type], SHARE_PRIOR_MATCHES * 1.4)

    cards = _shrunk_rate(float(history.get("yellow_cards", pd.Series(dtype=float))
                               .fillna(0).sum()), played_90, CARD_PRIOR_PER_90)
    def_actions = _shrunk_rate(
        float(history["defensive_contribution"].fillna(0).sum()), played_90,
        DEF_ACTION_PRIOR[element_type])
    saves = _shrunk_rate(float(history["saves"].fillna(0).sum()), played_90,
                         3.0 if element_type == GK else 0.0)

    return {
        "goal_share": float(np.clip(goal_share, 0.0, 0.75)),
        "assist_share": float(np.clip(assist_share, 0.0, 0.6)),
        "cards_per_90": float(np.clip(cards, 0.0, 0.6)),
        "def_actions_per_90": float(np.clip(def_actions, 0.0, 15.0)),
        "saves_per_90": float(np.clip(saves, 0.0, 12.0)),
        "minutes_seen": float(minutes.sum()),
    }


def bonus_table(history: pd.DataFrame) -> dict[tuple[int, int, int], np.ndarray]:
    """Empirisk bonusfordeling, laert fra faktiske kamper.

    Nokkelen er (posisjon, antall mal+assists begrenset til 2, clean sheet)
    og verdien er sannsynligheten for 0, 1, 2 og 3 bonuspoeng. Dette er en
    grov erstatning for a modellere BPS direkte - god nok til at bonus ikke
    mangler helt fra fordelingen, og apenbart forste kandidat til a byttes ut.
    """
    frame = history.copy()
    frame = frame[frame["minutes"] > 0]
    frame["returns"] = (frame["goals_scored"].fillna(0)
                        + frame["assists"].fillna(0)).clip(upper=2).astype(int)
    frame["cs"] = (frame["clean_sheets"].fillna(0) > 0).astype(int)
    frame["bonus"] = frame["bonus"].fillna(0).clip(0, 3).astype(int)

    table: dict[tuple[int, int, int], np.ndarray] = {}
    for key, group in frame.groupby(["element_type", "returns", "cs"]):
        counts = np.bincount(group["bonus"].to_numpy(), minlength=4).astype(float)
        if counts.sum() >= 25:
            table[tuple(int(k) for k in key)] = counts / counts.sum()

    return table


def bonus_distribution(table: dict, element_type: int, returns: int,
                       clean_sheet: int) -> np.ndarray:
    """Slaa opp i bonustabellen, med fallback nar kombinasjonen er sjelden."""
    key = (element_type, min(returns, 2), clean_sheet)
    if key in table:
        return table[key]
    fallback = (element_type, min(returns, 2), 0)
    if fallback in table:
        return table[fallback]
    if returns >= 2:
        return np.array([0.20, 0.18, 0.25, 0.37])
    if returns == 1:
        return np.array([0.55, 0.20, 0.15, 0.10])
    return np.array([0.93, 0.04, 0.02, 0.01])
