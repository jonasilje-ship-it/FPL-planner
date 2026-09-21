"""Samler alt siden trenger fra databasen til en enkelt dict.

Delt fra selve rendringen med vilje: denne modulen vet om SQL og modeller,
`render.py` vet om HTML. Da kan begge testes hver for seg, og dicten er
samtidig den konteksten den levende spoerreboksen paa siden faar.
"""

from __future__ import annotations

import math
from typing import Any

import numpy as np
import pandas as pd
from sqlalchemy import select

from .. import db
from ..analysis import basics, squad_view
from ..brief import run_brief
from ..models import backtest
from ..optimize import objective
from ..optimize import plan as planner

POSITIONS = {1: "GK", 2: "DEF", 3: "MID", 4: "FWD"}
HORIZON = 5


def clean(value: Any) -> Any:
    """Gjor numpy- og pandas-verdier trygge a serialisere til JSON."""
    if isinstance(value, np.integer):
        return int(value)
    if isinstance(value, (np.floating, float)):
        value = float(value)
        return None if math.isnan(value) else round(value, 3)
    if isinstance(value, (np.bool_, bool)):
        return bool(value)
    if value is pd.NaT:
        return None
    return value


def _records(frame: pd.DataFrame, columns: list[str]) -> list[dict]:
    return [{c: clean(row[c]) for c in columns} for _, row in frame.iterrows()]


