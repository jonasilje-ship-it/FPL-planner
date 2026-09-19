"""Sannsynlighet for at spilleren faktisk spiller.

Dette er den mest undervurderte delen av en FPL-modell. De fleste offentlige
verktoy bommer mer pa *om* en spiller star pa banen enn pa hvor bra han er:
en midtbanespiller med fantastiske underliggende tall er verdt null poeng hvis
han starter pa benken.

Tre utfall modelleres: 0 minutter, 1-59 minutter og 60+ minutter. Skillet gar
ved 60 fordi det er der FPL gir to poeng i stedet for ett, og der clean
sheet-poengene slar inn.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

RECENT_MATCHES = 6
HALF_LIFE = 3.0          # kamper - siste runde teller dobbelt sa mye som fjerde sist
PRIOR_WEIGHT = 1.5       # kamper med prior for en spiller vi vet lite om

MINUTES_IF_LONG = 84.0   # snitt minutter gitt 60+
MINUTES_IF_SHORT = 26.0  # snitt minutter gitt 1-59

# status fra APIet: a=tilgjengelig d=tvilsom i=skadet s=utestengt u=utilgjengelig
HARD_OUT = {"i", "s", "u", "n"}


@dataclass(frozen=True)
class MinuteOutcome:
    p_zero: float
    p_short: float
    p_long: float
    p_start: float

    @property
    def expected_minutes(self) -> float:
        return self.p_long * MINUTES_IF_LONG + self.p_short * MINUTES_IF_SHORT


def availability(status: str | None, chance: float | None) -> float:
    """Hvor mye av minuttmonsteret som overlever skadenyheter.

    `chance_of_playing_next_round` er FPLs eget tall og brukes nar det finnes.
    Ellers tolkes statusflagget: tvilsom halverer, skadet og utestengt nuller.
    """
    if chance is not None and not pd.isna(chance):
        return float(np.clip(chance / 100.0, 0.0, 1.0))
    if status in HARD_OUT:
        return 0.0
    if status == "d":
        return 0.5
    return 1.0


def estimate(recent: pd.DataFrame, status: str | None = "a",
             chance: float | None = None,
             season_start_rate: float | None = None) -> MinuteOutcome:
    """Estimer minuttfordelingen for neste kamp.

    `recent` er spillerens siste kamper med kolonnene `minutes` og `starts`,
    nyeste forst. Tom ramme gir en spiller vi ikke har sett spille.
    """
    avail = availability(status, chance)

    if recent.empty:
        base_long, base_play, base_start = 0.15, 0.25, 0.12
    else:
        window = recent.head(RECENT_MATCHES)
        w = 0.5 ** (np.arange(len(window)) / HALF_LIFE)
        minutes = window["minutes"].to_numpy(dtype=float)
        starts = window["starts"].fillna(0).to_numpy(dtype=float)

        base_long = float(np.average(minutes >= 60, weights=w))
        base_play = float(np.average(minutes > 0, weights=w))
        base_start = float(np.average(starts > 0, weights=w))

        # Med fa observasjoner trekkes anslaget mot sesongmonsteret, sa en
        # enkelt innhopper ikke blir behandlet som en fast innbytter.
        if season_start_rate is not None and not pd.isna(season_start_rate):
            k = PRIOR_WEIGHT / (len(window) + PRIOR_WEIGHT)
            base_long = (1 - k) * base_long + k * season_start_rate
            base_start = (1 - k) * base_start + k * season_start_rate
            base_play = (1 - k) * base_play + k * max(season_start_rate, 0.3)

    p_long = float(np.clip(base_long * avail, 0.0, 1.0))
    p_play = float(np.clip(max(base_play, base_long) * avail, 0.0, 1.0))
    p_short = float(np.clip(p_play - p_long, 0.0, 1.0))
    p_start = float(np.clip(base_start * avail, 0.0, 1.0))

    return MinuteOutcome(
        p_zero=float(np.clip(1.0 - p_long - p_short, 0.0, 1.0)),
        p_short=p_short, p_long=p_long, p_start=p_start,
    )
