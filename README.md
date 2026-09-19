# FPL Planner

Egen Fantasy Premier League-plattform: eget lag inn, statistikk og kampprogram ut —
og etter hvert poengfordelinger, clean sheet-sannsynligheter og en transfer-optimizer.

**Status: fase 5.** Hele kjeden står: data inn, poengfordeling per spiller fra 10 000
simulerte kamper, en transfer-optimizer over fem runder, og en brief som oppdager hva
som har endret seg og skriver om planen når det trengs.

---

## Slik henger det sammen

```
GitHub Actions (cron) ──► FPL API ──► Postgres ──► Streamlit
```

Appen snakker aldri med FPL-APIet direkte. Ingest-jobbene skriver til databasen,
appen leser fra den. Det gir tre ting: historikk APIet ikke selv har (priser time
for time), en app som laster raskt og overlever at FPL ligger nede, og muligheten
til å backteste — fordi vi har lagret hva vi visste da vi visste det.

## Kom i gang lokalt

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt
cp .env.example .env          # entry-ID ligger allerede inne

python scripts/run_ingest.py core        # lag, spillere, kamper (~5 sek)
python scripts/run_ingest.py squad       # mine picks
python scripts/run_ingest.py history     # xG per spiller per runde (~5 min)
python scripts/run_ingest.py historical  # tidligere sesonger
python scripts/run_ingest.py predict     # simuler de neste 5 rundene (~15 sek)
python scripts/run_ingest.py backtest    # valider mot forrige sesong
python scripts/run_ingest.py optimize    # anbefalte bytter (--risk -1 … 1)
python scripts/run_ingest.py brief       # ukens brief: endringer, råd og plan

streamlit run app/streamlit_app.py
```

Uten `DATABASE_URL` satt havner alt i `data/fpl.sqlite`. Samme kode kjører mot
Postgres i produksjon — det eneste som endrer seg er URL-en.

## Deploy

Det finnes to veier. Velg én.

### A. GitHub Pages — statisk side, ingen database å sette opp

Enkleste vei, og den som krever minst av deg: en GitHub Action bygger siden hver
morgen og legger den ut på en egen URL.

1. Push repoet til GitHub.
2. Settings → Pages → Source: **GitHub Actions**.
3. Settings → Secrets and variables → Actions → Variables → ny variabel
   `FPL_ENTRY_ID` med entry-ID-en din.
4. Actions-fanen → «Bygg og publiser siden» → Run workflow.

Databasen er en SQLite-fil som ligger i Actions-cachen mellom kjøringene, så den
tunge historikken hentes bare første gang. Første kjøring tar rundt ti minutter,
de neste under fem.

Du kan bygge den lokalt også:

```bash
python scripts/build_site.py --out site
open site/index.html
```

**To ting å vite.** Siden blir offentlig — GitHub Pages er åpent for alle som
kjenner URL-en, også fra et privat repo. FPL-laget ditt er offentlig data uansett,
men det er verdt å vite. Og spørsmålsboksen virker ikke der: den trenger
Claude-runtime, så den skrur seg av av seg selv utenfor en publisert artifact.

### B. Supabase og Streamlit — interaktivt

Denne veien gir deg skyvebryterne — risikoknappen, minuttgrenser, horisont — som
den statiske siden ikke kan ha. Til gjengjeld er det tre kontoer å sette opp.

Sett variabelen `USE_POSTGRES` til `true` under Actions → Variables for å slå på
ingest-jobben som hører til denne veien.

**1. Database (Supabase, gratis).** Opprett et prosjekt, kopier
connection string fra Settings → Database. Kjør så ingest lokalt én gang mot den
URL-en for å opprette tabellene:

```bash
DATABASE_URL="postgresql+psycopg2://postgres:PASSORD@db.xxx.supabase.co:5432/postgres" \
  python scripts/run_ingest.py daily
