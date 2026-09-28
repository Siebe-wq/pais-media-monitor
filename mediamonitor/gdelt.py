"""Small client for the GDELT DOC 2.0 API.

Docs: https://blog.gdeltproject.org/gdelt-doc-2-0-api-debuts/

Things to know about this source:
- Free, no API key. It covers online news in about 65 languages.
- It only searches a rolling window of roughly the last 3 months. To build a
  longer history, run `mediamonitor fetch` on a schedule (e.g. weekly) and let
  the local database accumulate.
- GDELT asks for at most one request every 5 seconds. The client waits between
  calls.
- An article list query returns at most 250 articles, so we query in short
  time windows.
"""

from __future__ import annotations

import json
import time
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

API_URL = "https://api.gdeltproject.org/api/v2/doc/doc"
MAX_RECORDS = 250


class GdeltError(RuntimeError):
    pass


@dataclass
class Article:
    url: str
    title: str
    domain: str
    language: str
    source_country: str
    seen_at: datetime


@dataclass
class DayCount:
    day: str  # YYYY-MM-DD
    count: int
    total_monitored: int  # GDELT's "norm": all articles it saw in that interval


def _fmt(dt: datetime) -> str:
    return dt.strftime("%Y%m%d%H%M%S")


def parse_seendate(value: str) -> datetime:
    return datetime.strptime(value, "%Y%m%dT%H%M%SZ").replace(tzinfo=timezone.utc)


def parse_articles(payload: dict) -> list[Article]:
    out = []
    for a in payload.get("articles", []) or []:
        out.append(
            Article(
                url=a["url"],
                title=(a.get("title") or "").strip(),
                domain=(a.get("domain") or "").lower(),
                language=a.get("language") or "",
                source_country=a.get("sourcecountry") or "",
                seen_at=parse_seendate(a["seendate"]),
            )
        )
    return out


def parse_timeline(payload: dict) -> list[DayCount]:
    """Sum GDELT's timeline points (which can be 15-min or hourly) into days."""
    by_day: dict[str, list[int]] = {}
    for series in payload.get("timeline", []) or []:
        for point in series.get("data", []):
            day = parse_seendate(point["date"]).date().isoformat()
            counts = by_day.setdefault(day, [0, 0])
            counts[0] += int(point.get("value", 0))
            counts[1] += int(point.get("norm", 0))
    return [DayCount(day=d, count=c[0], total_monitored=c[1]) for d, c in sorted(by_day.items())]


class GdeltClient:
    def __init__(self, min_interval: float = 5.5, timeout: float = 60, retries: int = 3):
        self.min_interval = min_interval
        self.timeout = timeout
        self.retries = retries
        self._last_call = 0.0

    def _get(self, params: dict) -> dict:
        params = {**params, "format": "json"}
        url = API_URL + "?" + urllib.parse.urlencode(params)
        last_error: Exception | None = None
        for attempt in range(self.retries):
            wait = self.min_interval - (time.monotonic() - self._last_call)
            if wait > 0:
                time.sleep(wait)
            self._last_call = time.monotonic()
            try:
                req = urllib.request.Request(url, headers={"User-Agent": "mediamonitor/0.1"})
                with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                    body = resp.read().decode("utf-8", errors="replace")
            except OSError as e:
                last_error = e
                time.sleep(self.min_interval * (attempt + 1))
                continue
            if not body.strip():
                return {}  # GDELT returns an empty body when nothing matches
            try:
                return json.loads(body)
            except json.JSONDecodeError:
                # GDELT reports errors (bad query, rate limit) as plain text.
                last_error = GdeltError(body.strip()[:300])
                if "limit requests" in body.lower():
                    time.sleep(self.min_interval * (attempt + 2))
                    continue
                raise last_error
        raise GdeltError(f"GDELT request failed after {self.retries} tries: {last_error}")

    @staticmethod
    def build_query(keywords: str, country: str | None) -> str:
        return f"{keywords} sourcecountry:{country}" if country else keywords

    def daily_counts(self, keywords: str, country: str | None,
                     start: datetime, end: datetime) -> list[DayCount]:
        payload = self._get({
            "query": self.build_query(keywords, country),
            "mode": "timelinevolraw",
            "startdatetime": _fmt(start),
            "enddatetime": _fmt(end),
        })
        return parse_timeline(payload)

    def articles(self, keywords: str, country: str | None,
                 start: datetime, end: datetime, window_days: int = 7) -> tuple[list[Article], bool]:
        """Fetch article lists in windows. Returns (articles, hit_cap).

        hit_cap is True if any window returned the 250-article maximum, which
        means some articles were missed. Use a smaller window if that happens.
        """
        out: list[Article] = []
        hit_cap = False
        cursor = start
        while cursor < end:
            window_end = min(cursor + timedelta(days=window_days), end)
            payload = self._get({
                "query": self.build_query(keywords, country),
                "mode": "artlist",
                "maxrecords": MAX_RECORDS,
                "sort": "datedesc",
                "startdatetime": _fmt(cursor),
                "enddatetime": _fmt(window_end),
            })
            batch = parse_articles(payload)
            hit_cap = hit_cap or len(batch) >= MAX_RECORDS
            out.extend(batch)
            cursor = window_end
        return out, hit_cap
