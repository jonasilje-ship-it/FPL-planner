"""Databaseskjema og tilkobling.

Skjemaet er skrevet med SQLAlchemy Core slik at det virker uendret paa SQLite
(lokal utvikling) og Postgres (Supabase i produksjon).
"""

from __future__ import annotations

from typing import Any, Iterable, Sequence

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Float,
    Integer,
    MetaData,
    String,
    Table,
    create_engine,
    delete,
    insert,
)
from sqlalchemy.engine import Engine

from .config import get_settings

metadata = MetaData()

events = Table(
    "events", metadata,
    Column("id", Integer, primary_key=True),
    Column("name", String(64)),
    Column("deadline_time", DateTime),
    Column("is_current", Boolean),
    Column("is_next", Boolean),
    Column("finished", Boolean),
    Column("average_entry_score", Integer),
    Column("highest_score", Integer),
)

teams = Table(
    "teams", metadata,
    Column("id", Integer, primary_key=True),
    Column("code", Integer),
    Column("name", String(64)),
    Column("short_name", String(8)),
    Column("strength", Integer),
    Column("strength_attack_home", Integer),
    Column("strength_attack_away", Integer),
    Column("strength_defence_home", Integer),
    Column("strength_defence_away", Integer),
)

players = Table(
    "players", metadata,
    Column("id", Integer, primary_key=True),
    Column("code", Integer),
    Column("web_name", String(64)),
    Column("first_name", String(64)),
    Column("second_name", String(64)),
    Column("team_id", Integer),
    Column("element_type", Integer),          # 1=GK 2=DEF 3=MID 4=FWD
    Column("now_cost", Integer),              # tideler av millioner: 55 = 5.5
    Column("status", String(4)),              # a=available d=doubtful i=injured s=suspended u=unavailable
    Column("news", String(512)),
    Column("chance_of_playing_next_round", Integer),
    Column("selected_by_percent", Float),
    Column("form", Float),
    Column("points_per_game", Float),
    Column("total_points", Integer),
    Column("minutes", Integer),
    Column("starts", Integer),
    Column("goals_scored", Integer),
    Column("assists", Integer),
    Column("clean_sheets", Integer),
    Column("expected_goals", Float),
    Column("expected_assists", Float),
    Column("expected_goals_conceded", Float),
    Column("defensive_contribution", Integer),
    Column("ep_next", Float),                 # FPL sitt eget estimat - vaar baseline aa slaa
    Column("penalties_order", Integer),
    Column("cost_change_event", Integer),
    Column("price_change_percent", Float),   # FPLs egen framdrift mot terskelen
    Column("loan_blocked_events", String(64)),
    Column("transfers_in_event", Integer),
    Column("transfers_out_event", Integer),
    Column("updated_at", DateTime),
)

fixtures = Table(
    "fixtures", metadata,
    Column("id", Integer, primary_key=True),
    Column("event", Integer),
    Column("kickoff_time", DateTime),
    Column("team_h", Integer),
    Column("team_a", Integer),
    Column("team_h_difficulty", Integer),
    Column("team_a_difficulty", Integer),
    Column("team_h_score", Integer),
    Column("team_a_score", Integer),
    Column("finished", Boolean),
    Column("started", Boolean),
)

player_gw = Table(
    "player_gw", metadata,
    Column("player_id", Integer, primary_key=True),
    Column("fixture", Integer, primary_key=True),
    Column("round", Integer),
    Column("opponent_team", Integer),
    Column("was_home", Boolean),
    Column("kickoff_time", DateTime),
    Column("minutes", Integer),
    Column("starts", Integer),
    Column("total_points", Integer),
    Column("goals_scored", Integer),
    Column("assists", Integer),
    Column("clean_sheets", Integer),
    Column("goals_conceded", Integer),
    Column("saves", Integer),
    Column("bonus", Integer),
    Column("bps", Integer),
    Column("expected_goals", Float),
    Column("expected_assists", Float),
    Column("expected_goals_conceded", Float),
    Column("defensive_contribution", Integer),
    Column("value", Integer),
)

