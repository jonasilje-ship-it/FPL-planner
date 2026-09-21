"""Sporringer og enkle beregninger som Streamlit-appen bygger paa.

Ingen modeller her - bare det som kan leses rett ut av databasen. Alt som
krever antakelser hoerer hjemme i models/.
"""

from __future__ import annotations

import pandas as pd
from sqlalchemy import select

from .. import db

POSITIONS = {1: "GK", 2: "DEF", 3: "MID", 4: "FWD"}
STATUS_TEXT = {
    "a": "", "d": "Tvilsom", "i": "Skadet", "s": "Utestengt",
    "u": "Utilgjengelig", "n": "Ikke tilgjengelig",
}


def _read(stmt) -> pd.DataFrame:
    with db.get_engine().connect() as conn:
        return pd.read_sql(stmt, conn)


def load_events() -> pd.DataFrame:
    return _read(select(db.events).order_by(db.events.c.id))


def current_event() -> int | None:
    events = load_events()
    current = events[events["is_current"] == True]  # noqa: E712
    if not current.empty:
        return int(current.iloc[0]["id"])
    finished = events[events["finished"] == True]  # noqa: E712
    return int(finished["id"].max()) if not finished.empty else None


def next_event() -> int | None:
    events = load_events()
    nxt = events[events["is_next"] == True]  # noqa: E712
    if not nxt.empty:
        return int(nxt.iloc[0]["id"])
    cur = current_event()
    return cur + 1 if cur and cur < 38 else None


def load_players() -> pd.DataFrame:
    """Alle spillere med lagnavn, posisjon og pris i millioner."""
    stmt = (
        select(
            db.players,
            db.teams.c.short_name.label("team"),
            db.teams.c.name.label("team_name"),
        )
        .select_from(db.players.join(db.teams, db.players.c.team_id == db.teams.c.id))
    )
    frame = _read(stmt)
    frame["pos"] = frame["element_type"].map(POSITIONS)
    frame["pris"] = frame["now_cost"] / 10.0
    frame["status_tekst"] = frame["status"].map(STATUS_TEXT).fillna("")
    frame["poeng_per_mill"] = (frame["total_points"] / frame["pris"]).round(1)
    return frame


def load_my_squad(entry_id: int, event: int) -> pd.DataFrame:
    """De 15 spillerne i laget mitt for en gitt gameweek."""
    stmt = (
        select(db.my_squad)
        .where(db.my_squad.c.entry_id == entry_id, db.my_squad.c.event == event)
        .order_by(db.my_squad.c.position)
    )
    picks = _read(stmt)
    if picks.empty:
        return picks
    players = load_players()
    squad = picks.merge(players, left_on="player_id", right_on="id", suffixes=("", "_p"))
    squad["rolle"] = squad.apply(
        lambda r: "K" if r["is_captain"] else ("V" if r["is_vice_captain"] else ""), axis=1
    )
    squad["på_benken"] = squad["position"] > 11
    return squad.sort_values("position")


def load_entry_history(entry_id: int) -> pd.DataFrame:
    stmt = (
        select(db.entry_history)
        .where(db.entry_history.c.entry_id == entry_id)
        .order_by(db.entry_history.c.event)
    )
    return _read(stmt)


def load_entry(entry_id: int) -> pd.Series | None:
    """Live-status for laget: totalpoeng, rank, bank og verdi."""
    frame = _read(select(db.my_entry).where(db.my_entry.c.entry_id == entry_id))
    return None if frame.empty else frame.iloc[0]


