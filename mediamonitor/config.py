"""Load the TOML config that says what to track and where."""

from __future__ import annotations

import tomllib
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path


@dataclass
class Country:
    code: str  # short label used in the database and report, e.g. "NL"
    name: str  # display name
    gdelt: str  # value for GDELT's sourcecountry: filter, e.g. "netherlands"


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
    model: str = "claude-opus-5"
    fetch_article_text: bool = True

    def gdelt_query(self) -> str:
        """Build the keyword part of a GDELT query from the configured terms."""
        parts = []
        for term in self.terms:
            term = term.strip()
            parts.append(f'"{term}"' if " " in term or "-" in term else term)
        if len(parts) == 1:
            return parts[0]
        return "(" + " OR ".join(parts) + ")"


def load_config(path: str | Path) -> Config:
    path = Path(path)
    with path.open("rb") as f:
        raw = tomllib.load(f)
    base = path.parent

    topic = raw["topic"]
    countries = [
        Country(code=c["code"], name=c.get("name", c["code"]), gdelt=c["gdelt"])
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
        model=classify.get("model", "claude-opus-5"),
        fetch_article_text=classify.get("fetch_article_text", True),
    )
    if tier_weights:
        cfg.tier_weights = tier_weights
    return cfg
