"""Endringsdeteksjon og strategibrief.

`run_brief` er hele løkka: les verdens tilstand, sammenlign med forrige
kjoering, la optimizeren regne på nytt, skriv briefen og frys tilstanden
til neste gang.
"""

from __future__ import annotations

import logging

from ..analysis import basics
from . import changes as change_detection
from . import narrative

log = logging.getLogger(__name__)


def run_brief(entry_id: int, horizon: int = 3, free_transfers: int = 1):
    """Kjor hele kjeden og lagre briefen."""
    world = change_detection.current_world(horizon=horizon)
    previous = change_detection.previous_snapshot()

    current_event = basics.current_event()
    squad = basics.load_my_squad(entry_id, current_event)
    squad_ids = set(int(p) for p in squad["player_id"]) if not squad.empty else set()

    detected = change_detection.detect(world, previous, squad_ids)
    detected += change_detection.price_alerts(world, squad_ids)
    log.info("fant %s endringer verdt å nevne", len(detected))

    brief = narrative.compose(entry_id, detected, horizon=horizon,
                              free_transfers=free_transfers)
    narrative.save(brief)
    change_detection.save_snapshot(world)
    return brief