def fixture_grid(start_event: int, horizon: int = 5) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Kampprogram per lag for de neste rundene.

    Returnerer to rammer med lag-ID som indeks og gameweek som kolonne: en med
    tekst ('ARS (H)') og en med FDR som tall. Dobbeltuker faar to motstandere i
    samme celle og gjennomsnittlig FDR; blanke uker blir tomme.
    """
    fixtures = _read(select(db.fixtures).where(
        db.fixtures.c.event >= start_event,
        db.fixtures.c.event < start_event + horizon,
    ))
    teams = _read(select(db.teams.c.id, db.teams.c.short_name))
    short = dict(zip(teams["id"], teams["short_name"]))

    rounds = list(range(start_event, start_event + horizon))
    text = pd.DataFrame(index=teams["id"], columns=rounds, dtype=object).fillna("")
    fdr = pd.DataFrame(index=teams["id"], columns=rounds, dtype=float)

    collected: dict[tuple[int, int], list[tuple[str, int]]] = {}
    for _, fx in fixtures.iterrows():
        if pd.isna(fx["event"]):
            continue
        gw = int(fx["event"])
        collected.setdefault((int(fx["team_h"]), gw), []).append(
            (f"{short.get(int(fx['team_a']), '?')} (H)", int(fx["team_h_difficulty"]))
        )
        collected.setdefault((int(fx["team_a"]), gw), []).append(
            (f"{short.get(int(fx['team_h']), '?')} (B)", int(fx["team_a_difficulty"]))
        )

    for (team_id, gw), entries in collected.items():
        if gw not in rounds or team_id not in text.index:
            continue
        text.at[team_id, gw] = " + ".join(e[0] for e in entries)
        fdr.at[team_id, gw] = sum(e[1] for e in entries) / len(entries)

    return text, fdr


def fixture_score(fdr: pd.DataFrame) -> pd.Series:
    """Ett tall per lag for hvor snilt programmet er.

    Blanke uker straffes med 5 (som den vanskeligste FDR-en), fordi en runde
    uten kamp er null poeng - ikke et fravaer av informasjon.
    """
    return fdr.fillna(5.0).mean(axis=1).round(2)


def team_exposure(squad: pd.DataFrame) -> pd.DataFrame:
    """Hvor mange spillere jeg har fra hvert lag, og hva de koster meg."""
    if squad.empty:
        return squad
    grouped = (
        squad.groupby(["team", "team_name"])
        .agg(antall=("player_id", "count"), verdi=("pris", "sum"),
             spillere=("web_name", lambda s: ", ".join(s)))
        .reset_index()
        .sort_values("antall", ascending=False)
    )
    return grouped


def squad_alerts(squad: pd.DataFrame, fdr: pd.DataFrame) -> list[str]:
    """Enkle regelbaserte varsler - ingen modell, bare ting man bor se."""
    alerts: list[str] = []
    if squad.empty:
        return ["Fant ingen picks for denne gameweeken."]

    exposure = team_exposure(squad)
    for _, row in exposure.iterrows():
        if row["antall"] >= 3:
            alerts.append(
                f"**{row['antall']} spillere fra {row['team_name']}** "
                f"({row['spillere']}) - maks tillatt er 3, og en tung kampuke "
                f"for dem treffer hele laget ditt samtidig."
            )

    skadet = squad[squad["status"].isin(["i", "s", "u", "n"])]
    for _, row in skadet.iterrows():
        alerts.append(f"**{row['web_name']}**: {row['status_tekst']}. {row['news'] or ''}".strip())

    tvilsom = squad[(squad["status"] == "d")]
    for _, row in tvilsom.iterrows():
        chance = row["chance_of_playing_next_round"]
        chance_txt = f"{int(chance)} % sjanse for aa spille" if pd.notna(chance) else "usikker"
        alerts.append(f"**{row['web_name']}**: {chance_txt}. {row['news'] or ''}".strip())

    if not fdr.empty:
        blanks = fdr.isna()
        for team_id in squad["team_id"].unique():
            if team_id not in blanks.index:
                continue
            blank_gws = [gw for gw in blanks.columns if blanks.at[team_id, gw]]
            if blank_gws:
                names = ", ".join(squad[squad["team_id"] == team_id]["web_name"])
                gw_txt = ", ".join(f"GW{gw}" for gw in blank_gws)
                alerts.append(f"**Blank runde**: {names} har ingen kamp i {gw_txt}.")

    return alerts


def value_picks(players: pd.DataFrame, min_minutes: int = 180, top: int = 20) -> pd.DataFrame:
    """Poeng per million blant spillere som faktisk har spilt.

    Minuttgrensen er ikke pynt: uten den fylles lista av backup-keepere som
    har staatt 90 minutter en gang og ser billige ut per poeng.
    """
    eligible = players[(players["minutes"] >= min_minutes) & (players["status"] == "a")]
    cols = ["web_name", "team", "pos", "pris", "total_points", "poeng_per_mill",
            "form", "selected_by_percent", "minutes", "ep_next"]
    return eligible.nlargest(top, "poeng_per_mill")[cols].reset_index(drop=True)


def load_effective_ownership(event: int | None) -> pd.DataFrame:
    """Effektivt eierskap blant stikkproven av toppmanagere for en gitt runde.

    Tom DataFrame naar ingen runde er oppgitt eller jobben ikke er kjort enna.
    """
    if event is None:
        return pd.DataFrame()
    frame = _read(select(db.effective_ownership)
                 .where(db.effective_ownership.c.event == event))
    if frame.empty:
        return frame
    players = load_players()[["id", "web_name", "team", "pos", "pris", "selected_by_percent"]]
    return frame.merge(players, left_on="player_id", right_on="id", how="left")


def rank_risk(squad_player_ids: set[int], eo: pd.DataFrame, top: int = 8) -> pd.DataFrame:
    """Spillere toppen eier tungt som du ikke har - selve poenget med aa maale EO.

    En spiller 40 % av feltet eier er en risiko for rangeringen din helt
    uavhengig av om du personlig synes han er god: leverer han, faller du
    bak alle som har ham, uansett hva resten av laget ditt gjor.
    """
    if eo.empty:
        return eo
    missing = eo[~eo["player_id"].isin(squad_player_ids)]
    cols = ["web_name", "team", "pos", "pris", "eo", "squad_pct",
            "captain_pct", "selected_by_percent"]
    return missing.nlargest(top, "eo")[cols].reset_index(drop=True)


def differentials(players: pd.DataFrame, max_ownership: float = 10.0,
                  min_minutes: int = 270, top: int = 20) -> pd.DataFrame:
    """Lavt eid, men leverer. Rangert paa form."""
    eligible = players[
        (players["selected_by_percent"] <= max_ownership)
        & (players["minutes"] >= min_minutes)
        & (players["status"] == "a")
    ]
    cols = ["web_name", "team", "pos", "pris", "selected_by_percent", "form",
            "total_points", "poeng_per_mill", "expected_goals", "expected_assists"]
    return eligible.nlargest(top, "form")[cols].reset_index(drop=True)
