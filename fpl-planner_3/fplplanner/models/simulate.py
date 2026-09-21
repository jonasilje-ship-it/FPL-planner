"""Monte Carlo-simulering av poeng, kamp for kamp.

Simuleringen skjer pa kampniva, ikke spillerniva. Vi trekker forst lagets mal
fra en Poisson-fordeling, og fordeler dem sa pa spillerne. Det er en viktig
detalj: det gjor at spillere fra samme lag blir korrelerte, slik de faktisk er.
Et lag som vinner 4-0 gir bade keeperens clean sheet og spissens hat trick i
samme simulering - og det er nettopp den korrelasjonen som avgjor om bench
boost eller trippel kaptein lonner seg.

Ut kommer ikke et snitt, men en fordeling: hvor sannsynlig er blank, hvor
sannsynlig er en haul.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from . import scoring
from .minutes import MinuteOutcome
from .rates import ASSISTED_FRACTION, bonus_distribution

DEFAULT_SIMS = 10_000


@dataclass(frozen=True)
class PlayerInput:
    player_id: int
    element_type: int
    mins: MinuteOutcome
    goal_share: float
    assist_share: float
    cards_per_90: float
    def_actions_per_90: float
    saves_per_90: float


@dataclass(frozen=True)
class PlayerOutcome:
    player_id: int
    points: np.ndarray          # ett tall per simulering
    goals: np.ndarray
    assists: np.ndarray
    clean_sheet: np.ndarray
    minutes: np.ndarray

    def summary(self) -> dict[str, float]:
        pts = self.points
        return {
            "exp_points": float(pts.mean()),
            "median_points": float(np.median(pts)),
            "p10": float(np.percentile(pts, 10)),
            "p25": float(np.percentile(pts, 25)),
            "p75": float(np.percentile(pts, 75)),
            "p90": float(np.percentile(pts, 90)),
            "p_blank": float((pts <= 2).mean()),
            "p_mid": float(((pts >= 3) & (pts <= 6)).mean()),
            "p_good": float(((pts >= 7) & (pts <= 9)).mean()),
            "p_haul": float((pts >= 10).mean()),
            "p_clean_sheet": float(self.clean_sheet.mean()),
            "p_goal": float((self.goals >= 1).mean()),
            "p_assist": float((self.assists >= 1).mean()),
            "exp_minutes": float(self.minutes.mean()),
        }


def _draw_minutes(mins: MinuteOutcome, n: int, rng: np.random.Generator) -> np.ndarray:
    """Trekk faktiske minutter fra de tre utfallene."""
    u = rng.random(n)
    minutes = np.zeros(n)

    short = (u >= mins.p_zero) & (u < mins.p_zero + mins.p_short)
    long_ = u >= mins.p_zero + mins.p_short

    minutes[short] = rng.integers(5, 60, size=int(short.sum()))
    # De fleste som passerer 60 spiller hele kampen; halen ned mot 60 er byttene.
    tail = np.clip(90 - rng.exponential(7.0, size=int(long_.sum())), 60, 90)
    minutes[long_] = tail
    return minutes


def simulate_fixture(team_lambda: float, opp_lambda: float,
                     players: list[PlayerInput], bonus_lookup: dict,
                     n_sims: int = DEFAULT_SIMS,
                     rng: np.random.Generator | None = None) -> list[PlayerOutcome]:
    """Simuler en kamp `n_sims` ganger for alle spillere pa ett av lagene."""
    rng = rng or np.random.default_rng()

    team_goals = rng.poisson(team_lambda, n_sims)
    opp_goals = rng.poisson(opp_lambda, n_sims)
    outcomes: list[PlayerOutcome] = []

    for p in players:
        pos = p.element_type
        minutes = _draw_minutes(p.mins, n_sims, rng)
        on_pitch = minutes > 0
        frac = minutes / 90.0

        # Hvert av lagets mal kan tilfalle spilleren, med sannsynlighet gitt av
        # andelen hans og hvor mye av kampen han var pa banen.
        goals = rng.binomial(team_goals, np.clip(p.goal_share * frac, 0, 1))
        assists = rng.binomial(
            team_goals, np.clip(p.assist_share * frac * ASSISTED_FRACTION, 0, 1))

        conceded_on_pitch = rng.binomial(opp_goals, np.clip(frac, 0, 1))
        clean_sheet = (opp_goals == 0) & (minutes >= 60)

        points = np.where(minutes >= 60, scoring.PLAY_LONG,
                          np.where(on_pitch, scoring.PLAY_SHORT, 0)).astype(float)
        points += goals * scoring.GOAL[pos]
        points += assists * scoring.ASSIST
        points += clean_sheet * scoring.CLEAN_SHEET[pos]

        if scoring.CONCEDED_PENALTY[pos]:
            points += (conceded_on_pitch // 2) * scoring.CONCEDED_PENALTY[pos]

        if pos == scoring.GK:
            saves = rng.poisson(np.maximum(p.saves_per_90 * frac, 0))
            points += (saves // scoring.SAVES_PER_POINT)

        if scoring.DEF_CONTRIB_POINTS[pos]:
            actions = rng.poisson(np.maximum(p.def_actions_per_90 * frac, 0))
            hit = actions >= scoring.DEF_CONTRIB_THRESHOLD[pos]
            points += hit * scoring.DEF_CONTRIB_POINTS[pos]

        yellow = rng.random(n_sims) < np.clip(p.cards_per_90 * frac, 0, 1)
        points += yellow * scoring.YELLOW

        points += _draw_bonus(bonus_lookup, pos, goals + assists,
                              clean_sheet, on_pitch, rng)

        outcomes.append(PlayerOutcome(
            player_id=p.player_id, points=points, goals=goals,
            assists=assists, clean_sheet=clean_sheet, minutes=minutes))

    return outcomes


def _draw_bonus(lookup: dict, pos: int, returns: np.ndarray,
                clean_sheet: np.ndarray, on_pitch: np.ndarray,
                rng: np.random.Generator) -> np.ndarray:
    """Trekk bonuspoeng fra den empiriske tabellen, gruppe for gruppe."""
    bonus = np.zeros(len(returns))
    capped = np.minimum(returns, 2)
    cs = clean_sheet.astype(int)

    for r in (0, 1, 2):
        for c in (0, 1):
            mask = on_pitch & (capped == r) & (cs == c)
            count = int(mask.sum())
            if count:
                probs = bonus_distribution(lookup, pos, r, c)
                bonus[mask] = rng.choice(4, size=count, p=probs)
    return bonus
