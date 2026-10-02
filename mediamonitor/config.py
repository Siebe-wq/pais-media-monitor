"""Load the TOML config that says what to track and where."""

from __future__ import annotations

import tomllib
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path


MAX_KEYWORD_QUERY = 190  # characters; leaves room for " sourcecountry:..." (see gdelt_queries)


def quote_term(term: str) -> str:
    """GDELT needs quotes around anything that is not one plain word (spaces, hyphens, slashes)."""
    term = term.strip()
    return term if term.isalnum() else f'"{term}"'


@dataclass
class Country:
    code: str  # short label used in the database and report, e.g. "NL"
    name: str  # display name
    gdelt: str  # value for GDELT's sourcecountry: filter, e.g. "netherlands"
    mediacloud: str | int | None = None  # Media Cloud collection name or id, e.g. "Netherlands - National"


@dataclass
class Action:
    """Something the organisation did in public (a protest, a report launch)."""

    date: date
    label: str


@dataclass
class Config:
    name: str
    description: str
    terms: list[str]
    countries: list[Country]
    actions: list[Action] = field(default_factory=list)
    outlets_file: Path | None = None
    tier_weights: dict[int, float] = field(default_factory=lambda: {1: 10.0, 2: 3.0, 3: 1.0})
    unknown_weight: float = 1.0
    database: Path = Path("mediamonitor.db")
    model: str = "claude-sonnet-5-5"
    fetch_article_text: bool = True
    stance_guide: str = ""
    subtopics: list[str] = field(default_factory=list)
    mc_terms: list[str] = field(default_factory=list)
    mc_raw: list[str] = field(default_factory=list)

    def mediacloud_query(self) -> str:
        """Media Cloud searches the original text, so its terms are in several languages.

        `terms` are quoted as exact phrases; `raw` entries are used as written,
        for combinations such as an abbreviation that only counts next to a topic word.
        """
        parts = [f'"{t.strip()}"' for t in self.mc_terms] + [f"({r.strip()})" for r in self.mc_raw]
        return " OR ".join(parts)

    def gdelt_query(self) -> str:
        """All terms as one OR query. Can be too long for GDELT; see gdelt_queries."""
        return _or_query([quote_term(t) for t in self.terms])

    def gdelt_queries(self, max_len: int = MAX_KEYWORD_QUERY) -> list[str]:
        """Split the terms into OR queries that each stay under `max_len` characters.

        GDELT rejects long queries ("Your query was too short or too long").
        In tests, 232 characters of terms worked on their own, but failed once
        " sourcecountry:netherlands" was added, so we leave room for that filter.
        Terms keep their config order, so related terms stay in the same group.
        """
        groups: list[list[str]] = [[]]
        for term in (quote_term(t) for t in self.terms):
            if groups[-1] and len(_or_query(groups[-1] + [term])) > max_len:
                groups.append([])
            groups[-1].append(term)
        return [_or_query(g) for g in groups if g]


def _or_query(parts: list[str]) -> str:
    return parts[0] if len(parts) == 1 else "(" + " OR ".join(parts) + ")"


def load_config(path: str | Path) -> Config:
    path = Path(path)
    with path.open("rb") as f:
        raw = tomllib.load(f)
    base = path.parent

    topic = raw["topic"]
    countries = [
        Country(code=c["code"], name=c.get("name", c["code"]), gdelt=c["gdelt"],
                mediacloud=c.get("mediacloud"))
        for c in raw["countries"]
    ]
    actions = [
        Action(date=a["date"] if isinstance(a["date"], date) else date.fromisoformat(a["date"]),
               label=a["label"])
        for a in raw.get("actions", [])
    ]
    reach = raw.get("reach", {})
    outlets_file = reach.get("outlets_file")
    tier_weights = {int(k): float(v) for k, v in reach.get("tier_weights", {}).items()}
    storage = raw.get("storage", {})
    classify = raw.get("classify", {})

    cfg = Config(
        name=topic["name"],
        description=topic.get("description", ""),
        terms=topic["terms"],
        countries=countries,
        actions=sorted(actions, key=lambda a: a.date),
        outlets_file=(base / outlets_file) if outlets_file else None,
        unknown_weight=float(reach.get("unknown_weight", 1.0)),
        database=base / storage.get("database", "mediamonitor.db"),
        model=classify.get("model", "claude-sonnet-5-5"),
        fetch_article_text=classify.get("fetch_article_text", True),
        stance_guide=classify.get("stance_guide", "").strip(),
        subtopics=classify.get("subtopics", []),
        mc_terms=raw.get("mediacloud", {}).get("terms", []),
        mc_raw=raw.get("mediacloud", {}).get("raw", []),
    )
    if tier_weights:
        cfg.tier_weights = tier_weights
    return cfg
