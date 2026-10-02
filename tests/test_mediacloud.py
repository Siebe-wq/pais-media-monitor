from datetime import date, datetime, timezone

import pytest

from mediamonitor.config import load_config
from mediamonitor.mediacloud_source import (MediaCloudError, fetch_mediacloud, resolve_collection,
                                            story_to_article)
from mediamonitor.report import write_report
from mediamonitor.store import Store


class FakeDirectory:
    def __init__(self, collections):
        self.collections = collections
        self.calls = []

    def collection_list(self, platform=None, name=None, limit=0):
        self.calls.append((platform, name))
        return {"count": len(self.collections),
                "results": [c for c in self.collections if name.lower() in c["name"].lower()]}


class FakeSearch:
    def __init__(self, pages):
        self.pages = list(pages)
        self.queries = []

    def story_count_over_time(self, query, start, end, collection_ids):
        self.queries.append((query, collection_ids))
        return [{"date": date(2026, 9, 1), "count": 3, "total_count": 1000, "ratio": 0.003},
                {"date": date(2026, 9, 2), "count": 1, "total_count": 900, "ratio": 0.001}]

    def story_list(self, query, start, end, collection_ids, pagination_token=None):
        return self.pages.pop(0)


NL = {"id": 34412100, "name": "Netherlands - National"}


def story(i, day=date(2026, 9, 1)):
    return {"id": str(i), "title": f" Kop {i} ", "url": f"https://www.nos.nl/artikel/{i}",
            "language": "nl", "media_name": "nos.nl", "media_url": "nos.nl", "publish_date": day}


def test_query_quotes_every_term(config_file):
    cfg = load_config(config_file)
    assert cfg.mediacloud_query() == '"long covid" OR "ME/CVS" OR "postcovid"'
    assert cfg.countries[0].mediacloud == "Netherlands - National"
    assert cfg.countries[1].mediacloud is None


def test_resolve_collection_by_exact_name_or_id():
    d = FakeDirectory([{"id": 1, "name": "Netherlands - State & Local"}, NL])
    assert resolve_collection(d, "netherlands - national") == 34412100
    assert resolve_collection(d, 42) == 42
    assert resolve_collection(d, "42") == 42
    with pytest.raises(MediaCloudError, match="Similar"):
        resolve_collection(d, "Netherlands")


def test_story_to_article(config_file):
    cfg = load_config(config_file)
    a = story_to_article(story(7), cfg.countries[0])
    assert a.url == "https://www.nos.nl/artikel/7"
    assert a.domain == "nos.nl"
    assert a.title == "Kop 7"
    assert a.seen_at == datetime(2026, 9, 1, tzinfo=timezone.utc)
    no_date = {**story(8), "publish_date": None, "indexed_date": datetime(2026, 9, 3, 12)}
    assert story_to_article(no_date, cfg.countries[0]).seen_at.date() == date(2026, 9, 3)


def test_fetch_mediacloud_stores_counts_and_pages(config_file):
    cfg = load_config(config_file)
    store = Store(cfg.database)
    search = FakeSearch([([story(1), story(2)], "next"), ([story(3)], None)])
    failed = fetch_mediacloud(cfg, store, date(2026, 9, 1), date(2026, 9, 30),
                              clients=(search, FakeDirectory([NL])))
    assert failed == 0
    assert search.queries == [('"long covid" OR "ME/CVS" OR "postcovid"', [34412100])]  # BE has no collection
    assert [tuple(r) for r in store.mc_daily_counts()] == [("NL", "2026-09-01", 3, 1000), ("NL", "2026-09-02", 1, 900)]
    rows = store.articles_with_labels()
    assert len(rows) == 3 and {r["source"] for r in rows} == {"mediacloud"}


def test_fetch_mediacloud_reports_bad_collection(config_file):
    cfg = load_config(config_file)
    store = Store(cfg.database)
    failed = fetch_mediacloud(cfg, store, date(2026, 9, 1), date(2026, 9, 30),
                              clients=(FakeSearch([]), FakeDirectory([])))
    assert failed == 1


def test_report_shows_both_sources(tmp_path, config_file):
    cfg = load_config(config_file)
    store = Store(cfg.database)
    fetch_mediacloud(cfg, store, date(2026, 9, 1), date(2026, 9, 30),
                     clients=(FakeSearch([([story(1)], None)]), FakeDirectory([NL])))
    page = write_report(cfg, store, tmp_path / "out").read_text()
    assert "Articles per week (Media Cloud)" in page
    assert "Media Cloud stories" in page
    assert ">Media Cloud</td>" in page
    header = (tmp_path / "out" / "weekly_counts.csv").read_text().splitlines()[0]
    assert header == "week_start,NL_gdelt,BE_gdelt,NL_mediacloud"
