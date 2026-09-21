"""FPLs poengregler for inneverende sesong.

Verdiene er hentet fra `game_config.scoring` i bootstrap-APIet og satt her som
konstanter, slik at simulatoren ikke trenger nettilgang. `verify_against_api`
sjekker at de fortsatt stemmer.
"""

from __future__ import annotations

GK, DEF, MID, FWD = 1, 2, 3, 4
POS_NAME = {GK: "GKP", DEF: "DEF", MID: "MID", FWD: "FWD"}

PLAY_SHORT = 1          # 1-59 minutter
PLAY_LONG = 2           # 60+ minutter

GOAL = {GK: 10, DEF: 6, MID: 5, FWD: 4}
ASSIST = 3
CLEAN_SHEET = {GK: 4, DEF: 4, MID: 1, FWD: 0}
CONCEDED_PENALTY = {GK: -1, DEF: -1, MID: 0, FWD: 0}   # per 2 baklengsmål
SAVES_PER_POINT = 3
YELLOW = -1
RED = -3
OWN_GOAL = -2
PENALTY_MISS = -2
PENALTY_SAVE = 5

# Defensive contribution, innfort i 2025/26: 2 poeng for aa passere terskelen.
# Terskelen ligger ikke i APIet - den er 10 forsvarshandlinger for forsvarere
# og 12 for midtbane og spisser.
DEF_CONTRIB_POINTS = {GK: 0, DEF: 2, MID: 2, FWD: 2}
DEF_CONTRIB_THRESHOLD = {GK: 99, DEF: 10, MID: 12, FWD: 12}


def verify_against_api(scoring: dict) -> list[str]:
    """Sammenlign konstantene med `game_config.scoring` fra bootstrap.

    Returnerer en liste med avvik. Tom liste betyr at reglene staar uendret.
    """
    issues: list[str] = []

    def check(label, ours, theirs):
        if theirs is not None and ours != theirs:
            issues.append(f"{label}: vi har {ours}, APIet sier {theirs}")

    check("long_play", PLAY_LONG, scoring.get("long_play"))
    check("short_play", PLAY_SHORT, scoring.get("short_play"))
    check("assists", ASSIST, scoring.get("assists"))
    check("yellow_cards", YELLOW, scoring.get("yellow_cards"))
    check("red_cards", RED, scoring.get("red_cards"))

    for pos, name in POS_NAME.items():
        check(f"goals {name}", GOAL[pos], (scoring.get("goals_scored") or {}).get(name))
        check(f"clean_sheet {name}", CLEAN_SHEET[pos],
              (scoring.get("clean_sheets") or {}).get(name))
        check(f"def_contrib {name}", DEF_CONTRIB_POINTS[pos],
              (scoring.get("defensive_contribution") or {}).get(name))
    return issues