price_history = Table(
    "price_history", metadata,
    Column("player_id", Integer, primary_key=True),
    Column("captured_at", DateTime, primary_key=True),
    Column("now_cost", Integer),
    Column("selected_by_percent", Float),
    Column("transfers_in_event", Integer),
    Column("transfers_out_event", Integer),
)

my_squad = Table(
    "my_squad", metadata,
    Column("entry_id", Integer, primary_key=True),
    Column("event", Integer, primary_key=True),
    Column("player_id", Integer, primary_key=True),
    Column("position", Integer),
    Column("multiplier", Integer),
    Column("is_captain", Boolean),
    Column("is_vice_captain", Boolean),
)

entry_history = Table(
    "entry_history", metadata,
    Column("entry_id", Integer, primary_key=True),
    Column("event", Integer, primary_key=True),
    Column("points", Integer),
    Column("total_points", Integer),
    Column("overall_rank", Integer),
    Column("bank", Integer),
    Column("value", Integer),
    Column("event_transfers", Integer),
    Column("event_transfers_cost", Integer),
    Column("points_on_bench", Integer),
)

my_entry = Table(
    "my_entry", metadata,
    Column("entry_id", Integer, primary_key=True),
    Column("name", String(128)),
    Column("player_name", String(128)),
    Column("summary_overall_points", Integer),
    Column("summary_overall_rank", Integer),
    Column("summary_event_points", Integer),
    Column("current_event", Integer),
    Column("bank", Integer),
    Column("value", Integer),
    Column("total_transfers", Integer),
    Column("updated_at", DateTime),
)

hist_player_gw = Table(
    "hist_player_gw", metadata,
    Column("season", String(8), primary_key=True),
    Column("element", Integer, primary_key=True),
    Column("round", Integer, primary_key=True),
    Column("fixture", Integer, primary_key=True),
    Column("name", String(96)),
    Column("position", String(4)),
    Column("team", String(64)),
    Column("opponent_team", Integer),
    Column("was_home", Boolean),
    Column("minutes", Integer),
    Column("starts", Integer),
    Column("total_points", Integer),
    Column("goals_scored", Integer),
    Column("assists", Integer),
    Column("clean_sheets", Integer),
    Column("goals_conceded", Integer),
    Column("expected_goals", Float),
    Column("expected_assists", Float),
    Column("expected_goals_conceded", Float),
    Column("bonus", Integer),
    Column("bps", Integer),
    Column("value", Integer),
)

team_params = Table(
    "team_params", metadata,
    Column("team_id", Integer, primary_key=True),
    Column("as_of_event", Integer, primary_key=True),
    Column("attack", Float),          # 1.0 = ligagjennomsnitt
    Column("defence", Float),         # lavere er bedre
    Column("matches", Integer),
    Column("xg_for_per_match", Float),
    Column("xg_against_per_match", Float),
    Column("updated_at", DateTime),
)

predictions = Table(
    "predictions", metadata,
    Column("player_id", Integer, primary_key=True),
    Column("fixture", Integer, primary_key=True),
    Column("event", Integer),
    Column("opponent_team", Integer),
    Column("was_home", Boolean),
    Column("exp_points", Float),
    Column("median_points", Float),
    Column("p10", Float),
    Column("p25", Float),
    Column("p75", Float),
    Column("p90", Float),
    Column("p_blank", Float),         # 2 poeng eller mindre
    Column("p_mid", Float),           # 3-6 poeng
    Column("p_good", Float),          # 7-9 poeng
    Column("p_haul", Float),          # 10 eller mer
    Column("p_start", Float),
    Column("p_60", Float),
    Column("exp_minutes", Float),
    Column("p_clean_sheet", Float),
    Column("p_goal", Float),
    Column("p_assist", Float),
    Column("team_lambda", Float),
    Column("opp_lambda", Float),
    Column("updated_at", DateTime),
)

world_snapshot = Table(
    "world_snapshot", metadata,
    Column("captured_at", DateTime, primary_key=True),
    Column("player_id", Integer, primary_key=True),
    Column("status", String(4)),
    Column("chance", Integer),
    Column("now_cost", Integer),
    Column("selected_by_percent", Float),
    Column("xp_horizon", Float),
    Column("fixtures_ahead", Integer),
    Column("news", String(512)),
)

