"""FPL Planner - fase 1: laget mitt, kampprogram og value.

Appen leser kun fra databasen. Ingen API-kall her inne, saa siden laster raskt
og fungerer selv naar FPL ligger nede.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fplplanner.analysis import basics, squad_view  # noqa: E402
from fplplanner.optimize import plan as transfer_plan  # noqa: E402
from fplplanner.config import get_settings  # noqa: E402

st.set_page_config(page_title="FPL Planner", page_icon="⚽", layout="wide")

FDR_COLORS = {
    1: "#375523", 2: "#01fc7a", 3: "#e7e7e7", 4: "#ff1751", 5: "#80072d",
}
FDR_TEXT = {1: "#ffffff", 2: "#1a1a1a", 3: "#1a1a1a", 4: "#ffffff", 5: "#ffffff"}


@st.cache_data(ttl=600)
def get_players() -> pd.DataFrame:
    return basics.load_players()


@st.cache_data(ttl=600)
def get_squad(entry_id: int, event: int) -> pd.DataFrame:
    return basics.load_my_squad(entry_id, event)


@st.cache_data(ttl=600)
def get_grid(start_event: int, horizon: int):
    return basics.fixture_grid(start_event, horizon)


@st.cache_data(ttl=600)
def get_events() -> pd.DataFrame:
    return basics.load_events()


@st.cache_data(ttl=600)
def get_model_squad(entry_id: int, event: int, next_event: int, horizon: int):
    return squad_view.squad_with_model(entry_id, event, next_event, horizon)


@st.cache_data(ttl=900, show_spinner="Optimerer bytter ...")
def get_transfer_plan(entry_id: int, horizon: int, risk: float, free_transfers: int):
    result = transfer_plan.run(entry_id, horizon=horizon, risk=risk,
                               free_transfers=free_transfers)
    return result["status"], result["plan"]


@st.cache_data(ttl=900, show_spinner="Regner ut referansen ...")
def get_no_transfer_plan(entry_id: int, horizon: int):
    return transfer_plan.no_transfer_baseline(entry_id, horizon=horizon)["plan"]


@st.cache_data(ttl=600)
def get_entry(entry_id: int):
    return basics.load_entry(entry_id)


@st.cache_data(ttl=600)
def get_entry_history(entry_id: int) -> pd.DataFrame:
    return basics.load_entry_history(entry_id)


def style_fdr(text: pd.DataFrame, fdr: pd.DataFrame):
    """Farg kampprogrammet etter FDR, med tekst i cellene."""
    def color(row_name, col):
        value = fdr.at[row_name, col]
        if pd.isna(value):
            return "background-color: #3a3a3a; color: #9a9a9a"
        bucket = int(round(value))
        return (
            f"background-color: {FDR_COLORS.get(bucket, '#e7e7e7')};"
            f"color: {FDR_TEXT.get(bucket, '#1a1a1a')}; text-align: center"
        )

    styles = pd.DataFrame(
        [[color(idx, col) for col in text.columns] for idx in text.index],
        index=text.index, columns=text.columns,
    )
    display = text.replace("", "–")
    return display.style.apply(lambda _: styles, axis=None)


def _player_card(col, p) -> None:
    """En spiller i banevisningen: xP, fordeling og de tre neste kampene."""
    badge = f" ({p['rolle']})" if p.get("rolle") else ""
    col.markdown(f"**{p['web_name']}**{badge}")
    col.caption(f"{p['team']} · {p['pris']:.1f}")
    col.metric("xP", f"{p['xp_next']:.1f}", f"{p['xp_horizon']:.1f} neste 3",
               delta_color="off", label_visibility="collapsed")
    fixtures = " ".join(label for _, label in (p.get("kamper") or []))
    col.caption(fixtures or "–")
    if p["rad"] in ("GK", "DEF"):
        col.caption(f"CS {p['p_clean_sheet'] * 100:.0f} %")
    else:
        col.caption(f"Mal {p['p_goal'] * 100:.0f} %")


def main() -> None:
    settings = get_settings()

    st.sidebar.title("⚽ FPL Planner")
    entry_id = st.sidebar.number_input(
        "Entry-ID", value=settings.entry_id, step=1, format="%d",
        help="Finnes i URL-en naar du er innlogget paa fantasy.premierleague.com",
    )

    events = get_events()
    if events.empty:
        st.error("Databasen er tom. Kjor `python scripts/run_ingest.py core` forst.")
        return

    current = basics.current_event() or 1
    upcoming = basics.next_event() or current

    event = st.sidebar.selectbox(
        "Gameweek (lag)", options=sorted(events["id"].tolist()),
        index=sorted(events["id"].tolist()).index(current),
    )
    horizon = st.sidebar.slider("Kamper framover", 3, 10, 5)
    st.sidebar.caption(f"Naavaerende: GW{current} · Neste: GW{upcoming}")

    players = get_players()
    squad = get_squad(int(entry_id), int(event))
    text, fdr = get_grid(int(upcoming), int(horizon))

    entry = get_entry(int(entry_id))
    history = get_entry_history(int(entry_id))

    st.title(entry["name"] if entry is not None else "Laget mitt")
    if entry is not None:
        cols = st.columns(5)
        cols[0].metric("Totalpoeng", int(entry["summary_overall_points"]))
        cols[1].metric(f"Poeng GW{int(entry['current_event'])}",
                       int(entry["summary_event_points"]))
        cols[2].metric("Overall rank",
                       f"{int(entry['summary_overall_rank']):,}".replace(",", " "))
        cols[3].metric("Lagverdi", f"{entry['value'] / 10:.1f}")
        cols[4].metric("I banken", f"{entry['bank'] / 10:.1f}")
        if not history.empty and len(history) > 1:
            with st.expander("Poeng per runde"):
                chart = history.set_index("event")[["points"]].rename(
                    columns={"points": "Poeng"})
                st.bar_chart(chart)
        st.caption(
            "Tallene over er live fra FPL og oppdateres underveis i runden. "
            "Grafen viser ferdigregnede runder."
        )

    (tab_pitch, tab_transfers, tab_squad, tab_fixtures, tab_value,
     tab_alerts) = st.tabs(
        ["Banen", "Bytter", "Troppen", "Kampprogram",
         "Value og differensialer", "Varsler"]
    )

    with tab_transfers:
        controls = st.columns(3)
        risk = controls[0].slider(
            "Trygt ↔ aggressivt", -1.0, 1.0, 0.0, step=0.1,
            help="0 maksimerer forventede poeng. Positivt vekter oppsiden i "
                 "fordelingen, negativt straffer nedsiden.")
        free_transfers = controls[1].number_input(
            "Gratis bytter", min_value=1, max_value=5, value=1)
        plan_horizon = controls[2].slider("Runder framover", 2, 5, 4)

        try:
            status, plan_table = get_transfer_plan(
                int(entry_id), int(plan_horizon), float(risk), int(free_transfers))
        except Exception as exc:                       # noqa: BLE001
            st.warning(f"Fant ingen losning: {exc}. "
                       "Kjor `python scripts/run_ingest.py predict` forst.")
        else:
            if status != "Optimal":
                st.info(f"Loseren stoppet med status «{status}» - "
                        "svaret kan vaere det nest beste.")
            st.dataframe(plan_table, hide_index=True, width="stretch")

            baseline = get_no_transfer_plan(int(entry_id), int(plan_horizon))
            gain = (plan_table["xP"].sum() + plan_table["Hit"].sum()
                    - baseline["xP"].sum())
            left, right = st.columns(2)
            left.metric("Forventede poeng med planen",
                        f"{plan_table['xP'].sum() + plan_table['Hit'].sum():.1f}")
            right.metric("Mot a la laget sta", f"{gain:+.1f}",
                         help="Referansen er samme optimering uten lov til a bytte.")
            st.caption(
                "Hits er regnet med som −4 i malfunksjonen, saa optimizeren tar "
                "dem bare naar gevinsten over horisonten er storre. xP-kolonnen "
                "er ekte forventede poeng ogsaa naar skyveknappen star pa noe "
                "annet enn null."
            )

    with tab_pitch:
        try:
            modelled = get_model_squad(int(entry_id), int(event), int(upcoming), 3)
        except Exception as exc:                       # noqa: BLE001
            modelled = squad.iloc[0:0]
            st.warning(f"Fant ingen modelltall: {exc}. "
                       "Kjor `python scripts/run_ingest.py predict` forst.")

        if modelled.empty or "xp_next" not in modelled:
            st.info("Ingen prediksjoner lagret enda.")
        else:
            st.caption(
                f"Store tallet er forventede poeng i GW{upcoming}. "
                "«Neste 3» er summen over de tre neste rundene."
            )
            lines = squad_view.formation(modelled)
            for label in ("GK", "DEF", "MID", "FWD"):
                row = lines[label]
                if row.empty:
                    continue
                cols = st.columns(len(row))
                for col, (_, p) in zip(cols, row.iterrows()):
                    _player_card(col, p)

            st.markdown("---")
            st.caption("Benk")
            bench_row = lines["BENCH"]
            cols = st.columns(max(len(bench_row), 1))
            for col, (_, p) in zip(cols, bench_row.iterrows()):
                _player_card(col, p)

            left, right = st.columns(2)
            with left:
                st.subheader("Kapteinsvalg")
                st.dataframe(squad_view.captain_advice(modelled).round(2),
                             hide_index=True, width="stretch")
            with right:
                st.subheader("Benkebytter")
                swaps = squad_view.bench_check(modelled)
                if swaps.empty:
                    st.success("Startellevern er riktig satt opp.")
                else:
                    st.dataframe(swaps.head(5), hide_index=True, width="stretch")

    with tab_squad:
        if squad.empty:
            st.warning(f"Ingen picks lagret for GW{event}. Kjor `run_ingest.py squad`.")
        else:
            squad = squad.copy()
            squad["Kampprogram"] = squad["team_id"].map(
                lambda t: basics.fixture_score(fdr).get(t, float("nan"))
            )
            view = squad[[
                "position", "web_name", "pos", "team", "pris", "total_points",
                "form", "poeng_per_mill", "selected_by_percent", "ep_next",
                "Kampprogram", "rolle", "status_tekst",
            ]].rename(columns={
                "position": "#", "web_name": "Spiller", "pos": "Pos", "team": "Lag",
                "pris": "Pris", "total_points": "Poeng", "form": "Form",
                "poeng_per_mill": "Poeng/mill", "selected_by_percent": "Eid %",
                "ep_next": "FPL xP", "rolle": "K/V", "status_tekst": "Status",
            })
            st.subheader("Startellever")
            st.dataframe(view[view["#"] <= 11], hide_index=True, width="stretch",
                         height=420)
            st.subheader("Benk")
            st.dataframe(view[view["#"] > 11], hide_index=True, width="stretch",
                         height=180)
            st.caption(
                "«FPL xP» er FPLs eget poengestimat for neste runde. Det er "
                "baselinen modellen vaar skal slaa i fase 2. «Kampprogram» er "
                "snitt-FDR over de neste rundene - lavere er snillere."
            )

    with tab_fixtures:
        st.subheader(f"GW{upcoming}–GW{upcoming + horizon - 1}")
        teams_in_squad = set(squad["team_id"]) if not squad.empty else set()
        only_mine = st.checkbox("Bare lagene jeg har spillere fra", value=False)

        team_names = basics.load_players()[["team_id", "team_name"]].drop_duplicates()
        name_by_id = dict(zip(team_names["team_id"], team_names["team_name"]))

        rows = [t for t in text.index if not only_mine or t in teams_in_squad]
        sub_text = text.loc[rows].rename(index=name_by_id)
        sub_fdr = fdr.loc[rows].rename(index=name_by_id)
        order = basics.fixture_score(sub_fdr).sort_values().index
        sub_text, sub_fdr = sub_text.loc[order], sub_fdr.loc[order]
        sub_text.columns = [f"GW{c}" for c in sub_text.columns]
        sub_fdr.columns = sub_text.columns
        sub_text.index.name = "Lag"
        sub_fdr.index.name = "Lag"

        st.dataframe(style_fdr(sub_text, sub_fdr), width="stretch", height=760)
        st.caption(
            "Sortert etter snilt program oeverst. Dobbeltuker vises som to "
            "motstandere i samme celle; graa celle er blank runde."
        )

    with tab_value:
        col_a, col_b = st.columns(2)
        with col_a:
            st.subheader("Poeng per million")
            min_minutes = st.slider("Minimum spilte minutter", 0, 720, 180, step=90)
            st.dataframe(
                basics.value_picks(players, min_minutes=min_minutes, top=25),
                hide_index=True, width="stretch",
            )
        with col_b:
            st.subheader("Differensialer")
            max_own = st.slider("Maks eierskap (%)", 1.0, 25.0, 10.0, step=0.5)
            st.dataframe(
                basics.differentials(players, max_ownership=max_own, top=25),
                hide_index=True, width="stretch",
            )

    with tab_alerts:
        st.subheader("Ting jeg bor se paa")
        for alert in basics.squad_alerts(squad, fdr):
            st.markdown(f"- {alert}")
        if not squad.empty:
            st.subheader("Eksponering per lag")
            st.dataframe(
                basics.team_exposure(squad), hide_index=True, width="stretch"
            )


if __name__ == "__main__":
    main()
