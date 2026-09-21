"""Klient mot det offentlige FPL-APIet.

APIet ligger bak Cloudflare og svarer av og til 403 eller 429 paa kall fra
datasenter-IP-er. Klienten haandterer det med retry og eksponentiell backoff,
en identifiserbar User-Agent og en liten pause mellom kall i de tunge jobbene.
"""

from __future__ import annotations

import logging
import time
from typing import Any

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from ..config import get_settings

log = logging.getLogger(__name__)

BASE_URL = "https://fantasy.premierleague.com/api"


class FPLError(RuntimeError):
    pass


class FPLClient:
    def __init__(self, throttle_seconds: float | None = None, timeout: int = 20) -> None:
        settings = get_settings()
        self.throttle = settings.throttle_seconds if throttle_seconds is None else throttle_seconds
        self.timeout = timeout
        self._last_call = 0.0

        retry = Retry(
            total=5,
            backoff_factor=1.5,          # 1.5s, 3s, 6s, 12s, 24s
            status_forcelist=(403, 429, 500, 502, 503, 504),
            allowed_methods=("GET",),
            raise_on_status=False,
        )
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": settings.user_agent,
            "Accept": "application/json",
        })
        adapter = HTTPAdapter(max_retries=retry, pool_maxsize=10)
        self.session.mount("https://", adapter)

    def _sleep_if_needed(self) -> None:
        elapsed = time.monotonic() - self._last_call
        if elapsed < self.throttle:
            time.sleep(self.throttle - elapsed)

    def get(self, path: str) -> Any:
        self._sleep_if_needed()
        url = f"{BASE_URL}/{path.lstrip('/')}"
        response = self.session.get(url, timeout=self.timeout)
        self._last_call = time.monotonic()
        if response.status_code != 200:
            raise FPLError(f"{url} svarte {response.status_code}")
        try:
            return response.json()
        except ValueError as exc:                      # pragma: no cover
            raise FPLError(f"{url} ga ikke gyldig JSON") from exc

    # --- endepunkter -------------------------------------------------

    def bootstrap(self) -> dict:
        """Spillere, lag, gameweeks, chips, regler. Alt som endrer seg sjelden."""
        return self.get("bootstrap-static/")

    def fixtures(self, event: int | None = None) -> list[dict]:
        return self.get("fixtures/" if event is None else f"fixtures/?event={event}")

    def element_summary(self, player_id: int) -> dict:
        """Per-kamp-historikk for en spiller, inkludert xG, xA og xGC."""
        return self.get(f"element-summary/{player_id}/")

    def entry(self, entry_id: int) -> dict:
        return self.get(f"entry/{entry_id}/")

    def entry_history(self, entry_id: int) -> dict:
        return self.get(f"entry/{entry_id}/history/")

    def entry_picks(self, entry_id: int, event: int) -> dict:
        return self.get(f"entry/{entry_id}/event/{event}/picks/")

    def league_standings(self, league_id: int, page: int = 1) -> dict:
        """En side (50 stk) med managere i en klassisk liga, sortert paa rangering."""
        return self.get(f"leagues-classic/{league_id}/standings/?page_standings={page}")