```

**2. Ingest (GitHub Actions).** Legg `DATABASE_URL` og `FPL_ENTRY_ID` inn som
repository secrets. `.github/workflows/ingest.yml` kjører da priser annenhver time
og full oppdatering 05:30 norsk tid — etter at FPL har gjort prisendringene sine
rundt 02:30. Du kan alltid kjøre en jobb manuelt fra Actions-fanen.

> Merk: i et privat repo bruker dette rundt 400 av de 2000 gratis
> Actions-minuttene i måneden. Gjør repoet offentlig, så er det gratis uansett.

**3. App (Streamlit Community Cloud).** Koble til repoet, pek på
`app/streamlit_app.py`, og legg `DATABASE_URL` og `FPL_ENTRY_ID` under Secrets.

## Hva som ligger hvor

| Mappe | Innhold |
|---|---|
| `fplplanner/ingest/` | API-klient med retry, ingest-jobber, historiske sesonger |
| `fplplanner/db.py` | Skjema som virker uendret på SQLite og Postgres |
| `fplplanner/models/` | Lagstyrke, minutter, andeler, Monte Carlo og backtest |
| `fplplanner/optimize/` | Transfer-optimizer i PuLP, med risikojustert målfunksjon |
| `fplplanner/brief/` | Endringsdeteksjon og den skrevne briefen |
| `fplplanner/analysis/` | Spørringer, banevisning og regelbaserte varsler |
| `app/` | Streamlit-frontend |
| `tests/` | Enhetstester + kontrakttester mot FPL-APIet |

Alt i `models/` er rene funksjoner — data inn, tall ut, ingen databasekall — bortsett
fra `predict.py`, som er det eneste som snakker med databasen. Det er derfor hver del
kan testes for seg uten at noe er lastet inn. Optimizeren (`optimize/`) kommer i fase 4.

## Modellen

| Modul | Gjør |
|---|---|
| `team_strength.py` | Angreps- og forsvarsrating per lag fra xG, iterativ skalering, krympet mot ligasnittet |
| `minutes.py` | Sannsynlighet for 0 / 1–59 / 60+ minutter, justert for skadenytt |
| `rates.py` | Spillerens andel av lagets xG og xA per 90, pluss kort-, redning- og DC-rater |
| `simulate.py` | Monte Carlo på kampnivå — mål trekkes for laget og fordeles på spillerne |
| `scoring.py` | FPLs poengregler, med en sjekk mot `game_config.scoring` i APIet |
| `backtest.py` | Walk-forward-validering mot tidligere sesonger |
| `ownership.py` | Effektivt eierskap (EO) blant en stikkprøve av toppmanagere |

## Optimizeren

| Modul | Gjør |
|---|---|
| `objective.py` | Gjør fordelingen om til én verdi per spiller, gitt risikoappetitt |
| `transfer_lp.py` | Selve heltallsproblemet: kjøp, salg, lag, benk, kaptein per runde |
| `plan.py` | Henter grunnlaget fra databasen og gjør svaret lesbart |

Hits er modellert eksplisitt som −4 i målfunksjonen. Optimizeren blir altså ikke
*fortalt* om et hit lønner seg — den regner det ut, og tar det bare når gevinsten over
horisonten er større. Gratis bytter spares opp korrekt (inntil fem), og framtidige
runder diskonteres med 0,84 per runde.

Risikoskyveknappen går fra −1 til +1: null er rene forventede poeng, positivt vekter
oppsiden (p90), negativt straffer nedsiden (p10). Planen rapporterer alltid ekte xP,
også når optimizeren har maksimert noe annet.

Simuleringen skjer på kampnivå, ikke spillernivå. Det gjør spillere fra samme lag
korrelerte slik de faktisk er: i simuleringene der laget vinner 4–0 får både keeperen
sin clean sheet og spissen sitt hat trick. Den korrelasjonen er det som avgjør om
bench boost og trippel kaptein lønner seg, og den forsvinner hvis man bare legger
sammen forventninger.

**Validering.** Clean sheet-modellen er testet walk-forward over to hele sesonger.
Brier-score 0,178 mot 0,184 for å tippe ligasnittet hver gang — 3 % bedre i 2025-26 og
6 % i 2024-25, med god kalibrering gjennom hele spennet. Beskjedent, men ekte.
Kjør `python scripts/run_ingest.py backtest` for tallene.

## Databasetabeller

| Tabell | Rolle |
|---|---|
| `players`, `teams`, `fixtures`, `events` | dimensjoner, byttes helt ut ved hver oppdatering |
| `player_gw` | fakta per spiller per kamp: minutter, poeng, xG, xA, xGC, BPS |
| `team_params` | estimert angreps- og forsvarsrating per lag |
| `predictions` | forventede poeng *og hele fordelingen* per spiller per kamp |
| `price_history` | pris og eierskap per tidspunkt — **APIet husker ikke dette** |
| `my_squad`, `entry_history` | mine picks og min poenghistorikk |
| `hist_player_gw` | tidligere sesonger fra vaastavs datasett |
| `ingest_log` | hva som kjørte når, og om det gikk bra |

## Tester

```bash
pytest -q                  # alt
pytest -q -m "not network" # uten å treffe FPL-APIet
```

Kontrakttestene i `test_api_contract.py` sjekker at feltene vi bygger på fortsatt
finnes. Feiler de, er det FPL som har endret APIet — ikke koden.

## Briefen

`run_ingest.py brief` kjører hele kjeden: leser verdens tilstand, sammenligner med
forrige kjøring, lar optimizeren regne på nytt, skriver briefen og fryser tilstanden
til neste gang.

| Modul | Gjør |
|---|---|
| `changes.py` | Finner hva som faktisk har endret seg — skader, priser, xP-svingninger, flyttede kamper, eierskap — og gir hver endring en alvorlighetsgrad |
| `narrative.py` | Skriver briefen fra tallene, og regner ut nest beste alternativ som sensitivitetsanalyse |

Teksten genereres deterministisk, ikke av en språkmodell. Hver setning kan spores til
et tall i databasen, og jobben kan kjøre på cron uten at noen betaler for et API-kall
eller risikerer at modellen finner på en skade. Den levende samtalen hører hjemme på
den publiserte siden, der spørsmål besvares med tallene som kontekst.

Alvorlighetsgradene: **3** påvirker troppen og endrer anbefalingen, **2** påvirker
troppen, **1** verdt å vite om. Terskelene i toppen av `changes.py` bestemmer hvor
snakkesalig briefen blir.

## Effektivt eierskap (EO)

`selected_by_percent` teller alle managere i FPL, også de som aldri sjekker laget sitt.
Det som faktisk flytter rangeringen din er hva *toppen* av tabellen eier og
kapteinsvalgene deres. `run_ingest.py eo` henter en stikkprøve på 150 managere fra
FPLs «Overall»-liga (314) og regner ut, per spiller:

```
EO = eierandel i stikkprøven + kapteinsandel + 2 × triple captain-andel
```

(triple captain tripler poengene, altså to ekstra ganger utover grunneierskapet).
`ownership.py` er den rene utregningen, `jobs.refresh_effective_ownership()` gjør
selve innhentingen og skrivingen. `basics.rank_risk()` er selve poenget med å måle
det: spillerne toppen eier tungt som du *ikke* har — reell rangeringsrisiko helt
uavhengig av om man personlig liker spilleren. Vises på siden som «Effektivt
eierskap».

## Veien videre

- **Chip-timing** — to sett chips per sesong fra 2025/26.
- **Salgspris** er tilnærmet med nåpris. Uten innlogging ser vi ikke faktisk salgspris,
  og avviket er opptil 0,1–0,2 per spiller som har steget i verdi.
- **Bonusmodellen** er svakeste ledd: den trekker fra en empirisk tabell over hva
  spillere med tilsvarende kamp faktisk fikk, ikke fra BPS. Første kandidat til
  utskifting.

Full plan ligger i prosjektdokumentet `arkitektur-og-byggeplan.md`.
