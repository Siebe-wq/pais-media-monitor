"""Command line entry point: fetch, classify, report."""

from __future__ import annotations

import argparse
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .config import load_config, quote_term
from .gdelt import DayCount, GdeltClient, GdeltError
from .store import Store


def cmd_fetch(args) -> None:
    cfg = load_config(args.config)
    store = Store(cfg.database)
    deadline = time.monotonic() + args.max_minutes * 60 if args.max_minutes else None
    client = GdeltClient(deadline=deadline)
    end = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0)
    start = end - timedelta(days=args.days)
    queries = cfg.gdelt_queries()
    print(f"Period: {start:%Y-%m-%d} to {end:%Y-%m-%d}")
    for q in queries:
        print(f"Query: {q}")
    failed = 0
    for c in cfg.countries:
        try:
            # Daily counts are summed over the query groups. An article that
            # matches terms in two groups is counted twice; article lists are
            # de-duplicated by URL in the database.
            counts = merge_counts([client.daily_counts(q, c.gdelt, start, end) for q in queries])
            store.upsert_counts(c.code, counts)
            articles, hit_cap = [], False
            for q in queries:
                batch, cap = client.articles(q, c.gdelt, start, end)
                articles += batch
                hit_cap = hit_cap or cap
            new = store.upsert_articles(c.code, articles)
        except GdeltError as e:
            print(f"  {c.name}: GDELT error: {e}", file=sys.stderr)
            failed += 1
            continue
        total = sum(x.count for x in counts)
        listed = len({a.url for a in articles})
        warn = "  (some 6-hour windows were still full; a few articles were missed)" if hit_cap else ""
        print(f"  {c.name}: {total} articles counted, {listed} listed, {new} new{warn}")
    store.close()
    if failed == len(cfg.countries):
        sys.exit("Every country failed. Nothing was fetched.")


def merge_counts(series: list[list[DayCount]]) -> list[DayCount]:
    by_day: dict[str, list[int]] = {}
    for counts in series:
        for d in counts:
            acc = by_day.setdefault(d.day, [0, d.total_monitored])
            acc[0] += d.count
            acc[1] = max(acc[1], d.total_monitored)
    return [DayCount(day, c, t) for day, (c, t) in sorted(by_day.items())]


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
            sample, _ = client.articles(query, None, start, end, split=False)
        except GdeltError as e:
            print(f"{term}: GDELT error: {e}\n")
            continue
        print(f"{term}: {total} articles worldwide in the last {args.days} days")
        for a in sample[: args.samples]:
            print(f"    {a.seen_at:%Y-%m-%d} {a.domain:<25} {a.title[:80]}")
        print()


def cmd_fetch_mediacloud(args) -> None:
    from .mediacloud_source import MediaCloudError, fetch_mediacloud

    cfg = load_config(args.config)
    store = Store(cfg.database)
    end = datetime.now(timezone.utc).date()
    start = end - timedelta(days=args.days)
    try:
        failed = fetch_mediacloud(cfg, store, start, end, max_pages=args.max_pages)
    except MediaCloudError as e:
        sys.exit(f"Media Cloud: {e}")
    finally:
        store.close()
    if failed and failed == sum(1 for c in cfg.countries if c.mediacloud):
        sys.exit("Every Media Cloud country failed. Nothing was fetched.")


def cmd_mc_collections(args) -> None:
    from .mediacloud_source import _client, find_collections

    _, directory = _client(None)
    for c in find_collections(directory, args.name):
        print(f'{c["id"]:>10}  {c["name"]}')


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
    f.add_argument("--max-minutes", type=float, default=None,
                   help="stop asking GDELT after this many minutes; what was fetched is kept")
    f.set_defaults(func=cmd_fetch)

    t = sub.add_parser("terms", help="test each search term separately, to spot noisy ones")
    t.add_argument("--days", type=int, default=30)
    t.add_argument("--samples", type=int, default=8, help="sample headlines to show per term")
    t.set_defaults(func=cmd_terms)

    m = sub.add_parser("fetch-mediacloud", help="download counts and article lists from Media Cloud")
    m.add_argument("--days", type=int, default=30)
    m.add_argument("--max-pages", type=int, default=10, help="article-list pages per country")
    m.set_defaults(func=cmd_fetch_mediacloud)

    mc = sub.add_parser("mc-collections", help="search Media Cloud collection names, e.g. 'Netherlands'")
    mc.add_argument("name")
    mc.set_defaults(func=cmd_mc_collections)

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
