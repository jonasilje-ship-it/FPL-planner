"""Briefen: hva som skjedde, hva du bor gjore, og hvor sikkert det rådet er.

Teksten genereres fra tallene, ikke av en språkmodell. Det er et bevisst valg:
hver setning her skal kunne spores tilbake til et tall i databasen, og briefen
skal kunne kjores på cron klokka fem om morgenen uten at noen betaler for et
API-kall eller risikerer at modellen finner på en skade.

Den levende samtalen - "hvorfor ikke Salah?" - hører hjemme på siden, der
leseren kan stille oppfølgingsspørsmål og selv vurdere svaret.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone

import pandas as pd

from .. import db
from ..optimize import plan as planner
from ..optimize import transfer_lp
from .changes import Change


@dataclass
class Brief:
    event: int
    headline: str
    body: str
    changes: list[Change]
    plan: pd.DataFrame
    confidence: str
    severity: int

    def as_text(self) -> str:
        return f"{self.headline}\n\n{self.body}"


def _names(players: pd.DataFrame, ids: list[int]) -> str:
    return ", ".join(players.loc[i, "web_name"] for i in ids) or "ingen"


def second_best(entry_id: int, horizon: int, free_transfers: int,
                first_move: transfer_lp.Move) -> tuple[pd.DataFrame | None, float]:
    """Beste plan hvis vi forbyr det anbefalte kjøpet.

    Dette er sensitivitetsanalysen: hvis nest beste alternativ ligger tett
    opptil, er rådet en smakssak. Ligger det langt bak, er det et tydelig
    råd. Koster en ekstra løsning, som tar sekunder.
    """
    if not first_move.transfers_in:
        return None, 0.0

    problem, players = planner.build(entry_id, horizon, risk=0.0,
                                     free_transfers=free_transfers)
    problem.banned = list(first_move.transfers_in)
    try:
        alternative = transfer_lp.solve(problem)
    except ValueError:
        return None, 0.0

    gap = 0.0
    if alternative.moves:
        gap = first_move.expected_points - alternative.moves[0].expected_points
    return planner.describe(alternative, players), gap


def compose(entry_id: int, changes: list[Change], horizon: int = 3,
            free_transfers: int = 1) -> Brief:
    """Sett sammen briefen for neste runde."""
    result = planner.run(entry_id, horizon=horizon, risk=0.0,
                         free_transfers=free_transfers)
    baseline = planner.no_transfer_baseline(entry_id, horizon=horizon,
                                            free_transfers=free_transfers)
    plan_table = result["plan"]
    solution = result["solution"]
    players = result["players"]
    move = solution.moves[0]
    event = move.event

    # --- overskrift ---
    material = [c for c in changes if c.severity >= 2]
    if move.transfers_in:
        headline = (f"GW{event}: {_names(players, move.transfers_in)} inn for "
                    f"{_names(players, move.transfers_out)}")
    elif material:
        headline = f"GW{event}: behold laget, men {len(material)} ting har endret seg"
    else:
        headline = f"GW{event}: ingen grunn til å røre laget"

    # --- hva som har skjedd ---
    parts: list[str] = []
    if changes:
        top = [c for c in changes if c.severity >= 2][:6]
        if top:
            parts.append("**Siden sist.** " + " ".join(c.text for c in top))
        rest = len(changes) - len(top)
        if rest > 0:
            parts.append(f"I tillegg {rest} mindre endringer i ligaen for øvrig.")
    else:
        parts.append("**Siden sist.** Ingenting som betyr noe for laget ditt.")

    # --- selve rådet ---
    if move.transfers_in:
        gain = plan_table.iloc[0]["xP"]
        cost = f", og et hit på {4 * move.hits} poeng" if move.hits else ", uten hit"
        parts.append(
            f"**Rådet for GW{event}.** Bytt inn {_names(players, move.transfers_in)} "
            f"for {_names(players, move.transfers_out)}{cost}. "
            f"Det gir {gain:.1f} forventede poeng i runden, mot "
            f"{baseline['plan']['xP'].iloc[0]:.1f} slik laget står nå. "
            f"Kaptein: {plan_table.iloc[0]['Kaptein']}.")
    else:
        parts.append(
            f"**Rådet for GW{event}.** Ikke bruk byttet. Ingen tilgjengelig spiller "
            f"gir nok over de neste {horizon} rundene til å forsvare det, og et spart "
            f"bytte er verdt mer enn et marginalt et. "
            f"Kaptein: {plan_table.iloc[0]['Kaptein']}.")

    # --- horisonten ---
    future = plan_table.iloc[1:]
    if not future.empty:
        steps = []
        for row in future.itertuples():
            if row.Inn != "–":
                steps.append(f"GW{row.GW}: {row.Inn} inn for {row.Ut}")
            else:
                steps.append(f"GW{row.GW}: spar byttet")
        parts.append("**Veien videre.** " + ". ".join(steps) +
                     ". Planen lenger fram er veiledende — den regnes på nytt "
                     "hver gang noe endrer seg.")

    # --- hvor sikkert ---
    alternative, gap = second_best(entry_id, horizon, free_transfers, move)
    if alternative is None or not move.transfers_in:
        confidence = "Ingen alternativ å sammenligne med når byttet står over."
    elif gap < 0.3:
        confidence = (f"Svakt råd: nest beste alternativ "
                      f"({alternative.iloc[0]['Inn']}) ligger bare {gap:.2f} xP bak. "
                      f"Her er det i praksis uavgjort — velg den du tror mest på.")
    elif gap < 1.0:
        confidence = (f"Middels sterkt råd: {alternative.iloc[0]['Inn']} er nest best, "
                      f"{gap:.2f} xP bak.")
    else:
        confidence = (f"Tydelig råd: nest beste alternativ "
                      f"({alternative.iloc[0]['Inn']}) ligger {gap:.2f} xP bak.")
    parts.append(f"**Hvor sikkert.** {confidence}")

    severity = max([c.severity for c in changes], default=0)
    return Brief(event=event, headline=headline, body="\n\n".join(parts),
                 changes=changes, plan=plan_table, confidence=confidence,
                 severity=severity)


def save(brief: Brief) -> datetime:
    created = datetime.now(timezone.utc).replace(tzinfo=None)
    db.append_rows(db.briefings, [{
        "created_at": created, "event": brief.event, "headline": brief.headline[:512],
        "body": brief.body[:8000],
        "changes_json": json.dumps([c.as_dict() for c in brief.changes],
                                   ensure_ascii=False)[:16000],
        "plan_json": brief.plan.to_json(orient="records")[:8000],
        "severity": brief.severity,
    }])
    return created
