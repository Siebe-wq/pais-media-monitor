"""Command line entry point: fetch, classify, report."""

from __future__ import annotations

import argparse
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .config import load_config, quote_term
from .gdelt import GdeltClient, GdeltError
from .store import Store


def cmd_fetch(args) -> None:
    cfg = load_config(args.config)
    store = Store(cfg.database)
    client = GdeltClient()
    end = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0)
    start = end - timedelta(days=args.days)
    query = cfg.gdelt_query()
    print(f"Query: {query}\nPeriod: {start:%Y-%m-%d} to {end:%Y-%m-%d}")
    for c in cfg.countries:
        try:
            counts = client.daily_counts(query, c.gdelt, start, end)
            store.upsert_counts(c.code, counts)
            articles, hit_cap = client.articles(query, c.gdelt, start, end, window_days=args.window)
            new = store.upsert_articles(c.code, articles)
        except GdeltError as e:
            print(f"  {c.name}: GDELT error: {e}", file=sys.stderr)
            continue
        total = sum(x.count for x in counts)
        warn = "  (some windows hit the 250 cap; try a smaller --window)" if hit_cap else ""
        print(f"  {c.name}: {total} articles counted, {len(articles)} listed, {new} new{warn}")
    store.close()


def cmd_terms(args) -> None:
    """Check each search term on its own: how many hits, and do sample headlines look right?"""
    cfg = load_config(args.config)
    client = GdeltClient()
    end = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0)
    start = end - timedelta(days=args.days)
    for term in cfg.terms:
        query = quote_term(term)
        try:
            total = sum(x.count for x in client.daily_counts(query, None, start, end))
            sample, _ = client.articles(query, None, start, end, window_days=args.days)
        except GdeltError as e:
            print(f"{term}: GDELT error: {e}\n")
            continue
        print(f"{term}: {total} articles worldwide in the last {args.days} days")
        for a in sample[: args.samples]:
            print(f"    {a.seen_at:%Y-%m-%d} {a.domain:<25} {a.title[:80]}")
        print()


def cmd_classify(args) -> None:
    from .classify import classify_all

    cfg = load_config(args.config)
    store = Store(cfg.database)
    n = classify_all(cfg, store, limit=args.limit)
    print(f"Labelled {n} articles.")
    store.close()


def cmd_report(args) -> None:
    from .report import write_report

    cfg = load_config(args.config)
    store = Store(cfg.database)
    path = write_report(cfg, store, Path(args.out))
    store.close()
    print(f"Wrote {path} (plus weekly_counts.csv and articles.csv)")


def main(argv=None) -> None:
    p = argparse.ArgumentParser(prog="mediamonitor", description=__doc__)
    p.add_argument("-c", "--config", default="config.toml", help="path to config file")
    sub = p.add_subparsers(dest="command", required=True)

    f = sub.add_parser("fetch", help="download counts and article lists from GDELT")
    f.add_argument("--days", type=int, default=30, help="how many days back (GDELT keeps ~90)")
    f.add_argument("--window", type=int, default=7, help="days per article-list request")
    f.set_defaults(func=cmd_fetch)

    t = sub.add_parser("terms", help="test each search term separately, to spot noisy ones")
    t.add_argument("--days", type=int, default=30)
    t.add_argument("--samples", type=int, default=8, help="sample headlines to show per term")
    t.set_defaults(func=cmd_terms)

    c = sub.add_parser("classify", help="label stored articles with Claude (optional)")
    c.add_argument("--limit", type=int, default=None, help="label at most this many articles")
    c.set_defaults(func=cmd_classify)

    r = sub.add_parser("report", help="write the HTML report and CSV files")
    r.add_argument("--out", default="reports", help="output folder")
    r.set_defaults(func=cmd_report)

    args = p.parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()