briefings = Table(
    "briefings", metadata,
    Column("created_at", DateTime, primary_key=True),
    Column("event", Integer),
    Column("headline", String(512)),
    Column("body", String(8000)),
    Column("changes_json", String(16000)),
    Column("plan_json", String(8000)),
    Column("severity", Integer),
)

effective_ownership = Table(
    "effective_ownership", metadata,
    Column("player_id", Integer, primary_key=True),
    Column("event", Integer, primary_key=True),
    Column("squad_pct", Float),       # eierandel i stikkproven av toppmanagere
    Column("captain_pct", Float),     # andel som kapteinet (utenom triple captain)
    Column("tc_pct", Float),          # andel som spilte triple captain paa ham
    Column("eo", Float),              # squad_pct + captain_pct + 2*tc_pct
    Column("sample_size", Integer),
    Column("captured_at", DateTime),
)

ingest_log = Table(
    "ingest_log", metadata,
    Column("job", String(64), primary_key=True),
    Column("ran_at", DateTime, primary_key=True),
    Column("rows", Integer),
    Column("ok", Boolean),
    Column("detail", String(512)),
)


_engine: Engine | None = None


def get_engine(echo: bool = False) -> Engine:
    """Motor med connection pooling. Gjenbrukes i hele prosessen."""
    global _engine
    if _engine is None:
        settings = get_settings()
        kwargs: dict[str, Any] = {"echo": echo, "future": True}
        if not settings.is_sqlite:
            # Supabase kobler ned inaktive tilkoblinger; sjekk at de lever for bruk.
            kwargs.update(pool_pre_ping=True, pool_recycle=300)
        _engine = create_engine(settings.database_url, **kwargs)
    return _engine


def create_all(engine: Engine | None = None) -> None:
    metadata.create_all(engine or get_engine())


def replace_table(table: Table, rows: Sequence[dict], engine: Engine | None = None) -> int:
    """Bytt ut hele innholdet i en tabell i en transaksjon.

    Brukt for dimensjonstabeller (spillere, lag, kamper) der APIet alltid gir
    oss hele sannheten. Enten gaar hele byttet gjennom, eller saa staar den
    gamle versjonen igjen - vi ender aldri med en halvfylt tabell.
    """
    engine = engine or get_engine()
    with engine.begin() as conn:
        conn.execute(delete(table))
        if rows:
            conn.execute(insert(table), list(rows))
    return len(rows)


def upsert_rows(table: Table, rows: Sequence[dict], engine: Engine | None = None) -> int:
    """Skriv rader og erstatt eventuelle eksisterende med samme primaernokkel.

    Holdt dialekt-noytralt med slett-og-sett-inn per nokkel i stedet for
    ON CONFLICT, slik at samme kode virker paa SQLite og Postgres.
    """
    if not rows:
        return 0
    engine = engine or get_engine()
    pk_cols = [c.name for c in table.primary_key.columns]
    with engine.begin() as conn:
        for row in rows:
            conn.execute(
                delete(table).where(
                    *[table.c[c] == row[c] for c in pk_cols]
                )
            )
        conn.execute(insert(table), list(rows))
    return len(rows)


def replace_where(table: Table, whereclause, rows: Sequence[dict],
                  engine: Engine | None = None) -> int:
    """Slett en avgrenset del av en tabell og sett inn nye rader for den.

    Ett DELETE + ett INSERT, uansett hvor mange rader. Alternativet - aa slette
    rad for rad paa primaernokkel - blir tusenvis av tur-retur mot databasen og
    er uspiselig tregt mot Postgres over nett.
    """
    engine = engine or get_engine()
    with engine.begin() as conn:
        conn.execute(delete(table).where(whereclause))
        if rows:
            conn.execute(insert(table), list(rows))
    return len(rows)


def append_rows(table: Table, rows: Sequence[dict], engine: Engine | None = None) -> int:
    if not rows:
        return 0
    engine = engine or get_engine()
    with engine.begin() as conn:
        conn.execute(insert(table), list(rows))
    return len(rows)


def table_names() -> Iterable[str]:
    return metadata.tables.keys()
