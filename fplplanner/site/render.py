"""Rendrer datagrunnlaget til en selvstendig HTML-side.

All CSS og JavaScript ligger i filen; ingen eksterne avhengigheter bortsett
fra skriftene fra Google Fonts. Det gjor at samme fil kan serveres fra
GitHub Pages, aapnes lokalt, eller publiseres som en artifact.
"""

from __future__ import annotations

import html
import json
import re


def render(D: dict) -> str:
    """Bygg hele siden fra dicten `collect.collect()` returnerer."""
    e, M, O, B = D["entry"], D["model"], D["opt"], D["brief"]

    esc = lambda s: html.escape(str(s if s is not None else ""))
    num = lambda v, d=1: "–" if v is None else f"{v:.{d}f}".replace(".", ",")
    pct = lambda v: "–" if v is None else f"{round(v * 100)}&nbsp;%"
    rank = lambda v: f"{v:,}".replace(",", " ")
    NB = "&#8239;"


    def chips(kamper, mini=False):
        cls = "chip chip--mini" if mini else "chip"
        out = []
        for f in kamper:
            if not f["txt"]:
                out.append(f'<span class="{cls} chip--blank">–</span>')
            else:
                b = int(round(f["fdr"])) if f["fdr"] else 3
                out.append(f'<span class="{cls} chip--{b}">{esc(f["txt"]).replace(" (", NB + "(")}</span>')
        return '<span class="chips">' + "".join(out) + "</span>"


    def dist_bar(p):
        """Fire segmenter: blank, 3-6, 7-9, 10+. Bredden er sannsynligheten."""
        parts = [("blank", p["p_blank"], "2 poeng eller mindre"),
                 ("mid", p["p_mid"], "3–6 poeng"),
                 ("good", p["p_good"], "7–9 poeng"),
                 ("haul", p["p_haul"], "10 poeng eller mer")]
        segs = "".join(
            f'<i class="seg seg--{k}" style="flex:{max(v or 0, 0.001)}" '
            f'title="{label}: {round((v or 0) * 100)} %"></i>'
            for k, v, label in parts)
        return f'<span class="bar">{segs}</span>'


    def card(p):
        role = f'<span class="role">{esc(p["rolle"])}</span>' if p["rolle"] else ""
        flag = f'<span class="warn">{esc(p["status_tekst"])}</span>' if p["status_tekst"] else ""
        cs = (f'<span class="cs">CS {pct(p["p_clean_sheet"])}</span>'
              if p["rad"] in ("GK", "DEF") else
              f'<span class="cs">Mål {pct(p["p_goal"])}</span>')
        return f"""<article class="card">
    <header><span class="who">{esc(p['web_name'])}</span>{role}</header>
    <p class="meta">{esc(p['team'])} · {num(p['pris'])}{flag}</p>
    <p class="xp"><span class="xp-v">{num(p['xp_next'], 1)}</span><span class="xp-k">xP</span></p>
    {dist_bar(p)}
    <p class="cs-line">{cs}<span class="h3">{num(p['xp_horizon'], 1)} neste 3</span></p>
    {chips(p['kamper'], mini=True)}
    </article>"""


    squad = D["squad"]
    lines = {r: [p for p in squad if p["position"] <= 11 and p["rad"] == r]
             for r in ("GK", "DEF", "MID", "FWD")}
    bench = [p for p in squad if p["position"] > 11]
    pitch = "".join(f'<div class="line line--{r.lower()}">' + "".join(card(p) for p in lines[r]) + "</div>"
                    for r in ("GK", "DEF", "MID", "FWD") if lines[r])
    bench_html = "".join(card(p) for p in bench)

    def _role(r):
        return f' <span class="role role--inline">{esc(r)}</span>' if r else ""


    cap_rows = "".join(
        f'<tr><td class="name">{esc(c["web_name"])}{_role(c["rolle"])}</td>'
        f'<td class="mono">{esc(c["team"])}</td><td class="mono">{esc(c["rad"])}</td>'
        f'<td class="mono num">{num(c["xp_next"])}</td>'
        f'<td class="mono num strong">{num(c["xp_kaptein"])}</td>'
        f'<td class="mono num">{pct(c["p_haul"])}</td></tr>'
        for c in D["captain"])

    bench_rows = "".join(
        f'<tr><td class="name">{esc(b["inn"])}</td><td class="mono num">{num(b["inn_xp"])}</td>'
        f'<td class="arrow">for</td><td class="name">{esc(b["ut"])}</td>'
        f'<td class="mono num">{num(b["ut_xp"])}</td>'
        f'<td class="mono num strong">+{num(b["gevinst"])}</td></tr>'
        for b in D["bench"]) or '<tr><td colspan="6">Startellevern er riktig satt opp.</td></tr>'


    def league_rows(rows):
        return "".join(
            f'<tr><td class="name">{esc(r["web_name"])}</td><td class="mono">{esc(r["lag"])}</td>'
            f'<td class="mono">{esc(r["rad"])}</td><td class="mono num">{num(r["pris"])}</td>'
            f'<td class="mono num">{num(r["eid"])}</td>'
            f'<td class="mono num strong">{num(r["xp3"])}</td></tr>' for r in rows)


    def eo_rows(rows):
        return "".join(
            f'<tr><td class="name">{esc(r["web_name"])}</td><td class="mono">{esc(r["team"])}</td>'
            f'<td class="mono">{esc(r["pos"])}</td><td class="mono num">{num(r["pris"])}</td>'
            f'<td class="mono num">{num(r["selected_by_percent"])}</td>'
            f'<td class="mono num">{num(r["captain_pct"])}</td>'
            f'<td class="mono num strong">{num(r["eo"])}</td></tr>' for r in rows
        ) or '<tr><td colspan="7">Ingen data ennå — kjøres i neste bygg.</td></tr>'


    def _grid_row(t):
        mine = sum(1 for s_ in squad if s_["team"] == t["short"])
        tag = f'<span class="own">{mine}</span>' if mine else ""
        cells = "".join(
            '<td class="cell cell--blank">&ndash;</td>' if not c["txt"]
            else f'<td class="cell cell--{int(round(c["fdr"]))}">{esc(c["txt"]).replace(" (", NB + "(")}</td>'
            for c in t["cells"])
        return (f'<tr data-mine="{1 if mine else 0}">'
                f'<th scope="row">{esc(t["team"])}{tag}</th>'
                f'<td class="mono num score">{num(t["score"], 2)}</td>{cells}</tr>')


    grid_rows = "".join(_grid_row(t) for t in D["grid"])

    cal_rows = "".join(
        f'<tr><td class="mono num">{pct(c["spadd"])}</td><td class="mono num">{pct(c["faktisk"])}</td>'
        f'<td class="mono num">{c["kamper"]}</td></tr>' for c in M["calibration"])

    alerts = "".join(
        "<li>" + re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", esc(a).replace(" - ", " — ")) + "</li>"
        for a in D["alerts"])

    def trade_card(p, kind):
        return f"""<article class="trade-card trade-card--{kind}">
    <p class="trade-k">{"Ut" if kind == "out" else "Inn"}</p>
    <p class="trade-name">{esc(p['navn'])}</p>
    <p class="meta">{esc(p['lag'])} · {esc(p['pos'])} · {num(p['pris'])} · eid {num(p['eid'])}&nbsp;%</p>
    <p class="trade-xp"><span class="xp-v">{num(p['xp'])}</span><span class="xp-k">xP GW{D['next_gw']}</span></p>
    <p class="trade-sub">{num(p['xp5'])} over fem runder · haul {pct(p['haul'])} · blank {pct(p['blank'])}</p>
    </article>"""


    trade_out = "".join(trade_card(x, "out") for x in O["anbefaling"]["ut"])
    trade_in = "".join(trade_card(x, "in") for x in O["anbefaling"]["inn"])
    gain_next = (sum(x["xp"] for x in O["anbefaling"]["inn"])
                 - sum(x["xp"] for x in O["anbefaling"]["ut"]))
    gain_five = (sum(x["xp5"] for x in O["anbefaling"]["inn"])
                 - sum(x["xp5"] for x in O["anbefaling"]["ut"]))

    plan_rows = "".join(
        f'<tr><td class="mono">GW{r["GW"]}</td><td class="name">{esc(r["Inn"])}</td>'
        f'<td class="name muted-cell">{esc(r["Ut"])}</td>'
        f'<td class="mono num">{r["Hit"] if r["Hit"] else "–"}</td>'
        f'<td class="mono">{esc(r["Kaptein"])}</td>'
        f'<td class="mono num strong">{num(r["xP"])}</td>'
        f'<td class="mono num">{num(r["Bank"])}</td></tr>' for r in O["plan"])

    strategy_rows = "".join(
        f'<tr><td class="name">{esc(t["navn"])}</td>'
        f'<td class="mono num">{num(t["netto"])}</td>'
        f'<td class="mono num strong">+{num(t["gevinst"])}</td>'
        f'<td class="mono num">{t["hits"] or "–"}</td>'
        f'<td class="mono">{esc(t["gw5_inn"])}</td>'
        f'<td class="mono">{esc(t["kaptein"])}</td></tr>' for t in O["strategier"])
    strategy_rows = (
        f'<tr><td class="name">Ingen bytter</td>'
        f'<td class="mono num">{num(O["baseline_netto"])}</td>'
        f'<td class="mono num">–</td><td class="mono num">–</td>'
        f'<td class="mono">–</td><td class="mono">Haaland</td></tr>' + strategy_rows)

    def brief_body(text):
        """Briefen kommer med **fete** ledetekster og tomme linjer mellom avsnitt."""
        out = []
        for para in text.split("\n\n"):
            para = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", esc(para.strip()))
            if para:
                out.append(f"<p>{para}</p>")
        return "".join(out)


    SEV = {3: ("kritisk", "Handle naa"), 2: ("viktig", "Verdt a vite"),
           1: ("info", "Notis")}

    change_rows = "".join(
        f'<li class="chg chg--{SEV.get(ch["severity"], SEV[1])[0]}">'
        f'<span class="chg-k">{esc(SEV.get(ch["severity"], SEV[1])[1])}</span>'
        f'<span class="chg-t">{esc(ch["text"])}</span></li>'
        for ch in B["changes"]) or '<li class="chg chg--info"><span class="chg-t">Ingenting har endret seg siden forrige kjoring.</span></li>'

    CONTEXT = json.dumps(D["ctx"], ensure_ascii=False, separators=(",", ":"))

    RULES_TEXT = "\n".join([
        "Du er analysedelen av et Fantasy Premier League-verktoy.",
        "Svar kort og paa norsk bokmaal, 2-4 setninger, uten punktlister.",
        "Bruk KUN tallene i JSON-en under. Finner du ikke svaret der, si det rett ut.",
        "Alle xP-tall er forventede poeng fra 10 000 simuleringer per spiller per kamp.",
        "xp = neste runde, xp3 = de tre neste. blank = sjanse for 2 poeng eller mindre,",
        "haul = sjanse for 10 eller mer, cs = clean sheet, eid = eierskap i prosent.",
        "Ikke finn paa skader, lagoppstillinger eller nyheter som ikke staar i dataene.",
        "Er forskjellen mellom to alternativer under 0,3 xP, si at det i praksis er jevnt.",
        "",
        "DATA:",
        CONTEXT,
        "",
        "SPORSMAL: ",
    ])
    RULES_JS = json.dumps(RULES_TEXT, ensure_ascii=False)

    gw_head = "".join(f"<th>GW{g}</th>" for g in D["gws"])
    horizon = ", ".join(f"GW{g}" for g in D["gws"][:3])

    HTML = f"""<title>Blåmåne FC GW{D['next_gw']}</title>
    <link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Bricolage+Grotesque:opsz,wght@12..96,600;12..96,800&family=Source+Sans+3:ital,wght@0,400;0,600;1,400&family=IBM+Plex+Mono:wght@400;500;600&display=swap">
    <style>
    :root {{
      --paper:#f8f5f7; --surface:#ffffff; --sunk:#f1ecf1;
      --ink:#231a2f; --ink-soft:#4b4055; --muted:#786b82; --line:#e3dae5;
      --accent:#a8761a; --accent-soft:#f6e9cd; --accent-line:#dcbf83;
      --pitch:#eaf0e8; --pitch-line:#d2ddcd; --pitch-edge:#cbd8c6;
      --fdr1:#0f7a3d; --fdr1-t:#ffffff; --fdr2:#57c983; --fdr2-t:#10331f;
      --fdr3:#ded7de; --fdr3-t:#3b3341; --fdr4:#e0526d; --fdr4-t:#ffffff;
      --fdr5:#8d0c2f; --fdr5-t:#ffffff; --blank:#ccc4ce; --blank-t:#5f5668;
      --seg-blank:#d8d1da; --seg-mid:#a99ab0; --seg-good:#d8a94e; --seg-haul:#a8761a;
      --shadow:0 1px 2px rgba(35,26,47,.06), 0 8px 24px -16px rgba(35,26,47,.35);
      --sans:"Source Sans 3", ui-sans-serif, system-ui, sans-serif;
      --display:"Bricolage Grotesque", var(--sans);
      --mono:"IBM Plex Mono", ui-monospace, SFMono-Regular, monospace;
    }}
    @media (prefers-color-scheme: dark) {{
      :root:not([data-theme="light"]) {{
        --paper:#16111d; --surface:#1e1728; --sunk:#241c30;
        --ink:#f1ecf4; --ink-soft:#cfc5d6; --muted:#9e91aa; --line:#332941;
        --accent:#f0b845; --accent-soft:#3a2c14; --accent-line:#6b5220;
        --pitch:#16211a; --pitch-line:#24332633; --pitch-edge:#26352a;
        --fdr1:#0d6a35; --fdr2:#3ea86a; --fdr2-t:#06210f;
        --fdr3:#3d3549; --fdr3-t:#ddd5e2; --fdr4:#c23b56; --fdr5:#780a28;
        --blank:#2c2439; --blank-t:#8a7f96;
        --seg-blank:#3a3147; --seg-mid:#6a5c78; --seg-good:#b98b32; --seg-haul:#f0b845;
        --shadow:0 1px 2px rgba(0,0,0,.4), 0 10px 28px -18px rgba(0,0,0,.9);
      }}
    }}
    :root[data-theme="dark"] {{
      --paper:#16111d; --surface:#1e1728; --sunk:#241c30;
      --ink:#f1ecf4; --ink-soft:#cfc5d6; --muted:#9e91aa; --line:#332941;
      --accent:#f0b845; --accent-soft:#3a2c14; --accent-line:#6b5220;
      --pitch:#16211a; --pitch-line:#24332633; --pitch-edge:#26352a;
      --fdr1:#0d6a35; --fdr2:#3ea86a; --fdr2-t:#06210f;
      --fdr3:#3d3549; --fdr3-t:#ddd5e2; --fdr4:#c23b56; --fdr5:#780a28;
      --blank:#2c2439; --blank-t:#8a7f96;
      --seg-blank:#3a3147; --seg-mid:#6a5c78; --seg-good:#b98b32; --seg-haul:#f0b845;
      --shadow:0 1px 2px rgba(0,0,0,.4), 0 10px 28px -18px rgba(0,0,0,.9);
    }}
    * {{ box-sizing:border-box; }}
    body {{ margin:0; background:var(--paper); color:var(--ink);
      font-family:var(--sans); font-size:16px; line-height:1.55; -webkit-font-smoothing:antialiased; }}
    .wrap {{ max-width:1120px; margin:0 auto; padding-inline:20px; padding-block:40px 72px; }}
    h1, h2 {{ font-family:var(--display); text-wrap:balance; margin:0; letter-spacing:-.015em; }}
    h1 {{ font-size:clamp(2.3rem,6vw,3.4rem); font-weight:800; line-height:1.02; }}
    h2 {{ font-size:1.4rem; font-weight:700; }}
    .eyebrow {{ font-family:var(--mono); font-size:.72rem; font-weight:500; letter-spacing:.14em;
      text-transform:uppercase; color:var(--muted); margin:0 0 8px; }}
    .masthead {{ border-bottom:2px solid var(--ink); padding-bottom:22px; }}
    .masthead p.sub {{ margin:12px 0 0; color:var(--ink-soft); max-width:64ch; }}
    .scoreboard {{ display:grid; gap:1px; background:var(--line); border:1px solid var(--line);
      grid-template-columns:repeat(auto-fit,minmax(148px,1fr)); margin:26px 0 46px; }}
    .readout {{ background:var(--surface); padding:14px 16px 16px; }}
    .readout .k {{ font-family:var(--mono); font-size:.68rem; letter-spacing:.12em;
      text-transform:uppercase; color:var(--muted); }}
    .readout .v {{ font-family:var(--display); font-weight:700; font-size:1.9rem;
      line-height:1.15; font-variant-numeric:tabular-nums; margin-top:2px; }}
    .readout--lead .v {{ color:var(--accent); }}
    section {{ margin-bottom:52px; }}
    .head {{ display:flex; align-items:baseline; justify-content:space-between;
      gap:16px; flex-wrap:wrap; margin-bottom:14px; }}
    .head p {{ margin:0; color:var(--muted); font-size:.9rem; max-width:54ch; }}

    /* --- banen --- */
    .pitch {{ background:var(--pitch); border:1px solid var(--pitch-edge);
      padding:22px 16px; display:grid; gap:20px; position:relative; overflow:hidden; }}
    .pitch::before {{ content:""; position:absolute; inset:14px; pointer-events:none;
      border:1px solid var(--pitch-line); border-radius:2px; }}
    .pitch::after {{ content:""; position:absolute; left:14px; right:14px; top:50%;
      border-top:1px solid var(--pitch-line); pointer-events:none; }}
    .line {{ display:flex; flex-wrap:wrap; gap:10px; justify-content:center;
      position:relative; z-index:1; }}
    .card {{ background:var(--surface); border:1px solid var(--line); width:158px;
      padding:9px 10px 10px; box-shadow:var(--shadow); }}
    .card header {{ display:flex; align-items:baseline; justify-content:space-between; gap:6px; }}
    .who {{ font-weight:600; font-size:.92rem; white-space:nowrap; overflow:hidden;
      text-overflow:ellipsis; }}
    .role {{ font-family:var(--mono); font-size:.6rem; font-weight:600; background:var(--accent-soft);
      color:var(--accent); border:1px solid var(--accent-line); padding:0 4px; }}
    .role--inline {{ margin-left:6px; }}
    .card .meta {{ font-family:var(--mono); font-size:.68rem; color:var(--muted); margin:1px 0 6px; }}
    .warn {{ color:var(--fdr4); margin-left:6px; }}
    .xp {{ margin:0; display:flex; align-items:baseline; gap:4px; }}
    .xp-v {{ font-family:var(--display); font-weight:800; font-size:1.65rem; line-height:1;
      font-variant-numeric:tabular-nums; }}
    .xp-k {{ font-family:var(--mono); font-size:.62rem; letter-spacing:.1em;
      text-transform:uppercase; color:var(--muted); }}
    .bar {{ display:flex; height:6px; margin:7px 0 6px; background:var(--sunk); }}
    .seg {{ display:block; }}
    .seg--blank {{ background:var(--seg-blank); }}
    .seg--mid {{ background:var(--seg-mid); }}
    .seg--good {{ background:var(--seg-good); }}
    .seg--haul {{ background:var(--seg-haul); }}
    .cs-line {{ display:flex; justify-content:space-between; gap:6px; margin:0 0 7px;
      font-family:var(--mono); font-size:.64rem; color:var(--muted); }}
    .h3 {{ color:var(--ink-soft); }}
    .bench {{ margin-top:14px; border-top:1px dashed var(--line); padding-top:16px;
      display:flex; flex-wrap:wrap; gap:10px; }}
    .bench-label {{ font-family:var(--mono); font-size:.68rem; letter-spacing:.12em;
      text-transform:uppercase; color:var(--muted); width:100%; margin:0 0 2px; }}

    .chips {{ display:flex; gap:3px; flex-wrap:wrap; }}
    .chip {{ font-family:var(--mono); font-size:.7rem; font-weight:500; white-space:nowrap;
      text-align:center; padding:3px 6px; min-width:66px; }}
    .chip--mini {{ font-size:.6rem; padding:2px 4px; min-width:0; flex:1; }}
    .chip--1, .cell--1 {{ background:var(--fdr1); color:var(--fdr1-t); }}
    .chip--2, .cell--2 {{ background:var(--fdr2); color:var(--fdr2-t); }}
    .chip--3, .cell--3 {{ background:var(--fdr3); color:var(--fdr3-t); }}
    .chip--4, .cell--4 {{ background:var(--fdr4); color:var(--fdr4-t); }}
    .chip--5, .cell--5 {{ background:var(--fdr5); color:var(--fdr5-t); }}
    .chip--blank, .cell--blank {{ background:var(--blank); color:var(--blank-t); }}

    /* --- brief --- */
    .brief {{ background:var(--surface); border:1px solid var(--line);
      border-top:3px solid var(--accent); padding:24px 26px 22px; box-shadow:var(--shadow); }}
    .brief h2 {{ font-size:1.75rem; margin-bottom:12px; }}
    .brief p {{ font-size:1rem; margin:0 0 13px; max-width:64ch; color:var(--ink-soft); }}
    .brief p:last-child {{ margin-bottom:0; }}
    .brief strong {{ color:var(--ink); }}
    .changes {{ list-style:none; margin:18px 0 0; padding:0; display:grid; gap:7px; }}
    .chg {{ display:flex; gap:10px; align-items:baseline; font-size:.9rem;
      background:var(--sunk); padding:8px 12px; }}
    .chg-k {{ font-family:var(--mono); font-size:.6rem; letter-spacing:.1em;
      text-transform:uppercase; white-space:nowrap; padding-top:2px; }}
    .chg--kritisk {{ border-left:3px solid var(--fdr4); }}
    .chg--kritisk .chg-k {{ color:var(--fdr4); }}
    .chg--viktig {{ border-left:3px solid var(--accent); }}
    .chg--viktig .chg-k {{ color:var(--accent); }}
    .chg--info {{ border-left:3px solid var(--line); }}
    .chg--info .chg-k {{ color:var(--muted); }}
    .chg-t {{ color:var(--ink-soft); }}

    /* --- spor --- */
    .ask {{ margin-top:20px; border-top:1px dashed var(--line); padding-top:18px; }}
    .ask-row {{ display:flex; gap:8px; flex-wrap:wrap; }}
    .ask input {{ flex:1 1 260px; font:inherit; font-size:.95rem; padding:10px 12px;
      background:var(--paper); color:var(--ink); border:1px solid var(--line); }}
    .ask button {{ font-family:var(--mono); font-size:.72rem; letter-spacing:.08em;
      text-transform:uppercase; padding:10px 18px; cursor:pointer;
      background:var(--accent); color:var(--paper); border:0; }}
    .ask button[disabled] {{ opacity:.5; cursor:default; }}
    .ask button.ghost {{ background:transparent; color:var(--muted);
      border:1px solid var(--line); }}
    .suggest {{ display:flex; gap:6px; flex-wrap:wrap; margin-top:10px; }}
    .suggest button {{ font-family:var(--sans); font-size:.82rem; text-transform:none;
      letter-spacing:0; padding:5px 11px; background:var(--sunk); color:var(--ink-soft);
      border:1px solid var(--line); cursor:pointer; }}
    .answer {{ margin-top:14px; font-size:.97rem; color:var(--ink-soft);
      white-space:pre-wrap; }}
    .answer:empty {{ display:none; }}
    .ask-note {{ font-family:var(--mono); font-size:.66rem; color:var(--muted);
      margin:10px 0 0; }}

    /* --- bytter --- */
    .trade {{ display:grid; gap:14px; align-items:stretch;
      grid-template-columns:1fr auto 1fr; }}
    .trade-card {{ background:var(--surface); border:1px solid var(--line);
      padding:14px 16px 15px; box-shadow:var(--shadow); }}
    .trade-card--out {{ opacity:.82; }}
    .trade-card--in {{ border-left:3px solid var(--accent); }}
    .trade-k {{ font-family:var(--mono); font-size:.66rem; letter-spacing:.14em;
      text-transform:uppercase; color:var(--muted); margin:0; }}
    .trade-name {{ font-family:var(--display); font-weight:700; font-size:1.5rem;
      line-height:1.1; margin:2px 0 0; }}
    .trade-card .meta {{ font-family:var(--mono); font-size:.7rem; color:var(--muted);
      margin:4px 0 10px; }}
    .trade-xp {{ margin:0; display:flex; align-items:baseline; gap:5px; }}
    .trade-sub {{ font-family:var(--mono); font-size:.66rem; color:var(--muted);
      margin:8px 0 0; }}
    .trade-arrow {{ display:flex; flex-direction:column; align-items:center;
      justify-content:center; gap:4px; font-family:var(--mono); }}
    .trade-arrow .sign {{ font-family:var(--display); font-weight:800; font-size:1.5rem;
      color:var(--accent); line-height:1; }}
    .trade-arrow .cap {{ font-size:.62rem; letter-spacing:.1em; text-transform:uppercase;
      color:var(--muted); text-align:center; }}
    .muted-cell {{ color:var(--muted); font-weight:400; }}
    @media (max-width:640px) {{
      .trade {{ grid-template-columns:1fr; }}
      .trade-arrow {{ flex-direction:row; gap:10px; }}
    }}

    .alerts {{ list-style:none; margin:0; padding:0; display:grid; gap:10px; }}
    .alerts li {{ background:var(--surface); border:1px solid var(--line);
      border-left:3px solid var(--accent); padding:13px 16px; box-shadow:var(--shadow); }}
    .scroller {{ overflow-x:auto; background:var(--surface); border:1px solid var(--line);
      box-shadow:var(--shadow); }}
    table {{ border-collapse:collapse; width:100%; font-size:.9rem; }}
    thead th {{ font-family:var(--mono); font-size:.68rem; font-weight:600; letter-spacing:.09em;
      text-transform:uppercase; color:var(--muted); text-align:left; padding:11px 10px;
      border-bottom:1px solid var(--line); white-space:nowrap; }}
    tbody td, tbody th {{ padding:8px 10px; border-bottom:1px solid var(--line); text-align:left; }}
    tbody tr:last-child td, tbody tr:last-child th {{ border-bottom:0; }}
    .mono {{ font-family:var(--mono); font-size:.82rem; }}
    .num {{ text-align:right; font-variant-numeric:tabular-nums; }}
    .strong {{ font-weight:600; color:var(--accent); }}
    .name {{ font-weight:600; white-space:nowrap; }}
    .arrow {{ font-family:var(--mono); font-size:.7rem; color:var(--muted); }}
    td.cell {{ font-family:var(--mono); font-size:.7rem; text-align:center; padding:7px 8px; }}
    .grid-table th[scope="row"] {{ font-weight:600; white-space:nowrap; }}
    .own {{ font-family:var(--mono); font-size:.62rem; background:var(--accent-soft);
      color:var(--accent); border:1px solid var(--accent-line); padding:1px 5px; margin-left:7px; }}
    .score {{ color:var(--muted); }}
    .toggle {{ display:inline-flex; align-items:center; gap:8px; font-size:.88rem;
      color:var(--ink-soft); cursor:pointer; user-select:none; }}
    .toggle input {{ accent-color:var(--accent); width:16px; height:16px; cursor:pointer; }}
    .two {{ display:grid; gap:26px; grid-template-columns:repeat(auto-fit,minmax(320px,1fr)); }}
    .legend {{ display:flex; flex-wrap:wrap; gap:7px; align-items:center; margin-top:12px;
      font-family:var(--mono); font-size:.68rem; line-height:1.6; color:var(--muted); }}
    .legend .sw {{ padding:2px 8px; }}
    .key {{ display:inline-flex; align-items:center; gap:5px; }}
    .key i {{ width:14px; height:8px; display:inline-block; }}
    .note {{ border-top:2px solid var(--ink); padding-top:22px; color:var(--ink-soft); }}
    .note p {{ max-width:66ch; }}
    .note code {{ font-family:var(--mono); font-size:.84em; background:var(--sunk);
      padding:1px 5px; border:1px solid var(--line); }}
    :focus-visible {{ outline:2px solid var(--accent); outline-offset:2px; }}
    @media (max-width:560px) {{
      .wrap {{ padding-block:28px 56px; }}
      .card {{ width:calc(50% - 5px); }}
      .pitch {{ padding:16px 10px; }}
    }}
    </style>

    <div class="wrap">
      <header class="masthead">
        <p class="eyebrow">Fase 4 · {D['generated']} · entry 3486140</p>
        <h1>{esc(e['name'])}</h1>
        <p class="sub">Hele kjeden står: poengfordeling per spiller fra {M['sims']:,} simulerte
        kamper, og en optimizer som bruker dem til å velge tropp, lag og kaptein for fem runder
        samtidig. Den sier også om et hit lønner seg — den regner det ut, den er ikke fortalt det.</p>
      </header>

      <div class="scoreboard">
        <div class="readout readout--lead"><div class="k">Totalpoeng</div><div class="v">{e['summary_overall_points']}</div></div>
        <div class="readout"><div class="k">GW{D['current_gw']}</div><div class="v">{e['summary_event_points']}</div></div>
        <div class="readout"><div class="k">Overall rank</div><div class="v">{rank(e['summary_overall_rank'])}</div></div>
        <div class="readout"><div class="k">Lagverdi</div><div class="v">{num(e['value'] / 10)}</div></div>
        <div class="readout"><div class="k">I banken</div><div class="v">{num(e['bank'] / 10)}</div></div>
      </div>

      <section>
        <div class="brief">
          <p class="eyebrow">Brief · {B['generated']}</p>
          <h2>{esc(B['headline'])}</h2>
          {brief_body(B['body'])}
          <ul class="changes">{change_rows}</ul>

          <div class="ask" id="ask" hidden>
            <div class="ask-row">
              <input id="ask-input" type="text" autocomplete="off"
                     placeholder="Spør om laget — «hvorfor ikke Tavernier?»">
              <button id="ask-send" type="button">Spør</button>
              <button id="ask-stop" type="button" class="ghost" hidden>Stopp</button>
            </div>
            <div class="suggest" id="ask-suggest">
              <button type="button">Hvorfor ikke Tavernier i stedet?</button>
              <button type="button">Er laget mitt for template?</button>
              <button type="button">Bør jeg ta et hit denne uka?</button>
            </div>
            <div class="answer" id="ask-answer"></div>
            <p class="ask-note">Svarer bare ut fra tallene på denne siden. Bruker din egen
              Claude-konto, og spør deg først.</p>
          </div>
        </div>
      </section>

      <section>
        <div class="head"><h2>Laget mitt</h2>
          <p>Store tallet er forventede poeng i GW{D['next_gw']}. Stripen under er hele
          fordelingen, og «neste 3» er summen over {horizon}.</p></div>
        <div class="pitch">{pitch}
          <div class="bench"><p class="bench-label">Benk</p>{bench_html}</div>
        </div>
        <div class="legend">
          <span class="key"><i style="background:var(--seg-blank)"></i>≤2 p</span>
          <span class="key"><i style="background:var(--seg-mid)"></i>3–6 p</span>
          <span class="key"><i style="background:var(--seg-good)"></i>7–9 p</span>
          <span class="key"><i style="background:var(--seg-haul)"></i>10+ p</span>
          <span>· K = kaptein, V = visekaptein · fargene på kampene er FDR</span>
        </div>
      </section>

      <section>
        <div class="head"><h2>Anbefalt bytte</h2>
          <p>Optimizeren velger tropp, lag og kaptein for {len(O['horisont'])} runder samtidig,
          under budsjett, klubbgrense og formasjonsregler.</p></div>
        <div class="trade">
          {trade_out}
          <div class="trade-arrow">
            <span class="sign">+{num(gain_next)}</span>
            <span class="cap">xP i GW{D['next_gw']}</span>
            <span class="sign">+{num(gain_five)}</span>
            <span class="cap">over fem runder</span>
          </div>
          {trade_in}
        </div>
        <div class="legend"><span>Ett gratis bytte, ingen hit. Banken etter byttet:
          {num(O['anbefaling']['bank'])}. Kaptein: {esc(O['anbefaling']['kaptein'])}.</span></div>

        <div class="two" style="margin-top:26px">
          <div>
            <div class="head"><h2>Planen framover</h2></div>
            <div class="scroller"><table>
              <thead><tr><th>Runde</th><th>Inn</th><th>Ut</th><th>Hit</th><th>Kaptein</th><th>xP</th><th>Bank</th></tr></thead>
              <tbody>{plan_rows}</tbody></table></div>
            <div class="legend"><span>Planen er veiledende lenger fram enn neste runde —
              skader og lagoppstillinger vi ikke kjenner ennå endrer den hver uke.</span></div>
          </div>
          <div>
            <div class="head"><h2>Strategiene mot hverandre</h2></div>
            <div class="scroller"><table>
              <thead><tr><th>Strategi</th><th>xP netto</th><th>Gevinst</th><th>Hits</th><th>Inn GW{D['next_gw']}</th><th>Kaptein</th></tr></thead>
              <tbody>{strategy_rows}</tbody></table></div>
            <div class="legend"><span>Alle tallene er ekte forventede poeng over fem runder,
              fratrukket hits — også for planene som maksimerte noe annet.</span></div>
          </div>
        </div>
      </section>

      <section>
        <div class="two">
          <div>
            <div class="head"><h2>Kapteinsvalg</h2></div>
            <div class="scroller"><table>
              <thead><tr><th>Spiller</th><th>Lag</th><th>Pos</th><th>xP</th><th>Med bind</th><th>Haul</th></tr></thead>
              <tbody>{cap_rows}</tbody></table></div>
            <div class="legend"><span>Haul-kolonnen er sannsynligheten for 10 poeng eller mer.
              To spillere med samme xP er ikke like gode kapteinsvalg hvis den ene oftere
              leverer den store uka.</span></div>
          </div>
          <div>
            <div class="head"><h2>Benken</h2></div>
            <div class="scroller"><table>
              <thead><tr><th>Inn</th><th>xP</th><th></th><th>Ut</th><th>xP</th><th>Gevinst</th></tr></thead>
              <tbody>{bench_rows}</tbody></table></div>
            <div class="legend"><span>Bytter modellen mener du bør gjøre i oppstillingen før
              deadline. Koster ingenting — dette er ikke overganger.</span></div>
          </div>
        </div>
      </section>

      <section>
        <div class="head"><h2>Varsler</h2>
          <p>Regelbaserte sjekker mot troppen — skader, tvilsomme, blanke runder og eksponering.</p></div>
        <ul class="alerts">{alerts}</ul>
      </section>

      <section>
        <div class="two">
          <div>
            <div class="head"><h2>Høyest xP neste tre</h2></div>
            <div class="scroller"><table>
              <thead><tr><th>Spiller</th><th>Lag</th><th>Pos</th><th>Pris</th><th>Eid&nbsp;%</th><th>xP&nbsp;3</th></tr></thead>
              <tbody>{league_rows(D['top'])}</tbody></table></div>
          </div>
          <div>
            <div class="head"><h2>Differensialer</h2></div>
            <div class="scroller"><table>
              <thead><tr><th>Spiller</th><th>Lag</th><th>Pos</th><th>Pris</th><th>Eid&nbsp;%</th><th>xP&nbsp;3</th></tr></thead>
              <tbody>{league_rows(D['diff'])}</tbody></table></div>
            <div class="legend"><span>Under 10&nbsp;% eierskap, rangert på modellens xP — ikke på form.</span></div>
          </div>
        </div>
      </section>

      <section>
        <div class="head"><h2>Effektivt eierskap</h2>
          <p>Blant en stikkprøve på {D['eo']['utvalg']} managere fra {esc(D['eo']['liga'])} —
          det som faktisk flytter rangeringen din, ikke hvor mange som eier spilleren totalt.</p></div>
        <div class="two">
          <div>
            <div class="head"><h2>Toppens lag</h2></div>
            <div class="scroller"><table>
              <thead><tr><th>Spiller</th><th>Lag</th><th>Pos</th><th>Pris</th>
                <th>Eid&nbsp;%</th><th>Kaptein&nbsp;%</th><th>EO</th></tr></thead>
              <tbody>{eo_rows(D['eo']['topp'])}</tbody></table></div>
            <div class="legend"><span>EO = eierandel + kapteinsandel (+ dobbel vekt for triple
              captain). Høyt EO uten at du eier spilleren er reell rangeringsrisiko.</span></div>
          </div>
          <div>
            <div class="head"><h2>Rangeringsrisiko</h2></div>
            <div class="scroller"><table>
              <thead><tr><th>Spiller</th><th>Lag</th><th>Pos</th><th>Pris</th>
                <th>Eid&nbsp;%</th><th>Kaptein&nbsp;%</th><th>EO</th></tr></thead>
              <tbody>{eo_rows(D['eo']['risiko'])}</tbody></table></div>
            <div class="legend"><span>Høyest EO blant spillerne du <em>ikke</em> eier. Leverer en
              av disse, faller du bak alle som har ham — uansett hva resten av laget ditt gjør.</span></div>
          </div>
        </div>
      </section>

      <section>
        <div class="head"><h2>Kampprogram</h2>
          <label class="toggle"><input type="checkbox" id="only-mine"> Bare lagene jeg har spillere fra</label></div>
        <div class="scroller">
          <table class="grid-table">
            <thead><tr><th>Lag</th><th>Snitt</th>{gw_head}</tr></thead>
            <tbody id="grid-body">{grid_rows}</tbody>
          </table>
        </div>
      </section>

      <section>
        <div class="head"><h2>Treffer modellen?</h2>
          <p>Testet på hele forrige sesong, walk-forward: modellen får bare se kamper som
          var spilt da prediksjonen skulle vært laget.</p></div>
        <div class="two">
          <div class="scroller"><table>
            <thead><tr><th>Modellen sier</th><th>Faktisk</th><th>Kamper</th></tr></thead>
            <tbody>{cal_rows}</tbody></table></div>
          <div>
            <p style="margin-top:0">Clean sheet-sannsynligheten er godt kalibrert: når modellen
            sier 35&nbsp;%, skjer det i 37&nbsp;% av tilfellene. Brier-scoren er
            <strong>{num(M['brier_2025'], 3)}</strong> mot <strong>{num(M['baseline_2025'], 3)}</strong>
            for å tippe ligasnittet hver gang — {pct(M['skill_2025'])} bedre, og
            {pct(M['skill_2024'])} bedre på sesongen før.</p>
            <p>Det er en ærlig, men beskjeden gevinst. Clean sheets er iboende vanskelige å
            spå, og en modell som slår basisraten med noen få prosent er omtrent det man
            skal forvente. Den systematiske skjevheten er verdt å merke seg: modellen spår
            {pct(M['mean_pred'])} i snitt mot {pct(M['base_rate'])} faktisk, altså litt for
            lavt — Poisson undervurderer nullen.</p>
          </div>
        </div>
      </section>

      <div class="note">
        <p><strong>Slik regnes tallene.</strong> Lagstyrke estimeres fra xG over tre sesonger,
        med nyere kamper vektet tyngre og ratingene krympet mot ligasnittet. Det gir forventede
        mål for hvert lag i hver kamp. Så simuleres kampen {M['sims']:,} ganger: målene trekkes
        fra en Poisson-fordeling, fordeles på spillerne etter deres andel av lagets xG, og
        kombineres med en minuttmodell, clean sheet, kort, defensive contribution og en
        empirisk bonusfordeling.</p>
        <p><strong>Hvorfor simulering i stedet for et snitt.</strong> Kampen simuleres samlet,
        ikke spiller for spiller. Det gjør at spillere fra samme lag blir korrelerte slik de
        faktisk er: i simuleringene der laget vinner 4–0 får både keeperen sin clean sheet og
        spissen sitt hat trick. Nettopp den korrelasjonen avgjør om bench boost og trippel
        kaptein lønner seg — og den forsvinner hvis man bare legger sammen forventninger.</p>
        <p><strong>Svakeste ledd.</strong> Bonuspoengene. De trekkes fra en empirisk tabell
        over hva spillere med tilsvarende kamp faktisk fikk, ikke fra en BPS-modell. Første
        kandidat til å byttes ut. Fase 4 er transfer-optimizeren, som bruker nettopp disse
        fordelingene.</p>
      </div>
    </div>

    <script>
      var RULES = {RULES_JS};

      (async function () {{
        var box = document.getElementById("ask");
        var input = document.getElementById("ask-input");
        var send = document.getElementById("ask-send");
        var stop = document.getElementById("ask-stop");
        var answer = document.getElementById("ask-answer");
        var suggest = document.getElementById("ask-suggest");
        if (!box || !window.claude || !window.claude.use) return;

        var sample = null;
        try {{ sample = await window.claude.use("sample"); }} catch (e) {{ sample = null; }}
        if (!sample) return;
        box.hidden = false;

        var controller = null;

        var COPY = {{
          not_granted: "Du må godkjenne at siden får spørre Claude for at dette skal virke.",
          rate_limited: "For mange spørsmål på kort tid. Vent litt og prøv igjen.",
          cancelled: "",
          too_large: "Spørsmålet ble for langt.",
        }};

        async function ask(question) {{
          if (!question.trim()) return;
          controller = new AbortController();
          send.disabled = true;
          stop.hidden = false;
          answer.textContent = "Tenker …";
          try {{
            await sample([{{ role: "user", content: RULES + question }}], {{
              signal: controller.signal,
              modelTier: "default",
              onText: function (ev) {{ answer.textContent = ev.text; }}
            }});
          }} catch (err) {{
            var partial = err && err.text ? err.text : "";
            var note = COPY[err && err.code] !== undefined
              ? COPY[err.code]
              : "Klarte ikke å svare akkurat nå.";
            answer.textContent = partial || note;
          }} finally {{
            send.disabled = false;
            stop.hidden = true;
            controller = null;
          }}
        }}

        send.addEventListener("click", function () {{ ask(input.value); }});
        input.addEventListener("keydown", function (ev) {{
          if (ev.key === "Enter") {{ ev.preventDefault(); ask(input.value); }}
        }});
        stop.addEventListener("click", function () {{
          if (controller) controller.abort();
        }});
        suggest.addEventListener("click", function (ev) {{
          if (ev.target.tagName !== "BUTTON") return;
          input.value = ev.target.textContent;
          ask(input.value);
        }});
      }})();

      document.getElementById("only-mine").addEventListener("change", function (ev) {{
        var rows = document.querySelectorAll("#grid-body tr");
        for (var i = 0; i < rows.length; i++) {{
          rows[i].hidden = ev.target.checked && rows[i].dataset.mine !== "1";
        }}
      }});
    </script>
    """

    return HTML
