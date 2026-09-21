#!/usr/bin/env python3
"""Kjor ingest-jobber fra kommandolinjen eller cron.

    python scripts/run_ingest.py core            # kjapt: spillere, lag, kamper
    python scripts/run_ingest.py prices          # prissnapshot (kjor hver time)
    python scripts/run_ingest.py history         # per-GW xG per spiller (tregt)
    python scripts/run_ingest.py squad           # mitt lag
    python scripts/run_ingest.py eo              # effektivt eierskap blant toppmanagere
    python scripts/run_ingest.py historical      # tidligere sesonger
    python scripts/run_ingest.py daily           # core + history + squad + prices
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

# Gjor pakken importerbar naar scriptet kjores direkte (cron, GitHub Actions).
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fplplanner import db
from fplplanner.ingest import historical, jobs
from fplplanner.ingest.client import FPLClient


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("job", choices=[
        "core", "prices", "history", "squad", "eo", "historical", "predict",
        "backtest", "optimize", "brief", "daily", "hourly",
    ])
    parser.add_argument("--seasons", nargs="*", default=["2025-26", "2024-25"])
    parser.add_argument("--entry", type=int, default=None,
                        help="entry-ID; standard er den i .env")
    parser.add_argument("--risk", type=float, default=0.0,
                        help="-1 trygt, 0 forventede poeng, +1 aggressivt")
    parser.add_argument("--free-transfers", type=int, default=1)
    parser.add_argument("--horizon", type=int, default=5,
                        help="antall gameweeks fremover som skal simuleres")
    parser.add_argument("--sims", type=int, default=10_000,
                        help="simuleringer per spiller per kamp")
    parser.add_argument("--sample-size", type=int, default=150,
                        help="antall toppmanagere i EO-stikkproven")
    parser.add_argument("--verbose", "-v", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    db.create_all()
    client = FPLClient()
    if args.entry is None:
        from fplplanner.config import get_settings
        args.entry = get_settings().entry_id

    if args.job == "core":
        print(jobs.refresh_core(client))
    elif args.job == "prices":
        print(f"{jobs.snapshot_prices(client)} prisrader")
    elif args.job == "history":
        print(f"{jobs.refresh_player_history(client)} kamprader")
    elif args.job == "squad":
        print(f"{jobs.refresh_my_squad(client=client)} picks")
    elif args.job == "eo":
        n = jobs.refresh_effective_ownership(sample_size=args.sample_size, client=client)
        print(f"{n} spillere fikk EO-tall fra en stikkprove paa {args.sample_size} managere")
    elif args.job == "predict":
        from fplplanner.models import predict
        print(predict.run(horizon=args.horizon, n_sims=args.sims))
    elif args.job == "optimize":
        from fplplanner.optimize import plan
        result = plan.run(args.entry, horizon=min(args.horizon, 5),
                          risk=args.risk, free_transfers=args.free_transfers)
        print(f"status: {result['status']}  (risk={args.risk})")
        print(result["plan"].to_string(index=False))
    elif args.job == "brief":
        from fplplanner.brief import run_brief
        brief = run_brief(args.entry, free_transfers=args.free_transfers)
        print(brief.as_text())
    elif args.job == "backtest":
        from fplplanner.models import backtest
        for season in ("2025-26", "2024-25"):
            print(season, backtest.clean_sheet_backtest(season))
        print(backtest.clean_sheet_calibration("2025-26"))
    elif args.job == "historical":
        print(historical.load_seasons(args.seasons))
    elif args.job == "hourly":
        jobs.refresh_core(client)
        jobs.snapshot_prices(client)
        print("timesjobb ferdig")
    elif args.job == "daily":
        jobs.refresh_core(client)
        jobs.snapshot_prices(client)
        jobs.refresh_player_history(client)
        jobs.refresh_my_squad(client=client)
        jobs.refresh_effective_ownership(sample_size=args.sample_size, client=client)
        from fplplanner.models import predict
        predict.run(horizon=args.horizon, n_sims=args.sims)
        from fplplanner.brief import run_brief
        run_brief(args.entry, free_transfers=args.free_transfers)
        print("daglig jobb ferdig")
    return 0


if __name__ == "__main__":
    sys.exit(main())
