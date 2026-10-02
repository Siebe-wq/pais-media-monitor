"""Second source: the Media Cloud online news archive (search.mediacloud.org).

Unlike GDELT, Media Cloud searches the original text of each article, so the
search terms must include each language you care about. It groups outlets
into collections such as "Netherlands - National".

Needs a free account and API key (MC_API_KEY). The client library allows
2 requests per minute by default, so a run takes a few minutes. The main index
starts in 2022.
"""

from __future__ import annotations

import os
import sys
from datetime import date, datetime, time, timezone
from urllib.parse import urlparse

from .config import Config, Country
from .gdelt import Article
from .store import Store


class MediaCloudError(RuntimeError):
    pass


def _client(api_key: str | None):
    try:
        import mediacloud.api
    except ImportError:
        sys.exit("Media Cloud needs its package: pip install -e '.[mediacloud]'")
    key = api_key or os.environ.get("MC_API_KEY")
    if not key:
        raise MediaCloudError("no MC_API_KEY set")
    return mediacloud.api.SearchApi(key), mediacloud.api.DirectoryApi(key)


def find_collections(directory, name: str) -> list[dict]:
    """Online-news collections whose name contains `name`."""
    page = directory.collection_list(platform="online_news", name=name, limit=100)
    return page["results"] if isinstance(page, dict) else list(page)


def resolve_collection(directory, wanted: str | int) -> int:
    """Turn a configured collection (id or exact name) into an id."""
    if isinstance(wanted, int) or str(wanted).isdigit():
        return int(wanted)
    matches = find_collections(directory, wanted)
    for c in matches:
        if c["name"].strip().lower() == wanted.strip().lower():
            return int(c["id"])
    names = ", ".join(f'"{c["name"]}" ({c["id"]})' for c in matches[:10]) or "none"
    raise MediaCloudError(f'no collection named "{wanted}". Similar: {names}')


def story_to_article(story: dict, country: Country) -> Article:
    when = story.get("publish_date") or story.get("indexed_date")
    if isinstance(when, datetime):
        seen = when if when.tzinfo else when.replace(tzinfo=timezone.utc)
    elif isinstance(when, date):
        seen = datetime.combine(when, time(), tzinfo=timezone.utc)
    else:
        seen = datetime.fromisoformat(str(when)[:10]).replace(tzinfo=timezone.utc)
    domain = urlparse(story.get("url") or "").netloc or story.get("media_url") or story.get("media_name") or ""
    return Article(
        url=story["url"],
        title=(story.get("title") or "").strip(),
        domain=domain.lower().removeprefix("www."),
        language=story.get("language") or "",
        source_country=country.name,
        seen_at=seen,
    )


def fetch_mediacloud(cfg: Config, store: Store, start: date, end: date,
                     max_pages: int = 10, api_key: str | None = None, clients=None) -> int:
    """Fetch counts and article lists for each country that has a collection.

    Returns the number of countries that failed.
    """
    query = cfg.mediacloud_query()
    if not query:
        raise MediaCloudError("no [mediacloud] terms in the config")
    search, directory = clients or _client(api_key)
    print(f"Media Cloud query: {query}\nPeriod: {start} to {end}")
    failed = 0
    for c in cfg.countries:
        if not c.mediacloud:
            continue
        try:
            cid = resolve_collection(directory, c.mediacloud)
            points = search.story_count_over_time(query, start, end, collection_ids=[cid])
            counts = [(str(p["date"])[:10], int(p["count"]), int(p.get("total_count") or 0)) for p in points]
            store.upsert_mc_counts(c.code, counts)
            stories, token, pages = [], None, 0
            while pages < max_pages:
                page, token = search.story_list(query, start, end, collection_ids=[cid],
                                                pagination_token=token)
                stories += page
                pages += 1
                if not token:
                    break
            new = store.upsert_articles(c.code, [story_to_article(s, c) for s in stories if s.get("url")],
                                        source="mediacloud")
        except Exception as e:  # API errors, bad collection names, network trouble
            print(f"  {c.name}: Media Cloud error: {e}", file=sys.stderr)
            failed += 1
            continue
        more = "  (more stories than were listed; raise max_pages)" if token else ""
        print(f"  {c.name}: {sum(n for _, n, _ in counts)} stories counted in collection {cid}, "
              f"{len(stories)} listed, {new} new{more}")
    return failed
