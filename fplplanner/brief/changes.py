"""Hva har faktisk endret seg siden forrige kjøring?

Poenget med denne modulen er å skille støy fra signal. FPL-data endrer seg
hele tiden - eierskap kryper, priser vipper, xP svinger med en desimal - men
bare noen få av endringene er verdt å vekke noen for.

Hver endring far en alvorlighetsgrad:

    3  påvirker troppen din og endrer anbefalingen
    2  påvirker troppen din
    1  verdt å vite om, men ikke handle på

Terskelene under er valgt slik at en vanlig runde gir en haandfull endringer,
ikke hundre. De er konstanter, ikke magi - juster dem hvis briefen blir for
snakkesalig eller for taus.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone

import pandas as pd
from sqlalchemy import func, select

from .. import db

# Terskler for hva som er verdt å nevne.
XP_SWING = 1.0              # poeng over horisonten
OWNERSHIP_SWING = 3.0       # prosentpoeng
PRICE_ALERT_PERCENT = 90.0  # hvor naer prisendringen maa vaere
UNAVAILABLE = {"i", "s", "u", "n"}

STATUS_TEXT = {"a": "tilgjengelig", "d": "tvilsom", "i": "skadet",
               "s": "utestengt", "u": "utilgjengelig", "n": "ikke tilgjengelig"}


@dataclass
class Change:
    kind: str                 # skade, tilbake, pris, prisvarsel, xp, kamp, eierskap
    player_id: int | None
    name: str
    severity: int
    text: str
    detail: dict = field(default_factory=dict)

    def as_dict(self) -> dict:
        return {"kind": self.kind, "player_id": self.player_id, "name": self.name,
                "severity": self.severity, "text": self.text, **self.detail}


def _read(stmt) -> pd.DataFrame:
    with db.get_engine().connect() as conn:
        return pd.read_sql(stmt, conn)


def current_world(horizon: int = 3) -> pd.DataFrame:
    """Dagens tilstand per spiller: status, pris, eierskap og xP framover."""
    players = _read(select(db.players))
    preds = _read(select(db.predictions.c.player_id, db.predictions.c.event,
                         db.predictions.c.exp_points))
    if preds.empty:
        players["xp_horizon"] = 0.0
        players["fixtures_ahead"] = 0
    else:
        window = sorted(preds["event"].unique())[:horizon]
        subset = preds[preds["event"].isin(window)]
        agg = subset.groupby("player_id").agg(
            xp_horizon=("exp_points", "sum"), fixtures_ahead=("event", "count"))
        players = players.merge(agg, left_on="id", right_index=True, how="left")
        players["xp_horizon"] = players["xp_horizon"].fillna(0.0)
        players["fixtures_ahead"] = players["fixtures_ahead"].fillna(0).astype(int)
    return players


def save_snapshot(world: pd.DataFrame) -> datetime:
    """Frys dagens tilstand slik at neste kjøring har noe å sammenligne med."""
    captured = datetime.now(timezone.utc).replace(tzinfo=None)
    db.append_rows(db.world_snapshot, [{
        "captured_at": captured, "player_id": int(r.id), "status": r.status,
        "chance": None if pd.isna(r.chance_of_playing_next_round)
        else int(r.chance_of_playing_next_round),
        "now_cost": int(r.now_cost),
        "selected_by_percent": float(r.selected_by_percent or 0),
        "xp_horizon": float(r.xp_horizon), "fixtures_ahead": int(r.fixtures_ahead),
        "news": (r.news or "")[:512],
    } for r in world.itertuples()])
    return captured


def previous_snapshot() -> pd.DataFrame:
    """Siste lagrede verdensbilde, eller tom ramme forste gang."""
    latest = _read(select(func.max(db.world_snapshot.c.captured_at).label("t")))
    if latest.empty or pd.isna(latest.iloc[0]["t"]):
        return pd.DataFrame()
    when = latest.iloc[0]["t"]
    return _read(select(db.world_snapshot)
                 .where(db.world_snapshot.c.captured_at == when))


def detect(world: pd.DataFrame, previous: pd.DataFrame,
           squad_ids: set[int]) -> list[Change]:
    """Sammenlign to verdensbilder og returner det som er verdt å nevne."""
    if previous.empty:
        return []

    before = previous.set_index("player_id")
    changes: list[Change] = []

    def own(pid: int) -> bool:
        return pid in squad_ids

    for row in world.itertuples():
        pid = int(row.id)
        if pid not in before.index:
            continue
        old = before.loc[pid]
        name = row.web_name
        mine = own(pid)
        relevant = mine or float(row.selected_by_percent or 0) >= 5.0

        # --- tilgjengelighet ---
        if row.status != old["status"]:
            was, now = STATUS_TEXT.get(old["status"], old["status"]), \
                STATUS_TEXT.get(row.status, row.status)
            if row.status in UNAVAILABLE and relevant:
                changes.append(Change(
                    "skade", pid, name, 3 if mine else 1,
                    f"{name} er nå {now} (var {was}). {row.news or ''}".strip(),
                    {"status": row.status}))
            elif old["status"] in UNAVAILABLE and row.status == "a" and relevant:
                changes.append(Change(
                    "tilbake", pid, name, 2 if mine else 1,
                    f"{name} er tilbake og tilgjengelig igjen.", {"status": "a"}))
            elif row.status == "d" and relevant:
                chance = row.chance_of_playing_next_round
                odds = f" {int(chance)} % sjanse for å spille." if pd.notna(chance) else ""
                changes.append(Change(
                    "skade", pid, name, 2 if mine else 1,
                    f"{name} er meldt tvilsom.{odds} {row.news or ''}".strip(),
                    {"status": "d"}))

        # --- pris ---
        if int(row.now_cost) != int(old["now_cost"]) and relevant:
            delta = (int(row.now_cost) - int(old["now_cost"])) / 10
            direction = "steg" if delta > 0 else "falt"
            severity = 2 if (mine and delta < 0) else 1
            changes.append(Change(
                "pris", pid, name, severity,
                f"{name} {direction} {abs(delta):.1f} til {row.now_cost / 10:.1f}.",
                {"delta": delta}))

        # --- xP over horisonten ---
        swing = float(row.xp_horizon) - float(old["xp_horizon"] or 0)
        if abs(swing) >= XP_SWING and relevant:
            direction = "opp" if swing > 0 else "ned"
            changes.append(Change(
                "xp", pid, name, 2 if mine else 1,
                f"{name} har gått {direction} {abs(swing):.1f} xP over de neste rundene "
                f"(nå {row.xp_horizon:.1f}).", {"swing": round(swing, 2)}))

        # --- kampprogram ---
        if int(row.fixtures_ahead) != int(old["fixtures_ahead"] or 0) and mine:
            changes.append(Change(
                "kamp", pid, name, 3,
                f"Antall kamper for {name} i horisonten endret seg fra "
                f"{int(old['fixtures_ahead'] or 0)} til {int(row.fixtures_ahead)} — "
                f"en kamp er flyttet, lagt til eller fjernet.",
                {"before": int(old["fixtures_ahead"] or 0),
                 "after": int(row.fixtures_ahead)}))

        # --- eierskap ---
        own_swing = float(row.selected_by_percent or 0) - float(old["selected_by_percent"] or 0)
        if abs(own_swing) >= OWNERSHIP_SWING:
            direction = "opp" if own_swing > 0 else "ned"
            changes.append(Change(
                "eierskap", pid, name, 1,
                f"{name} har gått {direction} {abs(own_swing):.1f} prosentpoeng i "
                f"eierskap (nå {row.selected_by_percent:.1f} %).",
                {"swing": round(own_swing, 1)}))

    return sorted(changes, key=lambda c: (-c.severity, c.kind, c.name))


def price_alerts(world: pd.DataFrame, squad_ids: set[int],
                 threshold: float = PRICE_ALERT_PERCENT) -> list[Change]:
    """Spillere som er i ferd med å endre pris i natt.

    FPL publiserer selv hvor langt en spiller har kommet mot terskelen. Vi
    bryr oss om to tilfeller: dine egne som er i ferd med å falle, og
    aktuelle kjøp som er i ferd med å stige.
    """
    alerts: list[Change] = []
    for row in world.itertuples():
        percent = row.price_change_percent
        if percent is None or pd.isna(percent):
            continue
        percent = float(percent)
        pid = int(row.id)
        mine = pid in squad_ids
        if abs(percent) < threshold:
            continue
        if percent >= threshold and (mine or float(row.xp_horizon) >= 8):
            alerts.append(Change(
                "prisvarsel", pid, row.web_name, 2 if not mine else 1,
                f"{row.web_name} ligger {percent:.0f} % mot en prisstigning — "
                f"kjøp i kveld hvis han skal inn.", {"percent": percent}))
        elif percent <= -threshold and mine:
            alerts.append(Change(
                "prisvarsel", pid, row.web_name, 2,
                f"{row.web_name} ligger {abs(percent):.0f} % mot et prisfall — "
                f"selg i kveld hvis han skal ut.", {"percent": percent}))
    return alerts
