#!/usr/bin/env python3
"""Bygg den statiske siden.

    python scripts/build_site.py --out site

Leser alt fra databasen, kjorer brief og optimizer, og skriver en enkelt
selvstendig HTML-fil. Ingen server, ingen byggeverktoy - filen kan legges
rett ut paa GitHub Pages.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fplplanner import db                                  # noqa: E402
from fplplanner.config import get_settings                 # noqa: E402
from fplplanner.site import collect, render                # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", default="site", help="mappe siden skrives til")
    parser.add_argument("--entry", type=int, default=None)
    parser.add_argument("--free-transfers", type=int, default=1)
    parser.add_argument("--with-data", action="store_true",
                        help="skriv ogsaa data.json ved siden av siden")
    parser.add_argument("--verbose", "-v", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    db.create_all()
    entry_id = args.entry or get_settings().entry_id

    data = collect.collect(entry_id, free_transfers=args.free_transfers)
    page = render.render(data)

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    (out / "index.html").write_text(page, encoding="utf-8")
    # GitHub Pages kjorer ellers Jekyll over filene, som spiser understrek-mapper.
    (out / ".nojekyll").write_text("")
    if args.with_data:
        (out / "data.json").write_text(
            json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")

    print(f"skrev {out / 'index.html'} ({len(page):,} tegn)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
