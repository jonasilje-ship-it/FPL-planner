"""Effektiv eierskap (EO) blant en stikkprove av topp-managere.

"selected_by_percent" fra APIet teller alle managere - ogsaa de som spiller
for goy og aldri sjekker laget sitt. Det som faktisk flytter rangeringen din
er hva TOPPEN eier og kapteinsvalgene deres, fordi det er de du konkurrerer
mot om plassering.

    EO = eierandel + andel som kapteinet + 2 * andel som triple-kapteinet

Kapteinen dobler poengene sine, saa en manager som kapteiner en spiller har
effektivt "dobbel eksponering" mot ham - derfor telles kapteinsandelen en
gang ekstra. Triple captain tripler poengene, altsaa to ganger ekstra utover
grunneierskapet.

Selve utregningen her er ren og testbar uten nettverk. Stikkproven - hvilke
managere, hvilke picks - hentes separat i ingest/jobs.py, som er eneste sted
i kodebasen som prater med APIet.
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

TRIPLE_CAPTAIN_CHIP = "3xc"

EO_COLUMNS = ["squad_pct", "captain_pct", "tc_pct", "eo", "n_sample"]


@dataclass
class ManagerPick:
    """En rad i en managers 15-troppspicks for en gitt runde."""

    entry_id: int
    player_id: int
    is_captain: bool
    active_chip: str | None = None


def aggregate_eo(picks: list[ManagerPick]) -> pd.DataFrame:
    """Slaa sammen picks fra stikkproven til EO per spiller.

    Returnerer en DataFrame indeksert paa player_id, sortert med hoyest EO
    forst. Tom stikkprove gir en tom (men riktig formet) DataFrame.
    """
    if not picks:
        return pd.DataFrame(columns=EO_COLUMNS)

    n = len({p.entry_id for p in picks})
    if n == 0:
        return pd.DataFrame(columns=EO_COLUMNS)

    frame = pd.DataFrame([{
        "player_id": p.player_id,
        "is_captain": p.is_captain,
        "is_tc": p.is_captain and p.active_chip == TRIPLE_CAPTAIN_CHIP,
    } for p in picks])

    squad = frame.groupby("player_id").size() / n * 100
    captain = frame[frame["is_captain"] & ~frame["is_tc"]].groupby("player_id").size() / n * 100
    tc = frame[frame["is_tc"]].groupby("player_id").size() / n * 100

    out = pd.DataFrame({"squad_pct": squad})
    out["captain_pct"] = captain.reindex(out.index).fillna(0.0)
    out["tc_pct"] = tc.reindex(out.index).fillna(0.0)
    out["eo"] = out["squad_pct"] + out["captain_pct"] + 2 * out["tc_pct"]
    out["n_sample"] = n
    return out.sort_values("eo", ascending=False)