def collect(entry_id: int, free_transfers: int = 1) -> dict:
    """Bygg hele datagrunnlaget for siden."""
    current = basics.current_event()
    upcoming = basics.next_event()
    horizon = list(range(upcoming, upcoming + HORIZON))

    entry = basics.load_entry(entry_id)
    players = basics.load_players()
    text, fdr = basics.fixture_grid(upcoming, HORIZON)
    score = basics.fixture_score(fdr)
    teams = players[["team_id", "team", "team_name"]].drop_duplicates().set_index("team_id")

    modelled = squad_view.squad_with_model(entry_id, current, upcoming, horizon=3)
    spread = (squad_view.predictions([upcoming])
              .groupby("player_id")
              .agg(p_mid=("p_mid", "max"), p_good=("p_good", "max"))
              .reset_index())
    modelled = modelled.merge(spread, on="player_id", how="left")

    squad_fields = ["position", "web_name", "rad", "team", "pris", "xp_next",
                    "xp_horizon", "p_blank", "p_mid", "p_good", "p_haul",
                    "p_clean_sheet", "p_goal", "p_60", "exp_minutes", "total_points",
                    "form", "selected_by_percent", "status_tekst", "news", "rolle",
                    "ep_next"]

    def squad_row(row) -> dict:
        out = {f: clean(row[f]) for f in squad_fields}
        out["kamper"] = [
            {"gw": int(gw), "txt": label,
             "fdr": clean(fdr.at[row["team_id"], gw]) if gw in fdr.columns else None}
            for gw, label in (row["kamper"] or [])
        ]
        return out

    squad_rows = [squad_row(row) for _, row in modelled.iterrows()]

    grid = sorted([
        {"team": teams.loc[t, "team_name"], "short": teams.loc[t, "team"],
         "score": clean(score.get(t)),
         "cells": [{"gw": int(gw), "txt": text.at[t, gw] or "",
                    "fdr": clean(fdr.at[t, gw])} for gw in text.columns]}
        for t in text.index], key=lambda r: r["score"])

    # --- optimizeren: anbefaling, plan og strategier ---
    preds = _read(select(db.predictions).where(db.predictions.c.event.in_(horizon)))
    true_values = objective.to_matrix(preds, risk=0.0)
    indexed = players.set_index("id")

    def player_note(player_id: int) -> dict:
        row = indexed.loc[player_id]
        match = preds[(preds["player_id"] == player_id) & (preds["event"] == upcoming)]
        return {
            "navn": row["web_name"], "lag": row["team"],
            "pos": POSITIONS[int(row["element_type"])], "pris": clean(row["pris"]),
            "eid": clean(row["selected_by_percent"]),
            "xp": clean(float(true_values.at[player_id, upcoming])
                        if player_id in true_values.index else 0.0),
            "xp5": clean(float(true_values.loc[player_id].sum())
                         if player_id in true_values.index else 0.0),
            "haul": clean(float(match["p_haul"].max()) if len(match) else None),
            "blank": clean(float(match["p_blank"].min()) if len(match) else None),
        }

    baseline = planner.no_transfer_baseline(entry_id, horizon=HORIZON,
                                            free_transfers=free_transfers)
    baseline_plan = planner.describe(baseline["solution"], baseline["players"],
                                     true_values)

    strategies, main = [], None
    for risk, label in ((0.0, "Forventede poeng"), (-0.6, "Trygt"), (0.6, "Aggressivt")):
        result = planner.run(entry_id, horizon=HORIZON, risk=risk,
                             free_transfers=free_transfers)
        net = float(result["plan"]["xP"].sum() + result["plan"]["Hit"].sum())
        if risk == 0.0:
            main = result
        strategies.append({
            "navn": label, "risk": risk, "netto": round(net, 1),
            "hits": int(-result["plan"]["Hit"].sum() // 4),
            "gevinst": round(net - float(baseline_plan["xP"].sum()), 1),
            "gw5_inn": result["plan"].iloc[0]["Inn"],
            "gw5_ut": result["plan"].iloc[0]["Ut"],
            "kaptein": result["plan"].iloc[0]["Kaptein"],
        })

    move = main["solution"].moves[0]

    def league(where: str, limit: int) -> list[dict]:
        query = f"""
            select p.web_name, t.short_name lag, p.element_type, p.now_cost/10.0 pris,
                   p.selected_by_percent eid, sum(pr.exp_points) xp3
            from predictions pr
            join players p on p.id = pr.player_id
            join teams t on t.id = p.team_id
            where pr.event between :a and :b and p.status = 'a' and {where}
            group by p.id order by xp3 desc limit {limit}
        """
        frame = pd.read_sql(query, db.get_engine(),
                            params={"a": upcoming, "b": upcoming + 2})
        frame["rad"] = frame["element_type"].map(POSITIONS)
        return _records(frame, ["web_name", "lag", "rad", "pris", "eid", "xp3"])

    eo = basics.load_effective_ownership(current)
    squad_ids = {int(p) for p in modelled["player_id"]} if not modelled.empty else set()
    eo_top = (_records(eo.nlargest(14, "eo"),
                       ["web_name", "team", "pos", "pris", "eo", "squad_pct",
                        "captain_pct", "selected_by_percent"])
              if not eo.empty else [])
    eo_risk = (_records(basics.rank_risk(squad_ids, eo, top=8),
                        ["web_name", "team", "pos", "pris", "eo", "squad_pct",
                         "captain_pct", "selected_by_percent"])
               if not eo.empty else [])
    eo_sample = int(eo["sample_size"].iloc[0]) if not eo.empty else 0

    brief = run_brief(entry_id, horizon=3, free_transfers=free_transfers)
    bt = backtest.clean_sheet_backtest("2025-26")
    bt_prev = backtest.clean_sheet_backtest("2024-25")
    calibration = backtest.clean_sheet_calibration("2025-26").reset_index()

    data = {
        "generated": pd.Timestamp.now("UTC").strftime("%d.%m.%Y %H:%M UTC"),
        "current_gw": int(current), "next_gw": int(upcoming),
        "gws": [int(g) for g in text.columns],
        "entry": {k: clean(entry[k]) for k in
                  ["name", "summary_overall_points", "summary_overall_rank",
                   "summary_event_points", "value", "bank"]},
        "squad": squad_rows,
        "captain": _records(squad_view.captain_advice(modelled),
                            ["web_name", "team", "rad", "xp_next", "xp_kaptein",
                             "p_haul", "p_blank", "rolle"]),
        "bench": _records(squad_view.bench_check(modelled).head(4),
                          ["inn", "inn_xp", "ut", "ut_xp", "gevinst"]),
        "top": league("p.minutes > 180", 14),
        "diff": league("p.minutes > 270 and p.selected_by_percent <= 10", 12),
        "eo": {"topp": eo_top, "risiko": eo_risk, "utvalg": eo_sample,
               "liga": "Overall (314)"},
        "grid": grid,
        "alerts": basics.squad_alerts(basics.load_my_squad(entry_id, current), fdr),
        "model": {
            "brier_2025": clean(bt["brier"]), "baseline_2025": clean(bt["brier_baseline"]),
            "skill_2025": clean(bt["skill"]), "n_2025": bt["n"],
            "base_rate": clean(bt["base_rate"]), "mean_pred": clean(bt["mean_predicted"]),
            "skill_2024": clean(bt_prev["skill"]), "brier_2024": clean(bt_prev["brier"]),
            "baseline_2024": clean(bt_prev["brier_baseline"]), "sims": 10_000,
            "calibration": [{"spadd": clean(r["spadd"]), "faktisk": clean(r["faktisk"]),
                             "kamper": int(r["kamper"])}
                            for _, r in calibration.iterrows()],
        },
        "opt": {
            "baseline_netto": round(float(baseline_plan["xP"].sum()), 1),
            "anbefaling": {
                "inn": [player_note(p) for p in move.transfers_in],
                "ut": [player_note(p) for p in move.transfers_out],
                "kaptein": main["plan"].iloc[0]["Kaptein"],
                "hits": move.hits, "bank": round(move.bank_after / 10, 1),
            },
            "plan": [{k: (round(v, 1) if isinstance(v, float) else v)
                      for k, v in row.items()}
                     for row in main["plan"].to_dict("records")],
            "strategier": strategies,
            "horisont": horizon,
        },
        "brief": {
            "headline": brief.headline, "body": brief.body,
            "confidence": brief.confidence, "severity": brief.severity,
            "changes": [{k: clean(v) for k, v in c.as_dict().items()}
                        for c in brief.changes],
            "generated": pd.Timestamp.now("UTC").strftime("%d.%m.%Y %H:%M UTC"),
        },
    }
    data["ctx"] = _context(data)
    return data


def _read(stmt) -> pd.DataFrame:
    with db.get_engine().connect() as conn:
        return pd.read_sql(stmt, conn)


def _context(data: dict) -> dict:
    """Kompakt utdrag som sendes til Claude naar noen spor siden om noe.

    Holdes bevisst liten: alt som ikke kan svare paa et sporsmaal om laget
    er ballast i en prompt med en storrelsesgrense.
    """
    squad = [{
        "n": p["web_name"], "pos": p["rad"], "lag": p["team"], "pris": p["pris"],
        "xp": p["xp_next"], "xp3": p["xp_horizon"], "blank": p["p_blank"],
        "haul": p["p_haul"], "cs": p["p_clean_sheet"], "min": p["exp_minutes"],
        "eid": p["selected_by_percent"], "start": p["position"] <= 11,
        "rolle": p["rolle"], "kamper": [k["txt"] for k in p["kamper"]],
    } for p in data["squad"]]

    market = [{"n": r["web_name"], "pos": r["rad"], "lag": r["lag"], "pris": r["pris"],
               "eid": r["eid"], "xp3": r["xp3"]} for r in data["top"]]

    return {
        "gw": data["next_gw"], "lag": data["entry"]["name"],
        "rank": data["entry"]["summary_overall_rank"],
        "poeng": data["entry"]["summary_overall_points"],
        "bank": round(data["entry"]["bank"] / 10, 1),
        "verdi": round(data["entry"]["value"] / 10, 1),
        "tropp": squad, "marked": market,
        "plan": data["opt"]["plan"], "anbefaling": data["opt"]["anbefaling"],
        "eo_topp": data["eo"]["topp"][:8], "eo_risiko": data["eo"]["risiko"],
        "brief": {"headline": data["brief"]["headline"],
                  "confidence": data["brief"]["confidence"],
                  "endringer": [c["text"] for c in data["brief"]["changes"]]},
        "modell": {"sims": data["model"]["sims"], "brier": data["model"]["brier_2025"],
                   "baseline": data["model"]["baseline_2025"]},
    }
