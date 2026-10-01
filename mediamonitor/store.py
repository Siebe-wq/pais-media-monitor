"""SQLite storage. Re-running a fetch updates rows instead of duplicating them."""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from .gdelt import Article, DayCount

SCHEMA = """
CREATE TABLE IF NOT EXISTS articles (
    url TEXT PRIMARY KEY,
    country TEXT NOT NULL,
    title TEXT,
    domain TEXT,
    language TEXT,
    source_country TEXT,
    seen_at TEXT NOT NULL,
    fetched_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_articles_country_seen ON articles(country, seen_at);

CREATE TABLE IF NOT EXISTS daily_counts (
    country TEXT NOT NULL,
    day TEXT NOT NULL,
    count INTEGER NOT NULL,
    total_monitored INTEGER NOT NULL,
    fetched_at TEXT NOT NULL,
    PRIMARY KEY (country, day)
);

CREATE TABLE IF NOT EXISTS classifications (
    url TEXT PRIMARY KEY REFERENCES articles(url),
    relevant INTEGER NOT NULL,
    stance TEXT NOT NULL,
    category TEXT NOT NULL,
    depth INTEGER NOT NULL,
    subtopic TEXT,
    rationale TEXT,
    model TEXT,
    classified_at TEXT NOT NULL
);
"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class Store:
    def __init__(self, path: str | Path):
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(path))
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(SCHEMA)
        # Databases made before the subtopic column existed.
        cols = {r["name"] for r in self.conn.execute("PRAGMA table_info(classifications)")}
        if "subtopic" not in cols:
            self.conn.execute("ALTER TABLE classifications ADD COLUMN subtopic TEXT")

    def close(self) -> None:
        self.conn.close()

    def upsert_articles(self, country: str, articles: list[Article]) -> int:
        """Insert new articles. Returns how many were new."""
        before = self.conn.total_changes
        now = _now()
        self.conn.executemany(
            """INSERT INTO articles (url, country, title, domain, language, source_country, seen_at, fetched_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(url) DO NOTHING""",
            [(a.url, country, a.title, a.domain, a.language, a.source_country,
              a.seen_at.isoformat(), now) for a in articles],
        )
        self.conn.commit()
        return self.conn.total_changes - before

    def upsert_counts(self, country: str, counts: list[DayCount]) -> None:
        now = _now()
        self.conn.executemany(
            """INSERT INTO daily_counts (country, day, count, total_monitored, fetched_at)
               VALUES (?, ?, ?, ?, ?)
               ON CONFLICT(country, day) DO UPDATE SET
                 count = excluded.count,
                 total_monitored = excluded.total_monitored,
                 fetched_at = excluded.fetched_at""",
            [(country, c.day, c.count, c.total_monitored, now) for c in counts],
        )
        self.conn.commit()

    def save_classification(self, url: str, relevant: bool, stance: str, category: str,
                            depth: int, rationale: str, model: str, subtopic: str | None = None) -> None:
        self.conn.execute(
            """INSERT INTO classifications
                 (url, relevant, stance, category, depth, subtopic, rationale, model, classified_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(url) DO UPDATE SET
                 relevant = excluded.relevant, stance = excluded.stance,
                 category = excluded.category, depth = excluded.depth, subtopic = excluded.subtopic,
                 rationale = excluded.rationale, model = excluded.model,
                 classified_at = excluded.classified_at""",
            (url, int(relevant), stance, category, depth, subtopic, rationale, model, _now()),
        )
        self.conn.commit()

    def unclassified_articles(self, limit: int | None = None) -> list[sqlite3.Row]:
        sql = """SELECT a.* FROM articles a
                 LEFT JOIN classifications c ON c.url = a.url
                 WHERE c.url IS NULL ORDER BY a.seen_at DESC"""
        if limit:
            sql += f" LIMIT {int(limit)}"
        return self.conn.execute(sql).fetchall()

    def daily_counts(self) -> list[sqlite3.Row]:
        return self.conn.execute(
            "SELECT country, day, count, total_monitored FROM daily_counts ORDER BY country, day"
        ).fetchall()

    def articles_with_labels(self) -> list[sqlite3.Row]:
        return self.conn.execute(
            """SELECT a.url, a.country, a.title, a.domain, a.language, a.seen_at,
                      c.relevant, c.stance, c.category, c.depth, c.subtopic, c.rationale
               FROM articles a LEFT JOIN classifications c ON c.url = a.url
               ORDER BY a.seen_at DESC"""
        ).fetchall()
