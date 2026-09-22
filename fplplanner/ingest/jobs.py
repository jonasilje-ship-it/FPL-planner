"""Ingest-jobber: FPL-APIet inn i databasen.

Appen leser aldri fra APIet direkte. Disse jobbene kjores paa cron og skriver
til databasen, som er eneste sannhetskilde for Streamlit-appen og modellene.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from .. import db
from ..config import get_settings
from ..models import ownership as ownership_model
from .client import FPLClient, FPLError

log = logging.getLogger(__name__)

GLOBAL_LEAGUE_ID = 314  # FPLs egen "Overall"-liga: alle spillere, sortert paa poeng.


# --- parsehjelpere ---------------------------------------------------
# APIet blander typer: tall kommer som strenger, tomme felter som "" eller None.

def _dt(value: str | None) -> datetime | None:
    if not value:
        return None
    return datetime.fromisoformat(value.replace("Z", "+00:00")).replace(tzinfo=None)


def _f(value) -> float | None:
    if value in (None, "", "None"):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _i(value) -> int | None:
    if value in (None, "", "None"):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _log_run(job: str, rows: int, ok: bool = True, detail: str = "") -> None:
    db.append_rows(db.ingest_log, [{
        "job": job, "ran_at": _now(), "rows": rows, "ok": ok, "detail": detail[:512],
    }])


# --- jobber ----------------------------------------------------------

def refresh_core(client: FPLClient | None = None) -> dict[str, int]:
    """Gameweeks, lag, spillere og kamper. Kjapt - kan kjores ofte."""
    client = client or FPLClient()
    data = client.bootstrap()
    now = _now()

    counts = {}
    counts["events"] = db.replace_table(db.events, [{
        "id": e["id"],
        "name": e["name"],
        "deadline_time": _dt(e.get("deadline_time")),
        "is_current": bool(e.get("is_current")),
        "is_next": bool(e.get("is_next")),
        "finished": bool(e.get("finished")),
        "average_entry_score": _i(e.get("average_entry_score")),
        "highest_score": _i(e.get("highest_score")),
    } for e in data["events"]])

    counts["teams"] = db.replace_table(db.teams, [{
        "id": t["id"], "code": t.get("code"), "name": t["name"],
        "short_name": t["short_name"], "strength": t.get("strength"),
        "strength_attack_home": t.get("strength_attack_home"),
        "strength_attack_away": t.get("strength_attack_away"),
        "strength_defence_home": t.get("strength_defence_home"),
        "strength_defence_away": t.get("strength_defence_away"),
    } for t in data["teams"]])

    counts["players"] = db.replace_table(db.players, [{
        "id": p["id"], "code": p.get("code"), "web_name": p.get("web_name"),
        "first_name": p.get("first_name"), "second_name": p.get("second_name"),
        "team_id": p["team"], "element_type": p["element_type"],
        "now_cost": p["now_cost"], "status": p.get("status"),
        "news": (p.get("news") or "")[:512],
        "chance_of_playing_next_round": _i(p.get("chance_of_playing_next_round")),
        "selected_by_percent": _f(p.get("selected_by_percent")),
        "form": _f(p.get("form")), "points_per_game": _f(p.get("points_per_game")),
        "total_points": _i(p.get("total_points")), "minutes": _i(p.get("minutes")),
        "starts": _i(p.get("starts")), "goals_scored": _i(p.get("goals_scored")),
        "assists": _i(p.get("assists")), "clean_sheets": _i(p.get("clean_sheets")),
        "expected_goals": _f(p.get("expected_goals")),
        "expected_assists": _f(p.get("expected_assists")),
        "expected_goals_conceded": _f(p.get("expected_goals_conceded")),
        "defensive_contribution": _i(p.get("defensive_contribution")),
        "ep_next": _f(p.get("ep_next")),
        "penalties_order": _i(p.get("penalties_order")),
        "cost_change_event": _i(p.get("cost_change_event")),
        "price_change_percent": _f(p.get("price_change_percent")),
        # scout_risks flagger blant annet laaneklausuler: en spiller som ikke
        # kan moete moderklubben sin er en garantert nullscore den runden.
        "loan_blocked_events": ",".join(
            str(r["gameweek"]) for r in (p.get("scout_risks") or [])
            if r.get("property") == "loan_ineligible" and r.get("gameweek")
        )[:64] or None,
        "transfers_in_event": _i(p.get("transfers_in_event")),
        "transfers_out_event": _i(p.get("transfers_out_event")),
        "updated_at": now,
    } for p in data["elements"]])

    fx = client.fixtures()
    counts["fixtures"] = db.replace_table(db.fixtures, [{
        "id": f["id"], "event": f.get("event"), "kickoff_time": _dt(f.get("kickoff_time")),
        "team_h": f["team_h"], "team_a": f["team_a"],
        "team_h_difficulty": f.get("team_h_difficulty"),
        "team_a_difficulty": f.get("team_a_difficulty"),
        "team_h_score": f.get("team_h_score"), "team_a_score": f.get("team_a_score"),
        "finished": bool(f.get("finished")), "started": bool(f.get("started")),
    } for f in fx])

    _log_run("refresh_core", sum(counts.values()), True, str(counts))
    log.info("refresh_core: %s", counts)
    return counts


def snapshot_prices(client: FPLClient | None = None) -> int:
    """Ta vare paa pris og eierskap akkurat naa.

    APIet husker ikke historikk her - uten dette snapshotet kan vi aldri
    modellere prisendringer, fordi dataene forsvinner i det de endrer seg.
    """
    client = client or FPLClient()
    data = client.bootstrap()
    captured = _now()
    rows = [{
        "player_id": p["id"], "captured_at": captured, "now_cost": p["now_cost"],
        "selected_by_percent": _f(p.get("selected_by_percent")),
        "transfers_in_event": _i(p.get("transfers_in_event")),
        "transfers_out_event": _i(p.get("transfers_out_event")),
    } for p in data["elements"]]
    n = db.append_rows(db.price_history, rows)
    _log_run("snapshot_prices", n)
    return n


def refresh_player_history(
    client: FPLClient | None = None,
    player_ids: list[int] | None = None,
) -> int:
    """Per-kamp-historikk med xG, xA og xGC for hver spiller.

    Ett API-kall per spiller (~660 stk), saa denne hoerer hjemme i den
    daglige jobben - ikke i timesjobben.
    """
    client = client or FPLClient()
    if player_ids is None:
        data = client.bootstrap()
        player_ids = [p["id"] for p in data["elements"]]

    total, failed = 0, []
    for idx, pid in enumerate(player_ids, start=1):
        try:
            summary = client.element_summary(pid)
        except FPLError as exc:
            failed.append(pid)
            log.warning("hoppet over spiller %s: %s", pid, exc)
            continue
        rows = [{
            "player_id": pid, "fixture": h["fixture"], "round": h.get("round"),
            "opponent_team": h.get("opponent_team"), "was_home": bool(h.get("was_home")),
            "kickoff_time": _dt(h.get("kickoff_time")),
            "minutes": _i(h.get("minutes")), "starts": _i(h.get("starts")),
            "total_points": _i(h.get("total_points")),
            "goals_scored": _i(h.get("goals_scored")), "assists": _i(h.get("assists")),
            "clean_sheets": _i(h.get("clean_sheets")),
            "goals_conceded": _i(h.get("goals_conceded")), "saves": _i(h.get("saves")),
            "bonus": _i(h.get("bonus")), "bps": _i(h.get("bps")),
            "expected_goals": _f(h.get("expected_goals")),
            "expected_assists": _f(h.get("expected_assists")),
            "expected_goals_conceded": _f(h.get("expected_goals_conceded")),
            "defensive_contribution": _i(h.get("defensive_contribution")),
            "value": _i(h.get("value")),
        } for h in summary.get("history", [])]
        total += db.replace_where(db.player_gw, db.player_gw.c.player_id == pid, rows)
        if idx % 100 == 0:
            log.info("spillerhistorikk: %s/%s", idx, len(player_ids))

    _log_run("refresh_player_history", total, not failed,
             f"{len(failed)} feilet: {failed[:20]}")
    return total


def refresh_my_squad(entry_id: int | None = None, client: FPLClient | None = None) -> int:
    """Mine picks og poenghistorikk for alle spilte gameweeks."""
    client = client or FPLClient()
    entry_id = entry_id or get_settings().entry_id

    # Live-tall: entry_history oppdateres forst naar runden er ferdigregnet,
    # saa underveis i en gameweek er dette eneste kilde til riktig poengsum.
    entry = client.entry(entry_id)
    db.upsert_rows(db.my_entry, [{
        "entry_id": entry_id,
        "name": entry.get("name"),
        "player_name": f"{entry.get('player_first_name', '')} {entry.get('player_last_name', '')}".strip(),
        "summary_overall_points": _i(entry.get("summary_overall_points")),
        "summary_overall_rank": _i(entry.get("summary_overall_rank")),
        "summary_event_points": _i(entry.get("summary_event_points")),
        "current_event": _i(entry.get("current_event")),
        "bank": _i(entry.get("last_deadline_bank")),
        "value": _i(entry.get("last_deadline_value")),
        "total_transfers": _i(entry.get("last_deadline_total_transfers")),
        "updated_at": _now(),
    }])

    history = client.entry_history(entry_id)
    hist_rows = [{
        "entry_id": entry_id, "event": h["event"], "points": h.get("points"),
        "total_points": h.get("total_points"), "overall_rank": h.get("overall_rank"),
        "bank": h.get("bank"), "value": h.get("value"),
        "event_transfers": h.get("event_transfers"),
        "event_transfers_cost": h.get("event_transfers_cost"),
        "points_on_bench": h.get("points_on_bench"),
    } for h in history.get("current", [])]
    db.upsert_rows(db.entry_history, hist_rows)

    total = 0
    for h in history.get("current", []):
        gw = h["event"]
        try:
            picks = client.entry_picks(entry_id, gw)
        except FPLError as exc:
            log.warning("ingen picks for GW%s: %s", gw, exc)
            continue
        rows = [{
            "entry_id": entry_id, "event": gw, "player_id": p["element"],
            "position": p["position"], "multiplier": p["multiplier"],
            "is_captain": bool(p.get("is_captain")),
            "is_vice_captain": bool(p.get("is_vice_captain")),
        } for p in picks.get("picks", [])]
        total += db.upsert_rows(db.my_squad, rows)

    _log_run("refresh_my_squad", total, True, f"entry={entry_id}")
    return total


def top_manager_ids(client: FPLClient, league_id: int = GLOBAL_LEAGUE_ID,
                    n: int = 150) -> list[int]:
    """De n hoyest rangerte managerne i en klassisk liga.

    Liga 314 er FPLs egen "Overall"-liga - alle som spiller er med, sortert
    paa total poengsum. Det gjor den til beste tilgjengelige proxy for "hva
    gjor de beste lagene", uten aa maatte gjette hvem som er dyktig.
    """
    ids: list[int] = []
    page = 1
    while len(ids) < n:
        try:
            data = client.league_standings(league_id, page=page)
        except FPLError as exc:
            log.warning("klarte ikke hente standings side %s: %s", page, exc)
            break
        results = data["standings"]["results"]
        if not results:
            break
        ids.extend(r["entry"] for r in results)
        if not data["standings"]["has_next"]:
            break
        page += 1
    return ids[:n]


def refresh_effective_ownership(
    sample_size: int = 150,
    league_id: int = GLOBAL_LEAGUE_ID,
    event: int | None = None,
    client: FPLClient | None = None,
) -> int:
    """Hent picks fra toppen av tabellen og regn ut effektivt eierskap.

    Det dyreste kallet i pipelinen - ett API-kall per manager i stikkproven i
    tillegg til rangeringssidene - saa stikkproven holdes moderat (standard
    150 managere, ca 150 + 3 kall og noen faa minutter med throttling).
    """
    client = client or FPLClient()
    if event is None:
        data = client.bootstrap()
        current = next((e["id"] for e in data["events"] if e.get("is_current")), None)
        if current is None:
            finished = [e["id"] for e in data["events"] if e.get("finished")]
            current = max(finished) if finished else 1
        event = current

    manager_ids = top_manager_ids(client, league_id, sample_size)
    picks: list[ownership_model.ManagerPick] = []
    failed = 0
    for entry_id in manager_ids:
        try:
            data = client.entry_picks(entry_id, event)
        except FPLError:
            failed += 1
            continue
        chip = data.get("active_chip")
        for p in data.get("picks", []):
            picks.append(ownership_model.ManagerPick(
                entry_id=entry_id, player_id=p["element"],
                is_captain=bool(p.get("is_captain")), active_chip=chip,
            ))

    eo = ownership_model.aggregate_eo(picks)
    captured = _now()
    rows = [{
        "player_id": int(pid), "event": event,
        "squad_pct": float(r["squad_pct"]), "captain_pct": float(r["captain_pct"]),
        "tc_pct": float(r["tc_pct"]), "eo": float(r["eo"]),
        "sample_size": int(r["n_sample"]), "captured_at": captured,
    } for pid, r in eo.iterrows()]

    n = db.replace_where(db.effective_ownership, db.effective_ownership.c.event == event, rows)
    ok = failed < max(1, len(manager_ids) // 2)
    _log_run("refresh_effective_ownership", n, ok,
             f"event={event} {failed} feilet av {len(manager_ids)}")
    return n
