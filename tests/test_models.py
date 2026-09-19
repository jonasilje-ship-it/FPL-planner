"""Tester for modellene. Ingen database, ingen nett - bare tall inn og ut."""

import numpy as np
import pandas as pd
import pytest

from fplplanner.models import scoring, team_strength
from fplplanner.models.minutes import MinuteOutcome, availability, estimate
from fplplanner.models.simulate import PlayerInput, simulate_fixture

ALWAYS_PLAYS = MinuteOutcome(p_zero=0.0, p_short=0.0, p_long=1.0, p_start=1.0)

# Bonustabell som aldri gir bonus, slik at poengreglene kan testes for seg.
NO_BONUS = {(pos, r, cs): np.array([1.0, 0.0, 0.0, 0.0])
            for pos in (1, 2, 3, 4) for r in (0, 1, 2) for cs in (0, 1)}


def _defender(**kwargs) -> PlayerInput:
    base = dict(player_id=1, element_type=scoring.DEF, mins=ALWAYS_PLAYS,
                goal_share=0.0, assist_share=0.0, cards_per_90=0.0,
                def_actions_per_90=0.0, saves_per_90=0.0)
    return PlayerInput(**{**base, **kwargs})


# --- lagstyrke -------------------------------------------------------

def _synthetic_league(attack, defence, mu=1.4, hfa=1.15):
    """Dobbel serie der xG genereres fra kjente parametre."""
    rows = []
    for i, team in enumerate(attack, start=1):
        for j, opp in enumerate(defence, start=1):
            if i == j:
                continue
            rows.append({"team_id": i, "opponent_id": j, "is_home": True,
                         "xg_for": mu * attack[i - 1] * defence[j - 1] * hfa,
                         "weight": 1.0})
            rows.append({"team_id": i, "opponent_id": j, "is_home": False,
                         "xg_for": mu * attack[i - 1] * defence[j - 1],
                         "weight": 1.0})
    return pd.DataFrame(rows)


def test_recovers_the_ordering_it_was_given():
    """Genererer xG fra kjente ratinger og sjekker at modellen finner dem igjen."""
    attack = [1.6, 1.2, 1.0, 0.9, 0.8, 0.6]
    defence = [0.7, 0.9, 1.0, 1.1, 1.2, 1.4]
    fitted = team_strength.fit(_synthetic_league(attack, defence))

    recovered_attack = fitted.ratings["attack"].tolist()
    recovered_defence = fitted.ratings["defence"].tolist()

    assert recovered_attack == sorted(recovered_attack, reverse=True)
    assert recovered_defence == sorted(recovered_defence)
    assert fitted.home_advantage == pytest.approx(1.15, abs=0.03)


def test_few_matches_are_pulled_toward_the_average():
    """Med lite data skal ratingen ligge naermere 1.0 enn radataene tilsier."""
    attack = [1.8, 1.0, 1.0, 1.0, 1.0, 1.0]
    defence = [1.0] * 6
    full = _synthetic_league(attack, defence)
    sparse = full.groupby("team_id").head(2).reset_index(drop=True)

    strong = team_strength.fit(full).ratings.loc[1, "attack"]
    thin = team_strength.fit(sparse).ratings.loc[1, "attack"]
    assert 1.0 < thin < strong


# --- minutter --------------------------------------------------------

@pytest.mark.parametrize("status,chance,expected", [
    ("a", None, 1.0), ("d", None, 0.5), ("i", None, 0.0),
    ("s", None, 0.0), ("d", 75.0, 0.75), ("a", 100.0, 1.0),
])
def test_availability_reads_status_and_chance(status, chance, expected):
    assert availability(status, chance) == expected


def test_regular_starter_is_expected_to_play():
    recent = pd.DataFrame({"minutes": [90, 90, 88, 90], "starts": [1, 1, 1, 1]})
    out = estimate(recent, status="a", season_start_rate=1.0)
    assert out.p_long > 0.95
    assert out.expected_minutes > 80


