"""ForexFactory weekly economic calendar scraper. Free, no key.
Output: list of events dengan timezone-aware UTC datetime.
"""
from __future__ import annotations
import json
import re
import time
from dataclasses import dataclass, asdict
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional

import requests
from bs4 import BeautifulSoup

from config.settings import DATA_CACHE, HIGH_IMPACT_BLACKOUT_MIN

CACHE_TTL_SEC = 3600  # 1 jam
CACHE = DATA_CACHE / "calendar.json"

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 yeehee/1.0"

# Currency yang relevan buat XAU
RELEVANT_CCY = {"USD", "EUR", "GBP", "CNY", "ALL"}

IMPACT_MAP = {"holiday": "low", "low": "low", "medium": "medium", "high": "high", "red": "high"}


@dataclass
class CalEvent:
    when_utc: str       # ISO
    currency: str
    impact: str         # low / medium / high
    title: str
    actual: str = ""
    forecast: str = ""
    previous: str = ""

    def dt(self) -> datetime:
        return datetime.fromisoformat(self.when_utc.replace("Z", "+00:00"))

    def is_high(self) -> bool:
        return self.impact == "high"


def _read_cache() -> Optional[list[CalEvent]]:
    if not CACHE.exists():
        return None
    age = time.time() - CACHE.stat().st_mtime
    if age > CACHE_TTL_SEC:
        return None
    try:
        raw = json.loads(CACHE.read_text(encoding="utf-8"))
        return [CalEvent(**e) for e in raw]
    except Exception:
        return None


def _write_cache(events: list[CalEvent]) -> None:
    try:
        CACHE.write_text(json.dumps([asdict(e) for e in events], indent=2), encoding="utf-8")
    except Exception:
        pass


def _fetch_ff_json() -> list[dict]:
    """ForexFactory has a public-ish JSON endpoint used by their calendar widget."""
    url = "https://nfs.faireconomy.media/ff_calendar_thisweek.json"
    r = requests.get(url, headers={"User-Agent": UA}, timeout=15)
    r.raise_for_status()
    return r.json()


def fetch_calendar(use_cache: bool = True) -> list[CalEvent]:
    if use_cache:
        cached = _read_cache()
        if cached is not None:
            return cached

    events: list[CalEvent] = []
    try:
        raw = _fetch_ff_json()
        for r in raw:
            try:
                # raw: {title, country, date (ISO with TZ), impact, forecast, previous, ...}
                ccy = r.get("country", "").upper()
                if ccy not in RELEVANT_CCY and ccy != "":
                    if ccy not in {"USD", "EUR", "GBP"}:
                        continue
                date_iso = r.get("date", "")
                if not date_iso:
                    continue
                dt = datetime.fromisoformat(date_iso.replace("Z", "+00:00")).astimezone(timezone.utc)
                impact = IMPACT_MAP.get((r.get("impact") or "").lower(), "low")
                events.append(CalEvent(
                    when_utc=dt.isoformat(),
                    currency=ccy,
                    impact=impact,
                    title=r.get("title", ""),
                    forecast=str(r.get("forecast", "") or ""),
                    previous=str(r.get("previous", "") or ""),
                ))
            except Exception:
                continue
    except Exception as e:
        print(f"[warn] calendar fetch failed: {e}")
        return []

    events.sort(key=lambda e: e.when_utc)
    _write_cache(events)
    return events


def upcoming_high_impact(within_hours: int = 48) -> list[CalEvent]:
    now = datetime.now(timezone.utc)
    cutoff = now + timedelta(hours=within_hours)
    return [e for e in fetch_calendar() if e.is_high() and now <= e.dt() <= cutoff]


def in_news_blackout(at: Optional[datetime] = None, blackout_min: int = HIGH_IMPACT_BLACKOUT_MIN) -> tuple[bool, Optional[CalEvent]]:
    """True kalau saat `at` ada high-impact event ±blackout_min menit."""
    at = at or datetime.now(timezone.utc)
    window = timedelta(minutes=blackout_min)
    for e in fetch_calendar():
        if e.is_high() and abs(e.dt() - at) <= window:
            return True, e
    return False, None


if __name__ == "__main__":
    events = fetch_calendar()
    print(f"[ok] {len(events)} events fetched")
    for e in upcoming_high_impact(72)[:10]:
        print(f"  {e.when_utc}  [{e.currency:3s}] {e.impact:6s}  {e.title}")
