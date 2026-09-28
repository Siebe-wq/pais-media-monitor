"""Weight articles by outlet reach, using a hand-kept list of outlet tiers.

GDELT gives no audience numbers. Instead you keep a CSV with columns
`domain,tier` (plus any notes). Tier 1 = large national outlet, 2 = regional
or trade outlet, 3 = small outlet. Tier weights come from the config.
Unknown outlets get `unknown_weight`.
"""

from __future__ import annotations

import csv
from pathlib import Path


class ReachTable:
    def __init__(self, tiers: dict[str, int], tier_weights: dict[int, float], unknown_weight: float):
        self.tiers = {d.lower().removeprefix("www."): t for d, t in tiers.items()}
        self.tier_weights = tier_weights
        self.unknown_weight = unknown_weight

    @classmethod
    def from_csv(cls, path: Path | None, tier_weights: dict[int, float], unknown_weight: float) -> "ReachTable":
        tiers: dict[str, int] = {}
        if path and path.exists():
            with path.open(newline="", encoding="utf-8") as f:
                for row in csv.DictReader(f):
                    domain = (row.get("domain") or "").strip()
                    if domain and not domain.startswith("#"):
                        tiers[domain] = int(row["tier"])
        return cls(tiers, tier_weights, unknown_weight)

    def tier(self, domain: str) -> int | None:
        """Look up a domain, also matching subdomains (e.g. nos.nl for www.nos.nl)."""
        d = domain.lower().removeprefix("www.")
        while d:
            if d in self.tiers:
                return self.tiers[d]
            if "." not in d:
                return None
            d = d.split(".", 1)[1]
        return None

    def weight(self, domain: str) -> float:
        t = self.tier(domain)
        return self.unknown_weight if t is None else self.tier_weights.get(t, self.unknown_weight)
