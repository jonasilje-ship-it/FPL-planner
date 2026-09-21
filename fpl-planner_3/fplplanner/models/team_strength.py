"""Angreps- og forsvarsrating per lag, estimert fra xG.

Modellen er den klassiske multiplikative Poisson-strukturen:

    lambda_hjemme = mu * angrep_h * forsvar_b * hjemmefordel
    lambda_borte  = mu * angrep_b * forsvar_h

der mu er ligasnittet for mal per lag per kamp. Ratingene loses med iterativ
skalering: gitt forsvarsratingene folger angrepsratingene i lukket form, og
omvendt. Noen faa runder frem og tilbake konvergerer.

To valg er verdt a merke seg:

* Vi bruker xG, ikke faktiske mal. Over fire runder er forskjellen mellom et
  lag som har scoret 8 og et som har scoret 3 stort sett flaks; xG rangerer
  dem riktigere.
* Ratingene krympes mot ligasnittet med vekt n/(n+k). Med fire spilte kamper
  betyr det at et lag som har herjet fortsatt havner nrmere midten enn
  tabellen antyder - som er det riktige svaret sa tidlig i sesongen.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

SHRINKAGE_K = 6.0       # antall kamper for halv vekt mot ligasnittet
HALF_LIFE_MATCHES = 12  # eldre kamper teller mindre


@dataclass(frozen=True)
class TeamStrength:
    """Ratinger pluss ligasnittet de er malt mot."""

    ratings: pd.DataFrame      # team_id, attack, defence, matches, xg_for/against_per_match
    mu: float                  # forventede mal per lag per kamp i ligaen
    home_advantage: float

    def lambdas(self, home_id: int, away_id: int) -> tuple[float, float]:
        """Forventede mal for hjemme- og bortelaget i en kamp."""
        att = self.ratings["attack"]
        dfc = self.ratings["defence"]
        lam_h = self.mu * att.get(home_id, 1.0) * dfc.get(away_id, 1.0) * self.home_advantage
        lam_a = self.mu * att.get(away_id, 1.0) * dfc.get(home_id, 1.0)
        return float(lam_h), float(lam_a)


def recency_weights(order: pd.Series, half_life: float = HALF_LIFE_MATCHES) -> pd.Series:
    """Eksponentiell nedvekting: `order` er 0 for nyeste kamp og oker bakover."""
    return pd.Series(0.5 ** (order.to_numpy() / half_life), index=order.index)


def fit(matches: pd.DataFrame, iterations: int = 60,
        shrinkage_k: float = SHRINKAGE_K) -> TeamStrength:
    """Estimer ratinger fra kamper pa lagniva.

    `matches` ma ha kolonnene team_id, opponent_id, is_home, xg_for og weight.
    Hver kamp opptrer to ganger, en gang sett fra hvert lag.
    """
    required = {"team_id", "opponent_id", "is_home", "xg_for", "weight"}
    missing = required - set(matches.columns)
    if missing:
        raise ValueError(f"mangler kolonner: {sorted(missing)}")

    data = matches.dropna(subset=["xg_for"]).copy()
    if data.empty:
        raise ValueError("ingen kamper med xG")

    teams = np.sort(data["team_id"].unique())
    index = {t: i for i, t in enumerate(teams)}
    n = len(teams)

    ti = data["team_id"].map(index).to_numpy()
    oi = data["opponent_id"].map(index).to_numpy()
    home = data["is_home"].to_numpy().astype(bool)
    xg = data["xg_for"].to_numpy(dtype=float)
    w = data["weight"].to_numpy(dtype=float)

    mu = float(np.average(xg, weights=w))

    home_xg = np.average(xg[home], weights=w[home]) if home.any() else mu
    away_xg = np.average(xg[~home], weights=w[~home]) if (~home).any() else mu
    home_adv = float(np.clip(home_xg / max(away_xg, 1e-6), 1.0, 1.5))

    # Hjemmefordelen ligger pa angrepssiden i den kampen den gjelder.
    hfa = np.where(home, home_adv, 1.0)

    attack = np.ones(n)
    defence = np.ones(n)

    for _ in range(iterations):
        # Angrep: observert xG delt pa det motstanderforsvarene tilsier.
        num = np.bincount(ti, weights=w * xg, minlength=n)
        den = np.bincount(ti, weights=w * mu * defence[oi] * hfa, minlength=n)
        attack = np.where(den > 0, num / np.maximum(den, 1e-9), attack)
        attack /= max(attack.mean(), 1e-9)

        # Forsvar: xG sluppet til, delt pa det motstanderangrepene tilsier.
        num_d = np.bincount(oi, weights=w * xg, minlength=n)
        den_d = np.bincount(oi, weights=w * mu * attack[ti] * hfa, minlength=n)
        defence = np.where(den_d > 0, num_d / np.maximum(den_d, 1e-9), defence)
        defence /= max(defence.mean(), 1e-9)

    counts = np.bincount(ti, weights=w, minlength=n)
    shrink = counts / (counts + shrinkage_k)
    attack = 1.0 + (attack - 1.0) * shrink
    defence = 1.0 + (defence - 1.0) * shrink

    raw_matches = np.bincount(ti, minlength=n)
    xg_for = np.bincount(ti, weights=xg, minlength=n) / np.maximum(raw_matches, 1)
    xg_ag = np.bincount(oi, weights=xg, minlength=n) / np.maximum(
        np.bincount(oi, minlength=n), 1)

    ratings = pd.DataFrame({
        "attack": attack, "defence": defence,
        "matches": raw_matches,
        "xg_for_per_match": xg_for, "xg_against_per_match": xg_ag,
    }, index=pd.Index(teams, name="team_id"))

    return TeamStrength(ratings=ratings, mu=mu, home_advantage=home_adv)
