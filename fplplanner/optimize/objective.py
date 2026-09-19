"""Fra fordeling til en verdi optimizeren kan maksimere.

Forventede poeng er riktig mal hvis du spiller mot gjennomsnittet. Ligger du
langt bak i miniligaen er det ikke snittet du vil maksimere, men sjansen for
den store uka - og da er to spillere med samme xP ikke like gode valg.

`risk` styrer dette, fra -1 til +1:

    risk =  0    rene forventede poeng
    risk > 0     vekter oppsiden: p90 trekker verdien opp
    risk < 0     straffer nedsiden: avstanden ned til p10 trekker verdien ned

Merk at dette *ikke* er forventede poeng lenger. Tallene optimizeren
sammenligner blir kunstig hoye eller lave; det er rangeringen mellom spillere
som er poenget. Planen rapporterer derfor alltid ekte xP ved siden av.
"""

from __future__ import annotations

import pandas as pd


def risk_adjusted(predictions: pd.DataFrame, risk: float = 0.0) -> pd.Series:
    """Verdi per rad i `predictions`, gitt risikoappetitt.

    Trenger kolonnene exp_points, p10 og p90.
    """
    if not -1.0 <= risk <= 1.0:
        raise ValueError("risk maa ligge mellom -1 og 1")

    expected = predictions["exp_points"].astype(float)
    if risk == 0.0:
        return expected

    if risk > 0:
        upside = predictions["p90"].astype(float) - expected
        return expected + risk * upside

    downside = expected - predictions["p10"].astype(float)
    return expected + risk * downside


def to_matrix(predictions: pd.DataFrame, risk: float = 0.0) -> pd.DataFrame:
    """Verdier per spiller per runde, med dobbeltuker summert.

    Rader er spillere, kolonner er gameweeks. En spiller uten kamp i en runde
    faar 0 - som er riktig: en blank runde gir ingen poeng.
    """
    frame = predictions.copy()
    frame["value"] = risk_adjusted(frame, risk)
    matrix = (frame.pivot_table(index="player_id", columns="event",
                                values="value", aggfunc="sum")
                   .fillna(0.0))
    matrix.columns = [int(c) for c in matrix.columns]
    return matrix