def test_injury_overrides_a_perfect_record():
    recent = pd.DataFrame({"minutes": [90, 90, 90, 90], "starts": [1, 1, 1, 1]})
    out = estimate(recent, status="i")
    assert out.p_long == 0.0
    assert out.expected_minutes == 0.0


# --- simulering ------------------------------------------------------

def test_clean_sheet_probability_matches_poisson():
    """P(CS) for en spiller som alltid spiller 90 skal vare exp(-lambda)."""
    rng = np.random.default_rng(7)
    opp_lambda = 1.4
    outcome = simulate_fixture(1.5, opp_lambda, [_defender()], NO_BONUS,
                               n_sims=40_000, rng=rng)[0]
    assert outcome.clean_sheet.mean() == pytest.approx(np.exp(-opp_lambda), abs=0.01)


def test_appearance_points_are_the_ceiling_without_returns():
    """En forsvarer uten mal, assists eller clean sheet far hoyst oppmotepoengene.

    Merk at selv mot 5 forventede baklengsmal holder laget nullen i drovt en
    halv prosent av kampene - det er nettopp den halen en simulering fanger og
    et gjennomsnitt ikke gjor.
    """
    rng = np.random.default_rng(11)
    outcome = simulate_fixture(0.0, 5.0, [_defender()], NO_BONUS,
                               n_sims=40_000, rng=rng)[0]

    assert outcome.clean_sheet.mean() == pytest.approx(np.exp(-5.0), abs=0.004)
    assert outcome.points[~outcome.clean_sheet].max() <= 2


def test_goals_scale_with_share_and_scoring_rules():
    """Forventede mal skal folge andelen, og poengene folge posisjonen."""
    rng = np.random.default_rng(3)
    lam = 2.0
    share = 0.25
    forward = PlayerInput(player_id=2, element_type=scoring.FWD, mins=ALWAYS_PLAYS,
                          goal_share=share, assist_share=0.0, cards_per_90=0.0,
                          def_actions_per_90=0.0, saves_per_90=0.0)
    outcome = simulate_fixture(lam, 1.0, [forward], NO_BONUS, n_sims=40_000, rng=rng)[0]

    assert outcome.goals.mean() == pytest.approx(lam * share, abs=0.05)
    # 2 for oppmote + mal * 4, med bonus slatt av.
    expected = 2 + lam * share * scoring.GOAL[scoring.FWD]
    assert outcome.points.mean() == pytest.approx(expected, abs=0.15)


def test_benched_player_scores_nothing():
    never = MinuteOutcome(p_zero=1.0, p_short=0.0, p_long=0.0, p_start=0.0)
    outcome = simulate_fixture(2.0, 0.5, [_defender(mins=never)], NO_BONUS,
                               n_sims=1_000)[0]
    assert outcome.points.sum() == 0
    assert outcome.minutes.sum() == 0


def test_defensive_contribution_needs_to_clear_the_threshold():
    """En forsvarer med mange forsvarshandlinger skal fa DC-poeng, en uten ikke."""
    rng = np.random.default_rng(5)
    busy = simulate_fixture(1.0, 1.0, [_defender(def_actions_per_90=16.0)], NO_BONUS,
                            n_sims=20_000, rng=rng)[0]
    quiet = simulate_fixture(1.0, 1.0, [_defender(def_actions_per_90=2.0)], NO_BONUS,
                             n_sims=20_000, rng=rng)[0]
    assert busy.points.mean() > quiet.points.mean() + 1.0


def test_summary_probabilities_sum_to_one():
    rng = np.random.default_rng(13)
    outcome = simulate_fixture(1.6, 1.2, [_defender(goal_share=0.05)], NO_BONUS,
                               n_sims=5_000, rng=rng)[0]
    s = outcome.summary()
    total = s["p_blank"] + s["p_mid"] + s["p_good"] + s["p_haul"]
    assert total == pytest.approx(1.0, abs=1e-9)
